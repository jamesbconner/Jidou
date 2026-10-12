# Frontend Simplification — Analysis (Spec)

**Date:** 2026-10-11 (same series as the six backend layer specs)
**Scope:** `frontend/src`: React 19, TanStack Query 5, React Router 8,
Tailwind 4, Vite 8, TypeScript 6. About 15.6k lines of hand-written
source, plus the 9k-line generated `types/api-generated.ts`. 55 test
files (Vitest, Testing Library, MSW).
**Status:** Analysis complete. The companion plan is
`docs/superpowers/plans/2026-10-11-frontend-simplification.md`. This is
the seventh and last per-layer analysis. After this, all seven plans
(API, services, orchestrators, workers, models, schemas, frontend) get
merged.

Measured at commit `4e9a995`, with Node 22 / npm 10 locally (the project
targets Node ≥ 24):

- `tsc -b` and `npm run lint` are clean.
- `vitest run` passes: **54 files, 413 tests**.
- Complexity was measured with ESLint's core `complexity` rule (threshold
  15) and `max-lines-per-function` (150). Neither rule is enabled in
  `eslint.config.js` today.

---

## 1. Summary

The frontend has a sound skeleton:
- one fetch client (`api/client.ts`);
- query-key factories per domain (`showKeys`, `fileKeys`, `rssKeys`, …);
- domain hooks under `hooks/`;
- shared UI primitives under `components/ui/`, which every `*Modal.tsx`
  uses;
- pure helpers under `utils/`, each with tests.

The complexity sits in **four page-sized components**. Each of them
mixes data access, UI state for many modals or tabs, and several tabs'
worth of JSX:

| Component | ESLint complexity | Function lines | `useState` |
|---|---|---|---|
| `pages/Settings.tsx` `Settings` | **92** | 589 | 7 (+ 4 inline connection-test mutations and 4 seed/backfill mutations) |
| `pages/ShowDetail.tsx` `ShowDetail` | **77** | 621 | 20 (12 of them modal open/target flags) |
| `components/ResolveFileModal.tsx` | **76** | 427 | 9 (3 search modes) |
| `pages/Shows.tsx` `Shows` | **73** | 736 | 10 (3 tabs, 13 `useMemo`) |

Another 25 functions exceed 15, including `Files` (34),
`AddShowFromFeedPane` (34), `RSS` (32), `LinkFileModal` (29),
`RematchModal` (28), `Settings/ServiceRow` (28) and
`ScanLocalFilesModal`'s row renderer (27).

The rest of the findings are about the **hooks boundary**. Several
components import `api/client` and `useQueryClient` directly, build
query keys by hand, and copy the same queries and cache invalidations.

## 2. Structural map

```
main.tsx ─ App.tsx (router, QueryClientProvider, ThemeProvider, WsConnectionProvider)
  pages/ (10) ──► hooks/ (17 domain hooks + key factories) ──► api/client.ts (fetch + ApiError)
     │  └──► components/ (≈60; ui/ primitives: Modal, Button, Card, Badge, SegmentedControl, …)
     ★ 5 pages + 6 components also import api/client directly; 5 own useQueryClient + invalidations
  hooks/useTaskProgress ─► api/websocket.ts ─► stores/wsConnection
  types/api.ts (hand-maintained: 39 aliases, 8 Omit<> overrides, ~40 hand-written interfaces)
     └──► types/api-generated.ts (openapi-typescript, regenerated manually via make.py generate-types)
  utils/ (pure: calendarRange, missingEpisodes, paths, dqChecks, …)
```

Places that bypass the hooks boundary:

- **Importing `api/client` directly:** `pages/{ShowDetail, Dashboard,
  RSS, Files, Settings}`, `components/{EditPathModal, LinkFileModal,
  RematchModal, FixEpisodeModal, NavBar, ResolveFileModal}`.
- **Calling `invalidateQueries` directly:** `pages/{RSS, Files}`,
  `components/{LinkFileModal, FixEpisodeModal, RecommendationsTab}`.

## 3. Findings

| # | Finding | Where | Target |
|---|---|---|---|
| F1 | `useQuery({ queryKey: ['config'], queryFn: () => api.get<AppConfig>('/config'), staleTime: 60_000 })` written inline **7 times**. `Settings` alone leaves out `staleTime`. | `EditPathModal`, `LinkFileModal`, `RematchModal`, `NavBar`, `ResolveFileModal`, `ShowDetail`, `Settings` | `hooks/useConfig.ts: useConfig()`, with `configKeys` |
| F2 | The same "fetch the task and poll every 3 s until it reaches a terminal status" query is written twice, under the key `['tasks', id]`. That key differs from `taskKeys.detail(id)`, so the same task is cached twice. A local `TERMINAL` set copies the backend's. | `pages/RSS.tsx` | `hooks/useTasks.ts: useTaskUntilDone(id, { intervalMs })` on `taskKeys.detail`; `TERMINAL_TASK_STATUSES` exported from `useTasks` |
| F3 | Hand-written key arrays `['rss', 'feeds']` / `['rss', 'subscriptions']` | `pages/RSS.tsx` (3 calls) | `rssKeys.feeds` / `rssKeys.subscriptions` |
| F4 | Redundant invalidations. `showKeys.all` (`['shows']`) is a prefix of `detail`, `episodes` and `episodeGroups`, but hooks invalidate both. One `onSuccess` invalidates `orphanKeys.all` twice; another invalidates `taskKeys.all` twice. | `hooks/useShows.ts` (5 blocks), `useOrphans.ts`, `useTasks.ts` | Invalidate the widest key once. Name each recurring cross-domain set as a helper (for example `invalidateLibrary(qc)` = shows, files and dashboard). |
| F5 | Mutations and cache invalidations inside components | `pages/Files.tsx` (×2: files + shows), `LinkFileModal`, `FixEpisodeModal` (files + shows), `RecommendationsTab`, `RSS` | Move into `hooks/useFiles.ts` / `useRss.ts` mutations that own their `onSuccess` |
| F6 | `api/client.ts`: the "not ok → parse `detail` → throw `ApiError`" block is copied **4 times** (`request`, `requestForm`, `requestWithTotal`, `downloadBlob`) | `api/client.ts` | `async function ensureOk(res: Response): Promise<Response>` |
| F7 | 12 separate "is modal X open / which row is it for" states | `pages/ShowDetail.tsx` | A discriminated-union state machine: `type ShowDetailModal = { kind: 'rematch' } \| { kind: 'linkFile'; episode: EpisodeList } \| …`, held in one `useState<ShowDetailModal \| null>`, with `<ShowDetailModals>` rendering the active one |
| F8 | One component renders 4 tabs, 4 connection tests and 2 dry/live task pairs | `pages/Settings.tsx` | One component per tab (`SettingsGeneralTab`, `SettingsFeaturesTab`, `SettingsServicesTab`, `SettingsDataTab`), plus `useConnectionTest(service)` and `useTriggerWithDryRun(path)` hooks |
| F9 | One component renders 3 tabs, with filters and memos for each | `pages/Shows.tsx` | `ShowsLibraryTab`, `ShowsMissingTab`, `ShowsDataQualityTab`. The existing pure `sortShows` / `applyFilters` / `applyMissingFilters` move to `utils/showFilters.ts` with tests. |
| F10 | One modal with 3 search modes, each with its own query, loading state and result list | `components/ResolveFileModal.tsx` | **Strategy per mode**: `useResolveCandidates(mode, …) → { candidates, isLoading }` plus a `<CandidateList>` shared by all three modes. The confirm step becomes its own component. |
| F11 | Dead hand-written types | `types/api.ts`: `EpisodeRead`, `FileList`, `WsMessageType`, `PathImportResult` (no references in `src/` outside their own definitions) | Delete. Three of them mirror the backend schemas that the schemas plan's SC1 deletes. |
| F12 | `ContentType` written out by hand as `'tv' \| 'anime' \| 'movie'` while the generated `components['schemas']['ContentType']` exists | `types/api.ts` | Alias the generated type |
| F13 | No complexity budget | `eslint.config.js` | Add `complexity: ['error', N]` as a ratchet. It starts at 92 and ends at 25 (§7). |

## 4. Complexity hotspots and replacement patterns

| Component | Now | Pattern | Target |
|---|---|---|---|
| `Settings` | 92 | Split per tab (F8); `useConnectionTest`; `useTriggerWithDryRun` | page ≤ 10; each tab ≤ 20 |
| `ShowDetail` | 77 | Modal state machine (F7); move the `useConfig`, watchlist and RSS-stub data into a `useShowDetailData(showId)` hook | page ≤ 25 |
| `ResolveFileModal` | 76 | Search strategy per mode (F10) | ≤ 20 |
| `Shows` | 73 | Split per tab (F9); `useShowsLibraryData()` | page ≤ 10; each tab ≤ 25 |
| `Files` 34, `RSS` 32 | — | F2/F3/F5 move data access into hooks; the rest of the conditional rendering goes into row components | ≤ 25 |
| The other 23 functions above 15 | — | Covered by the ratchet. Each one is touched only if it is still above the final budget after the shared extractions. | ≤ 25 |

## 5. Dead or redundant paths

F4 (redundant invalidations) and F11 (dead types) cover these. There is
no dead component; every `components/*.tsx` file is imported somewhere.

## 6. Decisions (not changed by this plan)

1. **Fetching the whole list with `limit=10000`.** `useShows('title_asc',
   10000)` and `useWatchlist(undefined, 10000)` are called from 7
   places, and comments in `Shows.tsx` and `Watchlist.tsx` already call
   that limit a sentinel. A real "all" endpoint or server-side
   pagination is a backend contract change.
2. **Keeping a hand-maintained `api.ts` on top of generated types.** 8
   `Omit<>` overrides exist only because the backend types are loose:
   `genres`/`networks` (schemas spec §6 item 3), `tracked_source`
   (models M5 / schemas SC8), `event_log`. When those backend changes
   land, delete the matching overrides; that belongs to the merged plan.
3. **CI type-drift check.** `make.py generate-types` is manual and needs
   a running API. A CI job that regenerates the types and fails on a
   diff would catch drift, but it needs the API container in the
   frontend job.
4. **Node versions.** The project says Node ≥ 24 and CI uses 24. With
   Node 22 / npm 10, `npm ci` rejects the lockfile because it resolves
   vitest's optional `msw` peer differently. This is not a repository
   defect, but the README should say "Node 24 is required for
   `npm ci`".

## 7. Priorities

- **High:** F13 complexity ratchet (first), F1 `useConfig`, F2/F3
  task-polling hook and keys, F6 client `ensureOk`, then the four big
  components (F7, F8, F9, F10).
- **Medium:** F4 invalidation cleanup, F5 moving mutations into hooks.
- **Low:** F11 dead types, F12 `ContentType` alias.
- **Final complexity budget: 25.** Start at 92, lower it after each
  hotspot task, and never raise it.

## 8. Interaction with the other plans

- **Schemas plan SC1** deletes the backend's `EpisodeRead`, `FileList`
  and `import_schema`. F11 deletes the matching frontend types. Either
  order works.
- **Schemas plan Tasks 5–7** regenerate `api-generated.ts`. Run this
  plan's type tasks (F11, F12) after those regenerations, or rebase onto
  them.
- **Models plan M2 / Task 3** centralize the backend's terminal task
  statuses. F2 exports the frontend's equivalent once, from
  `hooks/useTasks.ts`. It cannot come from the generated types:
  OpenAPI carries enum values, not sets.
- **The API plan's route splits** do not change any URL. No frontend
  task depends on them.
