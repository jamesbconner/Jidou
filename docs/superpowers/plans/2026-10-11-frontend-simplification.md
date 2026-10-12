# Frontend Simplification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bring every function in `frontend/src` to ESLint complexity
≤ 25, from a current worst of 92. Restore the hooks boundary, so that
components never import `api/client` or call `invalidateQueries`. Do
this without changing what the user sees or which requests the app
makes.

**Architecture:**
- An ESLint complexity ratchet comes first.
- Small shared extractions come next: `ensureOk`, `useConfig`,
  `useTaskUntilDone`, invalidation helpers.
- The four oversized components are then split with three patterns:
  - one component per tab (`Settings`, `Shows`);
  - a discriminated-union modal state (`ShowDetail`);
  - a candidate-search strategy per mode (`ResolveFileModal`).

The existing page and component tests drive the real DOM through
Testing Library and MSW. They are the behavior guard, and they must
pass unchanged.

**Tech Stack:** React 19, TypeScript 6, TanStack Query 5, React Router 8,
Vite 8, Vitest 5, Testing Library, MSW, ESLint 9 (flat config).

**Spec:** `docs/superpowers/specs/2026-10-11-frontend-simplification-design.md`.
Read it first. Finding IDs (F*) and section numbers (§) refer to it.

> **Status note:** This is the last of the seven per-layer plans. It will
> be merged with the other six before execution. Line numbers were
> correct at commit `4e9a995`. Find code by its quoted text.

## Global Constraints

- **No user-visible change.** Rendered text, ARIA roles, labels,
  `data-testid`s, routes, and the set and order of HTTP requests per
  interaction stay the same. Tasks 2–4 may remove duplicate *refetches*
  of the same key, but they never remove a distinct request.
- **The existing tests are the contract.** `src/tests/**` must pass with
  **no edits to existing assertions**. Only import paths may change
  (for example, a test importing a helper that moved). New tests may be
  added.
- **The hooks boundary** after Task 4: no file under `src/pages/` or
  `src/components/` imports `@/api/client` or calls `useQueryClient`,
  except `components/ErrorBoundary` if it needs the client for a reset.
  Task 4's ESLint rule enforces this.
- **Node / npm:** use Node ≥ 24 with `npm ci` (spec §6 item 4). Run
  every command from `frontend/`, or with `npm --prefix frontend`.
- **Checks before every push, in this order:** `npm run lint` →
  `npx tsc -b` → `npm test` → `npm run build`. If anything outside
  `frontend/` changed, also run the backend pre-push sequence from the
  other plans.
- **Style:** match the existing code: function components, named exports
  for components (default export only for pages, as today), `@/` imports,
  Prettier formatting (`npm run format`), and a short JSDoc comment on
  each new hook or component explaining *why* it exists.
- **Git:** never commit to `main`. Use one branch and one PR per row of
  "PR grouping", work serially, and merge with `--merge`. Each PR ends with
  a version-bump commit following the repo convention (see commit
  `69c7290`; it touches `frontend/package.json`).
- **Commit trailer:** end every commit message with
  `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. **A non-OK response from each of the four client paths** (JSON,
   form, list with total, blob). Expected: `ApiError(status, detail)`,
   with `detail` taken from the body's `detail` field, or from
   `statusText` when the body isn't JSON. Pinned by Task 2's
   `client.test.ts`.
2. **An RSS import or publish task that finishes.** Expected: polling
   stops at a terminal status, and when the task completes, the feeds and
   subscriptions lists refetch once. Pinned by the existing
   `RSS.test.tsx`, plus Task 3's `useTaskUntilDone.test.ts`.
3. **Two `ShowDetail` modals opened one after the other** (for example,
   Link File for one episode, then Assign Import for another). Expected:
   only one modal is mounted at a time, and the second gets the correct
   episode. Pinned by Task 6's `test: opening a second modal replaces
   the first`.
4. **Switching `Shows` tabs and coming back.** Expected: the filters
   persisted in `localStorage` survive the round trip, and the debounced
   search is not reset. Pinned by the existing `Shows.test.tsx`, plus
   Task 7's `utils/showFilters.test.ts`.
5. **Switching `ResolveFileModal` search modes.** Expected: queries for
   inactive modes are disabled (no request), and an already selected
   candidate is cleared, as today. Pinned by the existing
   `ResolveFileModal.test.tsx`, plus Task 8's mode-switch test.

## File Structure

| File | Status | Responsibility |
|---|---|---|
| `frontend/eslint.config.js` | Modify | `complexity` ratchet (Task 1); restricted imports (Task 4) |
| `src/api/client.ts` | Modify | `ensureOk` |
| `src/hooks/useConfig.ts` | Create | `configKeys`, `useConfig` |
| `src/hooks/useTasks.ts` | Modify | `TERMINAL_TASK_STATUSES`, `useTaskUntilDone` |
| `src/hooks/invalidation.ts` | Create | Named cross-domain invalidation helpers |
| `src/hooks/useSettingsActions.ts` | Create | `useConnectionTest`, `useTriggerWithDryRun` |
| `src/pages/settings/{GeneralTab,FeaturesTab,ServicesTab,DataTab}.tsx` | Create | Split of `Settings.tsx` |
| `src/pages/showDetail/{modalState.ts,ShowDetailModals.tsx,useShowDetailData.ts}` | Create | Split of `ShowDetail.tsx` |
| `src/pages/shows/{LibraryTab,MissingTab,DataQualityTab}.tsx`, `src/utils/showFilters.ts` | Create | Split of `Shows.tsx` |
| `src/components/resolveFile/{useResolveCandidates.ts,CandidateList.tsx,ResolveConfirm.tsx}` | Create | Split of `ResolveFileModal.tsx` |
| `src/types/api.ts` | Modify | Dead types and the `ContentType` alias (Task 10) |

## PR grouping

| PR | Branch | Tasks | Must run after |
|---|---|---|---|
| 1 | `refactor/fe-complexity-ratchet` | 1, 2 | — |
| 2 | `refactor/fe-hooks-boundary` | 3, 4 | PR 1 |
| 3 | `refactor/fe-settings-split` | 5 | PR 2 |
| 4 | `refactor/fe-showdetail-modals` | 6 | PR 2 |
| 5 | `refactor/fe-shows-split` | 7 | PR 2 |
| 6 | `refactor/fe-resolve-file-strategy` | 8 | PR 2 |
| 7 | `refactor/fe-remaining-hotspots` | 9 | PRs 3–6 |
| 8 | `chore/fe-types-cleanup` | 10, 11 | PR 7; after schemas plan PRs 1 and 3 if they are scheduled |

### Complexity ratchet rule

`complexity: ['error', N]` in `eslint.config.js` applies to `src/**`, and
`src/tests/**` is exempt. `N` starts at **92** (Task 1). Each hotspot
task lowers it to the new maximum reported by:

```bash
npx eslint src --ignore-pattern 'src/tests/**' --rule '{"complexity":["warn",1]}' -f json \
  | node -e 'let d="";process.stdin.on("data",c=>d+=c).on("end",()=>{let m=0;for(const f of JSON.parse(d))for(const x of f.messages)if(x.ruleId==="complexity"){const n=+x.message.match(/complexity of (\d+)/)[1];if(n>m)m=n}console.log(m)})'
```

It ends at **25** (Task 11). The value only goes down; it never goes up.

---

## Phase 0 — Guard and small extractions

### Task 1: Complexity ratchet (F13)

**Files:**
- Modify: `frontend/eslint.config.js`

- [ ] **Step 1: Add the rule.** Add `complexity: ['error', 92]` to the
  `**/*.{ts,tsx}` rules block, and add a separate config object for
  `src/tests/**` that sets `complexity: 'off'`. Put a comment above the
  rule pointing at the ratchet rule in this plan.
- [ ] **Step 2: Prove it bites.** Set the limit to 91 and confirm
  `npm run lint` fails on `Settings`. Restore 92 and confirm
  `npm run lint` passes.
- [ ] **Step 3: Commit.** `build(frontend): ESLint complexity ratchet (92)`

### Task 2: `ensureOk` in the API client (F6)

**Files:**
- Modify: `src/api/client.ts`
- Create: `src/tests/api/client.test.ts`

**Interfaces:**
- Produces (module-private):
  `async function ensureOk(res: Response): Promise<Response>`. It throws
  `new ApiError(res.status, body.detail ?? res.statusText)`, using
  `res.statusText` when the body is not JSON, and otherwise returns
  `res`. All four request functions call it.

- [ ] **Step 1: Write `client.test.ts`.** Stub `fetch` with
  `vi.stubGlobal`. For each of `api.get`, `api.postForm`,
  `api.getWithTotal` and `api.downloadBlob`:
  - a 404 with `{detail: "nope"}` → rejects with
    `ApiError { status: 404, message: "nope" }`;
  - a 500 with a non-JSON body and `statusText "Server Error"` → rejects
    with `message "Server Error"`.

  Also test success paths: `getWithTotal` reads `X-Total-Count`;
  `downloadBlob` parses the filename from `Content-Disposition`, falling
  back to `"download"`; a 204 from `api.delete` resolves to `undefined`.
- [ ] **Step 2: Run.** `npx vitest run src/tests/api/client.test.ts`.
  Expected: passes against the current code. It is a guard.
- [ ] **Step 3: Implement `ensureOk`.**
- [ ] **Step 4: Verify** with the full check sequence. Expected: all
  green.
- [ ] **Step 5: Commit.** `refactor(frontend): single ensureOk error path in the API client`

---

## Phase 1 — Hooks boundary

### Task 3: `useConfig`, `useTaskUntilDone`, RSS keys (F1, F2, F3)

**Files:**
- Create: `src/hooks/useConfig.ts`, `src/tests/hooks/useConfig.test.ts`, `src/tests/hooks/useTaskUntilDone.test.ts`
- Modify: `src/hooks/useTasks.ts`, `src/pages/RSS.tsx`, and the 7 inline config-query sites (`EditPathModal`, `LinkFileModal`, `RematchModal`, `NavBar`, `ResolveFileModal`, `ShowDetail`, `Settings`)

**Interfaces:**
- Produces:
  ```ts
  // hooks/useConfig.ts
  export const configKeys = { all: ['config'] as const }
  export function useConfig(): UseQueryResult<AppConfig>   // staleTime: 60_000
  // hooks/useTasks.ts
  export const TERMINAL_TASK_STATUSES: ReadonlySet<TaskStatus> = new Set(['completed', 'failed', 'cancelled'])
  export function useTaskUntilDone(id: number | null, opts?: { intervalMs?: number }): UseQueryResult<TaskRead>
      // key taskKeys.detail(id); enabled: id != null && id > 0; refetchInterval stops on a terminal status; default 3000
  ```
  - The key stays `['config']`, so every observer shares one cache entry,
    exactly as today.
  - `Settings` gains `staleTime: 60_000`. That is the only behavior
    nuance: Settings no longer refetches config on every mount within
    one minute. Call it out in the PR.
  - `RSS.tsx` replaces its two inline queries with
    `useTaskUntilDone(importTaskId)` and
    `useTaskUntilDone(publishTaskId)`. Its completion effects use
    `rssKeys.feeds` / `rssKeys.subscriptions` instead of literal arrays.
    The local `TERMINAL` set is deleted.

- [ ] **Step 1: Write the hook tests**, using a `QueryClientProvider`
  wrapper and MSW.
  - `useTaskUntilDone`: polls until the status becomes `completed`, then
    stops (advance fake timers and count requests). With `id = null` it
    makes no request.
  - `useConfig`: two hooks mounted together make one request.
- [ ] **Step 2: Run.** Expected: they fail (the modules don't exist yet).
- [ ] **Step 3: Implement it, and replace all the call sites.**
- [ ] **Step 4: Verify** with the full check sequence. Expected: all
  green. `RSS.test.tsx` passes unchanged.
- [ ] **Step 5: Commit.** `refactor(frontend): useConfig, useTaskUntilDone and rssKeys replace inline queries`

### Task 4: Invalidation helpers; move mutations into hooks; enforce the boundary (F4, F5)

**Files:**
- Create: `src/hooks/invalidation.ts`
- Modify: `src/hooks/useShows.ts`, `useOrphans.ts`, `useTasks.ts`, `useFiles.ts`, `useRss.ts`, `src/pages/Files.tsx`, `src/pages/RSS.tsx`, `src/pages/Dashboard.tsx`, `src/pages/ShowDetail.tsx`, `src/pages/Settings.tsx`, `src/components/{LinkFileModal,FixEpisodeModal,RecommendationsTab,EditPathModal,RematchModal,NavBar,ResolveFileModal}.tsx`, `frontend/eslint.config.js`

**Interfaces:**
- Produces:
  ```ts
  export function invalidateLibrary(qc: QueryClient): Promise<void>     // showKeys.all + fileKeys.all + dashboardKeys.all
  export function invalidateShowsAndFiles(qc: QueryClient): Promise<void> // showKeys.all + fileKeys.all
  ```
  Add only helpers that have two or more callers after the move.
- Remove redundant invalidations:
  - `showKeys.detail(id)`, `showKeys.episodes(id)` and
    `showKeys.episodeGroups(id)` when `showKeys.all` is already
    invalidated in the same `onSuccess`;
  - duplicate `orphanKeys.all` and `taskKeys.all` calls.
- Every component-level `useMutation` or `useQuery` that calls `api.*`
  moves into the matching domain hook file, as a named hook that owns
  its `onSuccess`. Examples: `useAssignFileShow` in `useFiles.ts` for
  `Files.tsx` lines ~41 and ~124; the link and fix mutations; the
  Dashboard stats, timeline and pipeline queries into `useDashboard.ts`.
  Settings' connection tests and seed/backfill triggers move in Task 5.
- ESLint: add `no-restricted-imports` for `@/api/client` and
  `no-restricted-syntax` for `useQueryClient`, both scoped to
  `src/pages/**` and `src/components/**`. If Task 5 has not landed yet,
  add a temporary override for `src/pages/Settings.tsx`; Task 5 removes
  it.

- [ ] **Step 1: Move each mutation and query, one file per commit.**
  After each move, run the test file for that page or component.
- [ ] **Step 2: Remove the redundant invalidations.** For each removal,
  confirm the remaining key is a prefix of the removed one by reading
  the key factory.
- [ ] **Step 3: Add the ESLint restrictions.** Run `npm run lint`.
  Expected: clean, apart from the temporary Settings override if it is
  still needed.
- [ ] **Step 4: Verify** with the full check sequence. Expected: all
  green, with no test edits.
- [ ] **Step 5: Commit** in several commits, ending with
  `build(frontend): enforce the hooks boundary in pages and components`.

---

## Phase 2 — Split the four hotspots

### Task 5: Split `Settings` by tab (F8)

**Files:**
- Create: `src/pages/settings/GeneralTab.tsx`, `FeaturesTab.tsx`, `ServicesTab.tsx`, `DataTab.tsx`, `src/hooks/useSettingsActions.ts`
- Modify: `src/pages/Settings.tsx` (it keeps the tab bar, the `Tab` state and `LiveImportTask`; `TextImportSection`, `DatabaseExportSection` and `DatabaseImportSection` move into `DataTab`, and `ServiceRow` moves into `ServicesTab`)

**Interfaces:**
- Produces:
  ```ts
  export type ConnectionService = 'tmdb' | 'sftp' | 'redis' | 'llm'
  export function useConnectionTest(service: ConnectionService): UseMutationResult<ConnectionTestResult, ApiError, void>
  export function useTriggerWithDryRun(taskType: 'seed' | 'backfill_show_metadata'): { dryRun: UseMutationResult<…>; live: UseMutationResult<…> }
  ```
  Each `*Tab` component takes only the props it needs, and reads its
  data through hooks. The JSX of each `{tab === 'x' && (…)}` block moves
  verbatim into its tab's component.

- [ ] **Step 1: Move each tab block into its component, one per
  commit.** After each move, run `npx vitest run src/tests/pages/Settings.test.tsx`.
- [ ] **Step 2: Replace the 4 inline connection tests and the 2 dry/live
  pairs** with the new hooks. Remove Task 4's temporary ESLint override.
- [ ] **Step 3: Lower the ratchet** per the rule. Expected: `Settings`
  ≤ 10, each tab ≤ 20, and `ServiceRow` (28) dropping toward 20 once its
  test-mutation props come from the hook.
- [ ] **Step 4: Verify** with the full check sequence. Expected: all
  green, and `Settings.test.tsx` unchanged.
- [ ] **Step 5: Commit.** `refactor(frontend): split Settings into per-tab components`

### Task 6: `ShowDetail` modal state machine (F7)

**Files:**
- Create: `src/pages/showDetail/modalState.ts`, `ShowDetailModals.tsx`, `useShowDetailData.ts`, `src/tests/pages/showDetail.modalState.test.ts`
- Modify: `src/pages/ShowDetail.tsx`

**Interfaces:**
- Produces:
  ```ts
  export type ShowDetailModal =
    | { kind: 'rematch' } | { kind: 'path' } | { kind: 'contentType' } | { kind: 'aliases' }
    | { kind: 'image' } | { kind: 'deleteConfirm' } | { kind: 'scanLocalFiles' } | { kind: 'episodeGroups' }
    | { kind: 'scanLocalMovieFile' } | { kind: 'fixMovieFile' }
    | { kind: 'fileRematch'; file: FileRead } | { kind: 'fileFixEps'; file: FileRead }
    | { kind: 'assignImport'; episode: EpisodeList } | { kind: 'linkFile'; episode: EpisodeList }
    | { kind: 'rssSubscription'; subscription: RssSubscriptionRead }
  export function ShowDetailModals(props: { show: ShowRead; modal: ShowDetailModal | null; onClose: () => void; … }): JSX.Element | null
  export function useShowDetailData(showId: number): { show, episodes, movieFiles, config, rssSubs, rssFeeds, watchlistEntries, isLoading }
  ```
  - The 12 flag `useState`s become one
    `const [modal, setModal] = useState<ShowDetailModal | null>(null)`.
  - `isDeleting` and `episodesTab` remain separate state; they are not
    modal flags.
  - Each opener calls `setModal({ kind: … })`, and every close callback
    is `setModal(null)`.
  - `ShowDetailModals` is a `switch (modal.kind)` with exhaustive
    `never` checking. Each case renders exactly the JSX that exists
    today.

- [ ] **Step 1: Write the tests.**
  - `modalState.test.ts`: the `ShowDetailModal` union is checked
    exhaustively. A helper `modalKindLabel(kind)` uses a `never` default,
    so adding a variant without handling it fails `tsc`.
  - In `ShowDetail.test.tsx`, append `test: opening a second modal
    replaces the first`. Open Link File on episode A, close it, open
    Assign Import on episode B, and assert only B's dialog is in the
    document.
- [ ] **Step 2: Run.** Expected: the new UI test passes today (it is a
  guard), and the union test fails (the module doesn't exist yet).
- [ ] **Step 3: Implement it.** Move the data hooks into
  `useShowDetailData`.
- [ ] **Step 4: Lower the ratchet.** Expected: `ShowDetail` ≤ 25.
- [ ] **Step 5: Verify** with the full check sequence. Expected: all
  green, with the existing `ShowDetail.test.tsx` assertions unchanged.
- [ ] **Step 6: Commit.** `refactor(frontend): ShowDetail modal state as a discriminated union`

### Task 7: Split `Shows` by tab (F9)

**Files:**
- Create: `src/pages/shows/LibraryTab.tsx`, `MissingTab.tsx`, `DataQualityTab.tsx`, `src/utils/showFilters.ts`, `src/tests/utils/showFilters.test.ts`
- Modify: `src/pages/Shows.tsx`

**Interfaces:**
- `sortShows`, `applyFilters`, `applyMissingFilters` and the two arrow
  helpers at lines ~104 and ~137 (complexity 17 and 22) move verbatim to
  `utils/showFilters.ts` and are exported.
- Each tab component owns its own `useMemo` derivations and its own
  `useLocalStorageState`, using the same storage keys as today, so
  persisted filters survive.
- `Shows.tsx` keeps the `tab` state, the shared queries
  (`useShows('title_asc', 10000)`, `useWatchlist`, `useOrphans`) and the
  TMDB modal, and passes the data down as props.

- [ ] **Step 1: Write `showFilters.test.ts`** before moving anything.
  Copy representative fixture rows from `Shows.test.tsx`, then assert
  sort order for each `ShowSortOrder` and filtering by genre, language,
  status and missing-only.
- [ ] **Step 2: Run.** Expected: fails on the import, until Step 3 moves
  the functions.
- [ ] **Step 3: Move the helpers, then each tab, one per commit.**
- [ ] **Step 4: Lower the ratchet.** Expected: `Shows` ≤ 10, each tab
  ≤ 25.
- [ ] **Step 5: Verify** with the full check sequence. Expected: all
  green, and `Shows.test.tsx` unchanged.
- [ ] **Step 6: Commit.** `refactor(frontend): split Shows into per-tab components; pure filters in utils`

### Task 8: `ResolveFileModal` search strategy (F10)

**Files:**
- Create: `src/components/resolveFile/useResolveCandidates.ts`, `CandidateList.tsx`, `ResolveConfirm.tsx`, `src/tests/components/resolveFile.useResolveCandidates.test.ts`
- Modify: `src/components/ResolveFileModal.tsx`

**Interfaces:**
- Produces:
  ```ts
  export type SearchMode = 'suggestions' | 'title' | 'tmdb_id'
  export interface Candidate { key: string; source: 'tmdb' | 'local'; tmdb?: TmdbSuggestion; local?: ShowSearchResult }
  export function useResolveCandidates(args: { mode: SearchMode; fileId: number; query: string; tmdbId: number | null; tmdbMediaType: 'tv' | 'movie' }): { candidates: Candidate[]; isLoading: boolean; error: unknown }
  ```
  - Each mode's query stays behind exactly the `enabled` condition it has
    today, so inactive modes make no request.
  - `CandidateList` renders the shared result grid.
  - `ResolveConfirm` holds the content-type and folder-name form, and
    the `useRematchFile` submit.

- [ ] **Step 1: Write the mode-switch test.** Using MSW, mount the hook
  in `suggestions` mode, switch to `tmdb_id`, and assert no suggestions
  request is made after the switch. Assert the candidates come from the
  TMDB-details response.
- [ ] **Step 2: Run.** Expected: fails (the module doesn't exist yet).
- [ ] **Step 3: Implement it.**
- [ ] **Step 4: Lower the ratchet.** Expected: `ResolveFileModal` ≤ 20.
- [ ] **Step 5: Verify** with the full check sequence. Expected: all
  green, and `ResolveFileModal.test.tsx` unchanged.
- [ ] **Step 6: Commit.** `refactor(frontend): ResolveFileModal candidate search as a per-mode strategy`

---

## Phase 3 — Remaining hotspots and closeout

### Task 9: Bring the remaining functions to ≤ 25

**Files:**
- Modify: whichever of these still exceed 25 after Tasks 3–8 (re-measure first): `pages/Files.tsx` (34), `components/AddShowFromFeedPane.tsx` (34), `pages/RSS.tsx` (32), `components/LinkFileModal.tsx` (29), `components/RematchModal.tsx` (28), `components/ScanLocalFilesModal.tsx` row renderer (27), `components/FeedFormModal.tsx` (26)

**Interfaces:**
- No new shared modules.
- In each file, extract the largest conditional JSX branch into a local
  component in the same file, and the largest data block into a hook in
  the matching `hooks/` file. A form with more than 6 `useState`s
  (`FeedFormModal`, `AddShowFromFeedPane`) moves to a single `useReducer`
  with a typed action union.

- [ ] **Step 1: Re-measure** with the ratchet command, and list the
  functions above 25.
- [ ] **Step 2: Fix each one in its own commit.** Run that component's
  test file after each change.
- [ ] **Step 3: Lower the ratchet to 25.**
- [ ] **Step 4: Verify** with the full check sequence. Expected: all
  green.
- [ ] **Step 5: Commit** (several). The last one is
  `build(frontend): complexity ratchet at 25`.

### Task 10: Dead types and the `ContentType` alias (F11, F12)

**Files:**
- Modify: `src/types/api.ts`

- [ ] **Step 1: Re-prove the four types are dead.** For each of
  `EpisodeRead`, `FileList`, `WsMessageType` and `PathImportResult`, run
  `grep -rnw <Name> src --include=*.ts --include=*.tsx`. The only hit
  allowed is the definition in `types/api.ts`.
- [ ] **Step 2: Delete them.** Replace
  `export type ContentType = 'tv' | 'anime' | 'movie'` with
  `export type ContentType = components['schemas']['ContentType']`.
- [ ] **Step 3: Verify.** `npx tsc -b` and `npm test`. Expected: green.
- [ ] **Step 4: Commit.** `chore(frontend): drop dead API types; alias the generated ContentType`

### Task 11: Closeout

- [ ] **Step 1: Confirm the ratchet is 25** and `npm run lint` passes.
- [ ] **Step 2: Add a "Frontend structure" section** to
  `docs/developer.md`. It covers the hooks boundary (and the ESLint rule
  that enforces it), the key factories, `useConfig`,
  `useTaskUntilDone`, the per-tab page layout, and the complexity budget.
  Also note that Node ≥ 24 is required for `npm ci` (spec §6 item 4).
- [ ] **Step 3: Run the full check sequence**, plus `graphify update .`
  from the repository root.
- [ ] **Step 4: Commit.** `docs(frontend): document the hooks boundary and complexity budget`

---

## Deferred to the merged app-wide plan

- Spec §6 decisions:
  - replacing the `limit=10000` "fetch everything" calls (7 call sites)
    with a real "all" endpoint or server-side pagination;
  - deleting the `api.ts` `Omit<>` overrides once the backend types are
    tightened (schemas SC8 / §6 item 3, models M5);
  - a CI job that regenerates the API types and fails on drift.
- Re-running `make.py generate-types` after every backend plan that
  changes OpenAPI. The schemas plan's Tasks 5–7 already require it.
