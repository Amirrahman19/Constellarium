# MVP — Constellarium

## Goal
A private, local, single-user version of IdeaBank delivered as one native Windows exe (no browser, no server to run, no cloud), pre-loaded with every project idea found in `Documents\GitHub` and `Desktop\Knowledge Hub\Projects`. (User request 2026-11-06.)

## Users and context
Amir Rahman only. Windows 11, offline. Conda env `ideabank` (PySide6, PyInstaller, Pillow) for building.

## Requirements (MUST)
- [x] Same tool as IdeaBank: categorised ideas, projects, tags, status, related ideas, auto-generated node graphs (tables board / full network / category-project map), import/export, backups
- [x] Local and private: data in `%APPDATA%\Constellarium`, no network calls, internal 127.0.0.1 server locked by a per-launch token + Host/Origin checks
- [x] Individual exe: `dist\Constellarium\Constellarium.exe` (folder build, runs in place), native Qt window (no Edge/Opera/browser)
- [x] New, creatively named folder in GitHub (Constellarium)
- [x] Compiled ideas from all GitHub projects + Knowledge Hub projects (see `tools/ideas_catalog.py`) plus the Problem Lab / ExCo chat ideas from IdeaBank
- [x] Conda env `ideabank` for builds; no local .venv

## Requirements (SHOULD / later)
- Auto-rescan of project folders for new ideas; app icon polish; code signing.

## Out of scope
Accounts, multi-user, auto-deploys by the assistant (the user pushes; Vercel deploys from GitHub).

## Constraints
The exe (desktop) path must not use Edge/Opera or any browser (user, 2026-11-06). Web deployment (2026-11-13) must not change any feature; it adds a password login (CONSTELLARIUM_PASSWORD) because a public URL needs one. No commits unless asked.

## Acceptance criteria
Web: 	ools/webtest.py passes (login gate, database seed/persist/backup, Vercel config) and the Vercel deployment shows the seeded ideas after login. Exe: starts a window, shows the seeded ideas, edits persist across restarts, `tools/selftest.py <exe>` passes.

## Change requests log
| Date | Requested by | Change | Status |
|---|---|---|---|
| 2026-11-06 | Amir | Same tool, local + private, individual exe, new creatively named folder, compile ALL project ideas from GitHub + Knowledge Hub/Projects | done (see HANDOFF for what is verified) |
| 2026-11-06 | Amir | Use conda env `ideabank`; delete local venv; keep the new name | done |
| 2026-11-06 | Amir | Do not use Edge (then Opera); "I'm asking for a direct exe" - no browser at all | done: native PySide6 window |

| 2026-11-12 | Amir | (1) set password prefilled for testing (ambiguous - Constellarium has no login; see HANDOFF); (2) export after filtering by tag/category; (3) add primary/secondary contacts to ideas for more context | (2),(3) in progress |
| 2026-11-12 | Amir | Remove the password from Constellarium (not needed); stop opening the window repeatedly while testing | done (lock removed; startup slowness still open) |
| 2026-11-12 | Amir | Put the coverage matrix in Constellarium too | Done in source; exe rebuilt (headless checks pending) |
| 2026-11-12 | Amir | Remove the coverage matrix; add a zoomable treemap, only to Constellarium | Done in source; exe rebuild running |
| 2026-11-13 | Amir | Switch Constellarium to web deployment on Vercel; update the project folder; no feature changes; then commit and push (private repo Amirrahman19/Constellarium); after the push delete the exe, dist and build folders | Done in source (api/index.py, vercel.json, web mode in core.py); see HANDOFF for what is verified |
| 2026-11-15 | Amir | Add a visible feature to delete ideas or sub-ideas, in both apps | Done locally (not committed/pushed) |
