# B&A — Constellarium

## 2026-11-06 — Initial build
- **Before:** IdeaBank was a web app (Python server + browser UI, Vercel-oriented). No private exe; project ideas lived across 19 GitHub folders and Knowledge Hub/Projects.
- **Change:** New folder `GitHub\Constellarium`: IdeaBank UI/logic reworked for local-only use (cloud/password code removed, token + Host/Origin gate, data in %APPDATA%), native PySide6 window, PyInstaller exe, bundled seed of 214 ideas (93 compiled from project MVP/HANDOFF/README files + 121 chat ideas). Switched build env to conda `ideabank`; deleted `.venv`. Edge → Opera → native window after user feedback.
- **Why:** User asked for the same tool locally and privately as an individual exe, with all project ideas compiled.
- **MVP alignment:** all MUSTs in MVP.md met; "no browser" constraint added mid-session.
- **Verified:** selftest 16/16 against the built exe; exe launches a window (title + Qt WebEngine process), page title loads, closing the window exits the app and removes instance.json; seeding gives 214 ideas.
- **Not verified:** visual look of the Qt window, Export/Import dialogs, graph interaction inside the exe; folder build starts in ~3 s.


## 2026-11-06 - Folder build + loading screen
- **Before:** onefile exe, 20-45 s blank wait at start.
- **Change:** switched to onedir (window in ~2-3 s warm) and added a native splash screen shown before the server starts.
- **Why:** user asked for a loading screen for the startup duration.
- **MVP alignment:** same MUSTs; startup UX only.
- **Verified:** selftest 16/16 on the new build; app opens and exits on close; splash rendered to PNG and inspected.
- **Not verified:** splash seen live on screen; first launch after a fresh build can take ~30 s.

## 2026-11-12 - Filtered export, contacts, login lock
- **Before:** Export dumped everything; ideas had no contact fields; no password.
- **Change:** export dialog with filters/format; primary+secondary contact on ideas; PBKDF2 login lock with test-mode prefill (Constellarium) and IdeaBank local lock + prefill.
- **Why:** user asked for export after filtering by tag/category, contacts for context, and a prefilled login lock on both apps for testing.
- **MVP alignment:** extends MVP; MVP.md change log updated.
- **Verified:** UI tested in browser pane (4 ideas for tag pdf, 17 for Desktop Tools incl. sub-categories; CSV + Markdown contain contacts; edit/save contacts); source selftest incl. lock + contacts passes; IdeaBank lock tested over HTTP.
- **Not verified:** exe build with these changes (running), real save-dialog download of exports in the Qt window, IdeaBank login screen visually.


## 2026-11-12 - Password removed from Constellarium; startup investigation
- **Before:** Constellarium had a login lock with prefilled test password.
- **Change:** removed the lock code, CLI options, UI prefill and the real lock.json; added crash logging, no-proxy flag, transparent-window-behind-splash, FastServer.
- **Why:** user: password not needed; user also asked to stop opening the window during tests.
- **MVP alignment:** MVP.md change log updated; privacy token/Host checks stay.
- **Verified:** source selftest passes (no-password check included).
- **Not verified:** rebuilt exe results, and whether --no-proxy-server fixed the ~24 s window load.

## 2026-11-12 - Matrix removed, zoomable treemap added (Constellarium)
- **Before:** a coverage matrix had been ported from IdeaBank; with Constellarium's 214 ideas it was 49 rows x 40 columns and had no zoom.
- **Change:** removed the matrix (code, CSS, option, '__none' project filter); added static/treemap.js: zoomable treemap with semantic zoom, project highlight, breadcrumb/Esc/wheel zoom.
- **Why:** user: wanted to see everything and zoom in for detail; matrix wasn't the right fit.
- **MVP alignment:** serves the auto-generated overview/graph requirement; calm by default (labels only when readable).
- **Verified:** see HANDOFF; browser pane vs source server, plus source selftest and exe selftest (result below if recorded).
- **Not verified:** exe window visually; IdeaBank unchanged (matrix kept there).

## 2026-11-12 - Window larger than screen (treemap cut off)
- **Before:** exe window opened at 1440x900 on a 1280x752 usable screen; bottom/right hung off-screen.
- **Change:** size to availableGeometry + showMaximized; treemap height clamped to the viewport.
- **Why:** user screenshot showed the treemap cut off at the bottom.
- **MVP alignment:** usability fix.
- **Verified:** diagnosed from the user's real screen size; exe selftest result pending/recorded when the build finishes; JS syntax ok.
- **Not verified:** the window on screen.

## 2026-11-13 - Switch to web deployment (Vercel)
- **Before:** Constellarium was a local Windows exe (token-locked localhost server, file store, no password).
- **Change:** web mode in core.py (database storage, password login, same-origin writes, seed on first load), api/index.py, vercel.json, .vercelignore, .gitignore, README deploy guide, tools/webtest.py (fake-Redis test); keep-alive ping limited to localhost. No feature changes; local exe path untouched.
- **Why:** user asked to switch to web deployment and update the folder for Vercel, then commit/push, then delete the exe/dist/build folders.
- **MVP alignment:** MVP.md updated (cloud no longer out of scope; web acceptance criteria; password required on a public URL).
- **Verified:** webtest 25 checks (3 of 4 runs fully green; 1 run lost a call to the fake DB to a loopback stall); local selftest 19/19 x2.
- **Not verified:** real Vercel/Neon deployment, live password env var.
