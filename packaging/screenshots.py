#!/usr/bin/env python3
"""Take screenshots of the window in its main states:  python packaging/screenshots.py OUTDIR [--suffix _dark]

For looking at the layout (and for the README), on a Mac that has a display, e.g. a GitHub macOS
runner (.github/workflows/screenshots.yml). Needs the real model files in models/ (fetch them with
`python enhance.py --download-models all`); a made-up picture stands in for a photo.
"""
import math
import os
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import tkinter as tk

from PIL import Image, ImageDraw, ImageFilter

import gui
import weights


def sample_picture(path, size=(960, 640)):
    """A small made-up landscape: sky, sun, hills, a house. Soft on purpose, like a small phone picture."""
    w, h = size
    zoom = k = w / 480  # sizes below are for a 480 px wide picture
    img = Image.new("RGB", size)
    px = ImageDraw.Draw(img)
    for y in range(h):  # sky
        t = y / h
        px.line([(0, y), (w, y)], fill=(int(90 + 120 * t), int(150 + 80 * t), int(230 - 20 * t)))
    px.ellipse((w * 0.68, h * 0.12, w * 0.68 + 60 * k, h * 0.12 + 60 * k), fill=(255, 238, 170))
    for n, (base, col) in enumerate(((0.62, (74, 110, 90)), (0.72, (52, 88, 62)), (0.84, (34, 64, 40)))):
        pts = [(0, h)]
        for x in range(0, w + 1, round(8 * k)):
            pts.append((x, h * base + 22 * zoom * ((n + 1) % 3 - 1) * math.sin(x / (zoom * (40 + 25 * n)) + n)))
        pts.append((w, h))
        px.polygon(pts, fill=col)
    px.rectangle((w * 0.18, h * 0.64, w * 0.30, h * 0.78), fill=(205, 175, 140))  # a house
    px.polygon([(w * 0.17, h * 0.64), (w * 0.24, h * 0.55), (w * 0.31, h * 0.64)], fill=(150, 60, 50))
    px.rectangle((w * 0.22, h * 0.69, w * 0.26, h * 0.78), fill=(90, 60, 40))
    for i in range(6):  # fence
        px.line([(w * 0.34 + i * 12 * k, h * 0.74), (w * 0.34 + i * 12 * k, h * 0.82)], fill=(235, 235, 225), width=round(3 * k))
    img = img.filter(ImageFilter.GaussianBlur(0.8 * k))
    img.save(path, quality=80)
    return path


def main():
    args = sys.argv[1:]
    out = args[0] if args else "screenshots"
    suffix = args[args.index("--suffix") + 1] if "--suffix" in args else ""
    os.makedirs(out, exist_ok=True)
    work = tempfile.mkdtemp()
    models = os.environ.get("MAC_IMAGE_ENHANCER_MODELS") or weights.default_models_dir()
    pic = sample_picture(os.path.join(work, "holiday.jpg"))

    root = tk.Tk()
    root.geometry("1120x780+40+60")
    app = gui.App(root, settings_path=os.path.join(work, "settings.json"), models_dir=models)
    app.lang = "en"
    app.relabel()
    root.lift()
    root.attributes("-topmost", True)

    def settle(seconds=0.8):
        end = time.time() + seconds
        while time.time() < end:
            root.update()
            time.sleep(0.02)

    def shot(name, window=None):
        w = window or root
        w.focus_force()  # a window that is not frontmost is drawn with its controls greyed out
        settle()
        x, y, wd, ht = w.winfo_rootx(), w.winfo_rooty(), w.winfo_width(), w.winfo_height()
        path = os.path.join(out, f"{name}{suffix}.png")
        r = subprocess.run(["screencapture", "-x", "-R", f"{x},{y - 28},{wd},{ht + 28}", path], capture_output=True, text=True)
        print(f"{name}: {'ok' if r.returncode == 0 else 'FAILED ' + r.stderr.strip()}", flush=True)

    shot("1-empty")
    app.load_images([pic])
    app.v["preset"].set("A3")
    app.on_preset()
    shot("2-source")

    app.center = (0.30, 0.76)  # the house and the fence: edges, where the difference shows
    app.draw_stage()
    app.on_preview()
    t0 = time.time()
    while (app.busy or not app.compare) and time.time() - t0 < 600:
        settle(0.3)
        if not app.busy and not app.compare:
            print("preview did not produce a comparison:", app.status_var.get(), flush=True)
            break
    shot("3-compare")
    app.on_back()

    gui.has_vision = lambda: True  # the layout with face recovery on, whether or not Vision is installed here
    app.v["faces"].set(True)
    app.on_faces()
    shot("4-faces")

    app.show_advanced()
    app.adv.geometry("+120+120")
    settle()
    shot("5-advanced", app.adv)
    app.hide_advanced()

    app.v["faces"].set(False)
    app.on_faces()
    app.set_busy(True)
    app.progress_var.set(0.42)
    app.eta = ("eta_min", {"m": 2})
    app.set_status("working_file", {"i": 2, "n": 5, "name": "holiday.jpg", "pct": 42})
    shot("6-busy")
    app.set_busy(False)
    app.eta = None

    app.v["preset"].set("custom")
    app.v["width"].set("2")
    app.v["unit"].set("ft")
    app._fill_choices()
    shot("7-huge")
    app.v["preset"].set("A2")
    app.on_preset()
    app.set_status("done", {"n": 1, "k": 0})
    app.last_output = os.path.join(work, "x.png")
    app.reveal_btn.pack(side="left", padx=8)
    shot("8-done")

    app.v["faces"].set(True)
    app.on_faces()
    for code in ("th", "zh", "fr"):
        app.lang = code
        app.relabel()
        shot(f"9-source-{code}")
    app.show_advanced()
    shot("9-advanced-fr", app.adv)
    app.hide_advanced()
    root.destroy()


if __name__ == "__main__":
    main()
