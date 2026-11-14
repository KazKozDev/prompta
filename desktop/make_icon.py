#!/usr/bin/env python3
"""Generates the app icon (1024×1024 PNG) without external assets."""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).resolve().parent / "icon.png"
SIZE = 1024
RADIUS = 220

TOP = (26, 140, 255)
BOTTOM = (0, 90, 214)


def make() -> None:
    image = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))

    # vertical gradient
    gradient = Image.new("RGBA", (SIZE, SIZE))
    draw = ImageDraw.Draw(gradient)
    for y in range(SIZE):
        t = y / (SIZE - 1)
        color = tuple(round(TOP[i] + (BOTTOM[i] - TOP[i]) * t) for i in range(3)) + (255,)
        draw.line([(0, y), (SIZE, y)], fill=color)

    # rounded-corner mask
    mask = Image.new("L", (SIZE, SIZE), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, SIZE - 1, SIZE - 1], radius=RADIUS, fill=255)

    image.paste(gradient, (0, 0), mask)

    # the «P →» glyph
    glyph = ImageDraw.Draw(image)
    font = None
    for candidate in (
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
    ):
        if Path(candidate).exists():
            try:
                font = ImageFont.truetype(candidate, 420)
                break
            except OSError:
                continue

    text = "P"
    arrow = "→"

    if font:
        box = glyph.textbbox((0, 0), text, font=font)
        w, h = box[2] - box[0], box[3] - box[1]
        glyph.text(((SIZE - w) / 2 - 90, (SIZE - h) / 2 - box[1] - 40), text, font=font, fill=(255, 255, 255, 255))

        small = ImageFont.truetype(font.path, 260)
        glyph.text((SIZE / 2 + 40, SIZE / 2 - 30), arrow, font=small, fill=(255, 255, 255, 235))
    else:
        glyph.rectangle([SIZE // 3, SIZE // 3, 2 * SIZE // 3, 2 * SIZE // 3], fill=(255, 255, 255, 255))

    image.save(OUT)
    print(f"icon: {OUT}")


if __name__ == "__main__":
    make()
