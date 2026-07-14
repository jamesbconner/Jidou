# Screenshots

A checklist of UI screenshots worth capturing and where each one slots into the docs. None of these exist yet — this is the shot list, not the gallery. Save captures to `docs/screenshots/<name>.png` (create the directory) and update the referenced doc to embed the image where noted; each target doc has an HTML comment marking the insertion point (`<!-- screenshot: name -->`) so this is a find-and-replace, not a guessing game.

General capture guidance:
- Use a library with a handful of real or realistic shows/episodes in it — empty-state screenshots are listed separately, don't fake a populated one with placeholder text.
- Browser window ~1440px wide, light theme (the app doesn't currently support a dark theme, so there's only one look to capture).
- Redact/blur any real host paths, SFTP hostnames, or API keys visible in Settings or config displays — see the `feedback_no_real_paths_in_tickets` house rule; use a generic library for every capture, not your own.
- PNG, not JPEG (UI screenshots compress better and stay crisp on text).

## Priority 1 — README and Quickstart (first impression)

| # | Screenshot | Capture | Insert into |
|---|-----------|---------|--------------|
| 1 | `dashboard-overview.png` | Dashboard landing page with pipeline donut, ingestion chart, and both Recently Added carousels populated | `README.md` hero, right under the intro paragraph |
| 2 | `add-show-search.png` | Shows → Add Show, search modal mid-search showing TMDB result cards | `quickstart.md` step 5 |
| 3 | `tasks-live-progress.png` | Tasks page with a task actively running — progress bar, current-file message, and the event log panel expanded showing several per-item entries | `quickstart.md`, after step 5, as "what running a scan looks like" |

## Priority 2 — Features doc (one per major capability)

| # | Screenshot | Capture | Insert into |
|---|-----------|---------|--------------|
| 4 | `shows-library-grid.png` | Shows page, poster grid, a mix of content types and a Data Quality amber badge visible on at least one card | `features.md` → Show library |
| 5 | `files-resolve-modal.png` | Files page, an `unmatched` file, Resolve modal open with TMDB search results | `features.md` → Episode matching |
| 6 | `show-detail-fix-eps.png` | Show Detail episode list, one episode with Fix Show/Fix Eps actions visible | `features.md` → Episode matching (manual fix) |
| 7 | `watchlist-drag-reorder.png` | Watchlist page mid-drag (drag handle + ghost row, if capturable) or at minimum the ordered list with status badges | `features.md` → Watchlist |
| 8 | `rss-subscriptions-tab.png` | RSS page, Subscriptions tab, a few rows with regex filters and an active/inactive mix | `features.md` → RSS feed integration |
| 9 | `rss-recommendations-tab.png` | RSS page, Recommendations tab with at least one flagged subscription | `features.md` → RSS feed integration |
| 10 | `data-quality-tab.png` | Shows page, Data tab, showing the per-show check table and an orphaned-tracking-record entry | `features.md` → Data Quality |
| 11 | `calendar-page.png` | Airing calendar with a mix of tracked/missing/upcoming episodes visible in the same week | `features.md` → Airing calendar |
| 12 | `dashboard-carousels.png` | Close crop on just the two Recently Added carousels (shows + episodes) | `features.md` → Dashboard |
| 13 | `settings-page.png` | Settings page, Services card showing connection-test results (green checks) plus the feature-toggle group | `features.md` → Settings, and `setup.md` → Verifying the installation |

## Priority 3 — Setup and Troubleshooting (state-dependent, capture last)

| # | Screenshot | Capture | Insert into |
|---|-----------|---------|--------------|
| 14 | `settings-connectivity-fail.png` | Settings → Services with one service (e.g. SFTP) showing a red/failed connection test and its error detail | `troubleshooting.md` → Parse cycle not detecting new SFTP files |
| 15 | `docker-compose-up-output.png` | Terminal output of `docker compose --profile default up --build -d` completing successfully (all 5 containers `Started`/`healthy`) | `setup.md` → Docker steps |
| 16 | `admin-health-response.png` | Terminal or browser output of `GET /api/admin/health` with all services `ok` | `setup.md` → Verifying the installation (currently uses a hand-typed JSON example — a real capture would replace it) |

## Explicitly out of scope for now

- Empty-state screenshots (no shows, no tasks yet) — lower value than populated states; add only if a specific doc section calls for "what you'll see on first boot."
- Mobile/responsive views — the app isn't designed mobile-first; not worth documenting until it is.
- Per-endpoint Swagger UI screenshots — `/docs` is self-documenting and changes with every schema edit; a static screenshot would go stale immediately.
