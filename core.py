"""Constellarium core: data model, import logic, REST handler. Standard library only.

Two ways to run (same features, same UI):
  * LOCAL (the exe / `python constellarium.py`): binds to 127.0.0.1 only, every request needs a random per-launch
    session token, Host/Origin checks block DNS-rebinding and cross-site writes, data lives in
    %APPDATA%\\Constellarium (override: CONSTELLARIUM_HOME); no network calls at all.
  * WEB (Vercel, see api/index.py + vercel.json): the same handler behind a password login. Data lives in a
    database (Neon Postgres or Upstash Redis, via plain HTTPS REST calls); on first use the database is filled
    from the bundled seed. Switched on by Vercel's VERCEL env var; the password is CONSTELLARIUM_PASSWORD.
"""
import hashlib
import hmac
import json
import os
import shutil
import sys
import threading
import time
import urllib.error
import urllib.request
import uuid
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import parse_qs, urlparse

FROZEN = getattr(sys, "frozen", False)
BUNDLE = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))   # read-only bundled resources
STATIC = BUNDLE / "static"
SEED = BUNDLE / "seed" / "seed_data.json"


def home_dir():
    env = os.environ.get("CONSTELLARIUM_HOME")
    if env:
        return Path(env)
    return Path(os.environ.get("APPDATA") or Path.home()) / "Constellarium"


HOME = home_dir()
STORE = HOME / "store.json"
BACKUPS = HOME / "backups"
LOCK = threading.RLock()

PALETTE = ["#4f8cff", "#f2994a", "#27ae60", "#bb6bd9", "#eb5757", "#2dccd3",
           "#e2b93b", "#f2709c", "#8d6e63", "#7c8cf8", "#56c596", "#c0ca33"]
STATUSES = ["new", "exploring", "in-progress", "done", "shelved"]
MAX_BODY = 32 * 1024 * 1024
_last_backup = 0.0

# set by constellarium.py at start-up (local mode)
SESSION_TOKEN = ""
ALLOWED_HOSTS = set()
LAST_PING = {"t": 0.0, "seen": False}

# ---- web deployment config (all optional locally) ----
ON_WEB = bool(os.environ.get("VERCEL"))
PASSWORD = os.environ.get("CONSTELLARIUM_PASSWORD", "")
PW_MODE = ON_WEB or bool(PASSWORD)          # password login instead of the per-launch token
REDIS_URL = os.environ.get("UPSTASH_REDIS_REST_URL") or os.environ.get("KV_REST_API_URL")
REDIS_TOKEN = os.environ.get("UPSTASH_REDIS_REST_TOKEN") or os.environ.get("KV_REST_API_TOKEN")
REDIS_KEY = os.environ.get("CONSTELLARIUM_KEY", "constellarium:store")


def _find_pg_url():
    """Neon / Vercel Postgres connection string (any integration prefix, e.g. CONSTELLARIUM_DB_POSTGRES_URL)."""
    for name in ("POSTGRES_URL", "DATABASE_URL"):
        for prefix in ("CONSTELLARIUM_DB_", ""):
            if os.environ.get(prefix + name):
                return os.environ[prefix + name]
    for name, val in os.environ.items():
        if val and (name.endswith("_POSTGRES_URL") or name.endswith("_DATABASE_URL")):
            return val
    return ""


PG_URL = _find_pg_url()
REMOTE = bool((REDIS_URL and REDIS_TOKEN) or PG_URL)


class StorageError(RuntimeError):
    pass


def now():
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def new_id():
    return uuid.uuid4().hex[:10]


def empty_store():
    return {"categories": [], "projects": [], "ideas": []}


# ---------------------------------------------------------------- storage
def _redis(*cmd):
    """Minimal Upstash / Vercel-KV REST client (stdlib only)."""
    req = urllib.request.Request(REDIS_URL, data=json.dumps(list(cmd)).encode("utf-8"), method="POST",
                                 headers={"Authorization": "Bearer " + REDIS_TOKEN, "Content-Type": "application/json"})
    out = None
    for attempt in (1, 2):          # one retry on a transient network error (the commands used here are idempotent)
        try:
            with urllib.request.urlopen(req, timeout=6) as r:
                out = json.load(r)
            break
        except Exception as e:  # network / auth problems
            if attempt == 2:
                raise StorageError(f"storage request failed: {e}")
            time.sleep(0.3)
    if isinstance(out, dict) and out.get("error"):
        raise StorageError("storage error: " + str(out["error"]))
    return out.get("result") if isinstance(out, dict) else None


_pg_ready = False


def _sql(query, params=()):
    """Neon 'SQL over HTTP' (stdlib only): POST https://<host>/sql with the connection string in a header."""
    host = urlparse(PG_URL).hostname
    req = urllib.request.Request(f"https://{host}/sql", method="POST",
                                 data=json.dumps({"query": query, "params": list(params)}).encode("utf-8"),
                                 headers={"Content-Type": "application/json", "Neon-Connection-String": PG_URL})
    out = None
    for attempt in (1, 2):          # one retry on a transient network error (the statements used here are idempotent)
        try:
            with urllib.request.urlopen(req, timeout=6) as r:
                out = json.load(r)
            break
        except urllib.error.HTTPError as e:
            try:
                msg = json.load(e).get("message", e.reason)
            except Exception:
                msg = e.reason
            raise StorageError(f"database error: {msg}")      # a real database error: do not retry
        except Exception as e:
            if attempt == 2:
                raise StorageError(f"database request failed: {e}")
            time.sleep(0.3)
    return out.get("rows") or []


def _pg_init():
    global _pg_ready
    if not _pg_ready:
        _sql("CREATE TABLE IF NOT EXISTS constellarium_kv (key text PRIMARY KEY, value text NOT NULL, updated_at timestamptz DEFAULT now())")
        _pg_ready = True


def _pg_get(key):
    _pg_init()
    rows = _sql("SELECT value FROM constellarium_kv WHERE key = $1", [key])
    if not rows:
        return None
    row = rows[0]
    return row[0] if isinstance(row, list) else row.get("value")


def _pg_set(key, value, backup_key=None):
    _pg_init()
    if backup_key:  # keep the previous version when importing / restoring / clearing
        _sql("INSERT INTO constellarium_kv (key, value) SELECT $2, value FROM constellarium_kv WHERE key = $1 "
             "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now()", [key, backup_key])
    _sql("INSERT INTO constellarium_kv (key, value) VALUES ($1, $2) "
         "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now()", [key, value])


def _check_storage():
    if ON_WEB and not REMOTE:
        raise StorageError("No database connected. In Vercel: Storage -> connect a Neon Postgres (or Upstash Redis) "
                           "database to this project, then redeploy.")


def _normalise(s):
    for k in ("categories", "projects", "ideas"):
        s.setdefault(k, [])
    return s


def load():
    _check_storage()
    if REMOTE:
        raw = _redis("GET", REDIS_KEY) if (REDIS_URL and REDIS_TOKEN) else _pg_get(REDIS_KEY)
        if raw:
            return _normalise(json.loads(raw))
        # first use of a fresh database: fill it from the bundled compilation of every project idea
        store = empty_store()
        if SEED.exists():
            do_import(store, json.loads(SEED.read_text(encoding="utf-8")))
        save(store)
        return store
    return _file_load()


def save(store, force_backup=False):
    _check_storage()
    if REMOTE:
        payload = json.dumps(store, ensure_ascii=False)
        if REDIS_URL and REDIS_TOKEN:
            if force_backup:  # keep the previous version when importing / restoring / clearing
                prev = _redis("GET", REDIS_KEY)
                if prev:
                    _redis("SET", REDIS_KEY + ":backup:last", prev)
            _redis("SET", REDIS_KEY, payload)
        else:
            _pg_set(REDIS_KEY, payload, backup_key=(REDIS_KEY + ":backup:last") if force_backup else None)
        return
    _file_save(store, force_backup)


def _file_load():
    if STORE.exists():
        with STORE.open(encoding="utf-8") as f:
            s = json.load(f)
    else:
        s = empty_store()
    for k in ("categories", "projects", "ideas"):
        s.setdefault(k, [])
    return s


def backup(force=False):
    global _last_backup
    if not STORE.exists():
        return
    if not force and time.time() - _last_backup < 300:
        return
    BACKUPS.mkdir(parents=True, exist_ok=True)
    shutil.copy2(STORE, BACKUPS / time.strftime("store-%Y%m%d-%H%M%S.json"))
    _last_backup = time.time()
    for old in sorted(BACKUPS.glob("store-*.json"))[:-30]:
        old.unlink(missing_ok=True)


def _file_save(store, force_backup=False):
    HOME.mkdir(parents=True, exist_ok=True)
    backup(force_backup)
    text = json.dumps(store, indent=2, ensure_ascii=False)
    tmp = STORE.with_suffix(".tmp")
    tmp.write_text(text, encoding="utf-8")
    # Windows: antivirus / indexers can briefly lock the file -> retry, then fall back to a direct write
    for attempt in range(8):
        try:
            tmp.replace(STORE)
            return
        except PermissionError:
            time.sleep(0.15 * (attempt + 1))
    STORE.write_text(text, encoding="utf-8")
    tmp.unlink(missing_ok=True)


def seed_if_empty():
    """First launch: fill the store from the bundled compilation of every project idea.
    Returns import stats, or None if the store already existed."""
    with LOCK:
        if STORE.exists() or not SEED.exists():
            return None
        payload = json.loads(SEED.read_text(encoding="utf-8"))
        store = empty_store()
        stats = do_import(store, payload)
        save(store)
        return stats


def reseed():
    """Merge the bundled compilation into the current store (matched by idea title; never duplicates)."""
    with LOCK:
        payload = json.loads(SEED.read_text(encoding="utf-8"))
        store = load()
        stats = do_import(store, payload)
        save(store, force_backup=True)
        return stats


# ---------------------------------------------------------------- helpers
def s(v, limit=5000):
    return str(v).strip()[:limit] if v is not None else ""


def str_list(v):
    if isinstance(v, str):
        v = [p for p in v.replace(";", ",").split(",")]
    out, seen = [], set()
    for p in v or []:
        p = s(p, 80).lower().lstrip("#")
        if p and p not in seen:
            seen.add(p)
            out.append(p)
    return out


def next_color(items):
    return PALETTE[len(items) % len(PALETTE)]


def find_by_name(items, name):
    n = name.strip().lower()
    return next((i for i in items if i["name"].strip().lower() == n), None)


def ensure_category(store, path):
    """'Parent > Child' -> category id (creates missing). Empty -> None."""
    parts = [p.strip() for p in str(path or "").replace("/", ">").split(">") if p.strip()]
    parent = None
    cat = None
    for name in parts:
        cat = next((c for c in store["categories"]
                    if c["name"].lower() == name.lower() and c.get("parent") == parent), None)
        if not cat:
            cat = {"id": new_id(), "name": name[:80], "parent": parent,
                   "color": next_color(store["categories"]), "description": ""}
            store["categories"].append(cat)
        parent = cat["id"]
    return cat["id"] if cat else None


def ensure_project(store, name):
    name = s(name, 120)
    if not name:
        return None
    p = find_by_name(store["projects"], name)
    if not p:
        p = {"id": new_id(), "name": name, "description": "", "color": next_color(store["projects"])}
        store["projects"].append(p)
    return p["id"]


def clean_idea(store, d, existing=None):
    """Normalise an idea payload coming from the UI (ids, not names)."""
    cat_ids = {c["id"] for c in store["categories"]}
    proj_ids = {p["id"] for p in store["projects"]}
    idea_ids = {i["id"] for i in store["ideas"]}
    idea = dict(existing or {"id": new_id(), "createdAt": now()})
    idea["title"] = s(d.get("title"), 200) or idea.get("title") or "Untitled idea"
    idea["description"] = s(d.get("description"), 20000)
    idea["category"] = d.get("category") if d.get("category") in cat_ids else None
    idea["projects"] = [p for p in dict.fromkeys(d.get("projects") or []) if p in proj_ids]
    idea["tags"] = str_list(d.get("tags"))
    idea["related"] = [r for r in dict.fromkeys(d.get("related") or [])
                       if r in idea_ids and r != idea["id"]]
    idea["author"] = s(d.get("author"), 80)
    idea["primaryContact"] = s(d.get("primaryContact"), 200)
    idea["secondaryContact"] = s(d.get("secondaryContact"), 200)
    idea["source"] = s(d.get("source"), 300)
    idea["status"] = d.get("status") if d.get("status") in STATUSES else "new"
    idea["updatedAt"] = now()
    return idea


def do_import(store, payload):
    """Bulk import by NAME; creates categories/projects as needed. Merges by idea title."""
    stats = {"ideasAdded": 0, "ideasUpdated": 0, "categoriesBefore": len(store["categories"]),
             "projectsBefore": len(store["projects"])}
    for c in payload.get("categories") or []:
        cid = ensure_category(store, c.get("name") if isinstance(c, dict) else c)
        if isinstance(c, dict) and cid:
            cat = next(x for x in store["categories"] if x["id"] == cid)
            if c.get("color"):
                cat["color"] = s(c["color"], 20)
            if c.get("description"):
                cat["description"] = s(c["description"], 2000)
    for p in payload.get("projects") or []:
        name = p.get("name") if isinstance(p, dict) else p
        pid = ensure_project(store, name)
        if isinstance(p, dict) and pid:
            proj = next(x for x in store["projects"] if x["id"] == pid)
            if p.get("description"):
                proj["description"] = s(p["description"], 2000)
            if p.get("color"):
                proj["color"] = s(p["color"], 20)
    pending_related = []
    by_title = {i["title"].strip().lower(): i for i in store["ideas"]}
    for raw in payload.get("ideas") or []:
        if not isinstance(raw, dict) or not s(raw.get("title")):
            continue
        title = s(raw["title"], 200)
        existing = by_title.get(title.lower())
        idea = existing or {"id": new_id(), "createdAt": now()}
        idea["title"] = title
        if existing is None or raw.get("description"):
            idea["description"] = s(raw.get("description"), 20000)
        if raw.get("category") or existing is None:
            idea["category"] = ensure_category(store, raw.get("category"))
        projs = raw.get("projects")
        if isinstance(projs, str):
            projs = [p for p in projs.replace(";", ",").split(",")]
        pids = [ensure_project(store, p) for p in projs or []]
        idea["projects"] = list(dict.fromkeys((idea.get("projects") or []) + [p for p in pids if p]))
        idea["tags"] = list(dict.fromkeys((idea.get("tags") or []) + str_list(raw.get("tags"))))
        idea.setdefault("related", [])
        if raw.get("author") or existing is None:
            idea["author"] = s(raw.get("author"), 80)
        if raw.get("source") or existing is None:
            idea["source"] = s(raw.get("source"), 300)
        for k in ("primaryContact", "secondaryContact"):
            if raw.get(k) or existing is None:
                idea[k] = s(raw.get(k), 200)
        st = s(raw.get("status")).lower().replace(" ", "-")
        idea["status"] = st if st in STATUSES else idea.get("status", "new")
        if raw.get("createdAt") and existing is None:
            idea["createdAt"] = s(raw["createdAt"], 40)
        idea["updatedAt"] = now()
        rel = raw.get("related")
        if isinstance(rel, str):
            rel = [r for r in rel.split(";")]
        pending_related.append((idea, rel or []))
        if existing is None:
            store["ideas"].append(idea)
            by_title[title.lower()] = idea
            stats["ideasAdded"] += 1
        else:
            stats["ideasUpdated"] += 1
    for idea, rel in pending_related:
        for r in rel:
            other = by_title.get(s(r).lower())
            if other and other["id"] != idea["id"] and other["id"] not in idea["related"]:
                idea["related"].append(other["id"])
    stats["categoriesAdded"] = len(store["categories"]) - stats["categoriesBefore"]
    stats["projectsAdded"] = len(store["projects"]) - stats["projectsBefore"]
    del stats["categoriesBefore"], stats["projectsBefore"]
    return stats


def delete_category(store, cid):
    victim = next((c for c in store["categories"] if c["id"] == cid), None)
    if not victim:
        return False
    for c in store["categories"]:
        if c.get("parent") == cid:
            c["parent"] = victim.get("parent")
    store["categories"] = [c for c in store["categories"] if c["id"] != cid]
    for i in store["ideas"]:
        if i.get("category") == cid:
            i["category"] = victim.get("parent")
    return True


def is_descendant(store, node, ancestor):
    seen = set()
    while node and node not in seen:
        if node == ancestor:
            return True
        seen.add(node)
        node = next((c.get("parent") for c in store["categories"] if c["id"] == node), None)
    return False


# ---------------------------------------------------------------- HTTP
class Handler(BaseHTTPRequestHandler):
    server_version = "Constellarium/1.0"
    protocol_version = "HTTP/1.1"   # keep-alive: with HTTP/1.0 the server closes right after big responses and Windows may reset them
    SERVE_STATIC = True     # local server serves the UI itself; on Vercel the CDN does (api/index.py turns this off)
    QUERY_PATH = False      # on Vercel the rewrite passes the API path as ?path=...

    def log_message(self, fmt, *args):
        pass

    def _path(self):
        u = urlparse(self.path)
        if self.QUERY_PATH:
            q = parse_qs(u.query)
            if "path" in q:
                return "/api/" + q["path"][0].strip("/")
        return u.path

    def _json(self, obj, code=200, headers=None):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n > MAX_BODY:
            raise ValueError("payload too large")
        raw = self.rfile.read(n) if n else b"{}"
        return json.loads(raw.decode("utf-8") or "{}")

    def _static(self, path):
        rel = "index.html" if path in ("", "/") else path.lstrip("/")
        f = (STATIC / rel).resolve()
        if STATIC.resolve() not in f.parents or not f.is_file():
            self.send_error(404)
            return
        ctype = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
                 ".css": "text/css; charset=utf-8", ".svg": "image/svg+xml", ".ico": "image/x-icon",
                 ".png": "image/png", ".json": "application/json"}.get(f.suffix, "application/octet-stream")
        data = f.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(data)

    # ---- access gate ----
    # LOCAL: random per-launch token + Host/Origin allow-list.   WEB / password mode: login cookie.
    def _host_ok(self):
        return ON_WEB or (self.headers.get("Host") or "").lower() in ALLOWED_HOSTS

    def _origin_ok(self):
        origin = self.headers.get("Origin")
        if not origin:
            return True
        if ON_WEB:      # same-origin only: the page's own host
            return urlparse(origin).netloc.lower() == (self.headers.get("Host") or "").lower()
        return urlparse(origin).netloc.lower() in ALLOWED_HOSTS

    @staticmethod
    def _pw_token():
        secret = os.environ.get("CONSTELLARIUM_SECRET") or PASSWORD
        return hmac.new(secret.encode("utf-8"), b"constellarium-session-v1", hashlib.sha256).hexdigest()

    def _authed(self):
        c = SimpleCookie(self.headers.get("Cookie") or "")
        if PW_MODE:
            got = c["cs_pw"].value if "cs_pw" in c else ""
            return bool(PASSWORD) and hmac.compare_digest(got, self._pw_token())
        got = c["cs_session"].value if "cs_session" in c else ""
        return bool(SESSION_TOKEN) and hmac.compare_digest(got, SESSION_TOKEN)

    def _cookie(self):
        return f"cs_session={SESSION_TOKEN}; Path=/; HttpOnly; SameSite=Strict; Max-Age=86400"

    def _pw_cookie(self, value, max_age):
        secure = ON_WEB or self.headers.get("X-Forwarded-Proto") == "https"
        return f"cs_pw={value}; Path=/; HttpOnly; SameSite=Strict; Max-Age={max_age}" + ("; Secure" if secure else "")

    def _deny(self, code=403):
        self._json({"error": "forbidden"}, code)

    def _gate(self):
        """True if the request may touch data; otherwise the error response has been sent."""
        if PW_MODE and not PASSWORD:
            self._json({"error": "Server not configured: set the CONSTELLARIUM_PASSWORD environment variable."}, 503)
            return False
        if not self._authed():
            if PW_MODE:
                self._json({"error": "login required", "login": True}, 401)
            else:
                self._deny()
            return False
        return True

    def _login(self, body):
        if not PASSWORD:
            return self._json({"error": "Server not configured: set the CONSTELLARIUM_PASSWORD environment variable."}, 503)
        if not hmac.compare_digest(str(body.get("password", "")).encode("utf-8"), PASSWORD.encode("utf-8")):
            time.sleep(1)   # slow down guessing
            return self._json({"error": "wrong password"}, 401)
        return self._json({"ok": True}, headers={"Set-Cookie": self._pw_cookie(self._pw_token(), 60 * 60 * 24 * 30)})

    # ---- routes ----
    def do_GET(self):
        if not self._host_ok():
            return self._deny()
        u = urlparse(self.path)
        path = self._path()
        try:
            # LOCAL one-time launch link: /?k=<token>  -> set the cookie, then show the app
            if not PW_MODE and u.path == "/" and u.query.startswith("k="):
                if hmac.compare_digest(u.query[2:], SESSION_TOKEN):
                    self.send_response(302)
                    self.send_header("Set-Cookie", self._cookie())
                    self.send_header("Location", "/")
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                return self._deny()
            if path == "/api/auth":
                if PW_MODE:
                    if not PASSWORD:
                        return self._json({"error": "Server not configured: set the CONSTELLARIUM_PASSWORD environment variable."}, 503)
                    return self._json({"required": True, "ok": self._authed()})
                if not self._authed():
                    return self._deny()
                return self._json({"required": False, "ok": True})
            if path.startswith("/api/"):
                if not self._gate():
                    return
                if path == "/api/ping":
                    LAST_PING["t"] = time.time()
                    LAST_PING["seen"] = True
                    return self._json({"ok": True})
                if path == "/api/data":
                    with LOCK:
                        return self._json(load())
                return self._json({"error": "not found"}, 404)
            # the UI itself: local mode needs the token; on the web it is just the empty app shell (data sits behind the login)
            if not PW_MODE and not self._authed():
                return self._deny()
            if self.SERVE_STATIC:
                return self._static(path)
            return self._json({"error": "not found"}, 404)
        except StorageError as e:
            return self._json({"error": str(e)}, 503)
        except (OSError, ValueError) as e:
            return self._json({"error": str(e)}, 500)

    def _mutate(self, method):
        if not self._host_ok() or not self._origin_ok():
            return self._deny()
        path = self._path()
        if not path.startswith("/api/"):
            return self._json({"error": "not found"}, 404)
        parts = [p for p in path.split("/") if p][1:]
        try:
            if PW_MODE and parts[:1] == ["login"] and method == "POST":
                return self._login(self._body())
            if parts[:1] == ["logout"]:
                return self._json({"ok": True}, headers={"Set-Cookie": self._pw_cookie("", 0)} if PW_MODE else None)
            if not self._gate():
                return
            body = self._body() if method in ("POST", "PUT") else {}
            with LOCK:
                store = load()
                result = self._route(store, method, parts, body)
                if result is None:
                    return self._json({"error": "not found"}, 404)
                save(store, force_backup=(parts[:1] in (["import"], ["replace"], ["clear"], ["reseed"])))
                return self._json(result)
        except StorageError as e:
            return self._json({"error": str(e)}, 503)
        except (ValueError, KeyError, json.JSONDecodeError) as e:
            return self._json({"error": str(e)}, 400)
        except OSError as e:
            return self._json({"error": f"could not write the store: {e}"}, 500)

    def _route(self, store, method, parts, body):
        kind = parts[0] if parts else ""
        if kind == "import" and method == "POST":
            return do_import(store, body)
        if kind == "reseed" and method == "POST":   # merge the bundled project-idea compilation again
            payload = json.loads(SEED.read_text(encoding="utf-8"))
            return do_import(store, payload)
        if kind == "replace" and method == "POST":  # full restore from an export
            for k in ("categories", "projects", "ideas"):
                store[k] = list(body.get(k) or [])
            return {"ok": True}
        if kind == "clear" and method == "POST":
            store.update(empty_store())
            return {"ok": True}
        if kind == "ideas":
            if method == "POST" and len(parts) == 1:
                idea = clean_idea(store, body)
                store["ideas"].append(idea)
                return idea
            if len(parts) == 2:
                cur = next((i for i in store["ideas"] if i["id"] == parts[1]), None)
                if not cur:
                    return None
                if method == "PUT":
                    cur.update(clean_idea(store, {**cur, **body}, existing=cur))
                    return cur
                if method == "DELETE":
                    store["ideas"].remove(cur)
                    for i in store["ideas"]:
                        i["related"] = [r for r in i.get("related", []) if r != cur["id"]]
                    return {"ok": True}
        if kind == "projects":
            if method == "POST" and len(parts) == 1:
                name = s(body.get("name"), 120)
                if not name:
                    raise ValueError("name required")
                pid = ensure_project(store, name)
                proj = next(p for p in store["projects"] if p["id"] == pid)
                proj["description"] = s(body.get("description"), 2000)
                if body.get("color"):
                    proj["color"] = s(body["color"], 20)
                return proj
            if len(parts) == 2:
                cur = next((p for p in store["projects"] if p["id"] == parts[1]), None)
                if not cur:
                    return None
                if method == "PUT":
                    cur["name"] = s(body.get("name"), 120) or cur["name"]
                    cur["description"] = s(body.get("description", cur.get("description")), 2000)
                    cur["color"] = s(body.get("color") or cur.get("color"), 20)
                    return cur
                if method == "DELETE":
                    store["projects"].remove(cur)
                    for i in store["ideas"]:
                        i["projects"] = [p for p in i.get("projects", []) if p != cur["id"]]
                    return {"ok": True}
        if kind == "categories":
            if method == "POST" and len(parts) == 1:
                name = s(body.get("name"), 80)
                if not name:
                    raise ValueError("name required")
                if ">" in name:
                    leaf = ensure_category(store, name)
                    return next(c for c in store["categories"] if c["id"] == leaf)
                parent = body.get("parent")
                if parent not in {c["id"] for c in store["categories"]}:
                    parent = None
                cat = {"id": new_id(), "name": name, "parent": parent,
                       "color": s(body.get("color"), 20) or next_color(store["categories"]),
                       "description": s(body.get("description"), 2000)}
                store["categories"].append(cat)
                return cat
            if len(parts) == 2:
                cur = next((c for c in store["categories"] if c["id"] == parts[1]), None)
                if not cur:
                    return None
                if method == "PUT":
                    cur["name"] = s(body.get("name"), 80) or cur["name"]
                    cur["description"] = s(body.get("description", cur.get("description")), 2000)
                    cur["color"] = s(body.get("color") or cur.get("color"), 20)
                    if "parent" in body:
                        p = body["parent"] or None
                        valid = p is None or (p in {c["id"] for c in store["categories"]}
                                              and not is_descendant(store, p, cur["id"]))
                        if not valid:
                            raise ValueError("invalid parent (would create a cycle)")
                        cur["parent"] = p
                    return cur
                if method == "DELETE":
                    delete_category(store, cur["id"])
                    return {"ok": True}
        return None

    def do_POST(self):
        self._mutate("POST")

    def do_PUT(self):
        self._mutate("PUT")

    def do_DELETE(self):
        self._mutate("DELETE")
