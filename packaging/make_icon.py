#!/usr/bin/env python3
"""Draw the app icon (the project's own logo) and write it as an .icns: make_icon.py OUT.icns

The idea in one picture: the lower-left of the square is coarse pixels, and it turns into a
smooth, sharp gradient toward the upper-right, which is what the program does to a picture.
"""
import os
import subprocess
import sys
import tempfile

import numpy as np
from PIL import Image, ImageDraw

SIZE = 1024


def logo():
    y, x = np.mgrid[0:SIZE, 0:SIZE].astype(np.float32) / (SIZE - 1)
    t = np.clip((x + (1 - y)) / 2, 0, 1)  # 0 at the lower-left, 1 at the upper-right
    a, b = np.array([22, 40, 92], np.float32), np.array([64, 214, 196], np.float32)  # deep blue -> teal
    smooth = (a[None, None] * (1 - t[..., None]) + b[None, None] * t[..., None]).astype(np.uint8)
    img = Image.fromarray(smooth)
    coarse = img.resize((10, 10), Image.BOX).resize((SIZE, SIZE), Image.NEAREST)  # the same picture, as 10x10 blocks
    # a soft diagonal edge between the blocks (lower-left) and the smooth part (upper-right)
    d = (x + (1 - y)) - 1  # < 0 in the lower-left half (the same diagonal as the gradient's midpoint)
    blend = np.clip(0.5 - d * 6, 0, 1)  # 1 = blocks, 0 = smooth, over a narrow band
    out = (np.asarray(coarse, np.float32) * blend[..., None] + np.asarray(img, np.float32) * (1 - blend[..., None]))
    out = Image.fromarray(out.astype(np.uint8)).convert("RGBA")
    # macOS-style rounded square with a margin, drop shadow-free (the system adds its own)
    margin, radius = 100, 185
    mask = Image.new("L", (SIZE, SIZE), 0)
    ImageDraw.Draw(mask).rounded_rectangle((margin, margin, SIZE - margin, SIZE - margin), radius, fill=255)
    canvas = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    canvas.paste(out, (0, 0), mask)
    # a small white arrow pointing up and to the right: "bigger"
    dr = ImageDraw.Draw(canvas)
    cx, cy, L = 560, 470, 190
    dr.line((cx - L, cy + L, cx + L, cy - L), fill=(255, 255, 255, 235), width=58)
    dr.polygon([(cx + L + 70, cy - L - 70), (cx + L - 150, cy - L + 20), (cx + L - 20, cy - L + 150)], fill=(255, 255, 255, 235))
    return canvas


def main(dest):
    img = logo()
    with tempfile.TemporaryDirectory() as d:
        iconset = os.path.join(d, "MacImageEnhancer.iconset")
        os.makedirs(iconset)
        for base in (16, 32, 128, 256, 512):
            img.resize((base, base), Image.LANCZOS).save(os.path.join(iconset, f"icon_{base}x{base}.png"))
            img.resize((base * 2, base * 2), Image.LANCZOS).save(os.path.join(iconset, f"icon_{base}x{base}@2x.png"))
        os.makedirs(os.path.dirname(os.path.abspath(dest)), exist_ok=True)
        subprocess.run(["iconutil", "-c", "icns", iconset, "-o", dest], check=True)
    img.save(os.path.splitext(dest)[0] + ".png")
    print(f"wrote {dest}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "build/MacImageEnhancer.icns")
