"""Constellarium core: data model, import logic, REST handler. Standard library only.

Two ways to run (same features, same UI):
  * LOCAL (the exe / `python constellarium.py`): binds to 127.0.0.1 only, every request needs a random per-launch
    session token, Host/Origin checks block DNS-rebinding and cross-site writes, data lives in
    %APPDATA%\\Constellarium (override: CONSTELLARIUM_HOME); no network calls at all.
  * WEB (Vercel, see api/index.py + vercel.json): the same handler behind a password login. Data lives in a
    database (Neon Postgres or Upstash Redis, via plain HTTPS REST calls); on first use the database is filled
    from the bundled seed. Switched on by Vercel's VERCEL env var; the password is CONSTELLARIUM_PASSWORD.
"""
import base64
import hashlib
import hmac
import json
import os
import re
import secrets
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
# the same policy is set for the deployed site in vercel.json: no third-party scripts, no framing, same-origin requests only
CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
       "connect-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'")
SESSION_DAYS = 14
VAULT_MINUTES = 30

# set by constellarium.py at start-up (local mode)
SESSION_TOKEN = ""
ALLOWED_HOSTS = set()
LAST_PING = {"t": 0.0, "seen": False}

# ---- web deployment config (all optional locally) ----
ON_WEB = bool(os.environ.get("VERCEL"))
PASSWORD = os.environ.get("CONSTELLARIUM_PASSWORD", "")
PW_MODE = ON_WEB or bool(PASSWORD)          # password login instead of the per-launch token
VAULT_PASSWORD = os.environ.get("CONSTELLARIUM_VAULT_PASSWORD", "")      # second password: opens the password manager
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


# ---- banks: IdeaBank and ProblemBank share all code and features but keep completely separate data ----
BANKS = ("ideabank", "problembank")
DEFAULT_BANK = "ideabank"
BANK_NAMES = {"ideabank": "IdeaBank", "problembank": "ProblemBank"}
_last_backup = {}


def bank_file(bank):
    return STORE if bank == "ideabank" else HOME / f"store-{bank}.json"           # IdeaBank keeps the original file


def bank_backups(bank):
    return BACKUPS if bank == "ideabank" else HOME / f"backups-{bank}"


def bank_key(bank):
    return REDIS_KEY if bank == "ideabank" else f"{REDIS_KEY}:{bank}"             # IdeaBank keeps the original key


def seed_path(bank):
    return BUNDLE / "seed" / f"seed_{bank}.json"


def check_bank(bank):
    bank = (bank or DEFAULT_BANK).strip().lower()
    if bank not in BANKS:
        raise ValueError("unknown bank: " + bank[:30])
    return bank


def _read_raw(bank):
    """The stored data of a bank, or None if the bank has no data yet."""
    if REMOTE:
        raw = _redis("GET", bank_key(bank)) if (REDIS_URL and REDIS_TOKEN) else _pg_get(bank_key(bank))
        return json.loads(raw) if raw else None
    path = bank_file(bank)
    if path.exists():
        with path.open(encoding="utf-8") as f:
            return json.load(f)
    return None


def load(bank=DEFAULT_BANK):
    bank = check_bank(bank)
    _check_storage()
    s = _read_raw(bank)
    if s is None:
        s = _first_use(bank)
    return _normalise(s)


def _first_use(bank):
    """A bank with no data yet is filled from its bundled seed. ProblemBank first tries to take its problem items out of an
    existing IdeaBank (installs created before the split), so edits are kept and nothing is duplicated."""
    with LOCK:
        again = _read_raw(bank)                       # another request may just have created it
        if again is not None:
            return again
        if bank == "problembank":
            return _first_use_problembank()
        store = empty_store()
        p = seed_path(bank)
        if p.exists():
            do_import(store, json.loads(p.read_text(encoding="utf-8")))
        save(store, False, bank)
        return store


def _first_use_problembank():
    p = seed_path("problembank")
    seed = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {"ideas": [], "categories": [], "projects": []}
    wanted = {i["title"].strip().lower(): i for i in seed.get("ideas", [])}
    ib = load("ideabank")                              # on a brand-new install this seeds IdeaBank (which has no problems)
    movers = [i for i in ib["ideas"] if i["title"].strip().lower() in wanted]
    store = empty_store()
    if not movers:
        do_import(store, seed)
        save(store, False, "problembank")
        return store
    save(store, False, "problembank")                  # create the bank first so transfer_ideas can load it
    transfer_ideas("ideabank", "problembank", [i["id"] for i in movers])
    store = load("problembank")
    for idea in store["ideas"]:                        # file each moved problem under its problem-domain category
        sd = wanted.get(idea["title"].strip().lower())
        if sd and sd.get("category"):
            idea["category"] = ensure_category(store, sd["category"])
    for _ in range(6):                                 # drop the empty categories the transfer re-created from IdeaBank's structure
        used = {i["category"] for i in store["ideas"]}
        parents = {c.get("parent") for c in store["categories"]}
        empty = [c["id"] for c in store["categories"] if c["id"] not in used and c["id"] not in parents]
        if not empty:
            break
        store["categories"] = [c for c in store["categories"] if c["id"] not in empty]
    save(store, False, "problembank")
    return store


def save(store, force_backup=False, bank=DEFAULT_BANK):
    bank = check_bank(bank)
    _check_storage()
    key = bank_key(bank)
    if REMOTE:
        payload = json.dumps(store, ensure_ascii=False)
        if REDIS_URL and REDIS_TOKEN:
            if force_backup:  # keep the previous version when importing / restoring / clearing
                prev = _redis("GET", key)
                if prev:
                    _redis("SET", key + ":backup:last", prev)
            _redis("SET", key, payload)
        else:
            _pg_set(key, payload, backup_key=(key + ":backup:last") if force_backup else None)
        return
    _file_save(store, force_backup, bank)


def backup(force=False, bank=DEFAULT_BANK):
    path, folder = bank_file(bank), bank_backups(bank)
    if not path.exists():
        return
    if not force and time.time() - _last_backup.get(bank, 0.0) < 300:
        return
    folder.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, folder / time.strftime("store-%Y%m%d-%H%M%S.json"))
    _last_backup[bank] = time.time()
    for old in sorted(folder.glob("store-*.json"))[:-30]:
        old.unlink(missing_ok=True)


def _atomic_write(path, text):
    tmp = path.with_suffix(".tmp")
    tmp.write_text(text, encoding="utf-8")
    # Windows: antivirus / indexers can briefly lock the file -> retry, then fall back to a direct write
    for attempt in range(8):
        try:
            tmp.replace(path)
            return
        except PermissionError:
            time.sleep(0.15 * (attempt + 1))
    path.write_text(text, encoding="utf-8")
    tmp.unlink(missing_ok=True)


def _file_save(store, force_backup=False, bank=DEFAULT_BANK):
    HOME.mkdir(parents=True, exist_ok=True)
    path = bank_file(bank)
    backup(force_backup, bank)
    _atomic_write(path, json.dumps(store, indent=2, ensure_ascii=False))


# ---- other documents (to-do list, password vault): same storage, one JSON document each ----
def kv_key(name):
    return f"{REDIS_KEY}:{name}"


def kv_read(name):
    _check_storage()
    if REMOTE:
        raw = _redis("GET", kv_key(name)) if (REDIS_URL and REDIS_TOKEN) else _pg_get(kv_key(name))
        return json.loads(raw) if raw else None
    p = HOME / f"{name}.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def kv_write(name, obj, force_backup=False):
    _check_storage()
    key = kv_key(name)
    if REMOTE:
        payload = json.dumps(obj, ensure_ascii=False)
        if REDIS_URL and REDIS_TOKEN:
            if force_backup:
                prev = _redis("GET", key)
                if prev:
                    _redis("SET", key + ":backup:last", prev)
            _redis("SET", key, payload)
        else:
            _pg_set(key, payload, backup_key=(key + ":backup:last") if force_backup else None)
        return
    HOME.mkdir(parents=True, exist_ok=True)
    p = HOME / f"{name}.json"
    if force_backup and p.exists():
        folder = HOME / f"backups-{name}"
        folder.mkdir(parents=True, exist_ok=True)
        shutil.copy2(p, folder / time.strftime(f"{name}-%Y%m%d-%H%M%S.json"))
        for old in sorted(folder.glob(f"{name}-*.json"))[:-30]:
            old.unlink(missing_ok=True)
    _atomic_write(p, json.dumps(obj, indent=2, ensure_ascii=False))


def seed_if_empty():
    """First launch (or first launch after the bank split): make sure every bank exists, filled from its seed.
    Returns {bank: items} for the banks that were created, or None if they all existed already."""
    with LOCK:
        missing = [b for b in BANKS if _read_raw(b) is None]
        if not missing:
            return None
        return {b: len(load(b)["ideas"]) for b in BANKS if b in missing or b == "ideabank"}


def reseed():
    """Merge each bank's bundled seed into its current data (matched by idea title; never duplicates)."""
    with LOCK:
        out = {}
        for bank in BANKS:
            p = seed_path(bank)
            if not p.exists():
                continue
            store = load(bank)
            out[bank] = do_import(store, json.loads(p.read_text(encoding="utf-8")))
            save(store, True, bank)
        return out


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


def _chain_ids(store, names):
    """Walk/create a category chain by NAMES (so a name containing '>' or '/' survives). Returns the leaf id or None."""
    parent, cat = None, None
    for name in names:
        cat = next((c for c in store["categories"] if c["name"].lower() == name.lower() and c.get("parent") == parent), None)
        if not cat:
            cat = {"id": new_id(), "name": name[:80], "parent": parent, "color": next_color(store["categories"]), "description": ""}
            store["categories"].append(cat)
        parent = cat["id"]
    return cat["id"] if cat else None


def transfer_ideas(src, dst, ids, restore_links=None, restore_titles=None):
    """Move ideas from bank `src` to bank `dst`. Categories and projects are re-created by name in the target, links among the moved
    ideas are kept, links to ideas that stay behind are dropped (returned so Undo can restore them). The target is saved first so a
    failure can never lose an idea (worst case it exists in both banks)."""
    src, dst = check_bank(src), check_bank(dst)
    if src == dst:
        raise ValueError("Choose the other bank: the source and target are the same.")
    ids = {x for x in ids if isinstance(x, str)}
    a, b = load(src), load(dst)
    moving = [i for i in a["ideas"] if i["id"] in ids]
    if not moving:
        raise ValueError("Nothing to move: those items are no longer in " + BANK_NAMES[src] + ".")
    cats = {c["id"]: c for c in a["categories"]}
    proj_name = {p["id"]: p["name"] for p in a["projects"]}
    have_titles = {i["title"].strip().lower() for i in b["ideas"]}
    have_ids = {i["id"] for i in b["ideas"]}
    renamed = 0
    original_titles = {}

    def chain_names(cid):
        out, guard = [], 0
        while cid and cid in cats and guard < 30:
            out.append(cats[cid]["name"])
            cid = cats[cid].get("parent")
            guard += 1
        return out[::-1]

    moved_ids = []
    for idea in moving:
        if idea["id"] in have_ids:           # already there (e.g. an interrupted earlier move): do not duplicate
            moved_ids.append(idea["id"])
            continue
        new = dict(idea)
        new["category"] = _chain_ids(b, chain_names(idea.get("category")))
        new["projects"] = list(dict.fromkeys(x for x in (ensure_project(b, proj_name[p]) for p in idea.get("projects", []) if p in proj_name) if x))
        title = (restore_titles or {}).get(idea["id"]) or idea["title"]           # Undo passes the title the idea had before it was renamed
        if title.strip().lower() in have_titles:           # never overwrite something with the same title: rename the incoming one
            base = f"{title} (from {BANK_NAMES[src]})"
            title, n = base, 2
            while title.strip().lower() in have_titles:
                title, n = f"{base} {n}", n + 1
            renamed += 1
            original_titles[idea["id"]] = idea["title"]
        have_titles.add(title.strip().lower())
        new["title"] = title
        new["related"] = [r for r in idea.get("related", []) if r in ids]
        new["updatedAt"] = now()
        b["ideas"].append(new)
        moved_ids.append(idea["id"])

    dropped = [[i["id"], r] for i in a["ideas"] if i["id"] not in ids for r in i.get("related", []) if r in ids]          # staying idea -> moved idea
    dropped += [[m["id"], r] for m in moving for r in m.get("related", []) if r not in ids]                                # moved idea -> staying idea
    a["ideas"] = [i for i in a["ideas"] if i["id"] not in ids]
    for i in a["ideas"]:
        i["related"] = [r for r in i.get("related", []) if r not in ids]

    present = {i["id"]: i for i in b["ideas"]}          # Undo: put back links that the earlier move had to drop
    for x, y in restore_links or []:
        if x in present and y in present and y not in present[x].setdefault("related", []):
            present[x]["related"].append(y)

    save(b, True, dst)
    save(a, True, src)
    relink_todos(src, dst, set(moved_ids))          # tasks linked to the moved items follow them
    return {"moved": len(moved_ids), "ids": moved_ids, "from": src, "to": dst, "renamed": renamed, "originalTitles": original_titles, "dropped": dropped,
            "counts": {src: len(a["ideas"]), dst: len(b["ideas"])}}


def is_descendant(store, node, ancestor):
    seen = set()
    while node and node not in seen:
        if node == ancestor:
            return True
        seen.add(node)
        node = next((c.get("parent") for c in store["categories"] if c["id"] == node), None)
    return False


# ---------------------------------------------------------------- to-do list (synced with the banks)
PRIORITIES = ("normal", "high")
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def load_todos():
    d = kv_read("todos") or {}
    d.setdefault("tasks", [])
    return d


def clean_link(v):
    """A task may point at one idea / problem: {bank, id}. Anything else -> None."""
    if isinstance(v, dict) and v.get("bank") in BANKS and isinstance(v.get("id"), str) and v["id"]:
        return {"bank": v["bank"], "id": v["id"][:40]}
    return None


def clean_task(d, existing=None):
    t = dict(existing or {"id": new_id(), "createdAt": now(), "done": False, "doneAt": ""})
    if "title" in d or not existing:
        t["title"] = s(d.get("title"), 300)
        if not t["title"]:
            raise ValueError("A task needs a title.")
    if "notes" in d or not existing:
        t["notes"] = s(d.get("notes"), 5000)
    if "due" in d or not existing:
        due = s(d.get("due"), 10)
        t["due"] = due if _DATE.match(due) else ""
    if "priority" in d or not existing:
        t["priority"] = d.get("priority") if d.get("priority") in PRIORITIES else "normal"
    if "link" in d or not existing:
        t["link"] = clean_link(d.get("link"))
    if "done" in d:
        done = bool(d["done"])
        if done != t.get("done"):
            t["doneAt"] = now() if done else ""
        t["done"] = done
    t["updatedAt"] = now()
    return t


def resolve_tasks(tasks):
    """Attach the CURRENT state of the linked idea/problem to each task (never stored, so it can not go stale):
    renames, status changes, moves between banks (the transfer also re-points the link) and deletes/Undo are always reflected."""
    banks = {}
    out = []
    for t in tasks:
        t = dict(t)
        link = t.get("link")
        if link:
            if link["bank"] not in banks:
                banks[link["bank"]] = {i["id"]: i for i in load(link["bank"])["ideas"]}
            idea = banks[link["bank"]].get(link["id"])
            t["ref"] = ({"exists": True, "title": idea["title"], "status": idea.get("status", "new"), "bank": link["bank"]}
                        if idea else {"exists": False, "title": "", "status": "", "bank": link["bank"]})
        out.append(t)
    return out


def relink_todos(src, dst, ids):
    """Called after ideas moved from bank `src` to `dst` (ids are kept by the transfer): re-point the tasks that link to them."""
    d = kv_read("todos")
    if not d:
        return 0
    n = 0
    for t in d.get("tasks", []):
        l = t.get("link")
        if l and l["bank"] == src and l["id"] in ids:
            l["bank"] = dst
            n += 1
    if n:
        kv_write("todos", d)
    return n


def todo_counts(d=None, today=None):
    d = d or load_todos()
    today = today if today and _DATE.match(today) else time.strftime("%Y-%m-%d")      # the browser's own date (the server may be in another time zone)
    open_ = [t for t in d["tasks"] if not t.get("done")]
    return {"open": len(open_), "overdue": sum(1 for t in open_ if t.get("due") and t["due"] < today),
            "today": sum(1 for t in open_ if t.get("due") == today), "done": len(d["tasks"]) - len(open_)}


def todo_route(method, parts, body, today=None):
    """parts excludes 'todos'. Returns a JSON-able result or None (404)."""
    with LOCK:
        d = load_todos()
        tasks = d["tasks"]
        if method == "GET" and not parts:
            return {"tasks": resolve_tasks(tasks), "counts": todo_counts(d, today)}
        if method == "GET" and parts[:1] == ["for"] and len(parts) == 3:
            mine = [t for t in tasks if t.get("link") and t["link"]["bank"] == parts[1] and t["link"]["id"] == parts[2]]
            return {"tasks": resolve_tasks(mine)}
        if method == "POST" and not parts:
            if len(tasks) >= 5000:
                raise ValueError("Too many tasks (5000). Clear some finished ones first.")
            t = clean_task(body)
            tasks.append(t)
            kv_write("todos", d)
            return resolve_tasks([t])[0]
        if method == "POST" and parts == ["clear-done"]:
            n = len([t for t in tasks if t.get("done")])
            d["tasks"] = [t for t in tasks if not t.get("done")]
            kv_write("todos", d, force_backup=True)
            return {"cleared": n}
        if len(parts) == 1:
            cur = next((t for t in tasks if t["id"] == parts[0]), None)
            if cur is None:
                return None
            if method == "PUT":
                cur.update(clean_task({**body}, existing=cur))
                kv_write("todos", d)
                return resolve_tasks([cur])[0]
            if method == "DELETE":
                d["tasks"] = [t for t in tasks if t is not cur]
                kv_write("todos", d)
                return {"ok": True}
    return None


def all_items():
    """Every idea / problem of both banks, for the 'link a task to...' picker."""
    return [{"bank": b, "id": i["id"], "title": i["title"], "status": i.get("status", "new")}
            for b in BANKS for i in load(b)["ideas"]]


# ---------------------------------------------------------------- password manager (vault)
# The server only ever stores ciphertext. The browser derives an AES-GCM key from the vault password (PBKDF2) and
# encrypts/decrypts there; the database holds {iv, ct} blobs. On top of that the server wants the vault password
# (CONSTELLARIUM_VAULT_PASSWORD) before it hands the blobs out at all.
_ID = re.compile(r"^[0-9a-f]{10}$")


def vault_configured():
    return bool(VAULT_PASSWORD) and VAULT_PASSWORD != PASSWORD


def load_vault():
    d = kv_read("vault")
    if d is None:
        d = {"salt": base64.b64encode(secrets.token_bytes(16)).decode(), "check": None, "entries": []}
        kv_write("vault", d)
    d.setdefault("entries", [])
    return d


def clean_blob(v):
    if (isinstance(v, dict) and isinstance(v.get("iv"), str) and isinstance(v.get("ct"), str)
            and 0 < len(v["iv"]) <= 64 and 0 < len(v["ct"]) <= 60000):
        return {"iv": v["iv"], "ct": v["ct"]}
    raise ValueError("invalid encrypted data")


def vault_route(method, parts, body):
    """parts excludes 'vault'. The caller has already checked that the vault is unlocked."""
    with LOCK:
        d = load_vault()
        if method == "GET" and not parts:
            return d
        if method == "PUT" and parts == ["check"]:             # first-time setup: store the encrypted 'known text'
            if d.get("check"):
                raise ValueError("The vault is already set up.")
            d["check"] = clean_blob(body.get("check"))
            kv_write("vault", d)
            return {"ok": True}
        if method == "POST" and parts == ["rekey"]:           # vault password changed: everything re-encrypted by the browser
            ents = []
            for e in body.get("entries") or []:
                if not _ID.match(str(e.get("id", ""))):
                    raise ValueError("invalid entry id")
                ents.append({"id": e["id"], "meta": clean_blob(e.get("meta")), "secret": clean_blob(e.get("secret")),
                             "createdAt": s(e.get("createdAt"), 30) or now(), "updatedAt": now()})
            d["check"] = clean_blob(body.get("check"))
            d["entries"] = ents
            kv_write("vault", d, force_backup=True)
            return {"ok": True, "count": len(ents)}
        if parts[:1] == ["entries"]:
            if method == "POST" and len(parts) == 1:
                eid = body.get("id") if _ID.match(str(body.get("id", ""))) else new_id()
                if any(e["id"] == eid for e in d["entries"]):
                    raise ValueError("duplicate id")
                if len(d["entries"]) >= 2000:
                    raise ValueError("Too many entries (2000).")
                e = {"id": eid, "meta": clean_blob(body.get("meta")), "secret": clean_blob(body.get("secret")),
                     "createdAt": now(), "updatedAt": now()}
                d["entries"].append(e)
                kv_write("vault", d)
                return e
            if len(parts) == 2:
                cur = next((e for e in d["entries"] if e["id"] == parts[1]), None)
                if cur is None:
                    return None
                if method == "PUT":
                    cur["meta"] = clean_blob(body.get("meta"))
                    cur["secret"] = clean_blob(body.get("secret"))
                    cur["updatedAt"] = now()
                    kv_write("vault", d)
                    return cur
                if method == "DELETE":
                    d["entries"] = [e for e in d["entries"] if e is not cur]
                    kv_write("vault", d, force_backup=True)
                    return {"ok": True}
    return None



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
            for one in (v if isinstance(v, list) else [v]):
                self.send_header(k, one)
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self):
        """Always consume the request body, even when we answer early (log out, 401, 403, 404...). With keep-alive an unread
        body would be glued onto the next request ("{}GET" -> 501). Read once per request and cache."""
        if getattr(self, "_raw", None) is not None:
            return self._raw
        n = int(self.headers.get("Content-Length") or 0)
        if n > MAX_BODY:
            self.close_connection = True                  # too big to read: answer and drop the connection instead
            raise ValueError("payload too large")
        self._raw = self.rfile.read(n) if n else b""
        return self._raw

    def _body(self):
        return json.loads(self._read_body().decode("utf-8") or "{}")

    def _static(self, path):
        rel = "index.html" if path in ("", "/") else path.lstrip("/")
        f = (STATIC / rel).resolve()
        if not f.is_file() and (STATIC / (rel + ".html")).is_file():
            f = (STATIC / (rel + ".html")).resolve()
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
        if f.suffix == ".html":
            self.send_header("Content-Security-Policy", CSP)
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
    def _sig(scope, exp, extra=""):
        secret = (os.environ.get("CONSTELLARIUM_SECRET") or PASSWORD or SESSION_TOKEN) + extra
        return hmac.new(secret.encode("utf-8"), f"constellarium-{scope}-v2:{exp}".encode("utf-8"), hashlib.sha256).hexdigest()

    @classmethod
    def _issue(cls, scope, seconds, extra=""):
        """A signed token that expires: '<unix expiry>.<hmac>'. Logging in again (or waiting) is the only way to get a new one."""
        exp = str(int(time.time()) + seconds)
        return exp + "." + cls._sig(scope, exp, extra)

    @classmethod
    def _verify(cls, token, scope, extra=""):
        try:
            exp, sig = (token or "").split(".", 1)
            if int(exp) < time.time():
                return False
        except ValueError:
            return False
        return hmac.compare_digest(sig, cls._sig(scope, exp, extra))

    def _pw_token(self):
        return self._issue("main", SESSION_DAYS * 86400)

    def _vault_ok(self):
        """Main session valid AND the vault password was entered recently (sliding window, VAULT_MINUTES)."""
        if not (vault_configured() and self._authed()):
            return False
        c = SimpleCookie(self.headers.get("Cookie") or "")
        return "cs_vault" in c and self._verify(c["cs_vault"].value, "vault", VAULT_PASSWORD)

    def _vault_cookie(self, on=True):
        secure = ON_WEB or self.headers.get("X-Forwarded-Proto") == "https"
        val, age = (self._issue("vault", VAULT_MINUTES * 60, VAULT_PASSWORD), VAULT_MINUTES * 60) if on else ("", 0)
        return f"cs_vault={val}; Path=/api; HttpOnly; SameSite=Strict; Max-Age={age}" + ("; Secure" if secure else "")

    def _authed(self):
        c = SimpleCookie(self.headers.get("Cookie") or "")
        if PW_MODE:
            got = c["cs_pw"].value if "cs_pw" in c else ""
            return bool(PASSWORD) and self._verify(got, "main")
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
        return self._json({"ok": True}, headers={"Set-Cookie": [self._pw_cookie(self._pw_token(), SESSION_DAYS * 86400), self._vault_cookie(False)]})

    def _bank(self):
        return check_bank(self.headers.get("X-Bank"))

    def _vault(self, _unused, method, parts, body):
        """Password manager routes. Needs the main session (already checked) plus the second password (cookie cs_vault)."""
        if parts == ["status"] and method == "GET":
            return self._json({"configured": vault_configured(), "unlocked": self._vault_ok(), "minutes": VAULT_MINUTES})
        if not vault_configured():
            why = ("The password manager needs its own, different password: it must not be the same as CONSTELLARIUM_PASSWORD."
                   if VAULT_PASSWORD else "The password manager is not set up: add the environment variable CONSTELLARIUM_VAULT_PASSWORD.")
            return self._json({"error": why, "setup": True}, 503)
        if parts == ["unlock"] and method == "POST":
            if not hmac.compare_digest(str(body.get("password", "")).encode("utf-8"), VAULT_PASSWORD.encode("utf-8")):
                time.sleep(1.5)
                return self._json({"error": "wrong vault password"}, 401)
            d = load_vault()
            return self._json({"ok": True, "salt": d["salt"], "check": d.get("check"), "count": len(d["entries"])},
                              headers={"Set-Cookie": self._vault_cookie(True)})
        if parts == ["lock"] and method == "POST":
            return self._json({"ok": True}, headers={"Set-Cookie": self._vault_cookie(False)})
        if not self._vault_ok():
            return self._json({"error": "vault locked", "vaultLocked": True}, 401)
        r = vault_route(method, parts, body)
        if r is None:
            return self._json({"error": "not found"}, 404)
        return self._json(r, headers={"Set-Cookie": self._vault_cookie(True)})       # every use keeps the window open

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
                        return self._json(load(self._bank()))
                if path == "/api/banks":      # item counts for the switcher badges
                    with LOCK:
                        return self._json({b: {"ideas": len(load(b)["ideas"])} for b in BANKS})
                parts = [p for p in path.split("/") if p][1:]
                if path == "/api/summary":    # the three hub cards
                    with LOCK:
                        return self._json({"banks": {b: {"ideas": len(load(b)["ideas"])} for b in BANKS},
                                           "todos": todo_counts(None, self.headers.get("X-Today")), "vault": {"configured": vault_configured()}})
                if path == "/api/items":
                    with LOCK:
                        return self._json({"items": all_items()})
                if parts[:1] == ["todos"]:
                    r = todo_route("GET", parts[1:], {}, self.headers.get("X-Today"))
                    return self._json(r) if r is not None else self._json({"error": "not found"}, 404)
                if parts[:1] == ["vault"]:
                    return self._vault(None, "GET", parts[1:], {})
                return self._json({"error": "not found"}, 404)
            # the UI itself: local mode needs the token; on the web it is just the empty app shell (data sits behind the login)
            if not PW_MODE and not self._authed():
                return self._deny()
            if self.SERVE_STATIC:
                return self._static(path)
            return self._json({"error": "not found"}, 404)
        except StorageError as e:
            return self._json({"error": str(e)}, 503)
        except ValueError as e:
            return self._json({"error": str(e)}, 400)
        except OSError as e:
            return self._json({"error": str(e)}, 500)

    def _mutate(self, method):
        self._raw = None
        try:
            self._read_body()
        except ValueError as e:
            return self._json({"error": str(e)}, 413)
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
                return self._json({"ok": True}, headers={"Set-Cookie": [self._pw_cookie("", 0), self._vault_cookie(False)]} if PW_MODE else {"Set-Cookie": self._vault_cookie(False)})
            if not self._gate():
                return
            body = self._body() if method in ("POST", "PUT") else {}
            if parts[:1] == ["todos"]:
                r = todo_route(method, parts[1:], body)
                return self._json(r) if r is not None else self._json({"error": "not found"}, 404)
            if parts[:1] == ["vault"]:
                return self._vault(None, method, parts[1:], body)
            if parts[:2] == ["ideas", "transfer"] and method == "POST":      # move ideas to the other bank
                with LOCK:
                    return self._json(transfer_ideas(self._bank(), body.get("to"), body.get("ids") or [], body.get("links") or [], body.get("titles") or {}))
            with LOCK:
                bank = self._bank()
                store = load(bank)
                result = self._route(store, method, parts, body)
                if result is None:
                    return self._json({"error": "not found"}, 404)
                save(store, force_backup=(parts[:1] in (["import"], ["replace"], ["clear"], ["reseed"]) or parts[:2] == ["ideas", "delete"]), bank=bank)
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
            p = seed_path(self._bank())
            return do_import(store, json.loads(p.read_text(encoding="utf-8"))) if p.exists() else {"ideasAdded": 0, "ideasUpdated": 0}
        if kind == "replace" and method == "POST":  # full restore from an export
            for k in ("categories", "projects", "ideas"):
                store[k] = list(body.get(k) or [])
            return {"ok": True}
        if kind == "clear" and method == "POST":
            store.update(empty_store())
            return {"ok": True}
        if kind == "ideas" and method == "POST" and parts[1:] == ["delete"]:   # bulk delete; returns what was removed so the UI can offer Undo
            ids = {x for x in (body.get("ids") or []) if isinstance(x, str)}
            removed = [i for i in store["ideas"] if i["id"] in ids]
            links = [[i["id"], r] for i in store["ideas"] if i["id"] not in ids for r in i.get("related", []) if r in ids]
            store["ideas"] = [i for i in store["ideas"] if i["id"] not in ids]
            for i in store["ideas"]:
                i["related"] = [r for r in i.get("related", []) if r not in ids]
            return {"deleted": removed, "links": links}
        if kind == "ideas" and method == "POST" and parts[1:] == ["restore"]:  # Undo: put deleted ideas back with their original ids + links
            have = {i["id"] for i in store["ideas"]}
            n = 0
            for raw in body.get("ideas") or []:
                if isinstance(raw, dict) and raw.get("id") and raw["id"] not in have:
                    idea = clean_idea(store, raw, existing={"id": raw["id"], "createdAt": s(raw.get("createdAt"), 40) or now()})
                    store["ideas"].append(idea)
                    have.add(idea["id"])
                    n += 1
            for a, b in body.get("links") or []:
                x = next((i for i in store["ideas"] if i["id"] == a), None)
                if x is not None and b in have and b not in x.setdefault("related", []):
                    x["related"].append(b)
            return {"restored": n}
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
