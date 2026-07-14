# Matching Pipeline

How Jidou decides what a media file *is* — show, season, episode, content type — and how that decision gets written to the database. This is a reference for the actual current behavior of the code, not an aspirational design; where the code has gaps or dead ends, they're called out explicitly rather than glossed over.

There are **two independent pipelines** that both end up creating/updating `Show`, `Episode`, and `DownloadedFile` rows, but they make their decisions completely differently and don't share code for the show/episode-resolution step. Mixing them up when debugging a specific file is the most common source of confusion.

| | SFTP pipeline | Path-list import |
|---|---|---|
| Entry point | Scan → Download → Match → Route tasks | Single `import` task |
| Input | Live SFTP directory listing | A text file of already-in-place absolute paths |
| Show name source | Extracted from the **filename** by LLM/regex | Primarily **directory structure**; each file's own extracted name is cross-checked against it, and a confirmed disagreement resolves that file against its own show instead |
| Files table role | Full lifecycle (`discovered` → ... → `routed`) | Display-only synthetic row, already `routed` |
| Orchestrators | `ScanOrchestrator`, `ParseOrchestrator`, `RouteOrchestrator` | `PathImportOrchestrator` |
| Code | `src/jidou/orchestrators/{scan,parse,route}_orchestrator.py` | `src/jidou/orchestrators/path_import_orchestrator.py`, `src/jidou/services/path_parser.py` |
| Shared code | `src/jidou/services/filename_parser.py` — regex heuristics + LLM filename parsing, used by both pipelines | (same) |

---

## Pipeline A — SFTP scan → download → match → route

### 1. Scan (`ScanOrchestrator`)

Lists every configured remote path recursively via `SFTPService`, filtered by `src/jidou/services/file_filters.py`:

- **`is_valid_media_file`** — allowlist of 12 extensions: `.mkv .mp4 .avi .mov .wmv .m4v .flv .ts .m2ts .iso .av1 .ogm`. Rejects anything whose lower-cased name contains `sample`, `screens`, `thumbs.db`, or `.ds_store`.
- **`is_valid_directory`** — same keyword exclusion, applied to directory names to decide whether to recurse at all.
- **`is_recently_modified`** — files modified within the last 60 seconds are skipped (still uploading).

No show/episode decisions happen here. Each surviving file becomes a `DownloadedFile` row: `show_id=NULL`, `episode_id=NULL`, `status=DISCOVERED`. Deduplication is on `remote_path` alone — an already-tracked file (any status) is skipped outright, so a file that was manually reset or errored keeps its history rather than being rediscovered as new.

### 2. Download

Plain SFTP transfer, `DISCOVERED → DOWNLOADING → DOWNLOADED`. No filename decisions made here.

### 3. Match (`ParseOrchestrator`) — where show/season/episode get decided

This is the real decision-making stage for this pipeline. Runs against every `DOWNLOADED` file, one at a time. The extraction itself (stages 1a/1b below) lives in the shared `src/jidou/services/filename_parser.py` module — `ParseOrchestrator` calls `parse_filename(filename, llm)` and gets back a `FilenameParseResult` dataclass (`show_name`, `season`, `episode`, `crc32`, `content_type`, `confidence`, `llm_ok`); everything after that (the confidence gate, DB lookups, alias teaching, `local_path` resolution) is `ParseOrchestrator`'s own logic.

**Stage 1a — regex anchor (`heuristic_se`).** Two fast, narrow patterns run first purely to produce a grounding hint for the LLM:
```
[Ss](\d{1,2})[Ee](\d{1,3})        # S01E02
(?<!\d)(\d{1,2})[xX](\d{1,3})(?!\d)   # 01x02
```
This result is *not* authoritative on its own — it's passed into the LLM prompt as `Regex anchor detected: season=X episode=Y` so the model has a structural signal to confirm or override rather than re-deriving it from scratch. `ParseOrchestrator.run()` also calls this directly (independent of `parse_filename`) to use as a final fallback if the LLM's own season/episode come back null.

**Stage 1b — LLM full parse (`parse_filename`).** If an LLM is configured and available, the *entire* raw filename is sent to it with the system prompt in `src/jidou/services/prompts/parse_filename.txt` (this is the long, detailed prompt — 9 numbered rule sections plus worked examples — not a trimmed-down one). It extracts, in one call:
- `show_name` — with explicit rules for where the title ends and metadata begins (hyphens as separators vs. part-of-title, honorifics like `-san`/`-kun` never treated as separators, parenthetical alternate titles kept, parenthetical pure-metadata dropped).
- `season` / `episode` — season only ever set on an explicit marker (`S02`, `Season 2`, `2nd Season`); a bare number is never inferred as a season.
- `crc32` — exactly 8 uppercase hex chars in a trailing bracket, else `null`.
- `content_type` — `"anime"` / `"tv"` / `"movie"` / `null`.
- `confidence` — starts at 1.0, penalized for missing season (−0.1), inferred (unmarked) episode (−0.15 to −0.25), version suffixes (−0.1), or null episode (−0.8).
- `reasoning` — one or two sentences, logged at debug level.

If the LLM is unavailable, returns no response, or returns unparseable JSON, this falls back to **`_heuristic_parse`**: seven ordered regex patterns (`_HEURISTIC_PATTERNS`, most- to least-specific — `"2nd Season 04"` style, `S01E02`, `S01 02`, `E02`, end-anchored bare number, mid-string bare number with optional `v2` suffix, then a leading-space `S01E02` variant). A heuristic match gets a flat `confidence=0.6`; no match at all gets `0.1` and the whole cleaned filename becomes the `show_name` guess. Heuristic results always set `content_type=null` — that field is LLM-only. `FilenameParseResult.llm_ok` is `False` whenever this fallback fired, `True` only for a genuine LLM response — path-import's per-file confirmation (see Pipeline B) relies on this flag directly.

**Stage 2 — confidence gate.** Only applies when the LLM actually ran (`llm_ok=True`) and the result isn't a movie (movies legitimately have `episode=null`, which would otherwise trigger the same penalty as a genuinely low-confidence parse). If `confidence < 0.7`, the file is set to `UNMATCHED` with an explanatory `error_message` and the pipeline moves on — no show/episode lookup is even attempted. Heuristic-only results skip this gate entirely and always proceed to lookup, regardless of their fixed 0.6/0.1 confidence.

**Stage 3 — show lookup (`_find_show`).**
1. `show.aliases` (GIN-indexed JSONB array) contains the case-folded parsed name — exact containment, not substring.
2. Case-insensitive `ILIKE '%name%'` against `show.title` (with `%`/`_`/`\` escaped so a parsed name containing those doesn't act as a wildcard).

**Stage 4 — episode lookup (`_find_episode`).**
1. `season` known → `(show_id, season_number, episode_number)` exact match.
2. `season` unknown → `absolute_episode_number == episode` (see [the caveat below](#episodeabsolute_episode_number-is-effectively-always-null) about this column).
3. Still nothing → assume `season=1, episode_number=episode` — correct for the common case of anime distributed with no season marker at all.

**Side effects on a successful match:**
- The parsed name is taught back into `show.aliases` / `show.aliases_sources["user"]` (`_add_alias`) — every subsequent file with that exact name skips the LLM entirely and resolves via the GIN index.
- `show.content_type` is backfilled from the LLM's parsed value **only if currently unset** — an existing value is never overwritten here.
- `show.local_path` is auto-populated via `_resolve_local_path` (content_type/media_type → base dir + `sys_name`) **only if** `show.content_type` is set, or `show.media_type == "movie"` (unambiguous either way). A show whose `media_type == "tv"` with no `content_type` set is intentionally left with `local_path=None` — TMDB's `"tv"` covers both real TV and anime, so guessing would risk routing to the wrong base directory. A warning is logged; someone has to `PATCH /shows/{id}` to set it manually.
- If the LLM returned `season=null` (anime absolute numbering) but the episode resolved successfully, `file.parsed_season` is backfilled from the resolved episode's actual `season_number` so `RouteOrchestrator` doesn't place the file at the show root by mistake.

No structured per-decision event log exists for this pipeline — `ParseOrchestrator.run()` only takes an `on_progress` callback, not an `on_event` one. LLM failures, low-confidence flags, and match outcomes are only visible via `logger.debug`/`logger.warning`/`logger.info` calls (Docker logs), never on the Tasks page. This is the same gap that was fixed for path-import in a recent PR (#279) — it has **not** been applied here.

### 4. Route (`RouteOrchestrator`)

Moves every `MATCHED`/`ROUTING` file from staging to its final path. No show/episode *decisions* happen here — it's placement logic:

- Movies (`content_type` or `media_type == "movie"`) go directly to `show.local_path/filename`.
- Everything else with a known season goes to `show.local_path/Season NN/filename` — **NN is zero-padded by default, but `_season_dir_name` checks the show's directory for an existing unpadded `Season N` convention first** (single-digit seasons only; a show already using `Season 1`/`Season 2` keeps getting unpadded directories for new seasons rather than a mixed `Season 1` + `Season 03`).
- No season known → placed directly at the show root.
- Destination collisions get a numeric suffix (`file.1.mkv`, `file.2.mkv`, ...) rather than overwriting.
- If a file's `episode_id` is still unset at route time (can happen after a manual match), it's resolved here as a last resort from `parsed_season`+`parsed_episode`, or `absolute_episode_number` if season is unknown — the same fallback chain as the match stage, run again defensively.

---

## Pipeline B — path-list import

Used for bulk-registering files that are **already in their final location** (e.g. an existing library being onboarded). Single task; one file content-type is declared explicitly at trigger time (`content_type: "anime" | "tv" | "movie"`, default `"anime"`) — nothing here is inferred from TMDB genre/language data the way the interactive "Add Show" flow does.

### 1. Line parsing (`path_parser.parse_line` / `parse_file`) — pure regex, no LLM at this layer

**Show directory resolution.** The caller (`_path_import` in `import_tasks.py`) maps `content_type` → `settings.local_{anime,tv,movie}_host_path` and passes that in as `root`.
- If the line falls under `root`: `show_dir` is the **first path segment below root**, full stop — regardless of how many extra directories (bonus-content folders, `Season 00`, anything) sit between it and the file. A `Season N` match is looked for at *any* depth in between, not just the immediate parent.
- If `root` is omitted, or the line doesn't fall under it (mismatched configuration, path-style mismatch): falls back to the old heuristic — the file's immediate parent directory (or grandparent, if the parent looks like `Season N`).

**Episode/season extraction (`_parse_episode`)** — ten patterns, in priority order, first match wins:

1. `SxxExx` / `SxxEyyy`
2. `NNxNN` (release-group style, e.g. `01x01`)
3. `Season N ... Episode N` long-form text
4. `Episode N` standalone
5. `Ep N` / `Ep. N`
6. `- N` at end-of-string or before a bracket
7. `N - Title` (episode number before a dash-separated title, title starts with a letter)
8. `N - Title` at start of stem (title may start with a digit)
9. Bare `Title NN` — a trailing 1-2 digit number separated from the title by nothing but whitespace, no dash or keyword (e.g. `Bamboo Blade 20.mkv`). Skipped entirely if the stem contains a non-episode asset marker (`NCED`, `NCOP`, `OP`, `ED`, `PV`, `CM`, `SP`, `OVA`, `OAD`) — those are left as `episode=None` so they fall through to the LLM, which knows to treat them as bonus content rather than a numbered episode.
10. Compact `SEEE`/`SSEEE` (e.g. `criminal.minds.201` → S02E01) — last resort, most ambiguous. A guess here also populates `ParsedPathEntry.absolute_candidate` with the **raw joined number** (e.g. `212` for `One Piece 212.mkv`, even though the guessed split is `S02E12`) — this is the disambiguation hook used later when the season/episode guess doesn't pan out (see below). Guesses whose encoded season disagrees with a season known from the directory are discarded outright.

### 2. Per-file show-name confirmation (`_import_show`)

Before resolving a show, `_import_show` no longer assumes every file grouped under a directory actually belongs to the show that directory name implies. For **every** entry it calls the shared `parse_filename(filename, self.llm)` (same function Pipeline A uses) purely to get an independent `show_name` signal, then checks it against the directory-resolved show via `_agrees_with_show` (same normalized-title-or-alias logic `_db_find_show` uses internally).

- **Only an LLM-confirmed disagreement (`parsed.llm_ok is True`) triggers a split.** If no LLM is configured, or a call fails and falls back to the heuristic parser, the extracted name is ignored for this check entirely — a generic filename with no real show title in it (e.g. `extras.mkv`) heuristically "extracts" its own cleaned name as `show_name`, which would disagree with every real show and wrongly split off a chunk of every import if it were trusted. This was found empirically during implementation, not designed in up front.
- A disagreeing file is pulled out of the group and resolved independently — full DB/TMDB resolution against its *own* extracted name (`_resolve_show`, the same show-resolution logic described below, shared between the primary directory-derived group and any split-off secondary one) — instead of being silently matched against the directory's show.
- `_import_show` therefore returns `list[ShowImportResult]` rather than one — usually a single entry (the whole directory is one show), but more if the directory turned out to contain files from more than one show. `run()` flattens the list when aggregating into `PathImportResult`; `shows_processed` still counts directories, not resolved shows.
- A split-off secondary show does **not** get `local_path` auto-set from `entries[0].show_root` — that value reflects the *directory's* root (the primary show's location), not the secondary show's actual location, so writing it would point the wrong show at the primary show's folder. The show is still fully created/matched; only the auto-path step is skipped, with a warn event pointing at manual configuration via `PATCH /shows/{id}` — same pattern as the SFTP pipeline's own "content_type unknown" skip.

### 3. Show resolution (`_resolve_show` → `_db_find_show` / `_tmdb_create_show`)

- DB lookup: GIN-indexed alias containment, then **exact** case-insensitive title match — deliberately *not* a substring match, so `"Daredevil"` never accidentally resolves to `"Daredevil: Born Again"`.
- Not found → TMDB search (`media_type="tv"` only). A normalized-exact title match wins outright; otherwise the LLM disambiguates among the top candidates (`_llm_pick_candidate`, given up to 10 candidate titles + years), falling back to TMDB's top-relevance result if the LLM is unavailable or doesn't pick one confidently.
- A newly created show gets `content_type` set to exactly whatever was passed to the import task — never inferred.
- `show.local_path` is set to `entry.show_root` (the literal directory the files were already found under) the first time it's unset, for the primary directory-derived group only (see above for why a split-off secondary group skips this) — no base-path + `sys_name` construction needed, since these files are already in place.
- Episodes are synced via `TMDBOrchestrator`, and aliases via `alias_orchestrator.generate_aliases` (TMDB alternative titles from JP/US/GB/KR country codes or transliteration-flagged entries, plus optional LLM-generated aliases, plus any preserved user-added aliases — merged into the same flat GIN-indexed array Pipeline A reads).

### 4. Episode resolution (`_find_episode`)

1. If regex found no episode at all, `_llm_parse_episode` (lightweight prompt — season/episode only, no show name needed since the directory already told us that) attempts to fill it in from the bare filename.
2. `season` known → exact `(season_number, episode_number)` lookup.
3. **On a miss with `season > 1`**: tries an absolute-number lookup (`_absolute_lookup`, using `absolute_candidate` when the entry came from the ambiguous compact-code guess, or the bare episode number otherwise) *before* falling to the LLM. This is what correctly resolves `One Piece 212.mkv` (guessed `S02E12`, but `212` is the real absolute episode) and `Bleach - 260 Conclusion!...avi` (same shape) without ever hitting the LLM.
4. `season == 1` or unknown → same `_absolute_lookup` chain, then the full-episode-list LLM match (`_llm_match` — sends the show's entire episode list + filename, asks the LLM to pick one).
5. `_absolute_lookup` itself: `absolute_episode_number` column check first, then a `ROW_NUMBER()` window ordering all non-special episodes by `(season_number, episode_number)` and matching on sequential position — this second step is what actually carries the load in practice (see caveat below).

**Side effects on a match:** `mark_episode_tracked` sets `file_tracked=True`, `tracked_filename`, `tracked_source="import"`. A synthetic `DownloadedFile` row is created (`remote_path="synthetic-import://<raw_path>"`, `status=ROUTED`) purely so the file shows up correctly on the Files page — it never enters the match/route pipeline; reassigning it later goes through the dedicated `assign-import` endpoint, which also keeps this row's `episode_id` in sync.

Every LLM call site in this pipeline (`_llm_parse_episode`, `_llm_match`, `_llm_pick_candidate`) emits a structured event via `on_event` on both success and failure — attempted, resolved values, or the specific failure reason — visible on the Tasks page's event log. The final "No match" event reflects whatever the LLM actually resolved, not the pre-LLM regex output.

---

## Content type — three different mechanisms, by entry point

There is no single "decide content type" function; each entry point does it differently:

| Entry point | Mechanism |
|---|---|
| Interactive "Add Show" (`POST /shows`, search modal / watchlist) | `_infer_content_type` (`shows.py`): `media_type == "movie"` → `movie`; Animation genre (TMDB genre id 16) **and** (`original_language == "ja"` or `"JP"` in `origin_country`) → `anime`; else → `tv`. |
| Path-list import | Whatever `content_type` was passed to the import task at trigger time. Never inferred. |
| SFTP match pipeline | Whatever the LLM's `content_type` field said for that filename, backfilled onto the show **only if `show.content_type` was previously unset**. |

## `local_path` — two different construction paths

- **Interactive Add / SFTP match pipeline**: `base_dir(content_type or media_type) / sys_name`, computed by `_auto_local_path` (`shows.py`) or the near-identical `ParseOrchestrator._resolve_local_path` — same mapping, duplicated in two places, both producing a *container-side* `PurePosixPath`.
- **Path import**: the literal `show_root` directory the files were already found under — no base-path construction, since path-import's whole premise is "these files are already correctly placed." Skipped entirely for a split-off secondary show (see per-file show-name confirmation above) — `show_root` reflects the directory it was split *out of*, not this show's actual location, so it's left unset for manual configuration instead.

---

## Data model reference

**`Show`** — fields relevant to matching/routing: `content_type` (see above), `media_type` (TMDB's own `tv`/`movie`, never user-editable), `sys_name` (filesystem-safe directory name, derived from title), `local_path`, `aliases` (flat, GIN-indexed `list[str]`, lower-cased), `aliases_sources` (`{"tmdb": [...], "llm": [...], "user": [...]}` — the provenance map the UI reads/writes; `aliases` is always the deduplicated union).

**`Episode`** — `season_number`, `episode_number`, `absolute_episode_number` (see caveat below), `file_tracked` / `file_tracked_at` / `tracked_filename` / `tracked_source` (set by `mark_episode_tracked`, `tracked_source` is `"match"` or `"import"` depending on which pipeline tracked it).

**`DownloadedFile`** — `status` (state machine documented on the model itself: `discovered → downloading → downloaded → matched/unmatched → routing → routed`, plus `error` from any stage and the terminal `seeded` state from the one-time baseline operation), `matched_by` (`llm` / `heuristic` / `manual`), `parsed_show_name` / `parsed_season` / `parsed_episode` / `parsed_confidence` / `parsed_content_type` (Pipeline A only — path-import's synthetic rows don't populate these).

---

## Known gaps and divergences

These are real, current behaviors worth knowing about when debugging a specific file — not proposals.

#### `path_parser.py`'s extension allowlist has drifted from `file_filters.py`'s

`path_parser._MEDIA_EXTENSIONS` (path-import) has 9 entries and does **not** include `.iso`, `.av1`, or `.ogm`, which `file_filters.MEDIA_EXTENSIONS` (SFTP scan) has had since a recent fix. A path-list import containing any of those three extensions silently drops that line — no warning, not counted as unmatched, just absent from every count in the task's result summary. Not yet filed as a tracked issue.

#### `Episode.absolute_episode_number` is effectively always `None`

`TMDBOrchestrator.sync_show_episodes` populates it from `ep_data.get("absolute_number")` on each episode returned by TMDB's raw `/tv/{id}/season/{n}` response — but that endpoint doesn't return an `absolute_number` field in TMDB's actual API shape, and no code anywhere merges the separately-fetched `/tv/{id}/episode_groups` (type-6 "Production" group) per-episode ordering into this column. `episode_groups` gets fetched and stored as raw summary metadata on `Show.episode_groups`, but never processed into per-episode absolute numbers. In practice, every absolute-number lookup in both pipelines falls through to the `ROW_NUMBER()` sequential-position fallback — the column check is a no-op step that always misses.

#### Four separate LLM prompts are involved in matching, at different levels of detail

`src/jidou/services/prompts/parse_filename.txt` (used by `filename_parser.parse_filename`, shared by both pipelines) is a full, detailed spec — 9 rule sections, worked examples, extracts show name + season + episode + content type + CRC32 + confidence + reasoning in one call. Path-import calls it once per file purely for the `show_name` field (see per-file show-name confirmation above) — the `season`/`episode`/`content_type`/`crc32` it also returns are discarded there, since `path_parser.py`'s own regex plus path-import's other prompts already own that job. Path-import's own three inline prompts (`_LLM_EPISODE_PARSE_SYSTEM`, `_LLM_SYSTEM`, `_LLM_SHOW_MATCH_SYSTEM` in `path_import_orchestrator.py`) remain intentionally much narrower — season/episode only, or episode-list matching, or TMDB candidate picking. Tuning the shared `parse_filename.txt` prompt now affects both pipelines' show-name extraction; tuning any of path-import's other three affects only that one narrow step.

#### SFTP match pipeline has no structured event log

`ParseOrchestrator.run()` takes `on_progress` but no `on_event` — every match/failure decision only reaches the Python logger (Docker logs), never the Tasks page. Path-import got this fixed (issue #274); the SFTP pipeline has the identical gap and hasn't been touched.

#### Remakes/reboots sharing a directory name collide (issue #271, open)

Both pipelines resolve a show by exact title/alias match with no year or TMDB-ID disambiguation. A classic show and its recent remake using the same on-disk directory name (`Rurouni Kenshin`, `Ranma 1/2`, etc.) will resolve to whichever one was created first — the second is never even attempted against TMDB independently. Manually adding a `(YYYY)` suffix to work around this breaks TMDB search entirely instead (that literal string doesn't match TMDB's title field), which is actively worse. No fix implemented yet; deferred by explicit choice. Note this is a *different* problem from the truncated-title case below — a `(YYYY)` suffix is user-added text that doesn't match TMDB at all, whereas per-file show-name confirmation (fixed, see Pipeline B above) only helps when a file's own name independently identifies the correct show; it doesn't disambiguate two shows that legitimately share one directory name with no distinguishing per-file signal either.

#### Truncated directory names can still land on the wrong TMDB show on first resolution

Per-file show-name confirmation (issue #282, fixed) closes the "wrong resolution persists forever" half of this problem — a file whose own name disagrees with a bad directory-based resolution now gets caught and re-resolved independently. But the *first* resolution attempt for a heavily truncated directory name (long titles shortened on disk for Windows path-length reasons) still isn't a confident one: `_normalize_title`'s exact-match check only strips punctuation/whitespace, no truncation tolerance, so it falls to LLM disambiguation (prompt written for "omitted article/subtitle," not "extreme truncation" — plausibly still works, not guaranteed) or, with no LLM, TMDB's raw #1 relevance result with no confirmation at all. If every file in that directory happens to agree with each other (the common case — one show, one truncated name), per-file confirmation has nothing to disagree with and won't catch a wrong pick.
