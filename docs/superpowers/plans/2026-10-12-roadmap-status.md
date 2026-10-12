# Simplification Roadmap — Execution Status and Handoff

**Read this first** when resuming the simplification program in a new
session or a new sub-agent. It holds the context that isn't in the
specs and plans: where execution stands, the open preconditions, the
process conventions and the environment gotchas.

- **Roadmap (source of truth for order and decisions):**
  `docs/superpowers/plans/2026-10-12-simplification-roadmap.md`
- **Layer plans (source of truth for task steps):**
  `docs/superpowers/plans/2026-10-11-{api,services,orchestrators,workers,models,schemas,frontend}-simplification.md`
- **Specs (the analysis behind each plan):**
  `docs/superpowers/specs/2026-10-11-*-simplification-design.md`

Last updated: 2026-10-12 (Wave 0 released as 0.4.3).

---

## 1. Where things stand

- **Planning is complete.** All 33 decisions in roadmap §7 have an
  outcome; none are open.
- **Wave 0 is released** (0.4.3, `chore/release-wave-0`). All six guard
  items merged; see §3.
- **Next step:** Wave 1. Lanes per roadmap §4A: MDL-2 → WRK-2 (WRK-2
  also needs ORC-2) · ORC-2 · SVC-2 → SVC-3 · API-2 → API-3 · SCH-1 ·
  FE-2. At most 4 sub-agents at once.
- **Carry into Wave 1:** ORC-2 must first add event-failure pins for the
  RSS import and RSS publish orchestrators (ORC-1 left them unpinned),
  then refactor onto `EventSink`. See §3A.
- **Execution method (decided):** parallel sub-agents.
  - The main session acts as **coordinator**. It dispatches one
    sub-agent per item, each in its own git worktree, using
    `superpowers:subagent-driven-development` (implementer plus fresh
    reviewer).
  - The coordinator merges PRs one at a time, and opens the
    `chore/release-wave-<n>` PR at the end of each wave (decision D1).

## 2. Preconditions

**None open.**

| ID | What | Result |
|---|---|---|
| P1 | The models plan Task 4 Step 1 data check: no stored value outside the target enums | **Passed on 2026-10-12** against production (the owner ran the check). The violations query returned no rows. MDL-3 can proceed as written. |

The value distribution found by P1 (useful for MDL-3 and DF-10):

| Column | Values (rows) |
|---|---|
| `shows.content_type` | `anime` 724, `tv` 474, `movie` 5; **no NULLs** |
| `episodes.tracked_source` | NULL 8,078 (untracked; real NULLs, not empty strings), `import` 32,529, `match` 1,330 |
| `orphaned_tracking_records.tracked_source` | the table is empty |
| `rss_config_snapshots.snapshot_type` | `import` 1, `pre_publish` 24, `post_publish` 17 |

Already settled, so don't ask again:
- There are **no `pending` rows** in `downloaded_files`; D24 is not
  needed.
- **Library size:** 1,203 shows (from P1, 2026-10-12). D10 was sized
  for "several thousand", the expected growth. DF-18 stays in scope;
  the Shows/Watchlist pagination backlog item is not urgent at this
  size.

## 3. Progress ledger

Statuses are `todo`, `in progress`, `merged`, `released`.

**Who updates this table, and when:** only the coordinator, and only in
each wave's `chore/release-wave-<n>` PR, where it records every item's
PR link and `released`. Item PRs must **not** edit this file: parallel
PRs would all conflict on it. Between releases, the live status of an
item is its open or merged PR on GitHub.

| Wave | Items | Status |
|---|---|---|
| 0 | API-1, MDL-1, SVC-1, ORC-1, WRK-1, FE-1 | released (0.4.3) |
| 1 | MDL-2, ORC-2, WRK-2, SVC-2, SVC-3, API-2, API-3, SCH-1, FE-2 | todo |
| 2 | API-4, XL-1, API-5, API-6, API-7, SVC-4, SVC-5, SVC-6, MDL-3 (P1 passed), MDL-4, MDL-5, WRK-3, WRK-4, ORC-4, ORC-5, ORC-6, ORC-9, ORC-10, SCH-2, SCH-3, FE-3, FE-4, FE-5, FE-6 | todo |
| 3 | API-8, SVC-7, SVC-8, SVC-9, ORC-3, ORC-7, ORC-8, XL-2, ORC-11, WRK-5, SCH-4 | todo |
| 4 | ORC-12, WRK-6, MDL-6, FE-7, FE-8, SCH-5 | todo |
| 5 | DF-1 … DF-20, then XL-3 | todo |

Per-item rows (item → PR) are added by the release PR of each wave.

| Item | PR(s) | Status | Notes |
|---|---|---|---|
| — | jamesbconner/Jidou#656 | released | `ruff format` on the plan docs' Python snippets; `main` lint was red before it |
| API-1 | jamesbconner/Jidou#657, jamesbconner/Jidou#662 | released | #662 fixed a vacuous route-shadowing guard (FastAPI 0.142.2 wraps routers in `_IncludedRouter`) |
| SVC-1 | jamesbconner/Jidou#658 | released | |
| ORC-1 | jamesbconner/Jidou#659 | released | RSS import/publish event-failure pins deferred to ORC-2 (§3A) |
| MDL-1 | jamesbconner/Jidou#660 | released | `celery_task_id` declared as a unique constraint only (the DB has no plain index) |
| WRK-1 | jamesbconner/Jidou#661 | released | includes an extra `shows_only` import golden |
| FE-1 | jamesbconner/Jidou#663 | released | |

### 3A. Decisions and deferred findings from Wave 0

- **ORC-2 pins RSS import/publish first.** ORC-1's brief omitted them, so
  ORC-2 adds pins for their current event-failure behaviour before moving
  them onto `EventSink`. DF-7 later flips them to "swallowed".
- **Guard hardening for XL-3.** The services and orchestrators AST
  guards skip relative imports (`from ..api import x`) and
  `from jidou import api`; none exist today. The workers include-list
  guard has no non-empty assertion on its disk-derived module set, and
  its `"@shared_task"` substring match would also hit comments. Fix all
  of these together in XL-3.
- **Test-strength minors (not blocking):** the settings-PATCH
  characterization test checks only the execute count; the dispatch test
  doesn't assert the other workers were not called; the scan
  event-failure pin asserts only `result is not None`; ORC-1's tests
  import private helpers from five sibling test modules; no frontend test
  covers a non-string `detail` in `ensureOk`.
- **Flaky frontend test:** `src/tests/components/AddShowFromFeedPane.test.tsx:257`
  failed once in CI (`regex_include` read as `null`) and passed on the
  re-run. Harden it in FE-2 or a standalone fix.

## 4. Process conventions (beyond roadmap §1)

- **Implementation work never commits to `main`.** Every item uses its
  own branch and PR (branch names are in the layer plans), and is
  merged with `--merge`.
- **Planning documents** (specs, plans, this file) were committed
  directly to `main` at the owner's request. That applies to planning
  docs only.
- **Commit trailer:**
  `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
  **Never include a claude.ai session link** in commits, PR bodies or
  issues. This is a repository convention. The early planning commits
  `71aa2e8`…`f74a309` contain one by mistake; leave them alone (do not
  rewrite `main`).
- **PR and issue text:** generic placeholder paths and titles, no real
  library paths. GitHub comments end with the Claude Code attribution
  footer.
- **Version:** per D1, item PRs do **not** bump the version. Only
  `chore/release-wave-<n>` does, following commit `69c7290`
  (`pyproject.toml`, `src/jidou/__init__.py`, `frontend/package.json`,
  `uv.lock`, plus a `CHANGELOG.md` entry).
- **Bugbot loop:** after each push, check the PR's checks for Cursor
  Bugbot every 60 s, at most 10 times, and address its comments before
  merging. See §5 for how to check without `gh`.

## 5. Environment gotchas (cloud session)

- **There is no `gh` CLI.** The layer plans say `gh pr checks` / `gh pr
  create`. Use the GitHub MCP tools instead (`mcp__github__*`, loaded via
  `ToolSearch`): `create_pull_request` (open as a **draft**),
  `pull_request_read`, `get_check_run`, `list_commits`, `issue_write`.
  Subscribe to each created PR with `subscribe_pr_activity`, so CI and
  review events arrive without polling.
- **GitHub push access** failed once with HTTP 403 until the owner
  reconnected GitHub. If a push returns 403 again, the fix is
  reconnecting at claude.ai, not retrying.
- **Node:** the container has Node 22 (npm 10); the project requires
  Node 24 (`.nvmrc` pins `24.19.0`, CI uses 24).
  - With npm 10, `npm ci` rejects the lockfile (vitest's optional `msw`
    peer resolves differently). This is **not** a repository bug.
  - For local frontend checks in this container, use
    `npm install --no-audit --no-fund --package-lock=false`, which never
    rewrites `package-lock.json`. Never commit lockfile changes made by
    npm 10.
- **Frontend baseline** (2026-10-12): `tsc -b` and `npm run lint` clean;
  `vitest run` 54 files, 413 tests passing; ESLint max complexity 92
  (`Settings`).
- **Backend baseline complexity maxima:** API 16, services 17,
  orchestrators 28, workers 16. The commands are in each plan's ratchet
  section.
- **`alembic check`** needs a migrated Postgres. Locally:
  `docker compose up -d postgres`, set `DATABASE_URL`, run
  `uv run alembic upgrade head`. In CI it runs in the existing
  docker-compose job (MDL-1 adds the step).
- **graphify:** run `graphify update .` after code changes (CLAUDE.md).
  Use `graphify query` for codebase questions when `graphify-out/` exists.
  **It is not installed in the cloud container**; there the step is
  skipped and the owner refreshes the graph locally.
- **Dev extras:** the repo-root `.venv` may lack the dev extras (no
  `bandit`, noisy `mypy`). Run `uv sync --extra dev` first.
- **Testing another worktree's code:** `uv run --project /home/user/Jidou`
  imports `jidou` from the main checkout. Set
  `PYTHONPATH=<worktree>/src` to test a worktree's own source.
- **Session restarts kill sub-agents.** In-flight implementers and
  reviewers stop without output. On resume, check `git ls-remote` and the
  report files, then re-dispatch whatever is missing.

## 6. Related work outside the program

- **jamesbconner/Jidou#655:** put the trending task to use.
  - Trending data must **never** be written to `shows`. It goes into
    the TMDB cache (warmed for `tv`, `movie` and `multi`) **and** a
    separate `trending_titles` table.
  - It is not blocked by the program. It's best started after Wave 1
    (MDL-1/MDL-2 model conventions, WRK-2 harness entrypoint).
- **D33 / DF-13:** flagging duplicate files for one episode came out of
  this planning conversation. It is fully specified in roadmap §5A.

## 7. How to resume

1. Read this file, then the roadmap's §1 (Global Constraints), §3
   (Reconciliations), §4 / §4A (order and parallel rules), and §5 / §5A
   (cross-layer and DF items).
2. Check §3 above for what has merged. Confirm against `main`'s history
   and the open PRs, using the GitHub MCP tools.
3. Pick the next items whose **Needs** are all merged and that satisfy
   the §4A concurrency rules, and dispatch them.
4. At the end of each wave, the release PR updates §3 of this file.
