# Schemas Layer Simplification — Analysis (Spec)

**Date:** 2026-10-11
**Scope:** `src/jidou/schemas/`: 13 modules, 72 Pydantic v2 classes,
1,530 lines.
**Status:** Analysis complete. The companion plan is
`docs/superpowers/plans/2026-10-11-schemas-simplification.md`. This is
the sixth per-layer analysis, after the API, services, orchestrators,
workers and models specs of the same date. Still to be analyzed:
`frontend/`.

Measured at commit `7d60acc`. `ruff C901` / PLR checks are clean; there
is no control-flow complexity here. The analysis covers
**contract design**: duplication, dead schemas, vocabulary typing, and
how the schemas surface in OpenAPI. That OpenAPI output is the input to
`make.py generate-types` → `frontend/src/types/api-generated.ts`.

---

## 1. Summary

The schemas are idiomatic Pydantic v2. They use `ConfigDict`,
`field_validator` / `model_validator` and `computed_field`, there is no
v1 API, and they carry good field descriptions. The problems:

1. **Dead contracts.** `schemas/import_schema.py` is never imported. Its
   two classes are stale copies of the orchestrator dataclasses with the
   same names, and they are missing `episodes_already_tracked`, `mode`
   and the path lists. `EpisodeRead`, `FileList`, `TaskProgress` and
   `WatchlistList` are not used by any route or service. The frontend
   keeps hand-written TypeScript interfaces with the same names, which
   makes them look alive.
2. **A copied validator.** The same "does this regex compile?" validator
   method is written on 6 classes.
3. **The same name for two different shapes.** `ShowBrief` is defined in
   both `file_schema` (`id`, `title`) and `watchlist_schema` (`title`,
   `tmdb_id`, `poster_path`, `backdrop_path`). FastAPI disambiguates them
   in OpenAPI as `jidou__schemas__file_schema__ShowBrief` and
   `jidou__schemas__watchlist_schema__ShowBrief`, and those names end up
   in the generated frontend types.
4. **Vocabularies typed inconsistently** with the model enums:
   - `ContentType` is used in some places, while
     `^(tv|anime|movie)$` pattern strings and plain `str` are used in
     others.
   - `media_type` is a pattern string in 2 places and an unvalidated
     `str` in `RematchRequest`.
   - `matched_by` and `ignored_reason` are `str` in `FileRead`, even
     though `MatchedBy` and `IgnoredReason` exist.
5. **The same configuration repeated.**
   `model_config = ConfigDict(from_attributes=True)` appears 21 times.
   Two configurations do nothing: `validate_assignment` on a request body
   that is never mutated, and `populate_by_name` on a model with no
   aliases.

## 2. Structural map

```
show_schema ──► models.show.ContentType, episode_schema.EpisodeList, file_schema.EpisodeBrief
rss_schema  ──► show_schema.ShowCreate              (FeedAddShowRequest.show)
calendar_schema ──► models.show.ContentType
task_schema ──► models.task.TaskStatus              (+ TaskType Literal mirroring worker task_type strings)
file_schema ──► models.downloaded_file.FileStatus
watchlist_schema ──► models.watchlist.WatchlistStatus
episode_schema, orphan_schema ──► services.path_transport (computed display field)   ★ schema → service import
import_schema  (no importers)                                                            ★ dead
consumers: api/routes/* (response_model / bodies); services/show_creation (ShowCreate as a domain DTO);
           orchestrators/{manual_match, show_rematch, feed_onboarding} (request bodies as inputs)
```

How the classes are used:

| Kind | Count | Examples |
|---|---|---|
| Responses read from ORM rows (`from_attributes=True`) | 21 | `ShowRead`, `ShowList`, `FileRead`, `RssSubscriptionRead`, `TaskList` |
| Request bodies | ~22 | `ShowCreate`, `ShowPatch`, `RssFeedCreate` / `Update`, `FeedAddShowRequest`, `TaskTrigger` |
| Computed response DTOs | ~20 | `CalendarEpisode`, `FeedEntriesRead`, `StatsResponse`, `DiscoverResult` |
| Dead | 6 | `import_schema.{ShowImportResult, PathImportResult}`, `EpisodeRead`, `FileList`, `TaskProgress`, `WatchlistList` |

## 3. Findings

| # | Finding | Where | Target | Changes OpenAPI? |
|---|---|---|---|---|
| SC1 | Dead schemas | `import_schema.py` (the whole module), `episode_schema.EpisodeRead`, `file_schema.FileList`, `task_schema.TaskProgress` (only `tests/test_task_routes.py` uses it), `watchlist_schema.WatchlistList` | Delete. They are not part of any route, so they are not in OpenAPI. | No |
| SC2 | Regex-compiles validator copied | `RegexHintSample.validate_hint`, `RssFeedCreate` / `Update.validate_regex_hint`, `RssSubscriptionCreate` / `Update.validate_regex`, `FeedRegexTestRequest.validate_regex`, `FeedAddShowRequest.validate_regex` (7 methods, 6 classes) | `RegexPattern = Annotated[str, AfterValidator(_validate_regex)]`. Error type (`value_error`), location and message are unchanged. | No |
| SC3 | `ConfigDict(from_attributes=True)` ×21 | Every ORM-backed response | `schemas/_base.py: class ORMModel(BaseModel)` | No |
| SC4 | Configuration that does nothing | `TaskTrigger.model_config = ConfigDict(validate_assignment=True)`; `ShowPatch.model_config = ConfigDict(populate_by_name=True)` (no aliases exist) | Remove | No |
| SC5 | `_coerce_task_status` (unknown string → PENDING) on `TaskList` / `TaskProgress` | `task_schema` | Delete once models plan Task 3 makes `BackgroundTask.status` a `TaskStatus`. At that point an unknown value already fails when the row loads, so the fallback can never run. | No |
| SC6 | Constraints copied from service constants | `AppSettingsRead` / `Patch.similar_titles_count` `ge=1, le=40` vs `settings_service.SIMILAR_TITLES_COUNT_MIN/MAX`; `MAX_REGEX_PATTERN_LENGTH` / `MAX_REGEX_SAMPLES` defined in the schema while `rss_regex_matching.MAX_TITLE_LENGTH` lives in the service | Import the service constants | No (same values) |
| SC7 | Two different `ShowBrief` classes | `file_schema`, `watchlist_schema`; `frontend/src/types/api.ts` lines 88 and 417 alias the namespaced component names | Rename to `FileShowBrief` / `WatchlistShowBrief`, and repoint the two `api.ts` aliases (their TypeScript names stay `ShowBrief` / `WatchlistShowBrief`) | **Yes**: component names |
| SC8 | Response vocabularies typed as `str` | `FileRead.matched_by` / `ignored_reason`, `RecentShowItem` / `DashboardShowSummary.content_type`, `OrphanRead.tracked_source`, `RssConfigDiff.snapshot_type` | Use the model enums: `MatchedBy`, `IgnoredReason`, `ContentType`, and `TrackedSource` / `SnapshotType` (models plan Task 4). The JSON values are the same. | **Yes**: `string` → `enum` |
| SC9 | Request vocabularies typed as pattern strings, or not validated at all | `ShowCreate.media_type`, `FileMatchRequest.tmdb_media_type` (`^(tv\|movie)$`); `FileMatchRequest.content_type` (`^(tv\|anime\|movie)$`); `RematchRequest.media_type: str` | `MediaType = Literal["tv", "movie"]`; `ContentType` | **Yes**, and the 422 error text changes. `RematchRequest` changes from **502** to **422** on bad input. → **§6 decision** |

## 4. Complexity hotspots

None.

## 5. Dead or redundant paths

Covered by SC1, SC4 and SC5.

**No action** on:
- `TaskTrigger.task_type: str`. It is deliberately not a `Literal`, so
  the route's own 400 "Unknown task type" stays, and the class's
  docstring explains why.
- `TaskType`, the `Literal` on `TaskList`. It duplicates the worker task
  type strings, but it is the OpenAPI enum the frontend relies on. Plan
  Task 5 adds a test that keeps it equal to the API plan's
  `TASK_REGISTRY` plus the import, RSS and DB-import types.

## 6. Decisions (not changed by this plan)

1. **`extra="forbid"` on request bodies.** Unknown fields are silently
   ignored today. Forbidding them is the safer contract, but any client
   (including the frontend) that sends extra keys would start getting
   422.
2. **Tightening request vocabularies (SC9).** This turns pattern errors
   into enum errors, and fixes `RematchRequest`'s 502-on-bad-input into
   a 422. Plan Task 7 is written and ready, but only runs if this is
   approved.
3. **Typed TMDB sub-objects** (`genres`, `networks`,
   `last_episode_to_air`, `external_ids`, `episode_groups` are
   `dict[str, object]` today). Typing them improves the frontend types,
   but it risks 500s on response validation whenever TMDB adds or changes
   a key, unless the sub-models use `extra="allow"`.
4. **`ShowCreate` doubles as the service-layer input**
   (`services/show_creation` calls `model_dump()` and pops 4 keys).
   A dedicated DTO would separate the HTTP contract from the domain
   input. Deferred, because the services and orchestrators plans
   already move this code.
5. **`episode_schema` / `orphan_schema` import a service**
   (`path_transport.decode_path_bytes_for_display`) for a computed
   display field. This is acceptable. Moving the function to a neutral
   `jidou/text.py` would be the purist fix, but nothing else needs it.

## 7. Priorities

- **High:** SC1 dead schemas, SC2 regex type. Neither changes behavior
  or the contract.
- **Medium:** SC7 duplicate name, SC8 response enums. Both change the
  contract and need the OpenAPI snapshot updated and the frontend types
  regenerated in the same PR.
- **Low:** SC3 base class, SC4 no-op configuration, SC5 coercion (after
  the models plan), SC6 shared constants.
- **Gated on §6:** SC9.

## 8. Interaction with the other plans

- **API plan Task 1** creates the OpenAPI snapshot. Every task here
  either keeps it byte-identical, or (Tasks 5–7) updates it on purpose
  in the same commit and runs `uv run python make.py generate-types`.
- **API plan Task 11** (table-driven settings PATCH) and SC6 both touch
  `AppSettingsPatch`. Do SC6 first or second; there is no conflict.
- **Models plan Tasks 3 and 4** provide the typed `TaskStatus` column,
  and `TrackedSource` / `SnapshotType`. SC5 and part of SC8 depend on
  them.
- **The frontend analysis (next)** should treat `api.ts`'s hand-written
  `EpisodeRead`, `FileList` and `WatchlistList` interfaces as orphans
  once SC1 lands. `WatchlistList` is already commented as
  "frontend-only".
