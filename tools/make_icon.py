"""Draw the Constellarium icon (a small constellation on a night-blue tile) -> static/favicon.png, assets/constellarium.ico"""
from pathlib import Path
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
N = 512
img = Image.new("RGBA", (N, N), (0, 0, 0, 0))
d = ImageDraw.Draw(img)
d.rounded_rectangle((8, 8, N - 8, N - 8), radius=110, fill=(16, 22, 44, 255))
d.rounded_rectangle((8, 8, N - 8, N - 8), radius=110, outline=(79, 140, 255, 255), width=10)
pts = [(120, 360), (210, 210), (330, 280), (400, 140), (300, 400)]
for a, b in [(0, 1), (1, 2), (2, 3), (2, 4), (1, 3)]:
    d.line([pts[a], pts[b]], fill=(120, 160, 255, 200), width=9)
for i, (x, y) in enumerate(pts):
    r = 30 if i in (1, 2) else 20
    d.ellipse((x - r - 14, y - r - 14, x + r + 14, y + r + 14), fill=(79, 140, 255, 55))
    d.ellipse((x - r, y - r, x + r, y + r), fill=(242, 201, 76, 255) if i == 3 else (233, 240, 255, 255))
(ROOT / "assets").mkdir(exist_ok=True)
img.save(ROOT / "static" / "favicon.png")
img.save(ROOT / "assets" / "constellarium.ico", sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
print("icon written")
