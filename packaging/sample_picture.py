#!/usr/bin/env python3
"""A made-up dusk landscape for screenshots: python3 packaging/sample_picture.py out.jpg [width]

Soft on purpose, like a small phone picture. Needs Pillow and numpy."""
import math
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFilter


def make(width=960):
    w, h = width, width * 2 // 3
    y = np.linspace(0, 1, h)[:, None]
    stops = [(0.0, (20, 28, 74)), (0.30, (67, 53, 127)), (0.56, (181, 82, 122)), (0.72, (255, 149, 102)), (0.86, (255, 210, 154)), (1.0, (255, 227, 184))]
    sky = np.zeros((h, w, 3), np.float32)
    for (t0, c0), (t1, c1) in zip(stops, stops[1:]):
        m = ((y >= t0) & (y <= t1))
        f = np.clip((y - t0) / (t1 - t0), 0, 1)
        for ch in range(3):
            sky[:, :, ch] += np.where(m, c0[ch] + (c1[ch] - c0[ch]) * f, 0)
    xs, ys = np.meshgrid(np.linspace(0, 1, w), np.linspace(0, 1, h))
    glow = np.exp(-(((xs - 0.64) / 0.22) ** 2 + ((ys - 0.74) / 0.17) ** 2))[:, :, None]
    sky = np.clip(sky + glow * np.array([255, 235, 190], np.float32) * 0.8, 0, 255)
    img = Image.fromarray(sky.astype(np.uint8))
    d = ImageDraw.Draw(img)
    rng = np.random.default_rng(3)
    for _ in range(70):  # stars in the dark top
        sx, sy = rng.integers(0, w), rng.integers(0, int(h * 0.3))
        d.point((int(sx), int(sy)), fill=(255, 255, 255))

    def ridge(base, amp, color, seed):
        r = np.random.default_rng(seed)
        ph = r.random(4) * 6
        pts = [(0, h)]
        for x in range(0, w + 1, 6):
            t = x / w
            v = sum(math.sin(t * f * 6.283 + p) / f for f, p in zip((1, 2.3, 4.1, 7.7), ph))
            pts.append((x, h * base - amp * h * v * 0.35))
        pts.append((w, h))
        d.polygon(pts, fill=color)

    ridge(0.70, 0.16, (109, 74, 140), 1)
    mist = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    md = ImageDraw.Draw(mist)
    for i in range(int(h * 0.2)):
        md.line([(0, int(h * 0.62) + i), (w, int(h * 0.62) + i)], fill=(255, 176, 150, int(110 * i / (h * 0.2))))
    img = Image.alpha_composite(img.convert("RGBA"), mist).convert("RGB")
    d = ImageDraw.Draw(img)
    ridge(0.80, 0.12, (59, 42, 102), 2)
    ridge(0.92, 0.09, (27, 18, 56), 3)
    return img.filter(ImageFilter.GaussianBlur(0.7 * width / 960))


if __name__ == "__main__":
    out = sys.argv[1]
    make(int(sys.argv[2]) if len(sys.argv) > 2 else 960).save(out, quality=82)
    print("wrote", out)
