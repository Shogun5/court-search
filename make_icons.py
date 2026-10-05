"""產生 PWA 圖示（天秤＋放大鏡）。需要 Pillow：pip install pillow"""
from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).with_name("static") / "icons"
BG, FG, GOLD = (31, 58, 95), (255, 255, 255), (240, 196, 92)


def draw(size, maskable=False):
    s = 1024  # 先畫大圖再縮小，邊緣較平滑
    img = Image.new("RGB", (s, s), BG)
    d = ImageDraw.Draw(img)
    k = 0.72 if maskable else 1.0  # maskable 圖示要留安全區
    c = s / 2
    P = lambda x, y: (c + (x - 512) * k, c + (y - 512) * k)
    w = lambda v: max(1, int(v * k))

    d.line([P(512, 200), P(512, 760)], fill=FG, width=w(40))              # 柱
    d.line([P(250, 300), P(774, 300)], fill=FG, width=w(36))              # 橫樑
    d.rounded_rectangle([P(380, 740), P(644, 800)], radius=w(20), fill=FG)  # 底座
    for x in (250, 774):                                                  # 秤盤
        d.line([P(x, 300), P(x - 90, 520)], fill=FG, width=w(14))
        d.line([P(x, 300), P(x + 90, 520)], fill=FG, width=w(14))
        d.chord([P(x - 120, 440), P(x + 120, 600)], 0, 180, fill=FG)
    d.ellipse([P(600, 560), P(820, 780)], outline=GOLD, width=w(40))      # 放大鏡
    d.line([P(800, 760), P(900, 860)], fill=GOLD, width=w(56))
    d.ellipse([P(472, 160), P(552, 240)], fill=GOLD)
    return img.resize((size, size), Image.LANCZOS)


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    draw(192).save(OUT / "icon-192.png")
    draw(512).save(OUT / "icon-512.png")
    draw(512, maskable=True).save(OUT / "icon-maskable-512.png")
    print("圖示已產生於", OUT)
