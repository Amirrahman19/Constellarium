"""Constellarium - a private, local idea atlas.  A native Windows desktop app (PySide6 / Qt).  No browser needed.

How it works: the UI is embedded in the app's own window (Qt WebEngine, bundled inside the exe). A tiny
internal server bound to 127.0.0.1 on a random port feeds it; it is locked with a random per-launch token
so nothing else on this PC or network can read the data.
Your data: %APPDATA%\\Constellarium\\store.json  (backups in backups\\). Nothing leaves this computer.

Options:  --reseed      merge the bundled project-idea compilation into your store again (no duplicates)
          --no-window   start the internal server only and print the URL (used by tools/selftest.py)
          --home PATH   use a different data folder
"""
import argparse
import json
import os
import secrets
import sys
import threading
import time
import urllib.request
from http.server import ThreadingHTTPServer

if "--home" in sys.argv:   # must be set before core computes its paths
    os.environ["CONSTELLARIUM_HOME"] = sys.argv[sys.argv.index("--home") + 1]

import core  # noqa: E402

APP_NAME = "Constellarium"


def log(msg):
    try:
        core.HOME.mkdir(parents=True, exist_ok=True)
        with (core.HOME / "constellarium.log").open("a", encoding="utf-8") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + msg + "\n")
    except OSError:
        pass
    if sys.stdout:
        print(msg, flush=True)


def _http_ok(port, token):
    try:
        req = urllib.request.Request(f"http://127.0.0.1:{port}/api/ping", headers={"Cookie": f"cs_session={token}"})
        with urllib.request.urlopen(req, timeout=2) as r:
            return r.status == 200
    except Exception:
        return False


def existing_instance():
    try:
        d = json.loads((core.HOME / "instance.json").read_text(encoding="utf-8"))
        return d if _http_ok(d["port"], d["token"]) else None
    except (OSError, ValueError, KeyError):
        return None


class FastServer(ThreadingHTTPServer):
    request_queue_size = 128      # default is 5: Chromium opens many connections at once; overflow gets reset/stalled on Windows

    def server_bind(self):
        # HTTPServer.server_bind() calls socket.getfqdn(), a reverse-DNS lookup that can stall ~20 s on some networks
        import socketserver
        socketserver.TCPServer.server_bind(self)
        self.server_name, self.server_port = "127.0.0.1", self.server_address[1]


def start_server(port=0):
    core.SESSION_TOKEN = secrets.token_urlsafe(32)
    srv = FastServer(("127.0.0.1", port), core.Handler)
    srv.daemon_threads = True
    p = srv.server_address[1]
    core.ALLOWED_HOSTS = {f"127.0.0.1:{p}", f"localhost:{p}"}
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    (core.HOME / "instance.json").write_text(
        json.dumps({"port": p, "token": core.SESSION_TOKEN, "pid": os.getpid()}), encoding="utf-8")
    return srv, p, f"http://127.0.0.1:{p}/?k={core.SESSION_TOKEN}"


def make_splash(QtCore, QtGui, QtWidgets):
    """Native loading screen, drawn in code (no image file) and shown the moment Qt is up."""
    Qt = QtCore.Qt
    w, h = 560, 320
    pm = QtGui.QPixmap(w, h)
    pm.fill(QtGui.QColor("#10162c"))
    p = QtGui.QPainter(pm)
    p.setRenderHint(QtGui.QPainter.Antialiasing)
    p.setPen(QtGui.QPen(QtGui.QColor("#4f8cff"), 3))
    p.drawRoundedRect(2, 2, w - 4, h - 4, 18, 18)
    pts = [(70, 150), (120, 80), (190, 120), (240, 60), (175, 170)]       # the logo constellation
    p.setPen(QtGui.QPen(QtGui.QColor(120, 160, 255, 170), 3))
    for a, b in [(0, 1), (1, 2), (2, 3), (2, 4), (1, 3)]:
        p.drawLine(*pts[a], *pts[b])
    p.setPen(Qt.NoPen)
    for i, (x, y) in enumerate(pts):
        p.setBrush(QtGui.QColor("#f2c94c" if i == 3 else "#e9f0ff"))
        p.drawEllipse(QtCore.QPointF(x, y), 7 if i in (1, 2) else 5, 7 if i in (1, 2) else 5)
    p.setPen(QtGui.QColor("#e9f0ff"))
    f = QtGui.QFont("Segoe UI", 26, QtGui.QFont.DemiBold)
    p.setFont(f)
    p.drawText(QtCore.QRect(290, 90, 260, 60), Qt.AlignLeft | Qt.AlignVCenter, "Constellarium")
    f2 = QtGui.QFont("Segoe UI", 11)
    p.setFont(f2)
    p.setPen(QtGui.QColor("#8fa2cf"))
    p.drawText(QtCore.QRect(292, 150, 260, 30), Qt.AlignLeft | Qt.AlignVCenter, "your private idea atlas")
    p.end()
    splash = QtWidgets.QSplashScreen(pm, Qt.WindowStaysOnTopHint)
    splash.setFont(QtGui.QFont("Segoe UI", 11))
    state = {"n": 0}

    def tick():                                  # animated "Loading your ideas..."
        state["n"] = (state["n"] + 1) % 4
        splash.showMessage("Loading your ideas" + "." * state["n"], Qt.AlignBottom | Qt.AlignHCenter,
                           QtGui.QColor("#8fa2cf"))

    timer = QtCore.QTimer(splash)
    timer.timeout.connect(tick)
    timer.start(350)
    tick()
    return splash


def run_window(prepare, icon_path):
    """prepare() seeds the store and starts the internal server; it returns the launch URL.
    The splash screen is up before any of that happens."""
    # The app only talks to its own 127.0.0.1 server. Chromium's automatic proxy detection (WPAD) can stall the
    # first request for ~20 s on some networks, so switch proxies off for the embedded browser. Must precede Qt init.
    os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = (os.environ.get("QTWEBENGINE_CHROMIUM_FLAGS", "") + " --no-proxy-server").strip()
    from PySide6 import QtCore, QtGui, QtWidgets
    from PySide6.QtCore import QUrl
    from PySide6.QtGui import QIcon
    from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile
    from PySide6.QtWebEngineWidgets import QWebEngineView
    from PySide6.QtWidgets import QApplication, QFileDialog, QMainWindow

    app = QApplication(sys.argv[:1])
    app.setApplicationName(APP_NAME)
    if icon_path and os.path.exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))
    splash = make_splash(QtCore, QtGui, QtWidgets)
    splash.show()
    app.processEvents()
    url = prepare()

    profile = QWebEngineProfile("constellarium", app)          # persistent: remembers sidebar state etc.
    profile.setPersistentStoragePath(str(core.HOME / "webdata"))
    profile.setCachePath(str(core.HOME / "webcache"))

    def on_download(item):                                      # Export / graph PNG -> native Save dialog
        name = item.downloadFileName() or "export"
        path, _ = QFileDialog.getSaveFileName(win, "Save", str(os.path.join(os.path.expanduser("~"), "Downloads", name)))
        if path:
            item.setDownloadDirectory(os.path.dirname(path))
            item.setDownloadFileName(os.path.basename(path))
            item.accept()
        else:
            item.cancel()

    profile.downloadRequested.connect(on_download)

    win = QMainWindow()
    win.setWindowTitle(APP_NAME)
    view = QWebEngineView(win)
    view.setPage(QWebEnginePage(profile, view))
    win.setCentralWidget(view)
    avail = app.primaryScreen().availableGeometry()           # usable screen area (excludes the taskbar)
    win.resize(min(1440, avail.width()), min(900, avail.height()))   # never taller/wider than the screen
    view.titleChanged.connect(lambda t: win.setWindowTitle(t or APP_NAME))
    shown = {"done": False}

    # A hidden QWebEngineView does not load its page, so the window is shown right away but fully transparent
    # behind the splash, then made opaque once the page has loaded.
    win.setWindowOpacity(0.0)
    win.showMaximized()                                       # fills the usable area exactly, so nothing hangs off-screen

    def reveal(ok=True):                         # page ready -> swap the splash for the real window
        if not shown["done"]:
            shown["done"] = True
            win.setWindowOpacity(1.0)
            win.raise_()
            win.activateWindow()
            splash.finish(win)

    view.loadFinished.connect(reveal)
    QtCore.QTimer.singleShot(15000, reveal)      # never leave the splash up forever
    view.load(QUrl(url))
    code = app.exec()
    view.setPage(None)
    return code


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--reseed", action="store_true")
    ap.add_argument("--no-window", action="store_true")
    ap.add_argument("--home")
    ap.add_argument("--port", type=int, default=0)
    a = ap.parse_args()

    core.HOME.mkdir(parents=True, exist_ok=True)
    if a.reseed:
        log(f"reseed: {core.reseed()}")
    if not a.no_window and existing_instance():
        log("already running - not starting a second copy")      # two writers on one store would be unsafe
        return
    holder = {}

    def prepare():
        stats = core.seed_if_empty()
        if stats:
            log(f"first launch: seeded {stats}")
        holder["srv"], port, url = start_server(a.port)
        log(f"{APP_NAME} internal server on 127.0.0.1:{port}")
        return url

    try:
        if a.no_window:
            url = prepare()
            print(url, flush=True)
            while True:
                time.sleep(1)
        run_window(prepare, str(core.BUNDLE / "assets" / "constellarium.ico"))
    except KeyboardInterrupt:
        pass
    finally:
        try:
            (core.HOME / "instance.json").unlink()
        except OSError:
            pass
        if "srv" in holder:
            holder["srv"].shutdown()
        log("closed")


if __name__ == "__main__":
    try:
        main()
    except Exception:          # windowed exe has no console: keep the traceback in the log file
        import traceback
        log("CRASH:\n" + traceback.format_exc())
        raise
