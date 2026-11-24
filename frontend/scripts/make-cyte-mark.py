#!/usr/bin/env python3
"""Make the Cyte mark used by the website and the app from the supplied icon.

Source (kept unchanged): frontend/images/onekami-product.png, the Cyte product icon: a red brush ensō around an
orange four-point star, on a cream app tile with rounded corners and a soft grey edge.

Output, in frontend/public/:
  cyte-mark.png     trimmed, transparent background, 256 px tall (for headers, heroes and Open Graph use)
  cyte-mark-64.png  the same, 64 px tall (for small marks such as the app sidebar)
  og-image.png      1200x630 sharing card: the mark on warm paper with the wordmark and one line (Open Graph)

The cream tile is removed by "un-mixing" the paper colour: each pixel is treated as ink laid over the paper with
some opacity, and the smallest opacity that explains the pixel is used. Soft brush edges therefore become
semi-transparent ink instead of a cream fringe, and the ink colours (the red ensō, the orange star) are kept. The
tile's grey edge and shadow are neutral, not ink, so pixels with almost no colour saturation are dropped.

Run from frontend/:  python3 scripts/make-cyte-mark.py   (needs Pillow; the sharing card uses Noto Serif and
Noto Sans from the system, found with fc-match, and is skipped with a message if they are missing)
"""

import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "images" / "onekami-product.png"
OUT = ROOT / "public"
PAD = 4  # transparent pixels kept around the trimmed mark, in source pixels
NOISE = 14  # alpha below this (out of 255) is paper texture, not ink
NEUTRAL = 40  # a pixel whose channels differ by less than this is grey (tile edge, shadow), not red or orange ink


def paper_colour(img: Image.Image) -> tuple[int, int, int]:
    """The most common light colour: the tile's cream."""
    counts: dict[tuple[int, int, int], int] = {}
    small = img.convert("RGB").resize((128, 128))
    pixels = small.get_flattened_data() if hasattr(small, "get_flattened_data") else small.getdata()
    for p in pixels:
        if min(p) > 200:
            counts[p] = counts.get(p, 0) + 1
    return max(counts, key=counts.__getitem__)


def unmix(img: Image.Image, paper: tuple[int, int, int]) -> Image.Image:
    src = img.convert("RGB")
    out = Image.new("RGBA", src.size)
    w, h = src.size
    s, o = src.load(), out.load()
    for y in range(h):
        for x in range(w):
            px = s[x, y]
            if max(px) - min(px) < NEUTRAL:
                o[x, y] = (0, 0, 0, 0)
                continue
            # Opacity needed in each channel to darken the paper to this pixel: (paper - c) / paper.
            a = max(round((p - c) * 255 / p) if c < p else 0 for c, p in zip(px, paper))
            if a < NOISE:
                o[x, y] = (0, 0, 0, 0)
                continue
            # c = ink * a + paper * (1 - a)  =>  ink = (c - paper * (1 - a)) / a
            ink = tuple(max(0, min(255, round((c - p * (255 - a) / 255) * 255 / a))) for c, p in zip(px, paper))
            o[x, y] = (*ink, a)
    return out


PAPER = (251, 250, 247)  # --color-page
INK = (15, 14, 12)  # --color-ink-950
MUTED = (98, 92, 83)  # --color-ink-500
RED = (170, 28, 26)  # --color-brush, the ensō red


def font(pattern: str, size: int) -> ImageFont.FreeTypeFont | None:
    try:
        path = subprocess.run(["fc-match", "-f", "%{file}", pattern], capture_output=True, text=True, check=True).stdout
        return ImageFont.truetype(path, size)
    except (OSError, subprocess.CalledProcessError):
        return None


def og_image(mark: Image.Image) -> None:
    serif, sans, mono = font("Noto Serif:style=Regular", 112), font("Noto Sans:style=Regular", 34), font("DejaVu Sans Mono", 20)
    if not (serif and sans and mono):
        print("og-image.png skipped: Noto Serif, Noto Sans or DejaVu Sans Mono not found")
        return
    card = Image.new("RGBA", (1200, 630), PAPER + (255,))
    draw = ImageDraw.Draw(card)
    # The same hairline 64px grid as the website's hero.
    for x in range(0, 1200, 64):
        draw.line([(x, 0), (x, 630)], fill=(236, 233, 227), width=1)
    for y in range(0, 630, 64):
        draw.line([(0, y), (1200, y)], fill=(236, 233, 227), width=1)
    m = mark.resize((round(mark.width * 300 / mark.height), 300), Image.LANCZOS)
    card.alpha_composite(m, (110, 165))
    draw.text((470, 170), "Cyte", font=serif, fill=INK)
    draw.text((474, 352), "Verified, cited answers from", font=sans, fill=MUTED)
    draw.text((474, 396), "legal and medical documents.", font=sans, fill=MUTED)
    draw.ellipse([(474, 481), (484, 491)], fill=RED)
    draw.text((498, 474), "BY ONEKAMI", font=mono, fill=MUTED)
    card.convert("RGB").save(OUT / "og-image.png", optimize=True)
    print("public/og-image.png: 1200x630")


def main() -> None:
    source = Image.open(SRC)
    mark = unmix(source, paper_colour(source))
    box = mark.getchannel("A").getbbox()
    assert box, "no ink found in the source image"
    left, top, right, bottom = box
    w, h = mark.size
    mark = mark.crop((max(0, left - PAD), max(0, top - PAD), min(w, right + PAD), min(h, bottom + PAD)))
    for height, name in ((256, "cyte-mark.png"), (64, "cyte-mark-64.png")):
        width = round(mark.width * height / mark.height)
        mark.resize((width, height), Image.LANCZOS).save(OUT / name, optimize=True)
        print(f"public/{name}: {width}x{height}")
    og_image(mark)


if __name__ == "__main__":
    main()
