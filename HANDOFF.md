# HANDOFF — Constellarium

_Last updated: 2026-11-06_

## Status
v1.0 built: `dist\Constellarium\Constellarium.exe` (folder build ~559 MB,  native PySide6/Qt window, no browser). First launch seeds `%APPDATA%\Constellarium\store.json` with 214 ideas / 50 categories / 39 projects (93 project ideas from GitHub + Knowledge Hub Projects, 121 Problem Lab/ExCo chat ideas). The user's real store was created by a test launch on 2026-11-06 (214 ideas, unedited).

## Run / build / test
```
dist\Constellarium\Constellarium.exe                              # run
.\build.ps1                                         # rebuild (conda env ideabank: PySide6, pyinstaller, pillow)
python -X utf8 tools\selftest.py dist\Constellarium\Constellarium.exe   # 16 privacy + API checks (temp data folder)
python -X utf8 tools\build_seed.py                  # regenerate seed after editing tools\ideas_catalog.py
Constellarium.exe --reseed                          # merge bundled ideas into the store (by title, no duplicates)
```
Env var `CONSTELLARIUM_HOME` or `--home` redirects the data folder (used for tests).

## Layout
core.py (store, import, HTTP handler + token/Host/Origin gate) · constellarium.py (internal server + Qt window) · static/ (UI copied from IdeaBank, rebranded) · seed/seed_data.json · tools/ (ideas_catalog, build_seed, selftest, make_icon, rebrand_static) · assets/ icon.

## Decisions
- Native Qt window (user rejected Edge/Opera/browser). The UI is the IdeaBank HTML embedded via Qt WebEngine; an internal 127.0.0.1 server with a per-launch token feeds it.
- Single instance: a second launch exits if one is running (one writer on the store).
- Data outside the exe folder (%APPDATA%) so rebuilds never touch it.

## Known problems / not verified
- Splash screen (drawn in code, constellation logo + animated 'Loading your ideas...') shows before the server starts and hides when the page has loaded (15 s safety timeout). Splash image verified by rendering it to PNG; its on-screen timing was not captured. Warm start ~2 s; the first launch after a fresh build was ~30 s (antivirus scan of the new files).
- Folder build (onedir) chosen for speed: window ready in ~3 s (onefile took 20-45 s). The exe must stay beside its _internal folder; use a shortcut.
- Not visually checked in the Qt window (no screenshot tool); verified via window title, remote-debug page title, process exit on close, and the HTTP checks. File Save dialog for Export (downloadRequested) and file picker for Import not click-tested.
- Idea compilation is hand-curated from MVP/HANDOFF/README files; the many auto-backfilled MVPs say "unknown", so those ideas are thin. Episode plan entries use file names and plan headings only.
- Edge/Opera attempts (abandoned) never connected; no longer in the code.

## Next actions
2. Click-test Export/Import and graph views in the exe.
3. Review the compiled ideas (statuses, categories).



## 2026-11-12 additions
- **Export after filtering:** Export button opens a dialog: scope (current sidebar filters or everything), extra category (incl. sub-categories) and tag pickers, format CSV / Markdown report / JSON. Filtered JSON is name-based (merges on import); "Everything" JSON is the full backup (replaces on import).
- **Contacts:** every idea has Primary contact and Secondary contact (free text: name + email/Telegram/phone). Shown in the edit form (autocomplete), idea detail panel, list cards, searchable, in CSV/JSON/Markdown export and import columns primaryContact / secondaryContact.
- **Login lock REMOVED (2026-11-12, user: not needed).** Constellarium has no password; /api/auth reports required=false. The per-launch session token, Host/Origin checks and 127.0.0.1-only binding remain. (IdeaBank keeps its own password lock.)
- Contacts and filtered export are in Constellarium only; IdeaBank (web) was not given them.

## Startup slowness (open, 2026-11-12)
- Page load in the window took ~24-50 s in the last tests although the internal server answers in <1 s. Not caused by the hostname lookup (FastServer added anyway) or hidden-window loading (window now shown at opacity 0 behind the splash). Latest attempt: --no-proxy-server for the embedded browser (Chromium proxy auto-detect); its effect is NOT verified because the user asked me to stop opening the window for tests. Before this, page load measured ~3 s.
- Do not launch the window repeatedly for testing; selftest.py uses --no-window.

## 2026-11-12: Zoomable treemap (replaces the coverage matrix, which was removed from Constellarium)
- Graph tab > Layout > 'Zoomable treemap (all ideas, click to zoom)': every idea is a tile inside nested category blocks (static/treemap.js, squarified layout, no libraries). Tile colour = status (new grey, exploring yellow, in-progress blue, done green, shelved dark). Overview shows all ideas with block headers only; labels appear only where a tile is big enough, so zooming in reveals sub-blocks and idea titles.
- Zoom: click a block (or scroll up over it) to zoom into it; scroll down, Esc or the path above to zoom out. Readable tile click = details panel, double-click = edit. 'Highlight project' dims every idea not in that project. Sidebar filters (category/tag/status/search) apply to it.
- Why not the matrix: with 214 ideas / 49 categories / 39 projects it was 40 columns wide. The matrix still exists in IdeaBank (pushed), by the user's choice.
- Verified in the browser pane against a source server (not the exe window): 214 tiles in 49 blocks, 0 tiles out of bounds; zoom levels 214 -> 121 -> 29 tiles with labels 0 -> 8 -> 29; click, Esc, breadcrumb and wheel zoom; tile select opens the panel; highlight UniSuite lit 11 of 214; no console errors.
- Not verified: the exe window (not opened per user request); very small windows; keyboard-only use.

## 2026-11-12: window-size bug fixed (treemap looked cut off)
- Cause: the exe window was requested at 1440x900 but the user's screen work area is 1280x752 (100% scale), so ~150 px of the bottom hung off-screen and clipped the treemap (and the app's bottom edge). Fix: window is now sized to the available screen area and shown maximized (constellarium.py); the treemap also clamps its height to the visible viewport (static/treemap.js).
- Not verified: visually in the exe (window not opened per the user's earlier request); the user should relaunch and confirm the bottom edge.

## 2026-11-13: web deployment (Vercel) added - features unchanged
- **How it works:** core.py now has a WEB mode, switched on by Vercel's VERCEL env var: data in a database (Neon Postgres via SQL-over-HTTP, or Upstash Redis REST; same code as IdeaBank, table constellarium_kv / key constellarium:store), first load of an empty database seeds it from seed/seed_data.json, password login (env CONSTELLARIUM_PASSWORD, HMAC session cookie, Secure/HttpOnly/SameSite=Strict, same-origin check on writes). api/index.py is the serverless entry (QUERY_PATH, no static); vercel.json serves static/ from the CDN and rewrites /api/* to it; .vercelignore keeps the exe tooling out. The local exe path is unchanged (token lock, file store; selftest 19/19).
- **Only UI-file change:** the keep-alive ping in static/index.html now runs only on localhost/127.0.0.1 (it would wake the serverless function every 10 s). All features are the same.
- **Needs from the user on Vercel:** connect a Neon (or Upstash) database to the project and set CONSTELLARIUM_PASSWORD, then redeploy. I did NOT touch Vercel and set no password.
- **Retry added:** storage calls retry once on a transient network error (6 s timeout each, inside the 15 s function limit).
- **Verified:** tools/webtest.py (25 checks) against the real handler + a fake Upstash Redis: passes in 3 of 4 runs; the 4th failed only because a loopback call to the fake database stalled (this Windows machine's loopback is flaky: see IdeaBank notes). Local selftest 19/19 twice.
- **NOT verified:** a real Vercel deployment; the Neon code path (copied from IdeaBank, no database here); the Vercel Python runtime's handling of the handler (HTTP/1.0 set for it). Pushed to a private GitHub repo (Amirrahman19/Constellarium); build outputs (exe, dist/, build/) were deleted after the push per the user, and can be rebuilt with .\build.ps1.

## 2026-11-13: why the deployed site showed no ideas
- The user saw an empty app and 'Import failed: Server not configured: set the CONSTELLARIUM_PASSWORD environment variable.' => the Vercel project has NO CONSTELLARIUM_PASSWORD (and probably no database connected yet). Nothing loads or imports until both exist; the 214 seeded ideas appear automatically on the first login after a database is connected and the project redeployed.
- UX fix (static/app.js showSetupProblem): when the server answers 503 (no password / no database / database unreachable) the app now shows a permanent 'Your ideas can't be loaded yet' panel with the exact fix instead of a brief toast and an empty screen. Verified in the browser pane for both cases (no password; password but no database) against the real handler. Not yet committed/pushed.
- The user's note: they can connect the Neon DB themselves. Steps are in README 'Deploy to Vercel'.

## 2026-11-15: visible delete for ideas (and categories/projects), with Undo
- Before: deleting an idea was only possible inside the Edit dialog (click idea -> Edit -> Delete); categories/projects likewise. Now: (1) a small muted x on every idea card in the Ideas tab (turns red on hover); (2) 'Delete' next to 'Edit' in the idea detail panel (graph / tables / treemap); (3) 'Select' in the Ideas toolbar -> tick cards (or 'Select all shown', e.g. after filtering to a category) -> 'Delete selected'; (4) 'Delete' next to 'Edit' on every row of the Categories & Projects tab. Every idea delete asks to confirm and then shows an Undo toast (9 s) that restores the ideas with their original ids and links. Deleting a category/sub-category keeps its ideas (they move up a level; the confirm says so); deleting a project only removes the link.
- Backend: POST /api/ideas/delete {ids} (returns the removed ideas + back-links, writes a safety backup) and POST /api/ideas/restore {ideas, links} (Undo; ids that already exist are skipped).
- 'Sub-ideas': the app has no separate sub-idea object; ideas sit under categories/sub-categories, so deleting everything in a sub-category = filter to it, Select all shown, Delete selected.
- Verified in the browser pane against throwaway ideas (all removed afterwards): card x, confirm text, Undo with links, Select mode, bulk delete + undo, detail-panel Delete, Manage-tab Delete for a throwaway category/project; API checks in tools/selftest.py (Constellarium, 24/24 x2). Not verified: deployed sites; touch devices; the exe window. Not committed/pushed.

## 2026-11-16: fixed 'Log out' -> 'Error response 501 Unsupported method ({}GET)'
- **Cause:** the local server keeps connections open (HTTP/1.1 keep-alive, added earlier to stop Windows resets). POST /api/logout answered without reading the request body ('{}'); the leftover bytes were glued onto the next request on that connection ('{}GET' -> 501). The same happened on any early exit that does not read the body: 401 (not logged in), 403 (cross-origin / no token), and unknown-route 404.
- **Fix:** _mutate now always reads the request body first (once, cached via _read_body; _body parses the cache); a body over the size limit gets 413 and the connection is closed instead of read. Applied to IdeaBank (api/_core.py) and Constellarium (core.py). The deployed handlers use HTTP/1.0 (one request per connection), so Vercel was never affected; this only hit local servers.
- **Verified:** reproduced before the fix (log out -> next request 501; 401/403 -> 400), after the fix 8/8 on IdeaBank (log out, 401, unknown bank, 404, cross-origin, wrong password, 200 KB body, 413) and 4/4 on Constellarium; real Log out button clicked in the browser pane: no error page, login box shown. Regression: IdeaBank three-bank 23, log 16, transfer 20; Constellarium selftest 24, web-mode 25 (3 runs). Test data purged again (86 / 5 / 30). Not committed/pushed.

## 2026-11-16: two banks, IdeaBank and ProblemBank (no To-Do bank)
- **What:** the same app now holds two separate banks with identical features: IdeaBank (207 ideas, blue) and ProblemBank (7 problems, orange). Switcher with live counts in the top bar; ProblemBank re-words idea -> problem ("+ New problem", "Search problems"); each bank has its own categories, projects, contacts, treemap/graph, export/import, backups. Move between banks: arrow button on every card, Move... in the detail panel and edit dialog, and Select -> Move... for several; popup = confirm -> spinner (locked) -> animated tick with Undo / OK / Open <bank> (or an error with Try again). Categories and projects are re-created by name in the target, links among moved items kept, links to items left behind dropped (reported, restored by Undo), same-title items renamed '(from <Bank>)'.
- **Why these 7 are problems:** the 'Problem Discovery & Research' items (SEEPO healthcare statements, satellite-data insights, reading-friction interviews, EV survey, Validated Problem Briefs, methodology timeline, product-manage the builders) describe problems to solve, not ideas to build. They are filed in ProblemBank under domains Healthcare / Climate & Space / Education / Method & Delivery. Everything else stays in IdeaBank. Edit tools/split_seed.py (or just Move items in the app) to change the split.
- **Storage:** per-bank files store.json (IdeaBank, unchanged) and store-problembank.json, backups/ and backups-problembank/; web: keys constellarium:store and constellarium:store:problembank (table constellarium_kv). Seeds: seed/seed_ideabank.json + seed/seed_problembank.json (replace seed_data.json; tools/split_seed.py made them). Existing installs migrate automatically on first start: the 7 problems are MOVED out of IdeaBank (with the user's edits, via transfer_ideas, with a backup) into a new ProblemBank. API: every request carries X-Bank (default ideabank); GET /api/banks; POST /api/ideas/transfer {ids,to,links,titles}.
- **Verified (source, temp data folders, browser pane):** new tools check script (scratchpad cs_banktest.py, 23 checks: fresh seed 207/7, separation, transfer, dropped links, Undo, rename, errors, migration keeping edits); tools/selftest.py all passed; tools/webtest.py all passed (fake Redis); keep-alive test all passed; UI in the browser pane: switcher, wording, accent, move popup states (confirm, spinner, tick, Undo, badges), no console errors.
- **Not verified:** the exe window (not opened, not rebuilt: dist/ was deleted earlier); real Vercel/Neon (ProblemBank key is created on the first load after redeploy); mobile layout. build_seed.py still writes the old single seed (stale; not used). Not committed/pushed.



## 2026-11-23: hub redesign - Banks / To-do list / Passwords (Vercel + Neon, two passwords)
- **What:** `static/index.html` is now the home (sign-in -> three cards). The old app moved to `static/banks.html` (unchanged features; new "<- Home" link, `?bank=` and `?q=` deep links, login handled by the home page, a Tasks section in the idea detail panel). Home views: static/hub.js (login, cards, Banks chooser, routing), todo.js, vault.js, shell.js/shell.css (shared). No inline scripts anywhere (CSP).
- **Passwords:** main `CONSTELLARIUM_PASSWORD`; second `CONSTELLARIUM_VAULT_PASSWORD` (must differ). Session cookie = signed token with expiry (14 days; old cookies stop working = one re-login); vault cookie = separate signed token, 30 min sliding, path /api. Wrong password = 1-1.5 s delay.
- **Vault:** server stores only ciphertext ({iv,ct} blobs per entry: `meta` = name/username/url, `secret` = password/notes; AAD = id:field). Browser derives the AES-GCM key (PBKDF2 600k) from the vault password, key only in memory; vault locks on leaving the view, Lock button, logout, 5 min idle. Eye icon decrypts ONE entry and re-masks after 20 s; the DOM never holds other passwords. Changing the vault password in Vercel triggers a one-time "enter old password" re-encrypt (POST /api/vault/rekey).
- **To-do:** document `constellarium:store:todos` (file `todos.json` locally). Task = title, notes, due (YYYY-MM-DD), priority, done/doneAt, link {bank,id}. Link resolved on every read (rename/status/move/delete/Undo stay in sync); transfer_ideas re-points links (relink_todos). Hub counts use the browser's date (X-Today header).
- **API added:** GET /api/summary, /api/items, /api/todos, /api/todos/for/<bank>/<id>; POST/PUT/DELETE /api/todos[/id], POST /api/todos/clear-done; /api/vault/{status,unlock,lock,check,rekey,entries[/id]}.
- **vercel.json:** CSP, HSTS, Permissions-Policy added (same CSP as core.CSP).
- **To deploy (not done by me):** commit + push, set both env vars in Vercel (Neon already connected per user), redeploy, sign in, open Passwords once (first unlock creates the vault with your vault password).
- **Verified:** tools/hubtest.py 40 checks (vault gating, forged/expired tokens, ciphertext-only storage, to-do CRUD, sync: rename/transfer/delete/Undo, summary/X-Today, logout) against the real Vercel handler + fake Redis; webtest.py and selftest.py still ALL PASSED; browser pane (tools/devserver.py): login, hub, Banks chooser, to-do add/edit/link, deep link into ProblemBank, Tasks in detail panel, vault unlock/wrong password/add/reveal one/re-mask/leave-relock/vault-password-change migration, encrypted file has no plaintext, mobile 375 px.
- **Not verified:** real Vercel + Neon (SQL path `_pg_get/_pg_set` is shared with the banks but not exercised by the new keys here), real phone, clipboard copy in a browser, Safari/Firefox WebCrypto, the exe (not rebuilt; web is the target), bank app at small widths (pre-existing crowded top bar), the Done tab / Clear completed / priority UI (API-tested only).
- **Known limits:** each document is saved whole (last write wins): editing the same list from two devices within seconds can overwrite; the home page refreshes counts/tasks when the tab regains focus. Lost vault password = lost entries by design. Mistake to avoid: an empty folder `C:\AMIRRA~1` was created at the drive root by a mis-targeted write; delete it manually (safe, empty).
