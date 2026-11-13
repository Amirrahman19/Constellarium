"""Web-mode test: runs the real Vercel handler (api/index.py) the way Vercel does (VERCEL=1, API path passed as ?path=...),
with a fake Upstash Redis REST server standing in for the database. Nothing leaves this machine.
Usage: python -X utf8 tools/webtest.py"""
import http.client
import http.server
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PASSWORD = "webtest-" + os.urandom(4).hex()
STORE = {}


class Srv(http.server.ThreadingHTTPServer):
    request_queue_size = 128      # default 5 makes Windows reset parallel loopback connections
    daemon_threads = True


class FakeRedis(http.server.BaseHTTPRequestHandler):      # Upstash REST: POST ["GET", key] / ["SET", key, value]
    protocol_version = "HTTP/1.1"
    def log_message(self, *a):
        pass

    def do_POST(self):
        cmd = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if self.headers.get("Authorization") != "Bearer fake-token":
            out, code = {"error": "unauthorized"}, 401
        elif cmd[0] == "GET":
            out, code = {"result": STORE.get(cmd[1])}, 200
        elif cmd[0] == "SET":
            STORE[cmd[1]] = cmd[2]
            out, code = {"result": "OK"}, 200
        else:
            out, code = {"error": "unsupported"}, 400
        b = json.dumps(out).encode()
        self.send_response(code)
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)


def free_port():
    import socket
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


fails = []


def check(name, ok, extra=""):
    print(("PASS " if ok else "FAIL ") + name + (f"  {extra}" if extra else ""))
    if not ok:
        fails.append(name)


# a tiny stand-in for the Vercel Python runtime: runs api/index.py's `handler` class on a local port
RUNNER = '''
import sys, http.server
sys.path.insert(0, r"%s")
from api.index import handler as _vercel_handler
class handler(_vercel_handler):
    protocol_version = "HTTP/1.1"   # test runner only: Windows loopback resets large HTTP/1.0 responses (Vercel itself runs on Linux)
class Srv(http.server.ThreadingHTTPServer):
    request_queue_size = 128
    daemon_threads = True
Srv(("127.0.0.1", int(sys.argv[1])), handler).serve_forever()
''' % ROOT

redis_port = free_port()
redis = Srv(("127.0.0.1", redis_port), FakeRedis)
threading.Thread(target=redis.serve_forever, daemon=True).start()


def start_app(extra_env):
    port = free_port()
    env = {**os.environ, "VERCEL": "1", **extra_env}
    for k in ("CONSTELLARIUM_HOME", "APPDATA"):
        env.pop(k, None) if k == "CONSTELLARIUM_HOME" else None
    p = subprocess.Popen([sys.executable, "-X", "utf8", "-c", RUNNER, str(port)], env=env, cwd=str(ROOT),
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(50):
        try:
            http.client.HTTPConnection("127.0.0.1", port, timeout=1).connect()
            break
        except OSError:
            time.sleep(0.2)
    return p, port


def call(port, method, api_path, body=None, cookie=None, headers=None):
    """Mimics Vercel's rewrite: /api/<x> -> /api/index?path=<x>"""
    h = {"Host": f"constellarium-test.vercel.app", "Content-Type": "application/json"}
    if cookie:
        h["Cookie"] = cookie
    h.update(headers or {})
    for attempt in range(4):          # Windows loopback occasionally resets / stalls a connection: retry the harness call
        try:
            c = http.client.HTTPConnection("127.0.0.1", port, timeout=20)
            c.request(method, f"/api/index?path={api_path}", body=json.dumps(body) if body is not None else None, headers=h)
            r = c.getresponse()
            raw = r.read()
            break
        except (ConnectionError, TimeoutError, http.client.HTTPException):
            if attempt == 3:
                raise
            time.sleep(0.5)
    try:
        data = json.loads(raw or b"{}")
    except ValueError:
        data = {"_raw": raw[:80]}
    return r.status, data, r.getheader("Set-Cookie")


# ---------------------------------------------------------------- 1) no password / no database configured
p, port = start_app({})
try:
    s, d, _ = call(port, "GET", "auth")
    check("no password set -> 503 with a clear message", s == 503 and "CONSTELLARIUM_PASSWORD" in d.get("error", ""), d.get("error", "")[:70])
finally:
    p.terminate()

# ---------------------------------------------------------------- 2) password set but no database
p, port = start_app({"CONSTELLARIUM_PASSWORD": PASSWORD})
try:
    s, d, ck = call(port, "POST", "login", {"password": PASSWORD})
    cookie = ck.split(";")[0]
    s, d, _ = call(port, "GET", "data", cookie=cookie)
    check("password but no database -> 503 'No database connected'", s == 503 and "No database" in d.get("error", ""), d.get("error", "")[:60])
finally:
    p.terminate()

# ---------------------------------------------------------------- 3) full web mode with (fake) Upstash Redis
env = {"CONSTELLARIUM_PASSWORD": PASSWORD, "UPSTASH_REDIS_REST_URL": f"http://127.0.0.1:{redis_port}", "UPSTASH_REDIS_REST_TOKEN": "fake-token"}
p, port = start_app(env)
try:
    s, d, _ = call(port, "GET", "auth")
    check("auth: login required, not logged in", s == 200 and d == {"required": True, "ok": False}, str(d))
    check("data without login -> 401 + login flag", call(port, "GET", "data")[0] == 401 and call(port, "GET", "data")[1].get("login") is True)
    check("writes without login -> 401", call(port, "POST", "ideas", {"title": "x"})[0] == 401)
    check("wrong password -> 401", call(port, "POST", "login", {"password": "nope"})[0] == 401)
    s, d, ck = call(port, "POST", "login", {"password": PASSWORD})
    check("right password -> 200 + secure session cookie", s == 200 and ck and "HttpOnly" in ck and "Secure" in ck and "SameSite=Strict" in ck, (ck or "")[:50])
    cookie = ck.split(";")[0]
    check("auth: logged in", call(port, "GET", "auth", cookie=cookie)[1] == {"required": True, "ok": True})
    check("forged cookie rejected", call(port, "GET", "data", cookie="cs_pw=deadbeef")[0] == 401)
    check("cross-origin write blocked", call(port, "POST", "ideas", {"title": "x"}, cookie=cookie, headers={"Origin": "https://evil.example"})[0] == 403)

    check("database empty before first use", "constellarium:store" not in STORE)
    s, d, _ = call(port, "GET", "data", cookie=cookie)
    check("first load seeds the database from the bundle", s == 200 and len(d["ideas"]) > 200 and "constellarium:store" in STORE,
          f"{len(d.get('ideas', []))} ideas / {len(d.get('categories', []))} categories / {len(d.get('projects', []))} projects")
    n0 = len(d["ideas"])

    s, idea, _ = call(port, "POST", "ideas", {"title": "web test idea", "status": "exploring"}, cookie=cookie)
    check("create idea", s == 200 and idea.get("title") == "web test idea", f"status {s} {str(idea)[:120]}")
    us, ud, _ = call(port, "PUT", f"ideas/{idea['id']}", {"description": "hello"}, cookie=cookie)
    check("update idea", us == 200, f"status {us} {str(ud)[:100]}")
    saved = json.loads(STORE["constellarium:store"])
    check("change is persisted in the database", any(i["title"] == "web test idea" and i["description"] == "hello" for i in saved["ideas"]))
    s, d2, _ = call(port, "GET", "data", cookie=cookie)
    check("reload reads it back from the database", s == 200 and len(d2.get("ideas", [])) == n0 + 1, f"status {s} {str(d2)[:120]}")
    ds, dd, _ = call(port, "DELETE", f"ideas/{idea['id']}", cookie=cookie)
    check("delete idea", ds == 200, f"status {ds} {str(dd)[:100]}")

    s, imp, _ = call(port, "POST", "import", {"ideas": [{"title": "csv idea", "category": "A > B", "projects": "P1;P2"}]}, cookie=cookie)
    check("import by name", s == 200 and imp.get("ideasAdded") == 1)
    check("import keeps the previous version as a backup", "constellarium:store:backup:last" in STORE)
    s, rs, _ = call(port, "POST", "reseed", {}, cookie=cookie)
    check("reseed merges the bundle without duplicating", s == 200 and rs.get("ideasAdded") == 0, str(rs))
    check("logout clears the cookie", "Max-Age=0" in (call(port, "POST", "logout", {}, cookie=cookie)[2] or ""))
finally:
    p.terminate()

# ---------------------------------------------------------------- 4) config files Vercel needs
vj = json.loads((ROOT / "vercel.json").read_text(encoding="utf-8"))
check("vercel.json: static output + /api rewrite + function", vj["outputDirectory"] == "static" and vj["rewrites"][0]["destination"].startswith("/api/index")
      and "api/index.py" in vj["functions"])
vi = (ROOT / ".vercelignore").read_text(encoding="utf-8")
check(".vercelignore keeps core.py, seed/, api/, static/ in the deploy", all(x not in vi.splitlines() for x in ("core.py", "seed/", "api/", "static/")))
check("seed is bundled", (ROOT / "seed" / "seed_data.json").exists())
check(".env files are git-ignored", ".env" in (ROOT / ".gitignore").read_text(encoding="utf-8"))

redis.shutdown()
print("\nALL PASSED" if not fails else f"\nFAILED: {fails}")
sys.exit(1 if fails else 0)


