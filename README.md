# Constellarium

Private idea atlas: ideas are stars; categories and projects are the constellations that connect them. Pre-loaded with every idea from the GitHub and Knowledge Hub project folders plus the Problem Lab / ExCo chat ideas (214 ideas).

## What it is
Sign in once (main password) and you get three cards:
- **Banks** - IdeaBank and ProblemBank (the original app, `banks.html`).
- **To-do list** - tasks with dates and priority; each task can be linked to an idea or problem.
- **Passwords** - a password manager behind a **second password**. Passwords stay hidden until you click that row's eye icon (one item, for 20 s).

## Deploy to Vercel (web)
1. Push this repo to GitHub (private) and import it as a Vercel project (Framework: Other; no build command; settings come from `vercel.json`).
2. **Storage:** in the project open *Storage*, create/connect a **Neon Postgres** database. Vercel adds the connection variables (`POSTGRES_URL` / `DATABASE_URL` / `*_POSTGRES_URL`; Upstash Redis also works).
3. **Passwords** (Settings -> Environment Variables, all environments):
   - `CONSTELLARIUM_PASSWORD` - the main site password. Make it long.
   - `CONSTELLARIUM_VAULT_PASSWORD` - the second password for the password manager. Must be **different** from the main one.
   - Optional: `CONSTELLARIUM_SECRET` (signing key for sessions; defaults to the main password) and `CONSTELLARIUM_KEY` (storage prefix, default `constellarium:store`).
4. Redeploy. First sign-in fills the empty database from `seed/` (207 ideas, 7 problems). Table used: `constellarium_kv` (one row per document: the two banks, `...:todos`, `...:vault`).
- Changing `CONSTELLARIUM_VAULT_PASSWORD` later is safe: the next time you open Passwords it asks for the **old** password once and re-encrypts everything with the new one. Forgetting the vault password means the saved passwords can not be recovered (they are encrypted in your browser; the server never sees them).
- Without the main password variable the site says "not ready yet"; without a database it says "No database connected"; without the vault variable the Passwords card explains what to add. Nothing is readable without signing in.

## How the pieces stay in sync
Banks and to-do list are separate documents in the database but linked: a task stores only `{bank, id}` of its idea. The server resolves the link every time the list is read, so renaming an idea, changing its status, moving it between IdeaBank and ProblemBank (the move also re-points the task), deleting it (the task stays and shows "linked item removed") and Undo all show up correctly in the to-do list. Inside a bank, the detail panel lists and adds the tasks of that idea.

## Password manager security (what it does and does not protect)
- The server asks for the vault password before it sends anything, and every entry is encrypted in the browser (AES-256-GCM, key from the vault password via PBKDF2-SHA256, 600,000 rounds). The database only holds ciphertext; the key lives in memory only while the vault is open.
- The vault locks when you leave the page, press Lock, log out, or are idle 5 minutes.
- Not protected: a compromised device/browser, or a keylogger. Copying a password puts it on the clipboard (cleared after 20 s).

## Run locally
- **Preview the whole web experience (throw-away data):** `python -X utf8 tools/devserver.py` -> http://127.0.0.1:8780 (main `dev-main-pass`, vault `dev-vault-pass`, only for this preview).
- **Desktop exe (optional):** `.\build.ps1` (conda env `ideabank`) -> `dist\Constellarium\Constellarium.exe`; data in `%APPDATA%\Constellarium`; token-locked localhost server, no password.
- **Local test:** `python -X utf8 tools\selftest.py` (headless, throw-away data).
- To try the password mode locally: set `CONSTELLARIUM_PASSWORD` before `python constellarium.py --no-window`.

## Layout
`core.py` (data model, import, REST handler; local + web modes) - `api/index.py` (Vercel entry) - `static/` (UI, served by Vercel's CDN) - `seed/` - `vercel.json` - `.vercelignore` - `tools/` (tests, seed builder).