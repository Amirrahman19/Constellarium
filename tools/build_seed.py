"""Build seed/seed_data.json = project-idea catalogue (ideas_catalog.py) + the Problem Lab / ExCo chat ideas
exported from the IdeaBank store.  Run:  python -X utf8 tools/build_seed.py"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import ideas_catalog as C  # noqa: E402

OUT = HERE.parent / "seed" / "seed_data.json"
IDEABANK_STORE = HERE.parent.parent / "IdeaBank" / "data" / "store.json"
CHAT_ROOT = "Problem Lab & ExCo"

payload = {"categories": [], "projects": [], "ideas": []}
titles = set()

for path, desc in C.CATEGORIES:
    payload["categories"].append({"name": path, "description": desc})
for name, desc in C.PROJECTS:
    payload["projects"].append({"name": name, "description": desc})

for t, desc, cat, projs, tags, status, src, *rel in C.IDEAS:
    assert t not in titles, "duplicate title: " + t
    titles.add(t)
    payload["ideas"].append({"title": t, "description": desc, "category": cat, "projects": projs,
                             "tags": tags, "status": status, "source": src, "author": C.A,
                             "related": rel[0] if rel else []})
n_catalog = len(payload["ideas"])

n_chat = 0
if IDEABANK_STORE.exists():
    st = json.loads(IDEABANK_STORE.read_text(encoding="utf-8"))
    cats = {c["id"]: c for c in st["categories"]}
    projs = {p["id"]: p for p in st["projects"]}
    by_id = {i["id"]: i for i in st["ideas"]}

    def cat_path(cid):
        parts = []
        while cid:
            parts.append(cats[cid]["name"])
            cid = cats[cid].get("parent")
        return " > ".join([CHAT_ROOT] + parts[::-1])

    payload["categories"].append({"name": CHAT_ROOT, "description": "Ideas extracted from the Problem Lab!! and ExCo Secrets Telegram chats (IdeaBank v0.1)."})
    for c in st["categories"]:
        payload["categories"].append({"name": cat_path(c["id"]), "description": c.get("description", "")})
    for p in st["projects"]:
        payload["projects"].append({"name": p["name"], "description": p.get("description", "")})
    for i in st["ideas"]:
        t = i["title"]
        if t in titles:
            t = t + " (chat)"
        titles.add(t)
        payload["ideas"].append({
            "title": t, "description": i.get("description", ""),
            "category": cat_path(i["category"]) if i.get("category") else CHAT_ROOT,
            "projects": [projs[p]["name"] for p in i.get("projects", []) if p in projs],
            "tags": i.get("tags", []) + ["chat"], "status": i.get("status", "new"),
            "source": i.get("source", ""), "author": i.get("author", ""),
            "related": [by_id[r]["title"] for r in i.get("related", []) if r in by_id],
            "createdAt": i.get("createdAt", "")})
        n_chat += 1
else:
    print("WARNING: IdeaBank store not found; chat ideas skipped")

# related titles must resolve
allt = {i["title"] for i in payload["ideas"]}
bad = [(i["title"], r) for i in payload["ideas"] for r in i["related"] if r not in allt]
if bad:
    print("UNRESOLVED related titles:")
    for b in bad:
        print("  ", b)
    sys.exit(1)

OUT.parent.mkdir(exist_ok=True)
OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
print(f"seed written: {len(payload['ideas'])} ideas ({n_catalog} project ideas + {n_chat} chat ideas), "
      f"{len(payload['categories'])} categories, {len(payload['projects'])} projects -> {OUT}")
