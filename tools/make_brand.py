"""Erzeugt Icon, Logo und Banner der Integration (Stil wie bei den anderen HA-Integrationen).

Aufruf aus dem Projektordner:  python tools/make_brand.py
Benötigt nur Pillow. Die Schrift ist Segoe UI Black (Windows); mit --font lässt sich eine andere angeben.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
BRAND_DIR = ROOT / "custom_components" / "discord_hub" / "brand"
DOCS_DIR = ROOT / "docs"

BASE = 512  # Zeichenfläche des Icons
SS = 4  # Supersampling für glatte Kanten

BG_TOP = (47, 38, 112)  # #2F2670
BG_BOTTOM = (26, 16, 64)  # #1A1040
TEAL = (32, 201, 190)  # #20C9BE
NAVY = (39, 69, 127)  # #27457F
ORANGE = (255, 138, 31)  # #FF8A1F
LAVENDER = (143, 130, 240)  # #8F82F0
WORD_LAVENDER = (123, 108, 240)  # #7B6CF0
GREEN = (61, 220, 132)  # #3DDC84
BADGE_DARK = (15, 16, 48)
WHITE = (255, 255, 255)


def diagonal_gradient(size: int, top: tuple[int, int, int], bottom: tuple[int, int, int]) -> Image.Image:
    """Diagonaler Verlauf von oben links nach unten rechts, klein berechnet und hochskaliert."""
    small = 256
    img = Image.new("RGB", (small, small))
    px = img.load()
    for y in range(small):
        for x in range(small):
            t = (x + y) / (2 * (small - 1))
            px[x, y] = tuple(round(a + (b - a) * t) for a, b in zip(top, bottom, strict=True))
    return img.resize((size, size), Image.BICUBIC)


def circle(draw: ImageDraw.ImageDraw, cx: float, cy: float, r: float, fill) -> None:
    draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=fill)


def draw_icon() -> Image.Image:
    """Quadratisches Icon: eine große und eine kleine Sprechblase (senden und empfangen), Abzeichen „verbunden“."""
    s = BASE * SS

    def p(v: float) -> float:
        return v * SS

    canvas = Image.new("RGBA", (s, s), (0, 0, 0, 0))

    bg = diagonal_gradient(s, BG_TOP, BG_BOTTOM).convert("RGBA")
    mask = Image.new("L", (s, s), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, s - 1, s - 1), radius=p(112), fill=255)
    canvas.paste(bg, (0, 0), mask)

    d = ImageDraw.Draw(canvas)

    # große Sprechblase mit Schwanz unten links, darin drei Textzeilen
    d.rounded_rectangle((p(70), p(130), p(362), p(318)), radius=p(58), fill=LAVENDER)
    d.polygon([(p(112), p(300)), (p(112), p(372)), (p(184), p(312))], fill=LAVENDER)
    for y, x1, color in ((168, 316, WHITE), (206, 280, TEAL), (244, 236, ORANGE)):
        d.rounded_rectangle((p(112), p(y), p(x1), p(y + 20)), radius=p(10), fill=color)

    # kleine Sprechblase unten rechts mit Schwanz, darin drei Punkte (die Antwort)
    d.rounded_rectangle((p(236), p(284), p(446), p(412)), radius=p(48), fill=TEAL, outline=BG_BOTTOM, width=int(p(10)))
    d.polygon([(p(386), p(396)), (p(426), p(458)), (p(346), p(406))], fill=TEAL)
    for cx in (290, 341, 392):
        circle(d, p(cx), p(348), p(14), NAVY)
    circle(d, p(286), p(338), p(4), (210, 255, 250))

    # glänzender Punkt oben links in der großen Blase
    circle(d, p(100), p(160), p(6), (225, 220, 255))

    # Abzeichen oben rechts: verbunden
    bx, by = 408, 112
    circle(d, p(bx), p(by), p(56), BADGE_DARK)
    circle(d, p(bx), p(by), p(36), GREEN)
    d.line(
        [(p(bx - 16), p(by + 1)), (p(bx - 4), p(by + 14)), (p(bx + 18), p(by - 12))],
        fill=WHITE,
        width=int(p(9)),
        joint="curve",
    )
    circle(d, p(bx - 16), p(by + 1), p(4.5), WHITE)
    circle(d, p(bx + 18), p(by - 12), p(4.5), WHITE)

    return canvas.resize((BASE, BASE), Image.LANCZOS)


def draw_banner(icon: Image.Image, font_path: str) -> Image.Image:
    """Breiter Banner: Icon links, Name zweizeilig rechts, transparenter Hintergrund."""
    height = 440
    pad = 40
    icon_size = height - 2 * pad
    icon_small = icon.resize((icon_size, icon_size), Image.LANCZOS)

    font = ImageFont.truetype(font_path, 150)
    lines = [("Discord", WORD_LAVENDER), ("Hub", ORANGE)]
    boxes = [font.getbbox(text) for text, _ in lines]
    text_w = max(b[2] - b[0] for b in boxes)
    line_h = [b[3] - b[1] for b in boxes]
    gap = 26
    block_h = sum(line_h) + gap
    text_x = pad + icon_size + 56
    width = text_x + text_w + pad + 20

    banner = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    banner.alpha_composite(icon_small, (pad, pad))
    d = ImageDraw.Draw(banner)
    y = (height - block_h) // 2
    for (text, color), box, h in zip(lines, boxes, line_h, strict=True):
        d.text((text_x - box[0], y - box[1]), text, font=font, fill=color)
        y += h + gap
    return banner


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--font", default=r"C:\Windows\Fonts\seguibl.ttf")
    args = parser.parse_args()

    BRAND_DIR.mkdir(parents=True, exist_ok=True)
    DOCS_DIR.mkdir(parents=True, exist_ok=True)

    icon = draw_icon()  # 512 x 512
    icon.save(BRAND_DIR / "icon@2x.png", optimize=True)
    icon.resize((256, 256), Image.LANCZOS).save(BRAND_DIR / "icon.png", optimize=True)
    icon.save(DOCS_DIR / "icon.png", optimize=True)

    banner = draw_banner(icon, args.font)
    banner.save(DOCS_DIR / "banner.png", optimize=True)
    for name, h in (("logo.png", 256), ("logo@2x.png", 512)):
        w = round(banner.width * h / banner.height)
        banner.resize((w, h), Image.LANCZOS).save(BRAND_DIR / name, optimize=True)

    print(
        "Fertig:",
        *sorted(p.relative_to(ROOT).as_posix() for p in (*BRAND_DIR.glob("*.png"), *DOCS_DIR.glob("*.png"))),
        sep="\n  ",
    )


if __name__ == "__main__":
    main()
