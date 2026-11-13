"""Vercel serverless entry: every /api/* request is rewritten here (see vercel.json).
The web app is the same core.Handler as the local exe, running in web mode (Vercel sets VERCEL=1):
password login (CONSTELLARIUM_PASSWORD) and database storage (Neon Postgres or Upstash Redis)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # project root: core.py, seed/
from core import Handler as _Handler  # noqa: E402


class handler(_Handler):
    QUERY_PATH = True        # the rewrite in vercel.json passes the API path as ?path=...
    SERVE_STATIC = False     # the UI (static/) is served by Vercel's CDN
    protocol_version = "HTTP/1.0"   # Vercel's Python runtime expects one response per connection
