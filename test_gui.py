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
    assert table["advanced_btn"] != en["advanced_btn"] or lang == "en"  # not just a copy of the English
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
        pos = {"t": 0, "fail": 0, "set_status": 0, "_reg": 1, "_section": 1}.get(node.func.attr)
        if pos is not None and len(node.args) > pos and isinstance(node.args[pos], ast.Constant):
            asked.add(node.args[pos].value)
assert len(asked) > 40, f"found only {len(asked)} text keys in calls: the scan no longer reads gui.py properly"
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
               "preset": "A9"}, open(path, "w"))
    assert gui.load_settings(path) == gui.DEFAULTS
    json.dump({"face_strength": 3, "faces": "yes"}, open(path, "w"))
    assert gui.load_settings(path) == gui.DEFAULTS  # out of range / wrong kind: dropped
    json.dump({"face_strength": 0, "faces": True, "preset": "custom"}, open(path, "w"))
    s = gui.load_settings(path)
    assert s["face_strength"] == 0 and s["faces"] is True and s["preset"] == "custom"
    gui.save_settings({**gui.DEFAULTS, "lang": "zh", "extra": 1}, path)
    assert gui.load_settings(path)["lang"] == "zh" and "extra" not in json.load(open(path))
assert gui.DEFAULTS["preset"] in gui.PRESETS and gui.DEFAULTS["dpi"] in dict(gui.QUALITY).values()

assert gui.parse_number("12.5") == 12.5 and gui.parse_number(" 12,5 ") == 12.5  # a decimal comma is fine
for bad in ("", "abc", "0", "-3", "nan", "inf", None):
    assert gui.parse_number(bad) is None, bad
assert gui.fmt_num(29.7) == "29.7" and gui.fmt_num(42.0) == "42" and gui.fmt_num(7.5000001) == "7.5"
assert gui.size_text(30.0, 20.5) == "30x20.5"
# a sheet turns to the picture: landscape picture, landscape sheet; unknown picture: upright
assert gui.preset_size("A4", (40, 30)) == (29.7, 21.0, "cm") and gui.preset_size("A4", (30, 40)) == (21.0, 29.7, "cm")
assert gui.preset_size("A4", None) == (21.0, 29.7, "cm") and gui.preset_size("24x36", (10, 10)) == (24.0, 36.0, "in")
for name in gui.PRESETS:  # every sheet is a plausible size
    w, h, unit = gui.preset_size(name, None)
    assert 0 < w < h and unit in gui.UNITS, name
# how far the picture is stretched, as a person is told
assert gui.quality_hint(0.5, 0) == ("hint_sharp", "ok") and gui.quality_hint(2.0, 1) == ("hint_good", "ok")
assert gui.quality_hint(4.0, 1) == ("hint_good", "ok") and gui.quality_hint(6.0, 1) == ("hint_stretch", "care")
assert gui.quality_hint(8.5, 2) == ("hint_huge", "bad")
# the file name a person types: an extension we can write; 16-bit and CMYK force TIFF
assert gui.save_path("/x/a.png", False) == ("/x/a.png", False) and gui.save_path("/x/a.JPG", False) == ("/x/a.JPG", False)
assert gui.save_path("/x/a", False) == ("/x/a.png", False) and gui.save_path("/x/a.gif", False) == ("/x/a.gif.png", False)
assert gui.save_path("/x/a.png", True) == ("/x/a.tif", True) and gui.save_path("/x/a.tiff", True) == ("/x/a.tiff", False)
assert gui.save_path("/x/a", True) == ("/x/a.tif", False)  # nothing was typed after the dot: nothing was renamed
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
assert gui.fit_box((1000, 500), (500, 500)) == (500, 250) and gui.fit_box((10, 10), (5000, 5000)) == (40, 40)
assert gui.fit_box((1000, 500), (0, 0)) == (1, 1)  # no room: still a picture Tk can make
left, right = Image.new("RGB", (8, 4), "red"), Image.new("RGB", (8, 4), "blue")
for frac, red_cols in ((0.0, 0), (0.25, 2), (0.5, 4), (1.0, 8)):
    m = np.asarray(gui.compare_image(left, right, frac))
    assert (m[:, :red_cols] == (255, 0, 0)).all() and (m[:, red_cols:] == (0, 0, 255)).all(), frac
assert gui.wrap_at(-58) == 120 and gui.wrap_at(9999) == 520 and gui.wrap_at(300) == 300
# the system language, read from `defaults`, only for the languages we have
import subprocess as sp
real_run = sp.run
for out, want in (('(\n    "th-TH",\n    "en-US"\n)', "th"), ('(\n    "zh-Hans-CN"\n)', "zh"), ('(\n    "de-DE",\n    "fr-FR"\n)', "fr"),
                  ('(\n    "de-DE"\n)', "en"), ("", "en")):
    gui.subprocess.run = lambda *a, **k: sp.CompletedProcess(a, 0, out, "")
    assert gui.system_language() == want, (out, gui.system_language())
gui.subprocess.run = real_run
print("gui logic ok")

# ---- the window, driven the way a person would, with the tiny model ---------------------------
import torch
from spandrel.architectures.Compact.__arch.SRVGG import SRVGGNetCompact

torch.manual_seed(0)
net = SRVGGNetCompact(num_feat=8, num_conv=2, upscale=4, act_type="prelu")
root.geometry("1120x740+20+20")
root.deiconify()


def pump(cond, timeout=60):
    t0 = time.time()
    while not cond() and time.time() - t0 < timeout:
        root.update()
        time.sleep(0.01)
    root.update()
    assert cond(), "timed out waiting for the window"


class Click:  # a mouse event, as far as the window cares
    def __init__(self, x, y):
        self.x, self.y = x, y


def status(app):
    return app.status_var.get()


def err(lang, key):
    return i18n.tr(lang, "error", msg=i18n.tr(lang, key))


def stage_texts(app):
    c = app.stage
    return [c.itemcget(i, "text") for i in c.find_all() if c.type(i) == "text"]


def marks(app):
    c = app.stage
    return [i for i in c.find_all() if c.type(i) == "rectangle" and c.itemcget(i, "outline") == gui.MARK]


with tempfile.TemporaryDirectory() as d:
    mdir = os.path.join(d, "models")
    os.makedirs(mdir)
    torch.save({"params": net.state_dict()}, os.path.join(mdir, weights.GENERAL_FILE))
    rng = np.random.default_rng(3)
    a, b = os.path.join(d, "a.png"), os.path.join(d, "b.png")
    Image.fromarray((rng.random((30, 40, 3)) * 255).astype(np.uint8)).save(a)
    Image.fromarray((rng.random((40, 40, 3)) * 255).astype(np.uint8)).save(b)
    sfile = os.path.join(d, "settings.json")
    json.dump({"model": "general", "denoise": 1.0, "preset": "custom", "width": "2", "height": "1.5", "unit": "in",
               "dpi": "100", "lang": "fr"}, open(sfile, "w"))
    real_missing = weights.missing
    weights.missing = lambda *args, **kw: []  # the tiny file is not the real size: pretend the files are fine
    revealed = []
    gui.reveal = revealed.append
    try:
        app = gui.App(root, settings_path=sfile, models_dir=mdir)
        root.update()
        assert app.lang == "fr" and status(app) == "Prêt" and app.root.title() == "Mac Image Enhancer"
        # the first look: nothing opened yet, and it says what to do
        assert app.mode == "empty" and app.stage.winfo_width() > 400 and app.panel.winfo_width() > 300
        assert i18n.tr("fr", "empty_title") in stage_texts(app) and app.summary_var.get() == i18n.tr("fr", "summary_none")
        assert app.open_btn.cget("text") == i18n.tr("fr", "open_btn") and app.open_btn.winfo_ismapped()
        assert app.preview_btn.instate(["!disabled"]) and app.cancel_btn.instate(["disabled"])
        assert app.cancel_btn.winfo_manager() == "" and app.progress.winfo_manager() == ""  # nothing running: no Cancel, no bar
        assert set(app.quality) == {"150", "200", "300"}

        # nothing to do yet: told so, in French, without crashing
        app.on_preview()
        assert status(app) == err("fr", "need_image"), status(app)
        app.on_save()
        assert status(app) == err("fr", "need_image"), status(app)

        # opening a picture fills in the plan: 2 in x 100 dpi = 200 px wide, the height follows the picture
        app.load_images([a])
        root.update()
        assert app.src_size == (40, 30) and app.mode == "source" and app.v["height"].get() == "1.5"
        assert app.summary_var.get() == "Résultat : 200 × 150 px  (0.0 mégapixels)", app.summary_var.get()
        assert app.size_label.cget("text") == "2 × 1.5 po"
        assert app.hint.cget("text") == "● " + i18n.tr("fr", "hint_stretch")  # 5x: some areas may look soft
        assert app.scale_note.cget("text") == "Agrandissement ×5.0" and app.crop_note.cget("text") == ""
        assert "a.png  ·  40 × 30 px" in stage_texts(app) and len(marks(app)) == 1
        app.v["height"].set("1")  # a size of one's own: the picture is cropped to fit
        root.update()
        assert app.summary_var.get().startswith("Résultat : 200 × 100 px") and app.crop_note.cget("text") != ""
        app.v["dpi"].set("abc")
        root.update()
        assert app.summary_var.get() == "" and app.hint.cget("text") == ""  # an invalid field shows no plan, not a wrong one
        assert app.mode == "source" and app.stage.find_all()  # the picture is still there
        app.v["dpi"].set("100")
        app.v["height"].set("1.5")

        # paper sizes: a chip fills in the fields and turns to the picture; typing makes it custom again
        app.v["preset"].set("A4")
        app.on_preset()
        assert (app.v["width"].get(), app.v["height"].get(), app.v["unit"].get()) == ("29.7", "21", "cm")  # landscape picture
        assert app.size_label.cget("text") == "29.7 × 21 cm" and app.orient_note.cget("text") != ""
        assert app.unit_box.get() == "cm" and app.summary_var.get().startswith("Résultat : 1169 × 827 px")  # 100 dpi
        app.v["width"].set("10")
        assert app.v["preset"].get() == "custom" and app.v["height"].get() == "7.5"  # follows the picture
        assert app.orient_note.cget("text") == ""
        app.v["height"].set("5")  # now it is the person's own height: typing a width leaves it alone
        app.v["width"].set("12")
        assert app.v["height"].get() == "5"
        app.v["preset"].set("A3")
        app.on_preset()  # a sheet takes both back
        assert (app.v["width"].get(), app.v["height"].get()) == ("42", "29.7")
        app.v["preset"].set("custom")
        app.on_preset()
        app.v["width"].set("2")
        app.v["height"].set("1.5")
        app.v["unit"].set("in")
        app._fill_choices()
        root.update()
        assert app.summary_var.get().startswith("Résultat : 200 × 150 px")

        # the quality buttons are the DPI
        app.v["dpi"].set("300")
        assert app.summary_var.get().startswith("Résultat : 600 × 450 px") and "300 DPI" in app.quality_note.cget("text")
        app.v["dpi"].set("100")
        assert app.v["dpi"].get() not in dict(gui.QUALITY).values()  # an own value from Advanced: no button is on

        # every language: the plan, the status and the menu follow
        app.fail("need_image")
        for code in ("en", "th", "zh"):
            app.lang_var.set(i18n.LANGUAGES[code])
            app.on_language_box()
            assert app.lang == code
            assert app.summary_var.get().startswith(i18n.tr(code, "summary_out", w=200, h=150, mp=0.03).split("200")[0]), code
            assert status(app) == err(code, "need_image"), (code, status(app))  # the error on screen speaks the new language
            assert app.preview_btn.cget("text") == i18n.tr(code, "preview_btn") and app.save_btn.cget("text")
            assert app.chips["custom"].cget("text") == i18n.tr(code, "preset_custom")
            assert app.unit_box.get() == i18n.tr(code, "unit_in") and i18n.tr(code, "file_info", name="a.png", w=40, h=30) in stage_texts(app)
            labels = [app.menubar.entrycget(i, "label") for i in range(app.menubar.index("end") + 1)
                      if app.menubar.type(i) == "cascade"]
            assert i18n.tr(code, "menu_file") in labels and i18n.tr(code, "menu_language") in labels, (code, labels)
        app.lang_var.set("Français")  # and back to the language this window started in
        app.on_language_box()
        assert status(app) == err("fr", "need_image")
        app.set_status("ready", {})

        # clicking the picture moves the marker; the centre stays within 0..1
        app.on_stage_click(Click(10_000, -50))
        assert app.center == (1, 0)
        ox, oy = app._origin
        w, h = app._view[2]
        app.on_stage_click(Click(ox + w / 2, oy + h / 2))
        assert abs(app.center[0] - 0.5) < 0.01 and abs(app.center[1] - 0.5) < 0.01
        assert len(marks(app)) == 1

        # bad input is refused with a message, not a traceback
        app.v["width"].set("zero")
        assert app.collect(None) is None and status(app) == err("fr", "need_size")
        app.v["width"].set("2")
        app.v["height"].set("1.5")
        app.v["dpi"].set("150.5")
        assert app.collect(None) is None and status(app) == err("fr", "need_dpi")
        app.v["dpi"].set("100")
        app.load_images([os.path.join(d, "no-such-picture.png"), os.path.join(d, "settings.json")])  # not pictures: ignored
        open(os.path.join(d, "notes.png"), "w").write("not a picture")
        app.load_images([os.path.join(d, "notes.png")])
        assert app.images == [a] and status(app).startswith("Erreur : notes.png")

        # Preview: runs enhance() in a worker, shows the real result next to the plain enlargement
        app.center = (0.5, 0.5)
        app.on_preview()
        assert app.busy and app.cancel_btn.instate(["!disabled"]) and app.preview_btn.instate(["disabled"])
        root.update_idletasks()
        assert app.cancel_btn.winfo_manager() == "pack" and app.progress.winfo_manager() == "grid"
        assert app.save_btn.instate(["disabled"])
        pump(lambda: not app.busy)
        assert app.compare and app.mode == "compare" and app.split == 0.5
        assert app.preview_images[0].size == (200, 150) and app.preview_images[1].size == (200, 150)
        assert app.progress_var.get() == 1 and status(app) == "Prêt" and app.progress.winfo_manager() == ""
        assert app.cancel_btn.winfo_manager() == "" and app.preview_btn.instate(["!disabled"])
        assert i18n.tr("fr", "before") in stage_texts(app) and i18n.tr("fr", "after") in stage_texts(app)
        assert i18n.tr("fr", "compare_hint") in stage_texts(app) and not marks(app)
        # the "before" is the plain enlargement of the same area, the "after" the AI one: they differ
        assert np.abs(np.asarray(app.preview_images[0]).astype(int) - np.asarray(app.preview_images[1])).mean() > 1
        # dragging the line: the left of it is the plain enlargement, the right of it the result
        cox, coy, cpw, cph = app._cmp
        app.on_stage_click(Click(cox + cpw * 0.25, coy + 10))
        assert abs(app.split - 0.25) < 0.01
        app.on_stage_click(Click(-500, 0))
        assert app.split == 0.0
        app.on_stage_click(Click(10_000, 0))
        assert app.split == 1.0
        # back to choosing an area
        app.on_back()
        assert app.mode == "source" and len(marks(app)) == 1
        # changing anything the picture depends on drops an open comparison: it would show something else
        app.on_preview()
        pump(lambda: not app.busy)
        assert app.mode == "compare"
        app.v["denoise"].set(0.9)
        assert app.mode == "source" and app.preview_images is None
        app.v["denoise"].set(1.0)
        # ... and a preview that was running when it happened is not shown as if it matched
        app.on_preview()
        app.v["denoise"].set(0.5)
        pump(lambda: not app.busy)
        assert app.mode == "source" and status(app) == "Prêt"
        app.v["denoise"].set(1.0)

        # time left: only once there is enough to go on, and shown beside the progress text
        app.t0 = time.monotonic() - 30
        assert app.estimate(0.5) == ("eta_sec", {"s": 30})
        assert app.estimate(0.1)[0] == "eta_min" and app.estimate(0.01) is None
        app.t0 = time.monotonic() - 1
        assert app.estimate(0.5) is None  # one second is too little to extrapolate from
        app.eta = ("eta_sec", {"s": 5})
        app.set_status("working", {"pct": 10})
        assert status(app) == i18n.tr("fr", "working", pct=10) + "  ·  " + i18n.tr("fr", "eta_sec", s=5)
        app.eta = None
        app.set_status("ready", {})

        # Save, one picture: the name comes from the dialog; the result is written; Finder can show it
        out = os.path.join(d, "prints")
        os.makedirs(out)
        asked_save = []
        gui.filedialog.asksaveasfilename = lambda **kw: asked_save.append(kw) or os.path.join(out, "mine.png")
        app.on_save()
        assert asked_save[0]["initialfile"] == "a-print.png" and asked_save[0]["title"] == i18n.tr("fr", "save_title")
        pump(lambda: not app.busy)
        assert Image.open(os.path.join(out, "mine.png")).size == (200, 150) and status(app) == i18n.tr("fr", "done", n=1)
        assert app.reveal_btn.winfo_manager() == "pack" and app.last_output == os.path.join(out, "mine.png")
        app.on_reveal()
        assert revealed == [os.path.join(out, "mine.png")]
        # 16-bit colour only exists in TIFF: the name is changed and the person is told
        app.v["bits16"].set(True)
        gui.filedialog.asksaveasfilename = lambda **kw: asked_save.append(kw) or os.path.join(out, "deep.png")
        app.on_save()
        assert asked_save[-1]["initialfile"] == "a-print.tif" and asked_save[-1]["defaultextension"] == ".tif"
        pump(lambda: not app.busy)
        assert os.path.exists(os.path.join(out, "deep.tif")) and not os.path.exists(os.path.join(out, "deep.png"))
        assert status(app) == i18n.tr("fr", "tiff_renamed")
        app.v["bits16"].set(False)
        # a dialog that was cancelled does nothing
        gui.filedialog.asksaveasfilename = lambda **kw: ""
        app.on_save()
        assert not app.busy

        # Save, several pictures: a folder, one file each, with a per-file status; 16-bit goes to TIFF
        app.load_images([a, b])
        root.update()
        assert any("+1" in t for t in stage_texts(app)) and app.reveal_btn.winfo_manager() == ""
        folder = os.path.join(d, "batch")
        gui.filedialog.askdirectory = lambda **kw: folder
        app.on_save()
        pump(lambda: not app.busy)
        assert sorted(f for f in os.listdir(folder) if not f.startswith(".")) == ["a.png", "b.png"], os.listdir(folder)
        assert Image.open(os.path.join(folder, "a.png")).size == (200, 150) and status(app) == i18n.tr("fr", "done", n=2)
        assert app.last_output == folder
        app.v["bits16"].set(True)
        app.on_save()
        pump(lambda: not app.busy)
        assert os.path.exists(os.path.join(folder, "a.tif")) and os.path.exists(os.path.join(folder, "b.tif"))
        app.v["bits16"].set(False)
        app.load_images([a])

        # Cancel: stops, leaves nothing half-written, and the window becomes usable again
        cancelled = os.path.join(d, "cancelled")
        os.makedirs(cancelled)
        app.v["width"].set("6")  # bigger: several tiles, so there is something to interrupt
        app.v["height"].set("4.5")
        opts = app.collect(None)
        opts["tile"] = 16
        app.run_enhance(opts, os.path.join(cancelled, "x.png"))
        pump(lambda: app.busy and app.progress_var.get() > 0)
        app.on_cancel()
        pump(lambda: not app.busy)
        assert status(app) == i18n.tr("fr", "cancelled") and app.preview_btn.instate(["!disabled"])
        assert not [f for f in os.listdir(cancelled) if not f.startswith(".mac")], os.listdir(cancelled)
        app.v["width"].set("2")
        app.v["height"].set("1.5")

        # 16-bit and CMYK together cannot be written: told so, nothing started
        app.set_profile("/somewhere/printer.icc")
        assert app.cmyk.get() == "printer.icc" and app.clear_profile_btn.instate(["!disabled"]) and app.compress.instate(["!disabled"])
        app.v["bits16"].set(True)
        app.run_enhance(app.collect(None), os.path.join(d, "no.tif"))
        assert status(app).startswith("Erreur : 16") and not app.busy
        app.v["bits16"].set(False)
        o = app.collect(None)
        assert o["cmyk_profile"] == "/somewhere/printer.icc" and o["bits"] == 8
        app.set_profile("")
        assert app.cmyk.get() == i18n.tr("fr", "no_profile") and app.clear_profile_btn.instate(["disabled"])
        assert app.compress.instate(["disabled"]) and app.collect(None)["cmyk_profile"] is None
        app.set_status("ready", {})

        # Advanced: a window of its own, with the settings few people need
        assert app.adv.state() == "withdrawn"
        app.show_advanced()
        root.update()
        assert app.adv.state() == "normal" and app.adv.title() == i18n.tr("fr", "advanced_title")
        assert app.model_box.get() == i18n.tr("fr", "model_general") and app.denoise.instate(["!disabled"])
        app.model_box.current(0)
        app.on_model()
        assert app.v["model"].get() == "photo" and app.denoise.instate(["disabled"])
        app.model_box.current(1)
        app.on_model()
        assert app.v["model"].get() == "general" and app.denoise.instate(["!disabled"])
        real_coreml = gui.has_coreml
        gui.has_coreml = lambda: False
        app._fill_choices()
        app.proc_box.current(4)  # Neural Engine, which this install lacks: refused politely, back to automatic
        app.on_processor()
        assert status(app) == err("fr", "proc_ane_missing") and app.v["processor"].get() == "auto"
        gui.has_coreml = lambda: True
        app._fill_choices()
        app.proc_box.current(3)
        app.on_processor()
        assert app.v["processor"].get() == "gpu16" and app.collect(None)["engine"] == "gpu16"
        app.proc_box.current(4)
        app.on_processor()
        assert app.v["processor"].get() == "ane" and status(app) == i18n.tr("fr", "ane_note")
        app.proc_box.current(0)
        app.on_processor()
        gui.has_coreml = real_coreml
        app.set_status("ready", {})
        app.hide_advanced()
        assert app.adv.state() == "withdrawn"

        # Faces: the switch, the strength slider, the note, and what collect() hands to enhance()
        import faces as face_lib
        real_vision = gui.has_vision
        assert not app.v["faces"].get() and app.faces_extra.winfo_manager() == ""
        gui.has_vision = lambda: False
        app.v["faces"].set(True)
        app.on_faces()  # no Apple Vision: told so, in French
        assert status(app) == err("fr", "faces_unavailable") and app.faces_extra.winfo_manager() == "pack"
        assert app.collect(None) is None
        gui.has_vision = lambda: True
        app.set_status("ready", {})
        app.on_faces()
        assert app.face_scale.instate(["!disabled"]) and app.faces_badge.cget("text") == i18n.tr("fr", "faces_badge")
        assert str(face_lib.MIN_FACE_PX) in app.faces_note.cget("text") and "IA" in app.faces_note.cget("text")
        # the note sits right under the switch, not after the Advanced button
        order = [str(w) for w in app.panel.pack_slaves()]
        assert order.index(str(app.faces_extra)) == order.index(str(app.faces_row)) + 1
        app.v["face_strength"].set(0.5)
        o = app.collect(None)
        assert o["faces"] is True and o["face_strength"] == 0.5 and o["models_dir"] == mdir
        app.lang_var.set("ไทย")
        app.on_language_box()
        assert "AI" in app.faces_note.cget("text") and app.faces_check.cget("text") == i18n.tr("th", "faces")
        app.lang_var.set("Français")
        app.on_language_box()

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
            app.center = (0.5, 0.5)
            app.v["faces"].set(False)
            app.on_preview()
            pump(lambda: not app.busy)
            without = np.asarray(app.preview_images[0]).astype(int)
            app.v["faces"].set(True)
            app.on_preview()
            pump(lambda: not app.busy)
            with_faces = np.asarray(app.preview_images[0]).astype(int)
            assert status(app) == "Prêt" and with_faces.shape == without.shape and app.mode == "compare"
            changed = (np.abs(with_faces - without).max(axis=2) > 0).mean()
            # the face is most of this tiny picture (a 32 x 24 px face of a 40 x 30 px source), but not all of it
            assert np.abs(with_faces - without).max() > 50 and 0.05 < changed < 0.95, changed
            # the same job through Save gets the same face
            faced = os.path.join(d, "faced.png")
            gui.filedialog.asksaveasfilename = lambda **kw: faced
            app.on_save()
            pump(lambda: not app.busy)
            saved = np.asarray(Image.open(faced)).astype(int)
            assert (saved.max(axis=2) > 0).any() and status(app) == i18n.tr("fr", "done", n=1)
        finally:
            face_lib.detect_faces, face_lib.Restorer = real_detect, real_restorer
            gui.has_vision = real_vision
        app.v["faces"].set(False)
        app.on_faces()
        assert app.faces_extra.winfo_manager() == ""

        # missing model files: the user is asked; "no" stops politely, "yes" downloads and carries on
        weights.missing = real_missing
        empty = os.path.join(d, "empty_models")
        app.models_dir = empty
        asked = []
        gui.messagebox.askyesno = lambda title, msg, **kw: asked.append(msg) or False
        app.on_preview()
        assert asked and "Mo" in asked[0], asked  # the French question, with the size in Mo
        assert status(app) == err("fr", "weights_declined")
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
        pump(lambda: not app.busy and fetched and status(app) == "Prêt" and app.mode == "compare")
        assert fetched == [weights.GENERAL_FILE]

        # Finder hands over pictures (Open With, dropped on the Dock icon)
        root.tk.call("::tk::mac::OpenDocument", a, b)
        root.update()
        assert app.images == [a, b]

        # the About window
        app.on_about()
        root.update()
        assert app.about.title() == i18n.tr("fr", "about_title")
        app.about.destroy()

        # settings survive a restart
        app.v["dpi"].set("240")
        app.v["faces"].set(True)
        app.v["face_strength"].set(0.4)
        app.v["preset"].set("A2")
        app.lang_var.set("Français")
        app.close()
    finally:
        weights.missing = real_missing
    root2 = tk.Tk()
    root2.withdraw()
    again = gui.App(root2, settings_path=sfile, models_dir=mdir)
    assert again.v["dpi"].get() == "240" and again.lang == "fr" and again.v["model"].get() == "general"
    assert again.v["faces"].get() is True and abs(again.v["face_strength"].get() - 0.4) < 1e-9
    assert again.v["preset"].get() == "A2" and again.v["width"].get() == "42"
    assert again.faces_extra.winfo_manager() == "pack"  # the note shows because the switch is on
    again.close()
    # a first run with no settings file starts in the language macOS uses
    gui.system_language = lambda: "th"
    fresh = tk.Tk()
    fresh.withdraw()
    first = gui.App(fresh, settings_path=os.path.join(d, "none.json"), models_dir=mdir)
    assert first.lang == "th" and first.status_var.get() == i18n.tr("th", "ready")
    first.close()
print("window tests ok")
print("ok")
