"""Local preview of the WEB experience (password login, hub, to-do, password manager) with throw-away data.
Usage: python -X utf8 tools/devserver.py [port]
Passwords for this preview (override with the usual env vars): main = dev-main-pass, vault = dev-vault-pass.
Data goes to a temporary folder (CONSTELLARIUM_HOME or the temp folder), never to your real store."""
import os
import sys
import tempfile
from http.server import ThreadingHTTPServer
from pathlib import Path

os.environ.setdefault("CONSTELLARIUM_PASSWORD", "dev-main-pass")
os.environ.setdefault("CONSTELLARIUM_VAULT_PASSWORD", "dev-vault-pass")
os.environ.setdefault("CONSTELLARIUM_HOME", str(Path(tempfile.gettempdir()) / "constellarium-dev"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import core  # noqa: E402

port = int(sys.argv[1]) if len(sys.argv) > 1 else 8780
core.ALLOWED_HOSTS = {f"127.0.0.1:{port}", f"localhost:{port}"}
print(f"Constellarium dev preview on http://127.0.0.1:{port}  (data in {core.HOME})", flush=True)
ThreadingHTTPServer(("127.0.0.1", port), core.Handler).serve_forever()
