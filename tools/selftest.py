"""End-to-end privacy + API test against a throw-away data folder.
Usage: python -X utf8 tools/selftest.py [path\\to\\Constellarium.exe]   (default: runs constellarium.py from source)"""
import http.client
import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
exe = sys.argv[1] if len(sys.argv) > 1 else None
home = Path(tempfile.mkdtemp(prefix="constellarium-test-"))
cmd = ([exe] if exe else [sys.executable, "-X", "utf8", str(ROOT / "constellarium.py")]) + ["--no-window", "--home", str(home)]
proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
fails = []


def check(name, ok, extra=""):
    print(("PASS " if ok else "FAIL ") + name + (f"  {extra}" if extra else ""))
    if not ok:
        fails.append(name)


try:
    inst = home / "instance.json"
    for _ in range(100):
        if inst.exists():
            break
        time.sleep(0.2)
    d = json.loads(inst.read_text(encoding="utf-8"))
    port, token = d["port"], d["token"]
    host = f"127.0.0.1:{port}"

    def req(method, path, body=None, cookie=True, headers=None):
        c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        h = {"Host": host}
        if cookie:
            h["Cookie"] = "; ".join([f"cs_session={token}"] + extra_cookies)
        h.update(headers or {})
        data = json.dumps(body).encode() if body is not None else None
        c.request(method, path, body=data, headers=h)
        r = c.getresponse()
        raw = r.read()
        req.last_set_cookie = r.getheader("Set-Cookie")
        return r.status, raw

    extra_cookies = []

    check("no cookie -> 403", req("GET", "/api/data", cookie=False)[0] == 403)
    check("wrong host header -> 403", req("GET", "/api/data", headers={"Host": "evil.com"})[0] == 403)
    check("bad launch token -> 403", req("GET", "/?k=nope", cookie=False)[0] == 403)
    check("good launch token -> 302", req("GET", f"/?k={token}", cookie=False)[0] == 302)
    auth = json.loads(req("GET", "/api/auth")[1])
    check("no password required", auth["required"] is False and auth["ok"] is True)
    code, raw = req("GET", "/api/data")
    data = json.loads(raw)
    check("seeded store loads", code == 200 and len(data["ideas"]) > 200,
          f"{len(data['ideas'])} ideas / {len(data['categories'])} categories / {len(data['projects'])} projects")
    check("index serves", b"Constellarium" in req("GET", "/")[1])
    check("static js serves", req("GET", "/app.js")[0] == 200)
    check("path traversal blocked", req("GET", "/../core.py")[0] in (403, 404))
    check("cross-origin POST blocked", req("POST", "/api/ideas", {"title": "x"}, headers={"Origin": "http://evil.com"})[0] == 403)
    code, raw = req("POST", "/api/ideas", {"title": "selftest idea", "status": "exploring"})
    iid = json.loads(raw)["id"]
    check("create idea", code == 200)
    check("update idea", req("PUT", f"/api/ideas/{iid}", {"description": "hello"})[0] == 200)
    code, raw = req("PUT", f"/api/ideas/{iid}", {"primaryContact": "Ann · ann@x.test", "secondaryContact": "Bob · @bob"})
    got = json.loads(raw)
    check("primary/secondary contacts saved", got.get("primaryContact") == "Ann · ann@x.test" and got.get("secondaryContact") == "Bob · @bob")
    code, raw = req("POST", "/api/import", {"ideas": [{"title": "contact import", "primaryContact": "Cy", "secondaryContact": "Di"}]})
    cdata = json.loads(req("GET", "/api/data")[1])
    ci = next(i for i in cdata["ideas"] if i["title"] == "contact import")
    check("contacts survive import", ci["primaryContact"] == "Cy" and ci["secondaryContact"] == "Di")
    check("delete idea", req("DELETE", f"/api/ideas/{iid}")[0] == 200)
    # ---- bulk delete + undo (restore keeps ids and links)
    ia = json.loads(req("POST", "/api/ideas", {"title": "del A"})[1])
    ib = json.loads(req("POST", "/api/ideas", {"title": "del B", "related": [ia["id"]]})[1])
    code, raw = req("POST", "/api/ideas/delete", {"ids": [ia["id"]]})
    dres = json.loads(raw)
    cur = json.loads(req("GET", "/api/data")[1])
    check("bulk delete removes the idea and its back-links", code == 200 and [d["id"] for d in dres["deleted"]] == [ia["id"]]
          and not any(i["id"] == ia["id"] for i in cur["ideas"]) and ia["id"] not in next(i for i in cur["ideas"] if i["id"] == ib["id"])["related"])
    code, raw = req("POST", "/api/ideas/restore", {"ideas": dres["deleted"], "links": dres["links"]})
    cur = json.loads(req("GET", "/api/data")[1])
    back = next((i for i in cur["ideas"] if i["id"] == ia["id"]), None)
    check("undo restores the idea with the same id and the link", code == 200 and json.loads(raw)["restored"] == 1 and back is not None
          and back["title"] == "del A" and ia["id"] in next(i for i in cur["ideas"] if i["id"] == ib["id"])["related"],
          f"status {code} restored={raw[:60]} back={back is not None} B.related={next(i for i in cur['ideas'] if i['id'] == ib['id'])['related']}")
    code, raw = req("POST", "/api/ideas/restore", {"ideas": dres["deleted"], "links": dres["links"]})
    check("restoring twice does not duplicate", json.loads(raw)["restored"] == 0)
    code, raw = req("POST", "/api/ideas/delete", {"ids": [ia["id"], ib["id"], "does-not-exist"]})
    cur = json.loads(req("GET", "/api/data")[1])
    check("bulk delete of several ids (unknown id ignored)", code == 200 and len(json.loads(raw)["deleted"]) == 2
          and not any(i["title"].startswith("del ") for i in cur["ideas"]),
          f"status {code} deleted={len(json.loads(raw)['deleted'])} leftovers={[i['title'] for i in cur['ideas'] if i['title'].startswith('del ')]}")
    check("bulk delete wrote a safety backup", any((home / "backups").glob("store-*.json")))
    n0 = len(json.loads(req("GET", "/api/data")[1])["ideas"])
    code, raw = req("POST", "/api/reseed", {})
    n1 = len(json.loads(req("GET", "/api/data")[1])["ideas"])
    check("reseed adds no duplicates", code == 200 and n0 == n1, raw.decode()[:120])
    code, raw = req("POST", "/api/import", {"ideas": [{"title": "csv idea", "category": "A > B", "projects": "P1;P2"}]})
    check("import by name", code == 200 and json.loads(raw)["ideasAdded"] == 1)
    check("store persisted on disk", (home / "store.json").exists())
    check("backup written on import", any((home / "backups").glob("store-*.json")))
finally:
    proc.terminate()
    try:
        proc.wait(5)
    except subprocess.TimeoutExpired:
        proc.kill()
print("\nALL PASSED" if not fails else f"\nFAILED: {fails}")
sys.exit(1 if fails else 0)
