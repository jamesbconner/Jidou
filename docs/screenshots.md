# Screenshots

All planned screenshots have been captured to `docs/screenshots/` and are embedded in `README.md`, `quickstart.md`, `features.md`, `setup.md`, and `troubleshooting.md`. This page is now just the capture guidance for retaking one after a UI change, not a to-do list.

General capture guidance:
- Use a library with a handful of real or realistic shows/episodes in it — empty-state screenshots are lower priority; don't fake a populated one with placeholder text.
- Browser window ~1440px wide, light theme (the app doesn't currently support a dark theme, so there's only one look to capture).
- Redact/blur any real host paths, SFTP hostnames, or API keys visible in Settings or config displays — see the `feedback_no_real_paths_in_tickets` house rule; use a generic library for every capture, not your own.
- PNG, not JPEG (UI screenshots compress better and stay crisp on text).
- Retake a screenshot when the UI it shows changes enough to make the capture misleading (a renamed button, a redesigned page, a moved feature) — check `docs/screenshots/<name>.png` against the live page rather than assuming it's still accurate.

## Explicitly out of scope

- Empty-state screenshots (no shows, no tasks yet) — lower value than populated states; add only if a specific doc section calls for "what you'll see on first boot."
- Mobile/responsive views — the app isn't designed mobile-first; not worth documenting until it is.
- Per-endpoint Swagger UI screenshots — `/docs` is self-documenting and changes with every schema edit; a static screenshot would go stale immediately.
