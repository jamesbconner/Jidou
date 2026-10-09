# RSS regex samples and real Re-Suggest

## Problem

LLM regex suggestions for RSS subscriptions are often poor (e.g. wrong token order), and
the Re-Suggest button returns the same regex repeatedly.

- Each feed stores one `regex_include_hint`: an example regex shape. The LLM never sees a
  real release name alongside the regex that matches it.
- `suggest_regex` builds an identical prompt on every call and does not pass
  `bypass_cache`, so `LLMService.complete()` returns the cached response (key: prompt,
  model, provider; 1h TTL).

## Goals

1. Replace the bare include hint with **sample name + hint** pairs.
2. Allow up to **3** pairs per feed.
3. Make Re-Suggest produce a genuinely new regex.

## Non-goals

- Changing how `regex_exclude_hint` is stored or its `""` = "no exclude needed" meaning.
- Server-side persistence of suggestion history.

## Design

### Storage

- New JSON column `rss_feeds.regex_include_samples`: list of
  `{"sample_name": str, "hint": str}`, max 3 entries. NULL/empty = no guidance.
- Alembic migration:
  - upgrade: add the column; for each feed with a non-empty `regex_include_hint`, write
    `[{"sample_name": "", "hint": <old>}]`; drop `regex_include_hint`.
  - downgrade: restore `regex_include_hint` from slot 1's hint; drop the new column.
- `regex_exclude_hint` is unchanged.

### Schemas / API

- `RssFeed` create/update/read schemas replace `regex_include_hint` with
  `regex_include_samples`.
- Validation: at most 3 entries; each `hint` must compile as a Python regex;
  `sample_name` may be empty (migrated data).
- `RssRegexSuggestRequest` gains `previous: list[str]` (max ~5 earlier `regex_include`
  suggestions, default empty).
- Regenerate `frontend/src/types/api-generated.ts` from OpenAPI.

### Prompt (`_feed_hint_prompt_suffix`)

- Each sample renders as a worked example:
  `Release "<sample_name>" is matched by regex_include "<hint>"`. Both strings pass
  through `sanitize_for_prompt`.
- Empty `sample_name` falls back to the existing "shape like ..." wording.
- The prompt instructs the model to follow the token order and structure shown in the
  samples.
- If the feed has a non-empty `regex_exclude_hint`, the route returns it verbatim as
  `regex_exclude`; the LLM generates only `regex_include`. Empty hint behavior (no
  exclude needed) is unchanged.

### Re-Suggest

- When `previous` is non-empty the route:
  - calls `llm.complete(..., bypass_cache=True)`;
  - appends "These were already suggested and rejected: ... Return a materially
    different pattern."
- If the result equals an entry in `previous`, retry once with a stronger instruction;
  if still identical, return it and log a warning.
- First-time Suggest still uses the cache.
- The edit modal keeps the session's suggestions and sends them as `previous` on each
  Re-Suggest click.

### Frontend

- `FeedFormModal`: up to 3 rows of "Sample name" + "Hint", Add row until 3, remove per
  row. Exclude hint field and "no exclude needed" checkbox unchanged. Help text tells the
  user to paste a real release title from the feed.
- `FeedsTable` "Incl. Hint" column shows the sample count (e.g. `2/3`).

## Testing

- Backend (`tests/test_rss_routes.py`): sample validation (max 3, bad regex, empty
  name); prompt content with 0/1/3 samples; Re-Suggest passes `bypass_cache` and includes
  previous patterns; duplicate-result retry; exclude-verbatim override; migration
  upgrade/downgrade data round-trip.
- Frontend: modal add/remove/limit; Re-Suggest sends `previous`.
- Update CHANGELOG and docs mentioning hints.
- Pre-push: `ruff check .`, `ruff format --check .`, `mypy src/`, `bandit -r src/ -l`,
  `pytest`, `npx tsc -b`.
