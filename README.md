# Constellarium

Private idea atlas: ideas are stars; categories and projects are the constellations that connect them. Pre-loaded with every idea from the GitHub and Knowledge Hub project folders plus the Problem Lab / ExCo chat ideas (214 ideas).

## Deploy to Vercel (web)
1. Push this repo to GitHub (private) and import it as a new Vercel project (Framework: Other; no build command; settings come from `vercel.json`).
2. **Storage:** in the Vercel project open *Storage*, create/connect a **Neon Postgres** (or Upstash Redis) database and connect it to this project. Vercel adds the connection variables; the app detects them (`POSTGRES_URL` / `DATABASE_URL` / `*_POSTGRES_URL`, or `UPSTASH_REDIS_REST_URL` + `UPSTASH_REDIS_REST_TOKEN`).
3. **Password:** add the environment variable `CONSTELLARIUM_PASSWORD` (the login password). Optional: `CONSTELLARIUM_SECRET` (cookie signing key, defaults to the password) and `CONSTELLARIUM_KEY` (storage key, default `constellarium:store`).
4. Redeploy. On first login the empty database is filled from `seed/seed_data.json` (214 ideas); after that the database is the source of truth. `Export` -> JSON gives a full backup; `Import` restores it.
- Without the password variable the site answers "Server not configured"; without a database it answers "No database connected". Nothing is readable without logging in.
- Test without cloud: `python -X utf8 tools/webtest.py` (runs the real Vercel handler against a fake Upstash Redis on your machine).

## Run locally
- **Desktop exe (optional):** `.\build.ps1` (conda env `ideabank`) -> `dist\Constellarium\Constellarium.exe`; data in `%APPDATA%\Constellarium`; token-locked localhost server, no password.
- **Local test:** `python -X utf8 tools\selftest.py` (headless, throw-away data).
- To try the password mode locally: set `CONSTELLARIUM_PASSWORD` before `python constellarium.py --no-window`.

## Layout
`core.py` (data model, import, REST handler; local + web modes) - `api/index.py` (Vercel entry) - `static/` (UI, served by Vercel's CDN) - `seed/` - `vercel.json` - `.vercelignore` - `tools/` (tests, seed builder).