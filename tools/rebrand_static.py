"""One-off: rebrand the UI copied from IdeaBank. Safe to re-run (asserts are skipped when already applied)."""
from pathlib import Path

S = Path(__file__).resolve().parent.parent / "static"


def sub(name, pairs):
    f = S / name
    t = f.read_text(encoding="utf-8")
    for a, b in pairs:
        if a in t:
            t = t.replace(a, b)
    f.write_text(t, encoding="utf-8", newline="")


PING = ("<script>setInterval(()=>fetch('/api/ping').catch(()=>{}),10000);"
        "fetch('/api/ping').catch(()=>{});</script>\n</body>")

sub("index.html", [
    ("<title>IdeaBank</title>", "<title>Constellarium</title>"),
    ('<span class="logo">&#9672;</span> IdeaBank', '<span class="logo">&#10022;</span> Constellarium'),
    ("IdeaBank login", "Constellarium login"),
    ("This IdeaBank is password protected.", "This session is locked."),
])
t = (S / "index.html").read_text(encoding="utf-8")
if "/api/ping" not in t:
    (S / "index.html").write_text(t.replace("</body>", PING), encoding="utf-8", newline="")

sub("app.js", [
    ("/* IdeaBank front-end. State lives on the server (data/store.json)",
     "/* Constellarium front-end. State lives in the local store (%APPDATA%/Constellarium/store.json)"),
    ("Your IdeaBank is empty", "Your Constellarium is empty"),
    ("Full IdeaBank backup", "Full Constellarium backup"),
    ("`ideabank-${stamp}", "`constellarium-${stamp}"),
    ("ideabank-template.csv", "constellarium-template.csv"),
    ("ideabankSide", "constellariumSide"),
])
sub("graph.js", [("ideabank-graph.png", "constellarium-graph.png")])
print("done")
