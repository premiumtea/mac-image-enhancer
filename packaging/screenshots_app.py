#!/usr/bin/env python3
"""Screenshots of the SwiftUI app in its main states, on a Mac with a display (a GitHub macos-26 runner):

    python3 packaging/screenshots_app.py "dist/Mac Image Enhancer.app" OUTDIR picture.jpg

Each scenario starts the app with MAC_IMAGE_ENHANCER_DEMO=<scenario> (see Demo.swift), waits, and photographs its window.
The compare scenario runs the real engine, so MAC_IMAGE_ENHANCER_ENGINE (or a bundled engine) and the model files must exist.
Needs pyobjc-framework-Quartz.
"""
import os
import subprocess
import sys
import time

import Quartz

APP, OUT, IMAGE = sys.argv[1:4]
BINARY = os.path.join(APP, "Contents/MacOS/MacImageEnhancer")
BUNDLE_ID = "org.mac-image-enhancer.MacImageEnhancer"
# scenario, language, seconds to wait (None: until the log says the comparison is up), file name
SCENARIOS = [("empty", "en", 5, "1-empty"), ("source", "en", 9, "2-source"), ("compare", "en", None, "3-compare"),
             ("faces", "en", 9, "4-faces"), ("advanced", "en", 9, "5-advanced"), ("saving", "en", 9, "6-saving"),
             ("source", "th", 9, "7-source-th"), ("faces", "zh", 9, "8-faces-zh"), ("source", "fr", 9, "9-source-fr"),
             ("empty", "th", 5, "10-empty-th")]


def window_id(pid):
    best = None
    for w in Quartz.CGWindowListCopyWindowInfo(Quartz.kCGWindowListOptionOnScreenOnly, Quartz.kCGNullWindowID):
        if w.get("kCGWindowOwnerPID") == pid and w.get("kCGWindowLayer") == 0:
            b = w["kCGWindowBounds"]
            if best is None or b["Width"] * b["Height"] > best[0]:
                best = (b["Width"] * b["Height"], w["kCGWindowNumber"])
    return best[1] if best else None


os.makedirs(OUT, exist_ok=True)
for scenario, lang, wait, name in SCENARIOS:
    subprocess.run(["defaults", "delete", BUNDLE_ID], capture_output=True)  # every scenario starts from the defaults
    log_path = os.path.join(OUT, f"{name}.log")
    env = dict(os.environ, MAC_IMAGE_ENHANCER_DEMO=scenario, MAC_IMAGE_ENHANCER_DEMO_IMAGE=IMAGE, MAC_IMAGE_ENHANCER_DEMO_LANG=lang)
    with open(log_path, "w") as log:
        proc = subprocess.Popen([BINARY], env=env, stdout=log, stderr=log)
        t0 = time.time()
        if wait is None:
            while time.time() - t0 < 420 and proc.poll() is None:
                if "compare=true" in open(log_path).read():
                    break
                time.sleep(1)
            time.sleep(3)
        else:
            time.sleep(wait)
        wid = window_id(proc.pid)
        path = os.path.join(OUT, f"{name}.png")
        if wid is None:
            print(f"{name}: no window", flush=True)
        else:
            r = subprocess.run(["screencapture", "-x", "-o", "-l", str(wid), path], capture_output=True, text=True)
            print(f"{name}: {'ok' if r.returncode == 0 else 'FAILED ' + r.stderr.strip()}", flush=True)
        proc.terminate()
        try:
            proc.wait(10)
        except subprocess.TimeoutExpired:
            proc.kill()
