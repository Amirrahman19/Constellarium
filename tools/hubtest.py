"""Hub test: the real Vercel handler (api/index.py, VERCEL=1, API path as ?path=...) against a fake Upstash Redis.
Covers the second (vault) password gate, ciphertext-only vault storage, the to-do list and its sync with the banks.
Usage: python -X utf8 tools/hubtest.py"""
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
MAIN, VAULT = "main-" + os.urandom(4).hex(), "vault-" + os.urandom(4).hex()
STORE = {}


class Srv(http.server.ThreadingHTTPServer):
    request_queue_size = 128
    daemon_threads = True


class FakeRedis(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def do_POST(self):
        cmd = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if cmd[0] == "GET":
            out = {"result": STORE.get(cmd[1])}
        else:
            STORE[cmd[1]] = cmd[2]
            out = {"result": "OK"}
        b = json.dumps(out).encode()
        self.send_response(200)
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


RUNNER = '''
import sys, http.server
sys.path.insert(0, r"%s")
from api.index import handler as _h
class handler(_h):
    protocol_version = "HTTP/1.1"
class Srv(http.server.ThreadingHTTPServer):
    request_queue_size = 128
    daemon_threads = True
Srv(("127.0.0.1", int(sys.argv[1])), handler).serve_forever()
''' % ROOT

redis_port = free_port()
threading.Thread(target=Srv(("127.0.0.1", redis_port), FakeRedis).serve_forever, daemon=True).start()


def start_app(extra_env):
    port = free_port()
    env = {**os.environ, "VERCEL": "1", "UPSTASH_REDIS_REST_URL": f"http://127.0.0.1:{redis_port}", "UPSTASH_REDIS_REST_TOKEN": "t", **extra_env}
    env.pop("CONSTELLARIUM_HOME", None)
    p = subprocess.Popen([sys.executable, "-X", "utf8", "-c", RUNNER, str(port)], env=env, cwd=str(ROOT), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(50):
        try:
            http.client.HTTPConnection("127.0.0.1", port, timeout=1).connect()
            break
        except OSError:
            time.sleep(0.2)
    return p, port


class Client:
    def __init__(self, port):
        self.port, self.jar = port, {}

    def call(self, method, path, body=None, headers=None, cookies=True):
        h = {"Host": "constellarium-test.vercel.app", "Content-Type": "application/json", **(headers or {})}
        if cookies and self.jar:
            h["Cookie"] = "; ".join(f"{k}={v}" for k, v in self.jar.items())
        for attempt in range(4):
            try:
                c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=20)
                c.request(method, f"/api/index?path={path}", body=json.dumps(body) if body is not None else None, headers=h)
                r = c.getresponse()
                raw = r.read()
                break
            except (ConnectionError, TimeoutError, http.client.HTTPException):
                if attempt == 3:
                    raise
                time.sleep(0.5)
        for k, v in r.getheaders():
            if k.lower() == "set-cookie":
                name, _, rest = v.partition("=")
                val = rest.split(";")[0]
                if "Max-Age=0" in v:
                    self.jar.pop(name, None)
                else:
                    self.jar[name] = val
        try:
            data = json.loads(raw or b"{}")
        except ValueError:
            data = {}
        return r.status, data


def blob(tag):
    return {"iv": "aXY=", "ct": "Y3Q-" + tag}


TODAY = time.strftime("%Y-%m-%d")

# ------------------------------------------------------------ vault not configured
p, port = start_app({"CONSTELLARIUM_PASSWORD": MAIN})
try:
    c = Client(port)
    c.call("POST", "login", {"password": MAIN})
    s, d = c.call("GET", "vault/status")
    check("no vault password -> status says not configured", s == 200 and d["configured"] is False)
    s, d = c.call("POST", "vault/unlock", {"password": MAIN})
    check("no vault password -> unlock refused with setup hint", s == 503 and "CONSTELLARIUM_VAULT_PASSWORD" in d.get("error", ""))
    s, d = c.call("GET", "summary")
    check("summary says vault not configured", d["vault"]["configured"] is False)
finally:
    p.terminate()

p, port = start_app({"CONSTELLARIUM_PASSWORD": MAIN, "CONSTELLARIUM_VAULT_PASSWORD": MAIN})
try:
    c = Client(port)
    c.call("POST", "login", {"password": MAIN})
    s, d = c.call("POST", "vault/unlock", {"password": MAIN})
    check("vault password equal to main password is refused", s == 503 and "different" in d.get("error", ""))
finally:
    p.terminate()

# ------------------------------------------------------------ everything configured
p, port = start_app({"CONSTELLARIUM_PASSWORD": MAIN, "CONSTELLARIUM_VAULT_PASSWORD": VAULT})
try:
    c = Client(port)
    s, d = c.call("GET", "vault")
    check("vault without any login -> 401 login", s == 401 and d.get("login"))
    s, d = c.call("POST", "login", {"password": VAULT})
    check("vault password does NOT open the main login", s == 401)
    s, d = c.call("POST", "login", {"password": MAIN})
    check("main login ok; sets session + clears vault cookie", s == 200 and "cs_pw" in c.jar and "cs_vault" not in c.jar)
    s, d = c.call("GET", "vault")
    check("signed in but vault locked -> 401 vaultLocked", s == 401 and d.get("vaultLocked"))
    s, d = c.call("POST", "vault/unlock", {"password": MAIN})
    check("main password does NOT open the vault", s == 401 and "cs_vault" not in c.jar)
    s, d = c.call("POST", "vault/unlock", {"password": VAULT})
    check("vault password unlocks (salt returned, no check yet)", s == 200 and d["salt"] and d["check"] is None and "cs_vault" in c.jar)
    s, d = c.call("PUT", "vault/check", {"check": blob("check")})
    check("first-time check stored", s == 200)
    s, d = c.call("PUT", "vault/check", {"check": blob("other")})
    check("check can not be overwritten", s == 400)
    s, d = c.call("POST", "vault/entries", {"id": "0123456789", "meta": blob("m1"), "secret": blob("s1")})
    check("add entry (ciphertext blobs)", s == 200 and d["id"] == "0123456789")
    s, d = c.call("POST", "vault/entries", {"meta": {"name": "plain"}, "secret": blob("s")})
    check("plaintext / malformed entry rejected", s == 400)
    s, d = c.call("PUT", "vault/entries/0123456789", {"meta": blob("m2"), "secret": blob("s2")})
    check("edit entry", s == 200 and d["meta"]["ct"].endswith("m2"))
    s, d = c.call("GET", "vault")
    check("vault returns salt, check, entries", s == 200 and len(d["entries"]) == 1 and d["check"])
    dumped = json.dumps(STORE)
    check("database holds only the blobs we sent (no plaintext fields)", '"name"' not in STORE.get("constellarium:store:vault", "") and "meta" in STORE.get("constellarium:store:vault", ""), "")
    # forged / replayed tokens
    bad = Client(port)
    bad.jar = {"cs_pw": c.jar["cs_pw"], "cs_vault": "9999999999.deadbeef"}
    s, d = bad.call("GET", "vault")
    check("forged vault cookie rejected", s == 401 and d.get("vaultLocked"))
    only_vault = Client(port)
    only_vault.jar = {"cs_vault": c.jar["cs_vault"]}
    s, d = only_vault.call("GET", "vault")
    check("vault cookie without the main session rejected", s == 401 and d.get("login"))
    sys.path.insert(0, str(ROOT))
    os.environ.update({"CONSTELLARIUM_PASSWORD": MAIN, "CONSTELLARIUM_VAULT_PASSWORD": VAULT, "VERCEL": "1"})
    import core
    expired = "100." + core.Handler._sig("vault", "100", VAULT)
    old = Client(port)
    old.jar = {"cs_pw": c.jar["cs_pw"], "cs_vault": expired}
    s, d = old.call("GET", "vault")
    check("expired (correctly signed) vault token rejected", s == 401 and d.get("vaultLocked"))
    expired_main = "100." + core.Handler._sig("main", "100")
    old.jar = {"cs_pw": expired_main}
    s, d = old.call("GET", "data")
    check("expired main session token rejected", s == 401 and d.get("login"))
    s, d = c.call("POST", "vault/rekey", {"check": blob("c2"), "entries": [{"id": "abcdefabcd", "meta": blob("a"), "secret": blob("b")}]})
    s2, d2 = c.call("GET", "vault")
    check("rekey replaces everything", s == 200 and [e["id"] for e in d2["entries"]] == ["abcdefabcd"] and d2["check"]["ct"].endswith("c2"))
    s, d = c.call("DELETE", "vault/entries/abcdefabcd")
    s2, d2 = c.call("GET", "vault")
    check("delete entry", s == 200 and d2["entries"] == [])
    c.call("POST", "vault/lock", {})
    s, d = c.call("GET", "vault")
    check("lock clears the vault cookie -> locked again", s == 401 and d.get("vaultLocked"))

    # ---------------- to-do list + sync with the banks
    s, d = c.call("POST", "todos", {"title": "   "})
    check("task without a title rejected", s == 400)
    s, d = c.call("GET", "data", headers={"X-Bank": "ideabank"})
    ideas = d["ideas"]
    idea = ideas[0]
    s, t1 = c.call("POST", "todos", {"title": "Call the supplier", "due": "not-a-date", "priority": "weird", "link": {"bank": "ideabank", "id": idea["id"]}})
    check("create linked task (bad date / priority sanitised)", s == 200 and t1["due"] == "" and t1["priority"] == "normal" and t1["ref"]["exists"] and t1["ref"]["title"] == idea["title"])
    s, t2 = c.call("POST", "todos", {"title": "Overdue thing", "due": "2000-01-01", "priority": "high"})
    s, t3 = c.call("POST", "todos", {"title": "Due today", "due": TODAY})
    s, d = c.call("GET", "summary", headers={"X-Today": TODAY})
    check("summary counts (open 3, overdue 1, today 1)", d["todos"]["open"] == 3 and d["todos"]["overdue"] == 1 and d["todos"]["today"] == 1, str(d["todos"]))
    s, d = c.call("GET", "summary", headers={"X-Today": "2000-01-01"})
    check("summary uses the browser's date (X-Today)", d["todos"]["today"] == 1 and d["todos"]["overdue"] == 0, str(d["todos"]))
    s, d = c.call("PUT", f"todos/{t1['id']}", {"done": True})
    check("mark done sets doneAt", s == 200 and d["done"] and d["doneAt"])
    s, d = c.call("PUT", f"todos/{t1['id']}", {"done": False})
    check("untick clears doneAt", d["done"] is False and d["doneAt"] == "")
    # rename follows
    s, _ = c.call("PUT", f"ideas/{idea['id']}", {"title": "Renamed in the bank"}, headers={"X-Bank": "ideabank"})
    s, d = c.call("GET", "todos")
    r = next(t for t in d["tasks"] if t["id"] == t1["id"])
    check("SYNC: renaming the idea updates the task's link", r["ref"]["title"] == "Renamed in the bank")
    s, d = c.call("GET", f"todos/for/ideabank/{idea['id']}")
    check("tasks-for-idea lookup (used by the bank detail panel)", [t["id"] for t in d["tasks"]] == [t1["id"]])
    # move to the other bank
    s, d = c.call("POST", "ideas/transfer", {"to": "problembank", "ids": [idea["id"]]}, headers={"X-Bank": "ideabank"})
    check("transfer to ProblemBank", s == 200 and d["moved"] == 1)
    s, d = c.call("GET", "todos")
    r = next(t for t in d["tasks"] if t["id"] == t1["id"])
    check("SYNC: moving the idea re-points the task to the other bank", r["link"]["bank"] == "problembank" and r["ref"]["exists"] and r["ref"]["bank"] == "problembank", str(r.get("ref")))
    s, d = c.call("GET", f"todos/for/problembank/{idea['id']}")
    check("task found under the new bank", len(d["tasks"]) == 1)
    # delete + undo
    s, d = c.call("POST", "ideas/delete", {"ids": [idea["id"]]}, headers={"X-Bank": "problembank"})
    deleted = d["deleted"]
    s, d = c.call("GET", "todos")
    r = next(t for t in d["tasks"] if t["id"] == t1["id"])
    check("SYNC: deleting the idea marks the task's link as removed (task kept)", r["ref"]["exists"] is False)
    s, d = c.call("POST", "ideas/restore", {"ideas": deleted, "links": []}, headers={"X-Bank": "problembank"})
    s, d = c.call("GET", "todos")
    r = next(t for t in d["tasks"] if t["id"] == t1["id"])
    check("SYNC: Undo of the delete re-connects the task", r["ref"]["exists"] is True)
    s, d = c.call("GET", "items")
    check("items list covers both banks", {i["bank"] for i in d["items"]} == {"ideabank", "problembank"} and len(d["items"]) >= 214)
    s, _ = c.call("PUT", f"todos/{t3['id']}", {"done": True})
    s, d = c.call("POST", "todos/clear-done", {})
    check("clear completed", s == 200 and d["cleared"] == 1)
    s, d = c.call("DELETE", f"todos/{t2['id']}")
    s, d = c.call("GET", "todos")
    check("delete task", all(t["id"] != t2["id"] for t in d["tasks"]) and len(d["tasks"]) == 1)
    s, d = c.call("POST", "logout", {})
    s, d = c.call("GET", "todos")
    check("after log out nothing is readable", s == 401)
finally:
    p.terminate()

print("\nALL PASSED" if not fails else f"\n{len(fails)} FAILED: {fails}")
sys.exit(1 if fails else 0)
