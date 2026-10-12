# Services Layer Simplification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reduce duplication, cyclomatic complexity and dead code in
`src/jidou/services/` without changing externally observable behavior. One
bug fix (S7) is the deliberate exception.

**Architecture:** Extract a few shared primitives
(`single_flight.py`, `llm_structured.py`, `redis_conn.py`). Then refactor
the hotspots behind the existing public signatures: an ordered rule table
in `path_parser`, an entry classifier in `sftp_service`, and a provider
dispatch method in `llm_service`. Fix the two layering violations by
dependency injection (`pubsub_subscriber`) and by moving one function to
the orchestrator layer (`show_creation`). Before any of that, a complexity
ratchet and a layering guard are put in place, so every later task is
checked against them.

**Tech Stack:** Python 3.13, SQLAlchemy 2 (async), redis-py asyncio,
httpx2, asyncssh, pytest (+ pytest-asyncio), ruff, mypy (strict), uv.

**Spec:** `docs/superpowers/specs/2026-10-11-services-simplification-design.md`.
Read it first. Finding IDs (S*, L*, D*) and hotspot names below refer to
it.

> **Status note:** This plan covers the services layer only. It will be
> merged with the API plan (`2026-10-11-api-simplification.md`) and the
> plans for the remaining layers before execution. Line numbers were
> correct at commit `71aa2e8`. Find code by its quoted text, not by line
> number.

## Global Constraints

- **No behavior change** except S7 (Task 6). Public function signatures,
  return values, raised exception types and messages, `on_event` messages,
  `BackgroundTask` writes, and Redis key/channel names stay byte-for-byte
  the same. Log message text is not a contract, except where a test
  asserts it: `"LLM call failed"` in `tests/test_llm_service.py` must keep
  appearing.
- **No backward-compatibility shims.** When a name moves, update every
  importer and every `patch("…")` target in `tests/`. Do not re-export it
  from the old location.
- **Do not edit existing test assertions** to make a refactor pass. Only
  import paths, patch targets and fixture wiring may change. Tasks 13
  (D1 test deletion) and 9 (pubsub DI wiring) are the only exceptions.
- **Commands:** use `uv` only. Never use `pip` or `python -m venv`.
- **Style:** ruff target `py313`, `line-length = 100`; mypy
  `strict = true`; Google-style docstrings on every public function and
  class; explicit type hints everywhere; a comment on each non-obvious
  branch explaining *why* it is there.
- **Pre-push checks, in this order:**
  1. `uv run ruff check .`
  2. `uv run ruff format --check .`
  3. `uv run mypy src/`
  4. `uv run bandit -r src/ -l`
  5. `uv run pytest`
- **After code changes:** run `graphify update .`.
- **Git:** never commit to `main`. Use one branch and one PR per row of
  "PR grouping", work serially, and merge with `--merge`. Each PR ends with
  a version-bump commit following the repo convention (see commit
  `69c7290`).
- **Commit trailer:** end every commit message with
  `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. **TMDB single-flight under a sustained outage.** Exactly
   `_MAX_DEDUP_ELECTION_ROUNDS` HTTP attempts happen, and every waiter
   re-raises the *owner's* exception, not a generic one. Pinned by the
   existing `test_inflight_dedup_fails_fast_after_max_election_rounds` and
   by Task 3's
   `test_max_rounds_reraises_owner_error_without_new_produce`.
2. **TMDB `bypass_cache` owner failure.** The stale entry is deleted
   before waiters re-check the cache, so no waiter gets the stale value.
   Pinned by the existing `test_bypass_cache_failure_deletes_a_stale_entry`
   and by Task 3's `test_on_owner_failure_runs_before_waiters_wake`.
3. **A new release-name format slipping through `_parse_episode`.** Every
   rule keeps its priority order, and the `NCOP`/`OVA` guard still blocks
   only the bare-trailing rule. Pinned by Task 2's golden table, which
   Task 7 must pass unchanged.
4. **An SFTP directory with a fresh mtime.** Expected: it is deferred (not
   walked) by the recursive walk, hidden by `list_remote_children`, and
   ignored by `list_remote_files`. Pinned by Task 8's
   `test_classify_entry` parameter cases.
5. **Redis unreachable during `emit_progress`.** Expected: a warning is
   logged, nothing is raised, and the client is still closed. Pinned by
   Task 9's `test_emit_progress_publish_failure_still_closes_client`.

## File Structure

| File | Status | Responsibility |
|---|---|---|
| `tests/test_services_architecture.py` | Create | Complexity ratchet + upward-import guard for `services/` |
| `tests/test_path_parser_episode_rules.py` | Create | Golden table for `_parse_episode` |
| `src/jidou/services/single_flight.py` | Create | `ElectedSingleFlight[T]` (S1) |
| `src/jidou/services/llm_structured.py` | Create | `JsonCallFailure`, `JsonCallResult`, `request_json_object` (S2) |
| `src/jidou/services/llm_json.py` | Modify | Gains `json_schema_format`, `NULLABLE_INT`, `NULLABLE_STRING`, `optional_int` |
| `src/jidou/services/redis_conn.py` | Create | `redis_session`, `TASK_PROGRESS_CHANNEL` (S6) |
| `src/jidou/orchestrators/show_creation_orchestrator.py` | Create | `get_or_create_show_from_tmdb`, `ShowCreationResult` (moved, L2) |
| `src/jidou/services/{tmdb,llm_service,episode_match_llm,filename_parser,rss_regex_suggestor,episode_lookup,episode_file_matching,path_parser,sftp_service,cache,rate_limiter,progress,pubsub_subscriber,show_creation,rss_regex_matching,feed_subscription_match,rss_stub,synthetic_file,file_reconciliation,path_transport,show_lookup,show_search,settings_service}.py` | Modify | As described per task |
| `src/jidou/main.py` | Modify (Task 9) | Passes `manager.broadcast_to_task` to `pubsub_subscriber.start` |
| `tests/test_single_flight.py`, `test_llm_structured.py`, `test_redis_conn.py` | Create | Unit tests for the new modules |

## PR grouping

| PR | Branch | Tasks | Must run after |
|---|---|---|---|
| 1 | `refactor/services-baseline-guards` | 1, 2 | — |
| 2 | `refactor/services-single-flight` | 3, 4 | PR 1 |
| 3 | `refactor/services-structured-llm` | 5, 6 | PR 2 |
| 4 | `refactor/services-path-parser-rules` | 7 | PR 1 |
| 5 | `refactor/services-sftp-entry-classifier` | 8 | PR 1 |
| 6 | `refactor/services-redis-pubsub-di` | 9 | PR 1 |
| 7 | `refactor/services-show-creation-orchestrator` | 10 | PR 1, API plan PR 8 |
| 8 | `refactor/services-rss-filters` | 11, 12 | API plan PR 8 (Task 12 edits the split route files) |
| 9 | `refactor/services-tmdb-surface-and-cleanups` | 13, 14, 15 | PR 2 |

### Complexity ratchet rule

`_SERVICES_MAX_COMPLEXITY` in `tests/test_services_architecture.py` starts
at **17** (Task 1) and ends at **9** (Task 15). Any task that removes the
current worst offender lowers it to the new maximum reported by:

```bash
uv run ruff check src/jidou/services --select C901 \
  --config lint.mccabe.max-complexity=1 --output-format concise --no-cache \
  | sed -E 's/.*\(([0-9]+) > 1\).*/\1/' | sort -n | tail -1
```

The value only goes down. It never goes up.

---

## Phase 0 — Safety net

### Task 1: Complexity ratchet and upward-import guard for `services/`

**Files:**
- Create: `tests/test_services_architecture.py`

**Interfaces:**
- Produces: `_SERVICES_MAX_COMPLEXITY: int` and
  `_KNOWN_UPWARD_IMPORTS: frozenset[tuple[str, str]]`. Later tasks lower
  the first and remove entries from the second.

- [ ] **Step 1: Write the ratchet test.**
  `test_services_cyclomatic_complexity_ratchet` runs
  `[sys.executable, "-m", "ruff", "check", <services dir>, "--select", "C901", "--config", f"lint.mccabe.max-complexity={_SERVICES_MAX_COMPLEXITY}", "--output-format", "concise", "--no-cache"]`
  with `subprocess.run(..., check=False)` and asserts
  `result.returncode == 0, result.stdout`. This is the same mechanism as
  API plan Task 2. Start with `_SERVICES_MAX_COMPLEXITY = 17`.

- [ ] **Step 2: Write the layering test.**
  `test_services_do_not_import_upper_layers` parses every
  `src/jidou/services/*.py` with `ast`, walks **all** nodes (so imports
  inside functions count), and collects
  `(module_stem, imported_module)` for each `Import`/`ImportFrom` whose
  target starts with `jidou.api` or `jidou.orchestrators`. It asserts:

  ```python
  assert found == _KNOWN_UPWARD_IMPORTS
  ```

  ```python
  # Shrinks to empty: Task 9 removes the first entry, Task 10 the other two.
  _KNOWN_UPWARD_IMPORTS = frozenset(
      {
          ("pubsub_subscriber", "jidou.api.websocket.task_progress"),
          ("show_creation", "jidou.orchestrators.tmdb_orchestrator"),
          ("show_creation", "jidou.orchestrators.alias_orchestrator"),
      }
  )
  ```

  Use exact equality, so a stale allowlist entry also fails.

- [ ] **Step 3: Prove both tests bite.** Set the ratchet to 16 and check
  that the run fails and names `_request`. Remove one allowlist entry and
  check that the run fails. Restore both. Then run
  `uv run pytest tests/test_services_architecture.py -v`.
  Expected: 2 passed.

- [ ] **Step 4: Commit.** `test(services): add complexity ratchet and layering guard`

### Task 2: Golden table for `_parse_episode`

**Files:**
- Create: `tests/test_path_parser_episode_rules.py`

**Interfaces:**
- Consumes: `jidou.services.path_parser._parse_episode(stem: str, dir_season: int | None = None) -> tuple[int | None, int | None, int | None]`

- [ ] **Step 1: Write `test_parse_episode_golden`**, parametrized over
  these `(stem, dir_season, expected)` rows. The values were captured from
  the code at `71aa2e8`.

  ```python
  GOLDEN = [
      ("Show S02E05", None, (2, 5, None)),
      ("Criminal.Minds.01x01", None, (1, 1, None)),
      ("Breaking Bad Season 2 Episode 09", None, (2, 9, None)),
      ("Episode 11 - 25 to Life", None, (None, 11, None)),
      ("Yawara Ep. 7", None, (None, 7, None)),
      ("[SubsPlease] Show - 06 (1080p) [ABCD1234]", None, (None, 6, None)),
      ("Show 01 - The Beginning [hash]", None, (None, 1, None)),
      ("32 - 100th Dirty Job Special", None, (None, 32, None)),
      ("Bamboo Blade 20", None, (None, 20, None)),
      ("Show NCOP 01", None, (None, None, None)),
      ("Show Season 2", None, (None, None, None)),
      ("criminal.minds.201", None, (2, 1, 201)),
      ("criminal.minds.1001", None, (10, 1, 1001)),
      ("Show.Name.2024.1080p.WEB-DL", None, (None, None, None)),
      ("Show 924", 10, (None, None, None)),
      ("Show 1024", 10, (10, 24, 1024)),
      ("One Piece 212", None, (2, 12, 212)),
      ("No numbers here", None, (None, None, None)),
      ("Show 1080", None, (None, None, None)),
  ]
  ```

  The assertion is `_parse_episode(stem, dir_season=dir_season) == expected`.

- [ ] **Step 2: Run it.** `uv run pytest tests/test_path_parser_episode_rules.py -v`.
  Expected: 19 passed. Any failure means the table is wrong for the
  current code. Recapture that row; do not change the code.

- [ ] **Step 3: Commit.** `test(services): pin _parse_episode rule priority with a golden table`

---

## Phase 1 — Shared primitives and worst hotspots (High)

### Task 3: `ElectedSingleFlight` and the TMDB adoption (S1)

**Files:**
- Create: `src/jidou/services/single_flight.py`, `tests/test_single_flight.py`
- Modify: `src/jidou/services/tmdb.py` (`__init__`, `_request`)

**Interfaces:**
- Produces:
  ```python
  class ElectedSingleFlight[T]:
      def __init__(self, *, max_rounds: int | None, label: str) -> None: ...
      async def run(
          self,
          key: str,
          *,
          lookup: Callable[[], Awaitable[T | None]],
          produce: Callable[[], Awaitable[T]],
          on_owner_failure: Callable[[BaseException], Awaitable[None]] | None = None,
          fail_fast_message: str = "in-flight dedup fail-fast",
      ) -> T: ...
  ```
  Semantics. These are taken from `TMDBService._request` lines 163–274;
  read them first.
  - The first caller for `key` becomes the owner and starts a new batch
    (`rounds[key] = 1`).
  - Each waiter waits on the event and then calls `lookup()`. If that
    returns a value, the waiter returns it. Otherwise, under the lock:
    if a new owner already exists, the waiter waits on that owner's event;
    otherwise the round count goes up by one.
  - If `max_rounds` is not `None` and the round exceeds it, the waiter
    re-raises the stored owner error. If no error is stored, it raises
    `RuntimeError(fail_fast_message)`. The round and error state are **not**
    popped here, so sibling waiters fail the same way.
  - Otherwise the waiter becomes the new owner.
  - The owner runs `produce()`:
    - On success, it pops the round and error state.
    - On an exception, it stores the error, awaits
      `on_owner_failure(exc)`, and re-raises.
    - In `finally`, it pops the in-flight entry under the lock, then sets
      the event.

- [ ] **Step 1: Write `tests/test_single_flight.py`** (pytest-asyncio):
  - `test_concurrent_callers_share_one_produce`: 3 concurrent `run("k")`.
    `produce` sleeps 0.02 s, then returns `"v"` and stores it in a dict
    that `lookup` reads. Assert all results are `"v"` and `produce` was
    called once.
  - `test_owner_failure_elects_exactly_one_new_owner`: `max_rounds=None`.
    The first `produce` raises `ValueError`; the second stores and returns
    `"v"`. With 3 callers, assert `produce` was called 2 times, the first
    caller raises `ValueError`, and the other two return `"v"`.
  - `test_max_rounds_reraises_owner_error_without_new_produce`:
    `max_rounds=2`. `produce` always raises `ValueError("boom")`. With 4
    callers, assert `produce` was called 2 times and all 4 raise
    `ValueError` with message `"boom"`.
  - `test_on_owner_failure_runs_before_waiters_wake`: `on_owner_failure`
    appends `"cleanup"` to a list, and `lookup` appends `"lookup"`. Assert
    that `"cleanup"` comes before the first `"lookup"` after the failure.
  - `test_new_batch_after_fail_fast_gets_fresh_owner`: after the
    fail-fast case has fully settled, one more `run("k")` calls `produce`
    again (the round count resets).

- [ ] **Step 2: Run.** `uv run pytest tests/test_single_flight.py -v`.
  Expected: fails with an ImportError.

- [ ] **Step 3: Implement `ElectedSingleFlight`.** Use `asyncio.Lock`,
  `dict[str, asyncio.Event]`, `dict[str, int]` and
  `dict[str, BaseException]`. Log the "owner failed; this coroutine
  retrying (election round %d/%s)" warning with `label` and `key`.

- [ ] **Step 4: Run.** Expected: 5 passed.

- [ ] **Step 5: Adopt it in `TMDBService`.**
  - In `__init__`, replace the four dedup attributes with
    `self._flight: ElectedSingleFlight[dict[str, Any]] = ElectedSingleFlight(max_rounds=self._MAX_DEDUP_ELECTION_ROUNDS, label="TMDB")`.
  - Rewrite `_request` as: the API-key check, URL/params/key setup, the
    first cache read unless `bypass_cache`, and then
    `return await self._flight.run(cache_key, lookup=…, produce=…, on_owner_failure=…, fail_fast_message=f"TMDB {endpoint} request failed (in-flight dedup fail-fast)")`.
  - `lookup` is `cache.get(cache_key)`.
  - `produce` is a new private method,
    `_fetch_and_cache(self, endpoint: str, url: str, params: dict[str, Any], cache_key: str, bypass_cache: bool) -> dict[str, Any]`.
    It contains the pre-request cache re-check (skipped under bypass), the
    `_get_with_retry` call, the info log, and `cache.set(... ttl=_ttl_for_response(...))`.
  - `on_owner_failure` deletes the cache entry only when `bypass_cache` is
    true. Keep the existing comment explaining why.

- [ ] **Step 6: Verify.**
  `uv run pytest tests/test_tmdb.py tests/test_single_flight.py -v`.
  Expected: all pass, with no edits to `test_tmdb.py`. Then
  `uv run ruff check src/jidou/services --select C901 --config lint.mccabe.max-complexity=8`
  must no longer list `_request`. Lower the ratchet per the ratchet rule
  (expected: 16) and run
  `uv run pytest tests/test_services_architecture.py`. Expected: pass.

- [ ] **Step 7: Commit.** `refactor(services): extract ElectedSingleFlight; TMDB _request uses it`

### Task 4: `LLMService.complete`: single-flight, provider dispatch, dead branches (S1, D2)

**Files:**
- Modify: `src/jidou/services/llm_service.py`, `tests/test_llm_service.py` (append only)

**Interfaces:**
- Consumes: `ElectedSingleFlight` (Task 3).
- Produces (private): `_call_provider(self, *, system: str | None, prompt: str, model: str, max_tokens: int, response_format: dict[str, Any] | None) -> tuple[str, int, int, str]`
  and `_strip_thinking(content: str) -> str` (module level).

- [ ] **Step 1: Write the failing tests** (append):
  - `test_call_provider_covers_every_configured_provider`: parametrize
    over `[p for p in LLMProvider if p is not LLMProvider.NONE]`. Patch
    `_call_openai_compatible` and `_call_anthropic` with `AsyncMock`s that
    return `("x", 1, 1, "stop")`. Assert that exactly one of them is
    awaited, and that it is `_call_anthropic` exactly when the provider is
    `ANTHROPIC`.
  - `test_strip_thinking_removes_think_and_thinking_blocks`: assert
    `_strip_thinking("<think>a</think> ok <thinking>b\nc</thinking>") == "ok"`.
- [ ] **Step 2: Run.** Expected: fails (the names do not exist yet).
- [ ] **Step 3: Implement.**
  - `_call_provider` has one branch: `ANTHROPIC` goes to `_call_anthropic`
    (with no `response_format`), and everything else goes to
    `_call_openai_compatible`. Add a comment that `is_available()`
    already excludes `NONE`.
  - `test_connection` keeps its two different pings but drops the
    unreachable `else: raise RuntimeError`.
  - `complete` keeps the cache-hit path. When `bypass_cache` is false it
    goes through
    `self._flight = ElectedSingleFlight[LLMResponse | None](max_rounds=None, label="LLM")`,
    with `lookup` returning a `cached=True` `LLMResponse` built from
    `_get_cached`, or `None` on a miss. When `bypass_cache` is true it
    calls `produce` directly; the existing behavior is that bypass calls
    are not deduplicated.
  - `produce` is a new private method, `_complete_uncached(...)`. It
    contains the timed `_call_provider` call (exception → warning
    `"LLM call failed (provider=%s model=%s): %s"` → `None`),
    `_strip_thinking`, cache-on-non-truncation, the info log, and builds
    the `LLMResponse`.
  - Remove `self._in_flight` and `self._flight_lock`.
- [ ] **Step 4: Verify.** `uv run pytest tests/test_llm_service.py -v`.
  Expected: all pass, and the pre-existing tests are unchanged. `complete`
  must be ≤ 8 under C901.
- [ ] **Step 5: Commit.** `refactor(services): LLMService.complete uses ElectedSingleFlight and a provider dispatch`

### Task 5: Structured LLM calls and schema helper (S2)

**Files:**
- Create: `src/jidou/services/llm_structured.py`, `tests/test_llm_structured.py`
- Modify: `src/jidou/services/llm_json.py`, `episode_match_llm.py`, `filename_parser.py`, `rss_regex_suggestor.py`, `llm_service.py` (ping schema), `tests/test_llm_json.py` (append)

**Interfaces:**
- Produces, in `llm_json.py`. This module stays free of any `LLMService`
  import.
  ```python
  NULLABLE_INT: dict[str, object]  # {"anyOf": [{"type": "integer"}, {"type": "null"}]}
  NULLABLE_STRING: dict[str, object]  # {"anyOf": [{"type": "string"}, {"type": "null"}]}


  def json_schema_format(name: str, properties: dict[str, object]) -> dict[str, object]: ...
  def optional_int(
      value: object,
  ) -> int | None: ...  # None -> None, else int(value); propagates TypeError/ValueError
  ```
  `json_schema_format` returns
  `{"type": "json_schema", "json_schema": {"name": name, "strict": True, "schema": {"type": "object", "properties": properties, "required": list(properties), "additionalProperties": False}}}`.
- Produces, in `llm_structured.py`:
  ```python
  class JsonCallFailure(StrEnum):
      RAISED = "raised"
      NO_RESPONSE = "no_response"
      INVALID_JSON = "invalid_json"
      NOT_OBJECT = "not_object"


  @dataclass(frozen=True)
  class JsonCallResult:
      data: dict[str, Any] | None
      response: LLMResponse | None
      failure: JsonCallFailure | None
      error: Exception | None = None


  async def request_json_object(
      llm: LLMService,
      *,
      prompt: str,
      system: str,
      response_format: dict[str, object],
      max_tokens: int = 1024,
      bypass_cache: bool = False,
  ) -> JsonCallResult: ...
  ```
  It catches `Exception` from `llm.complete` and returns `RAISED`. It
  never logs or emits events; callers keep their own messages.

- [ ] **Step 1: Write the tests.**
  - In `tests/test_llm_json.py`: `test_json_schema_format_matches_existing_filename_schema`
    asserts that `json_schema_format("filename_parse", {...})`, with the
    7 properties from `filename_parser._PARSE_RESPONSE_FORMAT`, `==` a
    literal copy of today's dict (paste it into the test before Step 3
    changes it). Do the same for `rss_regex`. Also add
    `test_optional_int` with the cases `None→None`, `"3"→3`, `4→4`, and
    `"x"` raising `ValueError`.
  - In `tests/test_llm_structured.py`, add one test per failure kind plus
    success: `complete` raises → `RAISED` with `error` set; returns `None`
    → `NO_RESPONSE`; content `"nope"` → `INVALID_JSON`; content `"[1]"` →
    `NOT_OBJECT`; content `'```json\n{"a": 1}\n```'` → `data == {"a": 1}`
    and `failure is None`. Also check that `max_tokens` and
    `bypass_cache` are passed through to `complete`.
- [ ] **Step 2: Run.** Expected: fails with ImportError / AttributeError.
- [ ] **Step 3: Implement both modules.** Replace the 6 schema dicts with
  `json_schema_format(...)` calls (in `episode_match_llm`,
  `filename_parser`, `rss_regex_suggestor`, and the ping in
  `llm_service`). `_LLM_EPISODE_PARSE_RESPONSE_FORMAT` and
  `_LLM_MATCH_RESPONSE_FORMAT` must keep their different `name` values
  (`"episode_parse"` and `"episode_match"`).
- [ ] **Step 4: Rewrite the callers on `request_json_object`.** Map each
  `JsonCallFailure` to the caller's existing log and `on_event` text,
  byte-for-byte. Keep the spec §6 item 6 divergence: in
  `llm_pick_candidate`, `NOT_OBJECT` emits "could not pick a candidate".
  In `filename_parser.parse_filename` and
  `RssRegexSuggestor._request`, which never caught exceptions,
  `RAISED` → `raise result.error`. In `rss_regex_suggestor`, check
  `finish_reason == "length"` after `NO_RESPONSE` and before the parse
  failures, as today. Use `optional_int` for the S/E coercion.
- [ ] **Step 5: Verify.**
  `uv run pytest tests/test_episode_match_llm.py tests/test_filename_parser.py tests/test_rss_regex_suggestor.py tests/test_llm_json.py tests/test_llm_structured.py tests/test_llm_service.py -v`.
  Expected: all pass, with existing assertions untouched.
- [ ] **Step 6: Commit.** `refactor(services): share structured-LLM call and json_schema helpers`

### Task 6: Episode lookup consolidation (S7) and the LLM-fallback tail (S8)

**Files:**
- Modify: `src/jidou/services/episode_lookup.py`, `episode_match_llm.py`, `episode_file_matching.py`
- Test: `tests/test_episode_lookup.py`, `tests/test_episode_match_llm.py`, `tests/test_episode_file_matching.py` (append)

**Interfaces:**
- Produces (private): `_first_episode(session: AsyncSession, show_id: int, *criteria: ColumnElement[bool]) -> Episode | None`.
  It always adds `Episode.show_id == show_id`, `.order_by(Episode.id)` and `.limit(1)`.
- Produces (private): `_llm_list_fallback(session, llm, show_id: int, show_title: str, filename: str, *, default_season: int | None, default_episode: int | None, on_event: OnEvent | None) -> tuple[Episode | None, int | None, int | None]`.
  It returns `(ep, s if s is not None else default_season, e if e is not None else default_episode)`.

- [ ] **Step 1: Write the failing tests.**
  - `test_llm_match_episode_final_lookup_is_ordered_and_limited`: drive
    `llm_match_episode` with a mocked LLM that returns
    `{"season": 1, "episode": 2}` and a mocked session. Capture the
    *last* statement passed to `session.execute`, and assert that
    `str(stmt.compile())` contains `"ORDER BY episodes.id"` and
    `"LIMIT"`. This is the S7 fix and is the only behavior change in the
    plan.
  - `test_match_entry_no_episode_uses_llm_season_when_list_match_has_none`:
    the entry has `season=None, episode=None`. `llm_parse_episode` (mocked)
    returns `(3, None)` and `llm_match_episode` returns `(None, None, None)`.
    Assert the result is `(None, 3, None)`.
- [ ] **Step 2: Run.** Expected: the first test fails; the second passes
  today. It guards the fallback-default semantics through the refactor.
- [ ] **Step 3: Implement.** `resolve_episode` becomes three
  `_first_episode` calls. `llm_match_episode`'s final lookup becomes
  `await resolve_episode(session, show_id, season, episode_num)`.
  `match_entry_to_episode`'s three fallback tails call
  `_llm_list_fallback`:
  - The first tail uses `default_season=fallback_season, default_episode=None`.
  - The other two use `default_season=season, default_episode=episode`.
- [ ] **Step 4: Verify.**
  `uv run pytest tests/test_episode_lookup.py tests/test_episode_match_llm.py tests/test_episode_file_matching.py tests/test_path_import.py -v`.
  Expected: all pass. Both functions must be ≤ 8 under C901.
- [ ] **Step 5: Commit.** `fix(services): llm_match_episode tolerates duplicate episode rows; dedupe lookup chain`.
  The PR body must call out the behavior change.

### Task 7: `path_parser`: rule table and media-file walker

**Files:**
- Modify: `src/jidou/services/path_parser.py`

**Interfaces:**
- Produces (private):
  ```python
  @dataclass(frozen=True)
  class _EpisodeRule:
      pattern: re.Pattern[str]
      has_season: bool                          # True: group(1)=season, group(2)=episode
      blocked_by: re.Pattern[str] | None = None  # rule skipped when this matches the stem
  _EPISODE_RULES: tuple[_EpisodeRule, ...]       # the 9 non-compact rules, in today's order
  def _compact_guess(stem: str, dir_season: int | None) -> tuple[int, int, int] | None
  def _iter_media_files(root: Path, recursive: bool) -> list[Path] | None  # None on OSError at the root
  def _build_entry(*, raw_path: str, show_dir: str, show_root: str, stem: str, dir_season: int | None) -> ParsedPathEntry
  ```
  `_build_entry` calls `_parse_episode`. It applies "directory season wins
  over filename season" and sets `is_absolute = season is None and episode is not None`.

- [ ] **Step 1: Confirm the guards exist.** Check that Task 2's golden
  table and `tests/test_path_import.py` pass:
  `uv run pytest tests/test_path_parser_episode_rules.py tests/test_path_import.py -q`.
  Expected: pass.
- [ ] **Step 2: Implement the rule table.** `_parse_episode` becomes:
  loop over `_EPISODE_RULES`; skip a rule when `blocked_by` matches; on
  the first match return `(s, e, None)`; then fall back to
  `_compact_guess`. Only the bare-trailing rule has
  `blocked_by=_NON_EPISODE_ASSET_WORD`. Keep every pattern's existing
  comment next to its rule entry.
- [ ] **Step 3: Implement the walker split.** `_iter_media_files`
  contains both the non-recursive `iterdir` branch and the `os.walk`
  branch (with the `(st_dev, st_ino)` cycle pruning and its comments).
  `scan_show_directory` becomes: resolve the root, encode the root
  strings once, call `_iter_media_files`, then
  `[_build_entry(...) for p in sorted(paths)]`. `parse_line` uses
  `_build_entry` too.
- [ ] **Step 4: Verify.**
  `uv run pytest tests/test_path_parser_episode_rules.py tests/test_path_import.py tests/test_episode_file_matching.py -v`.
  Expected: all pass. C901 must be ≤ 5 for `_parse_episode` and ≤ 6 for
  `scan_show_directory`. Lower the ratchet per the ratchet rule.
- [ ] **Step 5: Commit.** `refactor(services): table-driven episode rules and shared entry builder in path_parser`

### Task 8: SFTP directory-entry classifier (S5)

**Files:**
- Modify: `src/jidou/services/sftp_service.py`
- Test: `tests/test_sftp_service.py` (append)

**Interfaces:**
- Produces (private):
  ```python
  class _EntryKind(Enum):
      SKIP = auto(); DIRECTORY = auto(); DEFERRED_DIRECTORY = auto(); FILE = auto(); RECENT_FILE = auto()

  @dataclass(frozen=True)
  class _EntryVerdict:
      kind: _EntryKind
      path: str
      remote_file: RemoteFile | None  # set for DIRECTORY (is_dir=True, size=0) and FILE

  def _classify_entry(self, entry: Any, parent: str, pattern: str | None) -> _EntryVerdict
  ```
  The order of checks is: `.`/`..` → SKIP; directory: `is_valid_directory`
  fails → SKIP, recent mtime → DEFERRED_DIRECTORY, else DIRECTORY; file:
  `pattern` given and `fnmatch` fails → SKIP; `is_valid_media_file` fails
  → SKIP; recent mtime → RECENT_FILE; else FILE.

- [ ] **Step 1: Write `test_classify_entry`.** Parametrize it over fake
  entries (`SimpleNamespace(filename=..., attrs=SimpleNamespace(permissions=..., size=..., mtime=...))`)
  covering each of the 7 outcomes above. Include
  `pattern="*.mkv"` with an `.mp4` file → SKIP, and `pattern=None` with
  the same file → FILE.
- [ ] **Step 2: Run.** Expected: fails with AttributeError.
- [ ] **Step 3: Implement it, and rewrite the three listing methods as
  `match verdict.kind` statements:**
  - `list_remote_files`: keep FILE only. Every other kind is skipped,
    including directories, which this method never validated or walked.
  - `_collect_files_recursive`: recurse on DIRECTORY, increment
    `directories_deferred` on DEFERRED_DIRECTORY, increment
    `recently_modified_skipped` on RECENT_FILE, append on FILE.
  - `list_remote_children` (`pattern=None`): append DIRECTORY and FILE.
- [ ] **Step 4: Verify.** `uv run pytest tests/test_sftp_service.py -v`.
  Expected: all pass. Both listing hotspots must be ≤ 6.
- [ ] **Step 5: Commit.** `refactor(services): one directory-entry classifier for all SFTP listings`

---

## Phase 2 — Layering and smaller shared helpers (Medium)

### Task 9: Redis session helper, a single channel name, pubsub dependency injection (S6, L1, D3)

**Files:**
- Create: `src/jidou/services/redis_conn.py`, `tests/test_redis_conn.py`
- Modify: `cache.py`, `rate_limiter.py`, `progress.py`, `pubsub_subscriber.py`, `src/jidou/main.py`, `tests/test_pubsub.py` (wiring only), `tests/test_progress*.py` (append), `tests/test_services_architecture.py` (remove the pubsub allowlist entry)

**Interfaces:**
- Produces:
  ```python
  TASK_PROGRESS_CHANNEL: Final = "task_progress"


  @asynccontextmanager
  async def redis_session(
      url: str, *, decode_responses: bool = False
  ) -> AsyncIterator["aioredis.Redis"]: ...
  ```
  It must call `aioredis.from_url` (where `import redis.asyncio as aioredis`
  is a module-level import) at call time, so existing
  `patch("redis.asyncio.from_url")` tests keep working. It always awaits
  `aclose()`.
- Produces: `Broadcast = Callable[[str, dict[str, Any]], Awaitable[None]]`
  and `PubSubSubscriber.start(self, broadcast: Broadcast) -> None`. The
  private method `_handle_message(self, message: dict[str, Any] | None) -> None`
  contains today's per-message body.

- [ ] **Step 1: Write the tests.**
  - `test_redis_session_closes_on_exception`: `from_url` is patched to a
    mock client. Raise inside the `async with`, and assert `aclose`
    was awaited.
  - `test_emit_progress_publish_failure_still_closes_client`: `publish`
    raises `ConnectionError`. Assert `emit_progress` returns `None` and
    `aclose` was awaited once.
- [ ] **Step 2: Run.** Expected: the first fails (ImportError); the
  second passes today and guards the refactor.
- [ ] **Step 3: Implement.**
  - Replace `_get_redis` plus `try/finally aclose` in `cache.py` (5
    methods) and in `rate_limiter.acquire` with `redis_session`.
    `cache` passes `decode_responses=True`; `rate_limiter` keeps the
    default `False`.
  - `progress.emit_progress` uses `redis_session(...,
    decode_responses=True)` and `TASK_PROGRESS_CHANNEL`.
  - `pubsub_subscriber`:
    - Drop the `jidou.api` import. `start` stores `broadcast`, and
      `_handle_message` calls it.
    - The `_redis is None` guard runs once before the loop.
    - Delete the dead `pubsub = None` assignment.
    - Use `TASK_PROGRESS_CHANNEL`.
    - Delete both `REDIS_CHANNEL` constants.
  - `main.py`:
    `await pubsub_subscriber.start(manager.broadcast_to_task)`.
  - In `tests/test_pubsub.py`, pass an `AsyncMock` as `broadcast` instead
    of patching `jidou.services.pubsub_subscriber.manager`. Keep every
    assertion the same, with `mock_manager.broadcast_to_task` renamed to
    the mock.
  - Remove the pubsub entry from `_KNOWN_UPWARD_IMPORTS`.
- [ ] **Step 4: Verify.**
  `uv run pytest tests/test_redis_conn.py tests/test_cache_service.py tests/test_rate_limiter.py tests/test_progress.py tests/test_progress_service.py tests/test_pubsub.py tests/test_main.py tests/test_task_cancellation.py tests/test_services_architecture.py -v`.
  Expected: all pass. `_listen` must be ≤ 6.
- [ ] **Step 5: Commit.** `refactor(services): shared redis_session, one progress channel, inject pubsub broadcast`

### Task 10: Move show creation to the orchestrator layer (L2)

**Files:**
- Create: `src/jidou/orchestrators/show_creation_orchestrator.py`
- Modify: `src/jidou/services/show_creation.py` (keeps only `infer_content_type`, `auto_local_path`, `_ANIMATION_GENRE_ID`), `src/jidou/orchestrators/feed_onboarding_orchestrator.py`, the API route module that imports `get_or_create_show_from_tmdb` (find it with `grep -rn get_or_create_show_from_tmdb src/jidou/api`), `tests/test_show_creation.py` (imports and patch targets only), `tests/test_services_architecture.py`

**Interfaces:**
- Produces, in `show_creation_orchestrator.py`, with top-level imports
  only (no lazy imports):
  ```python
  @dataclass(frozen=True)
  class ShowCreationResult: show: Show; created: bool
  async def get_or_create_show_from_tmdb(session: AsyncSession, tmdb: TMDBService, payload: ShowCreate, *, llm: LLMService) -> ShowCreationResult
  async def _existing_show(session: AsyncSession, tmdb: TMDBService, tmdb_id: int) -> Show | None   # select + ensure_episode_group_map
  async def _sync_episodes_best_effort(session: AsyncSession, tmdb: TMDBService, show: Show) -> None  # re-raises SQLAlchemyError
  async def _generate_aliases_best_effort(session: AsyncSession, tmdb: TMDBService, llm: LLMService, show: Show) -> None
  ```
  `_existing_show` replaces both "select by tmdb_id → ensure map → return
  existing" blocks (the first-lookup block and the IntegrityError race
  block).

- [ ] **Step 1: Move the code and update imports.** Search
  `grep -rn "show_creation" src tests` to find the importers, including
  `tests/test_feed_onboarding_orchestrator.py`, which imports
  `ShowCreationResult`. `tests/test_shows_routes.py` imports
  `infer_content_type`, which stays put. **Patch targets:**
  `tests/test_show_creation.py` currently patches the *source* modules,
  for example `patch("jidou.orchestrators.tmdb_orchestrator.TMDBOrchestrator")`
  and `patch("jidou.services.tmdb_mapping.build_show_fields")`. That only
  works today because those names are imported lazily, inside the
  function. Once the new module imports them at the top, those patches no
  longer reach the code under test. Retarget every one of them to
  `jidou.orchestrators.show_creation_orchestrator.<Name>`. Leave
  `patch("jidou.config.settings")`, which covers `auto_local_path`, as it
  is. Assertions do not change.
- [ ] **Step 2: Extract the three helpers.** Keep the commit-before-aliases
  ordering and its comment.
- [ ] **Step 3: Remove both `show_creation` entries from
  `_KNOWN_UPWARD_IMPORTS`.** The set is now empty.
- [ ] **Step 4: Verify.**
  `uv run pytest tests/test_show_creation.py tests/test_shows_routes.py tests/test_feed_onboarding_orchestrator.py tests/test_services_architecture.py -v`.
  Expected: all pass. `get_or_create_show_from_tmdb` must be ≤ 7. Also
  run `uv run python -c "import jidou.main"` to prove there is no import
  cycle.
- [ ] **Step 5: Commit.** `refactor: move get_or_create_show_from_tmdb into the orchestrator layer`

### Task 11: Shared YaRSS2 filter (S11)

**Files:**
- Modify: `src/jidou/services/rss_regex_matching.py`, `feed_subscription_match.py`
- Test: `tests/test_rss_regex_matching.py` (append)

**Interfaces:**
- Produces, in `rss_regex_matching.py`:
  ```python
  def compile_pattern(pattern: str | None, ignorecase: bool) -> re.Pattern[str] | None  # ""/None -> None; raises re.error
  @dataclass(frozen=True)
  class CompiledFilter:
      include: re.Pattern[str] | None
      exclude: re.Pattern[str] | None
      def accepts(self, title: str) -> bool  # include None -> False; else include matches and (exclude None or no match)
  ```
  `evaluate_regex` keeps the `title[:MAX_TITLE_LENGTH]` truncation at its
  own call site. `feed_subscription_match._CompiledRule` holds a
  `CompiledFilter`. Its `_compile` keeps the per-pattern try/except and
  warning (spec §6 item 5), wrapping `compile_pattern`.

- [ ] **Step 1: Write `test_compiled_filter_accepts`.** Cover: include
  `None` → False; include matches with no exclude → True; include and
  exclude both match → False; case-folding off makes `"SHOW"` fail
  `"show"`.
- [ ] **Step 2: Run.** Expected: fails (ImportError).
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Verify.**
  `uv run pytest tests/test_rss_regex_matching.py tests/test_feed_subscription_match.py tests/test_rss_feed_regex_routes.py tests/test_rss_feed_entries_route.py -v`.
  Expected: all pass.
- [ ] **Step 5: Commit.** `refactor(services): one CompiledFilter for YaRSS2 include/exclude semantics`

### Task 12: `rss_stub` picker, synthetic-import constant, basename helper (S9, S10)

**Files:**
- Modify: `src/jidou/services/rss_stub.py`, `synthetic_file.py`, `file_reconciliation.py`, `path_transport.py`, `episode_file_matching.py`, `episode_match_llm.py`, `src/jidou/orchestrators/path_import_orchestrator.py`, and every file under `src/jidou/api/routes/` that contains `synthetic-import://` (after the API plan's Task 13 split; find them with `grep -rln "synthetic-import://" src/jidou/api`)
- Test: `tests/test_rss_stub_service.py`, `tests/test_synthetic_file.py`, `tests/test_path_transport.py` (append)

**Interfaces:**
- Produces:
  ```python
  # rss_stub.py
  def pick_unlinked_subscription(subs: Sequence[RssSubscription], show_title: str) -> RssSubscription | None
  # synthetic_file.py
  SYNTHETIC_IMPORT_SCHEME: Final = "synthetic-import://"
  def synthetic_remote_path(path: str) -> str            # SCHEME + path
  def is_synthetic_remote_path(remote_path: str) -> bool  # startswith(SCHEME)
  # path_transport.py
  def basename_any(path: str) -> str  # last segment after normalizing "\\" to "/"
  ```
  The SQL `LIKE` filters become `.like(f"{SYNTHETIC_IMPORT_SCHEME}%")`.

- [ ] **Step 1: Write the tests.** Use transient
  `RssSubscription(name=...)` objects with no session for
  `pick_unlinked_subscription`:
  - an exact case-insensitive name wins even when it comes after a
    higher-scoring fuzzy match;
  - two different subscriptions tied at the best fuzzy score ≥ 85 →
    `None`;
  - the best score < 85 → `None`.

  Also add `basename_any("C:\\a\\b.mkv") == "b.mkv"`,
  `basename_any("/x/y.mkv") == "y.mkv"`, `basename_any("z.mkv") == "z.mkv"`,
  and the round trip
  `is_synthetic_remote_path(synthetic_remote_path("/p"))`.
- [ ] **Step 2: Run.** Expected: fails (ImportError).
- [ ] **Step 3: Implement.** `ensure_rss_stub` calls
  `pick_unlinked_subscription`. Replace all 6 basename sites and every code
  use of the literal (7 at `71aa2e8`: 2 in services, 5 in the `shows.py` routes). After this, `grep -rn 'synthetic-import://' src` must
  show only the constant (docstrings may still mention the scheme).
- [ ] **Step 4: Verify.**
  `uv run pytest tests/test_rss_stub_service.py tests/test_synthetic_file.py tests/test_file_reconciliation.py tests/test_path_transport.py tests/test_shows_routes.py tests/test_path_import.py tests/test_episode_file_matching.py -v`.
  Expected: all pass. `ensure_rss_stub` must be ≤ 5.
- [ ] **Step 5: Commit.** `refactor(services): rss stub picker, synthetic-import helpers, basename_any`

### Task 13: TMDB surface: media-type validation, `get_show_seasons` delegate, remove the dead method (S3, D1, D4)

**Files:**
- Modify: `src/jidou/services/tmdb.py`, `tests/test_tmdb.py`

**Interfaces:**
- Produces (private): `_ANY_MEDIA: Final = frozenset({"movie", "tv", "multi"})`,
  `_TITLE_MEDIA: Final = frozenset({"movie", "tv"})`, and
  `_require_media_type(media_type: str, allowed: frozenset[str]) -> None`.
  The messages are exactly
  `f"Invalid media_type: {media_type!r}. Must be 'movie', 'tv', or 'multi'."`
  for `_ANY_MEDIA` and
  `f"Invalid media_type: {media_type!r}. Must be 'movie' or 'tv'."` for
  `_TITLE_MEDIA`.
- Changes: `get_details(self, tmdb_id: int, media_type: str = "tv", bypass_cache: bool = False)`.
  `get_show_seasons` becomes
  `return await self.get_details(tmdb_id, "tv", bypass_cache=bypass_cache)`.
  `get_episode_details` is deleted.

- [ ] **Step 1: Write `test_require_media_type_messages`.** Use
  `pytest.raises(ValueError, match=re.escape(...))` for both exact
  messages, through `search(…, "bad")` and `get_images(…, "multi")`.
- [ ] **Step 2: Implement it, and replace the 8 inline checks.** Delete
  `get_episode_details`, plus `test_get_episode_details_delegates_to_request`
  and `test_get_episode_details_invalid_episode_raises` in
  `tests/test_tmdb.py`. This is the D1 exception to "do not edit tests".
  First confirm that `grep -rn get_episode_details src` returns only the
  definition.
- [ ] **Step 3: Verify.**
  `uv run pytest tests/test_tmdb.py tests/test_orchestrators/test_tmdb_orchestrator.py tests/test_orchestrators/test_manual_match_orchestrator.py -v`.
  Expected: all pass.
- [ ] **Step 4: Commit.** `refactor(services): single media_type validator; drop unused get_episode_details`

---

## Phase 3 — Low priority cleanups and closeout

### Task 14: Small internal duplication in `progress`, `settings_service` and `show_lookup` (S12, S13, S14)

**Files:**
- Modify: `src/jidou/services/progress.py`, `settings_service.py`, `show_lookup.py`, `show_search.py`

**Interfaces:**
- Produces:
  - `progress.TERMINAL_STATUSES: Final[frozenset[str]]`, the `.value`s of
    CANCELLED, COMPLETED and FAILED.
  - `progress._select_task(celery_task_id: str, *, refresh: bool) -> Select[tuple[BackgroundTask]]`.
    `refresh=True` adds `.execution_options(populate_existing=True)`; it
    is used by `update_task_status` and `check_task_cancelled`, while
    `create_task_record` uses `refresh=False`.
  - `settings_service._get_bool(session: AsyncSession, key: str) -> bool`.
  - `show_search.escape_like` (renamed from `_escape_like`; it is now
    public because `show_lookup` imports it).
  - `show_lookup.find_show_by_name` normalizes with
    `alias_handling.sanitize_alias`.

- [ ] **Step 1: Implement.** These are pure refactors, covered by
  `tests/test_progress*.py`, `test_settings_service.py`,
  `test_show_lookup.py` and `test_show_search.py`. Add nothing else.
  Note: `update_task_status` compares `status.value`, while the
  completed-at check compares enum members. Keep both comparisons as they
  are.
- [ ] **Step 2: Verify.**
  `uv run pytest tests/test_progress.py tests/test_progress_service.py tests/test_task_cancellation.py tests/test_settings_service.py tests/test_show_lookup.py tests/test_show_search.py -v`.
  Expected: all pass.
- [ ] **Step 3: Commit.** `refactor(services): dedupe task-status, settings and LIKE-escape helpers`

### Task 15: Final ratchet, full verification, docs and graph

**Files:**
- Modify: `tests/test_services_architecture.py`, `docs/architecture.md` (only if it names moved symbols)

- [ ] **Step 1: Set `_SERVICES_MAX_COMPLEXITY = 9`.** Update the comment:
  the worst remaining function is `feed_fetch._follow_redirects`, kept on
  purpose (spec §4).
- [ ] **Step 2: Check the docs.**
  `grep -rn "show_creation\|pubsub_subscriber\|REDIS_CHANNEL\|get_episode_details" docs/*.md`
  and fix any stale references.
- [ ] **Step 3: Run the full pre-push sequence** from Global Constraints.
  Expected: everything clean.
- [ ] **Step 4: Run `graphify update .`** and commit the result.
- [ ] **Step 5: Commit.** `chore(services): final complexity ratchet (9) and docs refresh`

---

## Deferred to the merged app-wide plan

- **L3:** replace `RegexSuggestionError(status_code, …)` with
  `LLMNotConfiguredError` / `RegexSuggestionFailedError` and map them in
  the split `rss_*` route modules.
- Move `enqueue_task`, `TaskDispatchError` and `get_active_task` from
  `progress.py` into the API plan's `services/task_dispatch.py`.
- Adopt `request_json_object` / `json_schema_format` in
  `orchestrators/alias_orchestrator.py`.
- Spec §6 decisions (media extension lists, SxE caps, quality tokens).
- Rename the `jidou:tmdb_cache:*` key space now that `feed_fetch` shares
  it. This needs a flush/migration note.
