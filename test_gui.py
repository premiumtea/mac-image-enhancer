"""Run: python3 test_gui.py  (the text checks need nothing; the window checks need tkinter and a display)"""
import json
import os
import string
import tempfile

import i18n

# ---- interface text: every language complete, placeholders identical -----------------------------
en = i18n.STRINGS["en"]
assert set(i18n.LANGUAGES) == set(i18n.STRINGS) == {"en", "th", "zh", "fr"}
fmt = string.Formatter()
for lang, table in i18n.STRINGS.items():
    assert set(table) == set(en), (lang, set(en) ^ set(table))
    for key, text in table.items():
        assert text.strip(), (lang, key)
        want = {f for _, f, _, _ in fmt.parse(en[key]) if f}
        got = {f for _, f, _, _ in fmt.parse(text) if f}
        assert want == got, (lang, key, want, got)  # a translation must not lose or invent a {placeholder}
    assert table["denoise"] != en["denoise"] or lang == "en"  # not just a copy of the English
assert i18n.tr("fr", "done", n=3) == "Terminé. 3 fichier(s) enregistré(s)."
assert i18n.tr("xx", "ready") == "Ready"  # unknown language: English
print("i18n ok")

# every key the window asks for exists, and no translation is left unused. Read from the code itself.
import ast

tree = ast.parse(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "gui.py")).read())
asked, constants = set(), set()
for node in ast.walk(tree):
    if isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value in en:
        constants.add(node.value)
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
        pos = {"t": 0, "fail": 0, "set_status": 0, "_reg": 1}.get(node.func.attr)
        if pos is not None and len(node.args) > pos and isinstance(node.args[pos], ast.Constant):
            asked.add(node.args[pos].value)
assert len(asked) > 30, f"found only {len(asked)} text keys in calls: the scan no longer reads gui.py properly"
assert asked <= set(en), f"gui.py asks for text that does not exist: {asked - set(en)}"
assert not set(en) - constants, f"translations gui.py never uses: {set(en) - constants}"
print(f"all {len(asked)} text keys gui.py asks for exist, and every translation is used")

try:
    import tkinter as tk
    root = tk.Tk()
    root.withdraw()
except Exception as e:  # no tkinter, or no display
    print(f"window tests: skipped ({type(e).__name__}: {str(e)[:60]})")
    print("ok")
    raise SystemExit(0)

import time

import numpy as np
from PIL import Image

import enhance as E
import gui
import weights

# ---- logic without widgets --------------------------------------------------------------------
with tempfile.TemporaryDirectory() as d:
    path = os.path.join(d, "s.json")
    assert gui.load_settings(path) == gui.DEFAULTS  # no file: defaults
    open(path, "w").write("{broken")
    assert gui.load_settings(path) == gui.DEFAULTS  # damaged: defaults
    json.dump({"lang": "th", "dpi": "300", "denoise": 0.2, "bits16": True, "mystery": 1}, open(path, "w"))
    s = gui.load_settings(path)
    assert (s["lang"], s["dpi"], s["denoise"], s["bits16"]) == ("th", "300", 0.2, True) and "mystery" not in s
    # values of the wrong kind or outside their choices are dropped one by one, never crash the window
    json.dump({"lang": "klingon", "unit": "parsec", "processor": 5, "denoise": 7, "dpi": 150, "bits16": "yes",
               "format": "tiff"}, open(path, "w"))
    s = gui.load_settings(path)
    assert s == {**gui.DEFAULTS, "format": "tiff"}, s
    json.dump({"face_strength": 3, "faces": "yes"}, open(path, "w"))
    assert gui.load_settings(path) == gui.DEFAULTS  # out of range / wrong kind: dropped
    json.dump({"face_strength": 0, "faces": True}, open(path, "w"))
    assert gui.load_settings(path)["face_strength"] == 0 and gui.load_settings(path)["faces"] is True
    gui.save_settings({**gui.DEFAULTS, "lang": "zh", "extra": 1}, path)
    assert gui.load_settings(path)["lang"] == "zh" and "extra" not in json.load(open(path))

assert gui.parse_number("12.5") == 12.5 and gui.parse_number(" 12,5 ") == 12.5  # a decimal comma is fine
for bad in ("", "abc", "0", "-3", "nan", "inf", None):
    assert gui.parse_number(bad) is None, bad
assert gui.size_text(30.0, 20.0, True) == "30" and gui.size_text(30.0, 20.5, False) == "30x20.5"
assert gui.output_ext("png", False, None) == ".png" and gui.output_ext("jpeg", False, None) == ".jpg"
assert gui.output_ext("png", True, None) == ".tif" and gui.output_ext("png", False, "p.icc") == ".tif"  # they need TIFF
# processors map onto engines and devices enhance.py really has
for key, (engine, device) in gui.PROCESSORS.items():
    assert engine in E.ENGINE_NAMES and device in ("auto", "cpu", "gpu"), key
    assert E.check_engine_options(engine, 8, device) is None, key
# the marker: centered, kept inside the picture, scaled from print px to thumbnail px
# 200x100 of a 1000x500 print on a 400x200 thumbnail is an 80x40 box, centred at (200, 100)
assert gui.marker_box((0.5, 0.5), (200, 100), (1000, 500), (400, 200)) == (160.0, 80.0, 240.0, 120.0)
assert gui.marker_box((0, 0), (200, 100), (1000, 500), (400, 200))[:2] == (0, 0)
assert gui.marker_box((1, 1), (200, 100), (1000, 500), (400, 200))[2:] == (400, 200)  # never past the edge
assert gui.marker_box((0.5, 0.5), (5000, 5000), (1000, 500), (400, 200)) == (0, 0, 400, 200)  # bigger than the print
print("gui logic ok")

# ---- the window, driven the way a person would, with the tiny model ---------------------------
import torch
from spandrel.architectures.Compact.__arch.SRVGG import SRVGGNetCompact

torch.manual_seed(0)
net = SRVGGNetCompact(num_feat=8, num_conv=2, upscale=4, act_type="prelu")


def pump(app, cond, timeout=60):
    t0 = time.time()
    while not cond() and time.time() - t0 < timeout:
        root.update()
        time.sleep(0.01)
    root.update()
    assert cond(), "timed out waiting for the window"


def status(app):
    return app.status_var.get()


with tempfile.TemporaryDirectory() as d:
    mdir = os.path.join(d, "models")
    os.makedirs(mdir)
    torch.save({"params": net.state_dict()}, os.path.join(mdir, weights.GENERAL_FILE))
    rng = np.random.default_rng(3)
    a, b = os.path.join(d, "a.png"), os.path.join(d, "b.png")
    Image.fromarray((rng.random((30, 40, 3)) * 255).astype(np.uint8)).save(a)
    Image.fromarray((rng.random((40, 40, 3)) * 255).astype(np.uint8)).save(b)
    sfile = os.path.join(d, "settings.json")
    json.dump({"model": "general", "denoise": 1.0, "width": "2", "unit": "in", "dpi": "100", "lang": "fr"}, open(sfile, "w"))
    real_missing = weights.missing
    weights.missing = lambda *args, **kw: []  # the tiny file is not the real size: pretend the files are fine
    try:
        app = gui.App(root, settings_path=sfile, models_dir=mdir)
        root.update()
        assert app.lang == "fr" and app.status_var.get() == "Prêt" and app.root.title() == "Mac Enhancer"
        assert app.images_label.cget("text") == i18n.tr("fr", "no_image")
        assert app.preview_btn.instate(["!disabled"]) and app.cancel_btn.instate(["disabled"])

        # nothing to do yet: told so, in French, without crashing
        app.on_preview()
        assert status(app) == i18n.tr("fr", "error", msg=i18n.tr("fr", "need_image")), status(app)

        # opening a picture fills in the plan: 2 in x 100 dpi = 200 px wide, height from the picture
        app.load_images([a])
        root.update()
        assert app.src_size == (40, 30) and app.plan_px.cget("text") == "Résultat : 200 × 150 px"
        assert app.v["height"].get() == "1.5" and app.entries["height"].instate(["disabled"])  # follows the picture
        assert "×5.0" in app.plan_scale.cget("text") and app.plan_crop.cget("text") == ""
        app.v["keep_aspect"].set(False)
        app.v["height"].set("1")
        root.update()
        assert app.plan_px.cget("text") == "Résultat : 200 × 100 px" and app.plan_crop.cget("text") != ""  # cropped to fit
        app.v["dpi"].set("abc")
        root.update()
        assert app.plan_px.cget("text") == ""  # an invalid field shows no plan instead of a wrong one
        app.v["dpi"].set("100")
        app.v["keep_aspect"].set(True)
        root.update()
        for lang_name, expect in (("English", "Result: 200 × 150 px"), ("ไทย", "ผลลัพธ์: 200 × 150 พิกเซล"),
                                  ("中文", "结果：200 × 150 像素")):
            app.lang_var.set(lang_name)
            app.on_language()
            assert app.plan_px.cget("text") == expect, (lang_name, app.plan_px.cget("text"))
            code = {"English": "en", "ไทย": "th", "中文": "zh"}[lang_name]
            # the error from earlier is still on screen, and now speaks the new language
            assert status(app) == i18n.tr(code, "error", msg=i18n.tr(code, "need_image")), (lang_name, status(app))
            assert app.preview_btn.cget("text")
        app.lang_var.set("Français")  # and back to the language this window started in
        app.on_language()
        assert status(app) == i18n.tr("fr", "error", msg=i18n.tr("fr", "need_image"))
        app.set_status("ready", {})

        # clicking the picture moves the marker; the centre stays within 0..1
        class Click:
            x, y = 10_000, -50
        app.on_click(Click)
        assert app.center == (1, 0)

        # bad input is refused with a message, not a traceback
        app.v["width"].set("zero")
        assert app.collect(None) is None and status(app) == i18n.tr("fr", "error", msg=i18n.tr("fr", "need_size"))
        app.v["width"].set("2")
        app.v["dpi"].set("150.5")
        assert app.collect(None) is None and status(app) == i18n.tr("fr", "error", msg=i18n.tr("fr", "need_dpi"))
        app.v["dpi"].set("100")

        # Preview: runs enhance() in a worker, shows the real result, and tells the user nothing is running
        app.center = (0.5, 0.5)
        app.on_preview()
        assert app.busy and app.cancel_btn.instate(["!disabled"]) and app.preview_btn.instate(["disabled"])
        pump(app, lambda: not app.busy)
        assert app.preview_images and app.preview_images[0].size == (200, 150), app.preview_images and app.preview_images[0].size
        assert app.preview_images[1].size == (200, 150) and app.progress_var.get() == 1 and status(app) == "Prêt"
        original_view = app.preview_images[1]
        app.show.set("original")
        app.draw_preview()
        assert app.preview_canvas.bbox("all")[2] >= 200
        # the "original" is the plain enlargement of the same area; the result is the AI one: they differ
        assert np.abs(np.asarray(app.preview_images[0]).astype(int) - np.asarray(original_view)).mean() > 1

        # Enhance and save: two pictures into a folder, with a per-file status
        app.load_images([a, b])
        out = os.path.join(d, "prints")
        app.run_enhance(app.collect(None), out)
        pump(app, lambda: not app.busy)
        assert sorted(f for f in os.listdir(out) if not f.startswith(".")) == ["a.png", "b.png"], os.listdir(out)
        assert Image.open(os.path.join(out, "a.png")).size == (200, 150) and status(app) == i18n.tr("fr", "done", n=2)
        # 16-bit goes to TIFF whatever the format box says
        app.v["bits16"].set(True)
        app.run_enhance(app.collect(None), out)
        pump(app, lambda: not app.busy)
        assert os.path.exists(os.path.join(out, "a.tif")) and os.path.exists(os.path.join(out, "b.tif"))
        app.v["bits16"].set(False)

        # Cancel: stops the batch, leaves nothing half-written, and the window becomes usable again
        shutil_out = os.path.join(d, "cancelled")
        app.v["width"].set("6")  # bigger: several tiles, so there is something to interrupt
        opts = app.collect(None)
        opts["tile"] = 16
        app.run_enhance(opts, shutil_out)
        pump(app, lambda: app.busy and app.progress_var.get() > 0)
        app.on_cancel()
        pump(app, lambda: not app.busy)
        assert status(app) == i18n.tr("fr", "cancelled") and app.preview_btn.instate(["!disabled"])
        left = [f for f in os.listdir(shutil_out) if not f.startswith(".mac")] if os.path.isdir(shutil_out) else []
        assert not any(f.endswith(".partial") for f in left), left
        assert len([f for f in left if not f.startswith(".")]) < 2  # at most the first picture finished
        app.v["width"].set("2")

        # Faces: the checkbox, the strength slider, the note, and what collect() hands to enhance()
        import faces as face_lib
        real_vision = gui.has_vision
        assert not app.v["faces"].get() and app.face_scale.instate(["disabled"]) and app.faces_note.cget("text") == ""
        gui.has_vision = lambda: False
        app.v["faces"].set(True)
        app.on_faces()  # no Apple Vision: told so, in French
        assert status(app) == i18n.tr("fr", "error", msg=i18n.tr("fr", "faces_unavailable"))
        assert app.collect(None) is None
        gui.has_vision = lambda: True
        app.set_status("ready", {})
        app.on_faces()
        assert app.face_scale.instate(["!disabled"])
        assert str(face_lib.MIN_FACE_PX) in app.faces_note.cget("text") and "IA" in app.faces_note.cget("text")
        app.v["face_strength"].set(0.5)
        o = app.collect(None)
        assert o["faces"] is True and o["face_strength"] == 0.5 and o["models_dir"] == mdir
        app.lang_var.set("ไทย")
        app.on_language()
        assert "AI" in app.faces_note.cget("text") and app.faces_check.cget("text") == i18n.tr("th", "faces")
        app.lang_var.set("Français")
        app.on_language()

        # the licence note rides along when the face model has to be downloaded
        asked_faces = []
        gui.messagebox.askyesno = lambda title, msg, **kw: asked_faces.append(msg) or False
        weights.missing = lambda md, names: [n for n in names if n == weights.GFPGAN_FILE]
        app.on_preview()
        assert asked_faces and "Mo" in asked_faces[0] and "NOTICE" in asked_faces[0] and "GFPGAN" in asked_faces[0], asked_faces
        weights.missing = lambda *args, **kw: []
        gui.messagebox.askyesno = lambda title, msg, **kw: True

        # Preview with faces: the stand-in detector and restorer paint a white face into the area the window shows
        # (white, because the window keeps the picture's own colours and only takes the brightness from the restorer)
        class Stand(face_lib.Restorer):
            def __init__(self, path, device):
                pass

            def __call__(self, crop):
                return np.full((512, 512, 3), 255, np.uint8)
        real_detect, real_restorer = face_lib.detect_faces, face_lib.Restorer
        face_lib.detect_faces = lambda img: [face_lib.Face((8, 6, 40, 30), np.array([[16, 14.0], [30, 14], [23, 24]]), 0.99)]
        face_lib.Restorer = Stand
        open(os.path.join(mdir, weights.GFPGAN_FILE), "wb").close()  # present (the check for it is patched above)
        try:
            app.v["width"].set("2")
            app.center = (0.5, 0.5)
            app.v["faces"].set(False)
            app.on_preview()
            pump(app, lambda: not app.busy)
            without = np.asarray(app.preview_images[0]).astype(int)
            app.v["faces"].set(True)
            app.on_preview()
            pump(app, lambda: not app.busy)
            with_faces = np.asarray(app.preview_images[0]).astype(int)
            assert status(app) == "Prêt" and with_faces.shape == without.shape
            changed = (np.abs(with_faces - without).max(axis=2) > 0).mean()
            # the face is most of this tiny picture (a 32 x 24 px face of a 40 x 30 px source), but not all of it
            assert np.abs(with_faces - without).max() > 50 and 0.05 < changed < 0.95, changed
            # the same job through Enhance and save gets the same face
            run_out = os.path.join(d, "faces_out")
            app.run_enhance(app.collect(None), run_out)
            pump(app, lambda: not app.busy)
            saved = np.asarray(Image.open(os.path.join(run_out, "b.png"))).astype(int)
            assert (np.abs(saved - 0).max(axis=2) > 0).any() and status(app) == i18n.tr("fr", "done", n=2)
        finally:
            face_lib.detect_faces, face_lib.Restorer = real_detect, real_restorer
            gui.has_vision = real_vision
        app.v["faces"].set(False)
        app.on_faces()

        # missing model files: the user is asked; "no" stops politely, "yes" downloads and carries on
        weights.missing = real_missing
        empty = os.path.join(d, "empty_models")
        app.models_dir = empty
        asked = []
        gui.messagebox.askyesno = lambda title, msg, **kw: asked.append(msg) or False
        app.on_preview()
        assert asked and "Mo" in asked[0], asked  # the French question, with the size in Mo
        assert status(app) == i18n.tr("fr", "error", msg=i18n.tr("fr", "weights_declined"))
        gui.messagebox.askyesno = lambda title, msg, **kw: True
        fetched = []

        def fake_download(name, models_dir, progress=None, cancel=None, files=None):
            fetched.append(name)
            os.makedirs(models_dir, exist_ok=True)
            for n in (weights.GENERAL_FILE,):
                torch.save({"params": net.state_dict()}, os.path.join(models_dir, n))
            progress(10, 20)
            progress(20, 20)
            return os.path.join(models_dir, name)
        weights.download = fake_download
        weights.missing = lambda md, names: [n for n in names if not os.path.exists(os.path.join(md, n))]
        app.on_preview()
        pump(app, lambda: not app.busy and app.preview_images is not None and fetched and status(app) == "Prêt")
        assert fetched == [weights.GENERAL_FILE]

        # settings survive a restart
        app.v["dpi"].set("240")
        app.v["faces"].set(True)
        app.v["face_strength"].set(0.4)
        app.lang_var.set("Français")
        app.close()
    finally:
        weights.missing = real_missing
    root2 = tk.Tk()
    root2.withdraw()
    again = gui.App(root2, settings_path=sfile, models_dir=mdir)
    assert again.v["dpi"].get() == "240" and again.lang == "fr" and again.v["model"].get() == "general"
    assert again.v["faces"].get() is True and abs(again.v["face_strength"].get() - 0.4) < 1e-9
    again.close()
print("window tests ok")
print("ok")
