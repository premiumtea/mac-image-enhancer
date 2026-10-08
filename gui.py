#!/usr/bin/env python3
"""Mac Image Enhancer: the window.

Made for people who just want a big print from a small picture: open a picture, pick a paper
size, pick a quality, press Save. A preview shows the real result for any area at 100%, side by
side with the plain enlargement. Everything shown is computed by enhance.py itself, so the
preview is the print, not an approximation of it.

The window has three parts: the stage on the left (empty, the picture with the preview marker,
or the before/after comparison), the three steps on the right, and the bar at the bottom with
the result size, progress and the Preview and Save buttons. Rarely needed settings (picture type,
processor, 16-bit, CMYK) live in the Advanced window.

Needs tkinter (brew install python-tk@3.12) besides the packages enhance.py needs.
"""
import importlib.util
import json
import os
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import tkinter as tk
from tkinter import filedialog, font, messagebox, ttk

import enhance as E
import faces as face_lib
import i18n
import weights

SETTINGS_PATH = os.path.join(weights.app_support_dir(), "settings.json")
# paper sizes: name -> (short side, long side, unit)
PRESETS = {"A4": (21.0, 29.7, "cm"), "A3": (29.7, 42.0, "cm"), "A2": (42.0, 59.4, "cm"),
           "A1": (59.4, 84.1, "cm"), "A0": (84.1, 118.9, "cm"), "24x36": (24.0, 36.0, "in")}
PRESET_TEXT = {"24x36": "24×36″"}  # what a chip says when it is not just its name
QUALITY = (("quality_normal", "150"), ("quality_good", "200"), ("quality_fine", "300"))  # key, DPI
DEFAULTS = {"lang": "en", "unit": "cm", "dpi": "200", "width": "21", "height": "29.7", "preset": "A4",
            "model": "photo", "denoise": 0.5, "processor": "auto", "bits16": False, "compress": False,
            "last_dir": "", "faces": False, "face_strength": 1.0}
UNITS = ("cm", "mm", "in", "ft")
UNIT_KEYS = {"cm": "unit_cm", "mm": "unit_mm", "in": "unit_in", "ft": "unit_ft"}
IMAGE_TYPES = [("Images", "*.jpg *.jpeg *.png *.tif *.tiff *.bmp *.webp"), ("All files", "*.*")]
SAVE_TYPES = [("PNG", "*.png"), ("TIFF", "*.tif *.tiff"), ("JPEG", "*.jpg *.jpeg")]
SAVE_EXTS = (".png", ".tif", ".tiff", ".jpg", ".jpeg")
THUMB_PX = 1600  # the long side of the picture kept for the stage
PREVIEW_MAX = (960, 720)  # the preview crop, in print px (shown 1:1): at most this, and what the stage can show
BAND = 44  # height of the strips above and below the picture on the stage
# processor choice -> (enhance engine, enhance device preference)
PROCESSORS = {"auto": ("gpu", "auto"), "cpu": ("gpu", "cpu"), "gpu": ("gpu", "gpu"),
              "gpu16": ("gpu16", "gpu"), "ane": ("ane", "auto")}
# the stage is dark in light and dark mode alike: pictures are judged against a neutral dark
STAGE_BG, STAGE_FG, STAGE_DIM, MARK = "#262626", "#f4f4f4", "#a3a3a3", "#ffd60a"
HINT_COLORS = {"ok": "#1a9e4b", "care": "#c77700", "bad": "#d93025"}

CHOICES = {"lang": tuple(i18n.LANGUAGES), "unit": UNITS, "model": ("photo", "general"),
           "processor": tuple(PROCESSORS), "preset": (*PRESETS, "custom")}


# ---- logic without widgets (tested without a display) ----------------------------------------

def load_settings(path=SETTINGS_PATH):
    """Saved settings over the defaults. A missing or damaged file, an unknown key or a value of
    the wrong kind falls back to the default, so a hand-edited file cannot break the window."""
    try:
        with open(path) as f:
            saved = json.load(f)
    except (OSError, ValueError):
        saved = {}
    out = dict(DEFAULTS)
    for key, value in (saved.items() if isinstance(saved, dict) else ()):
        if key not in DEFAULTS:
            continue
        default = DEFAULTS[key]
        if key in CHOICES and value not in CHOICES[key]:
            continue
        if key in ("denoise", "face_strength"):  # a number from 0 to 1
            if not (isinstance(value, (int, float)) and not isinstance(value, bool) and 0 <= value <= 1):
                continue
        elif type(value) is not type(default):
            continue
        out[key] = value
    return out


def save_settings(data, path=SETTINGS_PATH):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path + ".tmp", "w") as f:
        json.dump({k: data[k] for k in DEFAULTS if k in data}, f, indent=1)
    os.replace(path + ".tmp", path)


def system_language():
    """The interface language macOS is set to, if we have it ('th-TH' -> 'th'; Chinese -> 'zh'), else 'en'."""
    try:
        out = subprocess.run(["defaults", "read", "-g", "AppleLanguages"], capture_output=True, text=True,
                             timeout=5).stdout
    except (OSError, subprocess.SubprocessError):
        return "en"
    for line in out.splitlines():
        code = line.strip().strip('(),"').lower().replace("_", "-").split("-")[0]
        if code in i18n.LANGUAGES:
            return code
    return "en"


def parse_number(text):
    """A positive number typed by a person ('12.5' or '12,5'), else None."""
    try:
        v = float(str(text).strip().replace(",", "."))
    except ValueError:
        return None
    return v if v > 0 and v == v and v != float("inf") else None


def fmt_num(x):
    """A size for people: 29.7, 42, 0.5 (never 42.00000001)."""
    return f"{x:.2f}".rstrip("0").rstrip(".")


def size_text(width, height):
    """The --size string for the two fields."""
    return f"{width:g}x{height:g}"


def preset_size(name, src_size):
    """(width, height, unit) of a paper size, turned to match the picture: a landscape picture
    gets a landscape sheet. With no picture yet the sheet stands upright."""
    short, long_, unit = PRESETS[name]
    landscape = bool(src_size) and src_size[0] > src_size[1]
    return (long_, short, unit) if landscape else (short, long_, unit)


def quality_hint(scale, passes):
    """(text key, level) for how far the picture is stretched. `scale` is print px over source px."""
    if not passes:
        return "hint_sharp", "ok"
    if scale <= 4:
        return "hint_good", "ok"
    if scale <= 8:
        return "hint_stretch", "care"
    return "hint_huge", "bad"


def save_path(path, tiff_needed):
    """(path, renamed) for the file name a person typed: an extension we can write, and .tif when
    16-bit colour or CMYK is on (they only exist in TIFF)."""
    stem, ext = os.path.splitext(path)
    if tiff_needed:
        return (path, False) if ext.lower() in (".tif", ".tiff") else (stem + ".tif", bool(ext))
    return (path, False) if ext.lower() in SAVE_EXTS else (path + ".png", False)


def has_coreml():
    return importlib.util.find_spec("coremltools") is not None


def has_vision():
    """Apple Vision through PyObjC: what face recovery uses to find faces."""
    return importlib.util.find_spec("Vision") is not None


def marker_box(center, preview_px, print_px, thumb_px):
    """The preview area as a rectangle on the thumbnail: (x0, y0, x1, y1) in thumbnail px.
    `center` is (fx, fy) as fractions of the print, the same convention as --preview."""
    (fx, fy), (pw, ph), (tw, th), (cw, ch) = center, preview_px, print_px, thumb_px
    w, h = min(pw / tw, 1.0) * cw, min(ph / th, 1.0) * ch
    x0 = min(max(fx * cw - w / 2, 0), cw - w)
    y0 = min(max(fy * ch - h / 2, 0), ch - h)
    return x0, y0, x0 + w, y0 + h


def wrap_at(n, widest=520):
    """A text wrap width in px for a canvas of width `n`: never negative (Tk refuses) or absurdly narrow."""
    return max(120, min(int(n), widest))


def fit_box(size, area):
    """(w, h) of `size` scaled to fit inside `area` (never enlarged beyond 4x), at least 1 px."""
    k = min(area[0] / size[0], area[1] / size[1], 4.0)
    return max(1, round(size[0] * k)), max(1, round(size[1] * k))


def compare_image(original, result, split):
    """The before/after picture: the plain enlargement left of the line, the AI result right of it.
    `split` is the line's place as a fraction of the width."""
    sx = round(split * result.width)
    merged = original.copy()
    if sx < result.width:
        merged.paste(result.crop((sx, 0, result.width, result.height)), (sx, 0))
    return merged


def reveal(path):
    """Show a file in Finder, or open a folder."""
    subprocess.Popen(["open", "-R", path] if os.path.isfile(path) else ["open", path])


def notice_path():
    """The NOTICE file: beside the code, or in the .app's data folder."""
    for base in (getattr(sys, "_MEIPASS", ""), os.path.dirname(os.path.abspath(__file__))):
        p = os.path.join(base, "NOTICE")
        if base and os.path.exists(p):
            return p
    return None


def dim_color(root):
    """A grey for notes that reads on the window background, light or dark. (Tk ignores the
    transparency of the system's own secondary-text colours, so they come out as plain white.)"""
    try:
        r, g, b = root.winfo_rgb("systemWindowBackgroundColor")
    except tk.TclError:
        return "#6e6e73"
    return "#a1a1a6" if (0.299 * r + 0.587 * g + 0.114 * b) / 65535 < 0.5 else "#6e6e73"


# ---- the window --------------------------------------------------------------------------------

class App:
    def __init__(self, root, settings_path=SETTINGS_PATH, models_dir=None):
        self.root, self.settings_path = root, settings_path
        self.models_dir = models_dir or weights.default_models_dir()
        first_run = not os.path.exists(settings_path)
        self.s = load_settings(settings_path)
        self.lang = system_language() if first_run else self.s["lang"]
        self.tmpdir = tempfile.mkdtemp(prefix="mac-image-enhancer-")
        self.images, self.src_size, self.full_thumb = [], None, None
        self.center, self.split = (0.5, 0.5), 0.5
        self.preview_images, self.compare, self.option_gen = None, False, 0
        self._view = self._compare_photo = None  # what the stage shows now, kept so Tk does not lose the images
        self.queue, self.cancel_ev, self.busy = queue.Queue(), threading.Event(), False
        self.status_state, self.eta, self.t0, self.last_output = ("ready", {}), None, 0.0, None
        self._labels = []  # (widget, translation key, option) for relabelling when the language changes
        self._cmyk_path, self._setting, self._height_manual = "", False, False
        self.preview_px, self.mode = PREVIEW_MAX, "empty"
        self._build_styles()
        self._build()
        self._build_advanced()
        self.relabel()
        self.apply_preset(initial=True)
        root.protocol("WM_DELETE_WINDOW", self.close)
        try:
            for key, command in (("o", self.on_open), ("s", self.on_save), ("p", self.on_preview), ("w", self.close)):
                root.bind(f"<Command-{key}>", lambda e, c=command: c())
            # Finder: Open With, and pictures dropped on the Dock icon
            root.createcommand("::tk::mac::OpenDocument", lambda *paths: self.load_images(list(paths)))
            root.createcommand("tkAboutDialog", self.on_about)
        except tk.TclError:
            pass

    # -- text ------------------------------------------------------------------------------------
    def t(self, key, **kw):
        return i18n.tr(self.lang, key, **kw)

    def _reg(self, widget, key, option="text"):
        self._labels.append((widget, key, option))
        return widget

    def relabel(self):
        self.root.title(self.t("app_title"))
        for widget, key, option in self._labels:
            widget.configure(**{option: self.t(key)})
        self.adv.title(self.t("advanced_title"))
        self.lang_var.set(i18n.LANGUAGES[self.lang])
        self.build_menu()
        self._fill_choices()
        self.set_status(*self.status_state)
        self.update_plan()
        self.draw_stage()

    # -- widgets ---------------------------------------------------------------------------------
    def _build_styles(self):
        base = font.nametofont("TkDefaultFont")
        self.bold = base.copy()
        self.bold.configure(weight="bold")
        self.h2 = base.copy()
        self.h2.configure(weight="bold", size=base.cget("size") + 2)
        self.big = base.copy()
        self.big.configure(weight="bold", size=base.cget("size") + 9)
        self.small = base.copy()
        self.small.configure(size=max(base.cget("size") - 1, 9))
        self.apply_theme_colors()
        self.root.bind("<<ThemeChanged>>", lambda e: self.apply_theme_colors())

    def apply_theme_colors(self):
        self.dim = dim_color(self.root)
        ttk.Style(self.root).configure("Hint.TLabel", foreground=self.dim, font=self.small)

    def make(self, cls, parent, style=None, **kw):
        """A ttk widget in the given style, or in the default one on a Tk that lacks that style."""
        if style:
            try:
                return cls(parent, style=style, **kw)
            except tk.TclError:
                pass
        return cls(parent, **kw)

    def _build(self):
        r = self.root
        self.v = {k: (tk.BooleanVar if isinstance(self.s[k], bool) else tk.DoubleVar if k in ("denoise", "face_strength")
                      else tk.StringVar)(value=self.s[k]) for k in DEFAULTS if k not in ("lang", "last_dir")}
        self.lang_var = tk.StringVar(value=i18n.LANGUAGES[self.lang])
        self.progress_var, self.status_var, self.summary_var = tk.DoubleVar(value=0), tk.StringVar(), tk.StringVar()
        r.columnconfigure(0, weight=1)
        r.rowconfigure(0, weight=1)

        body = ttk.Frame(r)
        body.grid(row=0, column=0, sticky="nsew")
        body.columnconfigure(0, weight=1)
        body.rowconfigure(0, weight=1)

        # the stage
        self.stage = tk.Canvas(body, background=STAGE_BG, highlightthickness=0, width=640, height=480)
        self.stage.grid(row=0, column=0, sticky="nsew")
        self.stage.bind("<Configure>", lambda e: self.draw_stage())
        self.stage.bind("<Button-1>", self.on_stage_click)
        self.stage.bind("<B1-Motion>", self.on_stage_click)
        self.open_btn = self._reg(self.make(ttk.Button, self.stage, "Accent.TButton", command=self.on_open), "open_btn")
        self.change_btn = self._reg(ttk.Button(self.stage, command=self.on_open), "change_pic")
        self.back_btn = self._reg(ttk.Button(self.stage, command=self.on_back), "back_to_pick")

        # the three steps
        panel = ttk.Frame(body, padding=(18, 14, 18, 8), width=372)
        panel.grid(row=0, column=1, sticky="ns")
        panel.grid_propagate(False)
        self.panel = panel
        head = ttk.Frame(panel)
        head.pack(fill="x")
        ttk.Label(head, text="Mac Image Enhancer", font=self.h2).pack(side="left")
        self.lang_box = ttk.Combobox(head, textvariable=self.lang_var, state="readonly", width=8,
                                     values=list(i18n.LANGUAGES.values()))
        self.lang_box.pack(side="right")
        self.lang_box.bind("<<ComboboxSelected>>", self.on_language_box)

        self._section(panel, "section_size")
        self.size_label = ttk.Label(panel, font=self.big)
        self.size_label.pack(anchor="w", pady=(0, 6))
        chips = ttk.Frame(panel)
        chips.pack(fill="x")
        self.chips = {}
        for i, name in enumerate((*PRESETS, "custom")):
            chip = self.make(ttk.Radiobutton, chips, "Toolbutton", variable=self.v["preset"], value=name,
                             command=self.on_preset, text=PRESET_TEXT.get(name, name))
            chip.grid(row=i // 4, column=i % 4, sticky="ew", padx=2, pady=2)
            chips.columnconfigure(i % 4, weight=1, uniform="chip")
            self.chips[name] = chip
        self._reg(self.chips["custom"], "preset_custom")
        fields = ttk.Frame(panel)
        fields.pack(fill="x", pady=(8, 0))
        self.entries = {}
        for col, (key, label) in enumerate((("width", "width"), ("height", "height"))):
            self._reg(ttk.Label(fields, style="Hint.TLabel"), label).grid(row=0, column=col, sticky="w", padx=2)
            e = ttk.Entry(fields, textvariable=self.v[key], width=7)
            e.grid(row=1, column=col, sticky="ew", padx=2)
            self.entries[key] = e
            fields.columnconfigure(col, weight=1, uniform="field")
        self._reg(ttk.Label(fields, style="Hint.TLabel"), "unit").grid(row=0, column=2, sticky="w", padx=2)
        self.unit_box = ttk.Combobox(fields, state="readonly", width=5)
        self.unit_box.grid(row=1, column=2, sticky="ew", padx=2)
        fields.columnconfigure(2, weight=1, uniform="field")
        self.unit_box.bind("<<ComboboxSelected>>", self.on_unit)
        self.orient_note = ttk.Label(panel, style="Hint.TLabel", wraplength=330, justify="left")
        self.orient_note.pack(anchor="w", pady=(6, 0))
        self.crop_note = ttk.Label(panel, style="Hint.TLabel", wraplength=330, justify="left")
        self.crop_note.pack(anchor="w")
        self.v["width"].trace_add("write", lambda *_: self.on_size_edit("width"))
        self.v["height"].trace_add("write", lambda *_: self.on_size_edit("height"))
        self.v["unit"].trace_add("write", self.on_option_change)

        self._section(panel, "section_quality")
        seg = ttk.Frame(panel)
        seg.pack(fill="x")
        self.quality = {}
        for i, (key, dpi) in enumerate(QUALITY):
            b = self.make(ttk.Radiobutton, seg, "Toolbutton", variable=self.v["dpi"], value=dpi, command=self.on_quality)
            b.grid(row=0, column=i, sticky="ew", padx=2)
            seg.columnconfigure(i, weight=1, uniform="seg")
            self._reg(b, key)
            self.quality[dpi] = b
        self.quality_note = ttk.Label(panel, style="Hint.TLabel", wraplength=330, justify="left")
        self.quality_note.pack(anchor="w", pady=(6, 0))
        self.hint = ttk.Label(panel, font=self.bold, wraplength=330, justify="left")
        self.hint.pack(anchor="w", pady=(6, 0))
        self.scale_note = ttk.Label(panel, style="Hint.TLabel")
        self.scale_note.pack(anchor="w")
        self.v["dpi"].trace_add("write", self.on_option_change)

        self._section(panel, "section_options")
        row = self.faces_row = ttk.Frame(panel)
        row.pack(fill="x")
        self.faces_check = self._reg(self.make(ttk.Checkbutton, row, "Switch.TCheckbutton", variable=self.v["faces"],
                                               command=self.on_faces), "faces")
        self.faces_check.pack(side="left")
        self.faces_badge = self._reg(ttk.Label(row, foreground="#c77700", font=self.small), "faces_badge")
        self.faces_badge.pack(side="left", padx=8)
        self.faces_extra = ttk.Frame(panel)
        strength = ttk.Frame(self.faces_extra)
        strength.pack(fill="x", pady=(4, 0))
        self._reg(ttk.Label(strength, style="Hint.TLabel"), "face_strength").pack(side="left")
        self.face_scale = ttk.Scale(strength, from_=0, to=1, variable=self.v["face_strength"])
        self.face_scale.pack(side="left", fill="x", expand=True, padx=8)
        self.faces_note = ttk.Label(self.faces_extra, style="Hint.TLabel", wraplength=330, justify="left")
        self.faces_note.pack(anchor="w", pady=(2, 0))
        for key in ("faces", "face_strength"):
            self.v[key].trace_add("write", self.on_option_change)
        self.advanced_btn = self._reg(ttk.Button(panel, command=self.show_advanced), "advanced_btn")
        self.advanced_btn.pack(anchor="w", pady=(14, 0))

        # the bar
        ttk.Separator(r).grid(row=1, column=0, sticky="ew")
        bar = ttk.Frame(r, padding=(18, 10))
        bar.grid(row=2, column=0, sticky="ew")
        bar.columnconfigure(0, weight=1)
        self.summary = ttk.Label(bar, textvariable=self.summary_var, font=self.bold)
        self.summary.grid(row=0, column=0, sticky="w")
        self.progress = ttk.Progressbar(bar, variable=self.progress_var, maximum=1.0)
        self.progress.grid(row=1, column=0, sticky="ew", pady=(4, 0), padx=(0, 16))
        self.progress.grid_remove()
        line = ttk.Frame(bar)
        line.grid(row=2, column=0, sticky="w", pady=(2, 0))
        self.status_label = ttk.Label(line, textvariable=self.status_var, style="Hint.TLabel")
        self.status_label.pack(side="left")
        self.reveal_btn = self._reg(ttk.Button(line, command=self.on_reveal), "reveal_btn")
        btns = ttk.Frame(bar)
        btns.grid(row=0, column=1, rowspan=3)
        self.cancel_btn = self._reg(ttk.Button(btns, command=self.on_cancel), "cancel_btn")
        self.preview_btn = self._reg(ttk.Button(btns, command=self.on_preview), "preview_btn")
        self.save_btn = self._reg(self.make(ttk.Button, btns, "Accent.TButton", command=self.on_save), "save_btn")
        self.preview_btn.pack(side="left", padx=4)
        self.save_btn.pack(side="left", padx=4)
        self.cancel_btn.state(["disabled"])
        self.face_scale.state(["disabled"])

    def _section(self, parent, key):
        ttk.Separator(parent).pack(fill="x", pady=(14, 8))
        self._reg(ttk.Label(parent, font=self.bold), key).pack(anchor="w", pady=(0, 6))

    def _build_advanced(self):
        win = tk.Toplevel(self.root)
        win.withdraw()
        win.resizable(False, False)
        win.protocol("WM_DELETE_WINDOW", self.hide_advanced)
        self.adv = win
        f = ttk.Frame(win, padding=18)
        f.pack(fill="both", expand=True)
        f.columnconfigure(1, weight=1)
        self._reg(ttk.Label(f), "model").grid(row=0, column=0, sticky="w", pady=4)
        self.model_box = ttk.Combobox(f, state="readonly", width=26)
        self.model_box.grid(row=0, column=1, sticky="ew", padx=(12, 0))
        self.model_box.bind("<<ComboboxSelected>>", self.on_model)
        self._reg(ttk.Label(f), "denoise").grid(row=1, column=0, sticky="w", pady=4)
        self.denoise = ttk.Scale(f, from_=0, to=1, variable=self.v["denoise"])
        self.denoise.grid(row=1, column=1, sticky="ew", padx=(12, 0))
        self._reg(ttk.Label(f), "processor").grid(row=2, column=0, sticky="w", pady=4)
        self.proc_box = ttk.Combobox(f, state="readonly", width=26)
        self.proc_box.grid(row=2, column=1, sticky="ew", padx=(12, 0))
        self.proc_box.bind("<<ComboboxSelected>>", self.on_processor)
        self._reg(ttk.Label(f), "dpi_custom").grid(row=3, column=0, sticky="w", pady=4)
        self.dpi_entry = ttk.Entry(f, textvariable=self.v["dpi"], width=8)
        self.dpi_entry.grid(row=3, column=1, sticky="w", padx=(12, 0))
        ttk.Separator(f).grid(row=4, column=0, columnspan=2, sticky="ew", pady=8)
        self.bits16 = self._reg(ttk.Checkbutton(f, variable=self.v["bits16"], command=self.sync_output_controls), "bits16")
        self.bits16.grid(row=5, column=0, columnspan=2, sticky="w")
        self._reg(ttk.Label(f), "cmyk").grid(row=6, column=0, sticky="w", pady=(6, 0))
        prof = ttk.Frame(f)
        prof.grid(row=6, column=1, sticky="ew", padx=(12, 0), pady=(6, 0))
        self.cmyk = tk.StringVar(value="")
        self.cmyk_label = ttk.Label(prof, textvariable=self.cmyk, style="Hint.TLabel", width=14)
        self.cmyk_label.pack(side="left")
        self.clear_profile_btn = ttk.Button(prof, text="✕", width=2, command=lambda: self.set_profile(""))
        self.clear_profile_btn.pack(side="right")
        self._reg(ttk.Button(prof, command=self.on_profile), "choose_profile").pack(side="right", padx=4)
        self.compress = self._reg(ttk.Checkbutton(f, variable=self.v["compress"]), "tiff_compress")
        self.compress.grid(row=7, column=0, columnspan=2, sticky="w", pady=(6, 0))
        self._reg(ttk.Label(f, style="Hint.TLabel", wraplength=380, justify="left"), "tiff_note"
                  ).grid(row=8, column=0, columnspan=2, sticky="w")
        self.close_adv_btn = self._reg(ttk.Button(f, command=self.hide_advanced), "close_btn")
        self.close_adv_btn.grid(row=9, column=1, sticky="e", pady=(14, 0))
        self.v["model"].trace_add("write", self.on_option_change)
        self.v["denoise"].trace_add("write", self.on_option_change)

    def build_menu(self):
        t = self.t
        bar = tk.Menu(self.root)
        file_menu = tk.Menu(bar, tearoff=False)
        file_menu.add_command(label=t("menu_open"), accelerator="⌘O", command=self.on_open)
        file_menu.add_command(label=t("menu_save"), accelerator="⌘S", command=self.on_save)
        file_menu.add_command(label=t("menu_preview"), accelerator="⌘P", command=self.on_preview)
        file_menu.add_separator()
        file_menu.add_command(label=t("menu_about"), command=self.on_about)
        file_menu.add_command(label=t("menu_close"), accelerator="⌘W", command=self.close)
        lang_menu = tk.Menu(bar, tearoff=False)
        for code, name in i18n.LANGUAGES.items():
            lang_menu.add_radiobutton(label=name, value=name, variable=self.lang_var, command=self.on_language_box)
        bar.add_cascade(label=t("menu_file"), menu=file_menu)
        bar.add_cascade(label=t("menu_language"), menu=lang_menu)
        self.root.configure(menu=bar)
        if getattr(self, "menubar", None):
            self.menubar.destroy()
        self.menubar = bar

    def _fill_choices(self):
        """Widgets whose entries are translated: rebuilt, keeping the current choice."""
        self._unit_keys = list(UNITS)
        self.unit_box.configure(values=[self.t(UNIT_KEYS[u]) for u in UNITS])
        self.unit_box.set(self.t(UNIT_KEYS[self.v["unit"].get()]))
        models = {"photo": self.t("model_photo"), "general": self.t("model_general")}
        self.model_box.configure(values=list(models.values()))
        self.model_box.set(models[self.v["model"].get()])
        procs = {"auto": "proc_auto", "cpu": "proc_cpu", "gpu": "proc_gpu", "gpu16": "proc_gpu16",
                 "ane": "proc_ane" if has_coreml() else "proc_ane_missing"}
        self.proc_box.configure(values=[self.t(k) for k in procs.values()])
        self.proc_box.set(self.t(procs[self.v["processor"].get()]))
        self._proc_keys, self._model_keys = list(procs), list(models)
        self.denoise.state(["!disabled" if self.v["model"].get() == "general" else "disabled"])
        self.sync_faces()
        self.sync_output_controls()
        self.cmyk.set(os.path.basename(self._cmyk_path) if self._cmyk_path else self.t("no_profile"))

    def sync_faces(self):
        on = self.v["faces"].get()
        self.face_scale.state(["!disabled" if on else "disabled"])
        self.faces_note.configure(text=self.t("faces_note", px=face_lib.MIN_FACE_PX))
        if on:
            self.faces_extra.pack(fill="x", after=self.faces_row)
        else:
            self.faces_extra.pack_forget()

    def sync_output_controls(self):
        tiff = self.v["bits16"].get() or bool(self._cmyk_path)
        self.compress.state(["!disabled" if tiff else "disabled"])
        self.clear_profile_btn.state(["!disabled" if self._cmyk_path else "disabled"])

    # -- events ----------------------------------------------------------------------------------
    def on_language_box(self, _=None):
        names = list(i18n.LANGUAGES.values())
        self.lang = list(i18n.LANGUAGES)[names.index(self.lang_var.get())]
        self.relabel()

    def on_about(self):
        dlg = tk.Toplevel(self.root)
        dlg.title(self.t("about_title"))
        dlg.resizable(False, False)
        f = ttk.Frame(dlg, padding=24)
        f.pack()
        ttk.Label(f, text="Mac Image Enhancer", font=self.h2).pack()
        ttk.Label(f, text=self.t("about_body", version=E.__version__), justify="center", wraplength=380
                  ).pack(pady=12)
        buttons = ttk.Frame(f)
        buttons.pack()
        if notice_path():
            ttk.Button(buttons, text=self.t("about_licenses"), command=lambda: subprocess.Popen(["open", notice_path()])
                       ).pack(side="left", padx=4)
        ttk.Button(buttons, text=self.t("close_btn"), command=dlg.destroy).pack(side="left", padx=4)
        self.about = dlg

    def show_advanced(self):
        self.adv.deiconify()
        self.adv.lift()
        self.adv.transient(self.root)

    def hide_advanced(self):
        self.adv.withdraw()

    def on_model(self, _=None):
        self.v["model"].set(self._model_keys[self.model_box.current()])
        self.denoise.state(["!disabled" if self.v["model"].get() == "general" else "disabled"])

    def on_processor(self, _=None):
        key = self._proc_keys[self.proc_box.current()]
        if key == "ane" and not has_coreml():
            self.fail("proc_ane_missing")
            key = "auto"
            self.proc_box.set(self.t("proc_auto"))
        self.v["processor"].set(key)
        if key == "ane":
            self.set_status("ane_note", {})

    def on_faces(self):
        self.sync_faces()
        if self.v["faces"].get() and not has_vision():
            self.fail("faces_unavailable")

    def on_profile(self):
        path = filedialog.askopenfilename(parent=self.adv, filetypes=[("ICC profile", "*.icc *.icm"), ("All files", "*.*")])
        if path:
            self.set_profile(path)

    def set_profile(self, path):
        self._cmyk_path = path or ""
        self.cmyk.set(os.path.basename(path) if path else self.t("no_profile"))
        self.sync_output_controls()

    def on_option_change(self, *_):
        """Anything that changes the picture: the open comparison no longer shows it, and a running
        preview must not show up as if it did."""
        if self._setting:
            return
        self.option_gen += 1
        if self.compare:
            self.compare, self.preview_images = False, None
        if hasattr(self, "hint"):
            self.update_plan()

    def on_preset(self):
        self._height_manual = False
        self.apply_preset()

    def apply_preset(self, initial=False):
        """Put the chosen paper size in the fields, turned to the picture's orientation."""
        name = self.v["preset"].get()
        if name in PRESETS:
            w, h, unit = preset_size(name, self.src_size)
            self._setting = True
            try:
                self.v["width"].set(fmt_num(w))
                self.v["height"].set(fmt_num(h))
                self.v["unit"].set(unit)
            finally:
                self._setting = False
            self._fill_choices()
            if not initial:
                self.on_option_change()
        self.update_plan()

    def on_size_edit(self, which):
        """A size field was typed in: the size is now the person's own. Until they type a height,
        it follows the picture's proportions, so the whole picture is printed."""
        if self._setting:
            return
        if self.v["preset"].get() != "custom":
            self.v["preset"].set("custom")
        if which == "height":
            self._height_manual = True
        elif not self._height_manual and self.src_size:
            w = parse_number(self.v["width"].get())
            if w:
                self._setting = True
                try:
                    self.v["height"].set(fmt_num(w * self.src_size[1] / self.src_size[0]))
                finally:
                    self._setting = False
        self.on_option_change()

    def on_unit(self, _=None):
        self.v["unit"].set(self._unit_keys[self.unit_box.current()])
        self.update_plan()

    def on_quality(self):
        self.update_plan()

    def on_open(self):
        paths = filedialog.askopenfilenames(parent=self.root, filetypes=IMAGE_TYPES, initialdir=self.s["last_dir"] or None)
        if paths:
            self.load_images(list(paths))

    def load_images(self, paths):
        from PIL import Image, ImageOps

        import color
        paths = [p for p in paths if os.path.isfile(p)]
        if not paths:
            return
        try:
            raw = Image.open(paths[0])
            w, h = raw.size
            if raw.getexif().get(0x0112, 1) in (5, 6, 7, 8):
                w, h = h, w
            if raw.format == "JPEG":
                raw.draft("RGB", (THUMB_PX * 2, THUMB_PX * 2))  # decode a small version: much faster
            img, _ = color.to_working_rgb(ImageOps.exif_transpose(raw), raw.info.get("icc_profile"))
        except Exception as e:
            self.set_status("error", {"msg": f"{os.path.basename(paths[0])}: {e}"})
            return
        self.images, self.src_size = list(paths), (w, h)
        self.s["last_dir"] = os.path.dirname(paths[0])
        self.full_thumb = img.copy()
        self.full_thumb.thumbnail((THUMB_PX, THUMB_PX))
        self.center, self.preview_images, self.compare, self._view = (0.5, 0.5), None, False, None
        self.last_output = None
        self.reveal_btn.pack_forget()
        self.set_status("ready", {})
        if self.v["preset"].get() in PRESETS:
            self.apply_preset(initial=True)  # turn the sheet to the new picture
        elif not self._height_manual:
            wv = parse_number(self.v["width"].get())
            if wv:
                self._setting = True
                try:
                    self.v["height"].set(fmt_num(wv * h / w))
                finally:
                    self._setting = False
        self.update_plan()
        self.draw_stage()

    def current_plan(self):
        """(tw, th, crop, passes) for the fields as they stand, or None while they are not valid."""
        if not self.src_size:
            return None
        w, h, dpi = (parse_number(self.v[k].get()) for k in ("width", "height", "dpi"))
        if not (w and h and dpi) or dpi != int(dpi):
            return None
        try:
            return E.plan_print(self.src_size, size_text(w, h), self.v["unit"].get(), int(dpi))
        except ValueError:
            return None

    def update_plan(self, *_):
        if not hasattr(self, "hint"):
            return
        w, h = (parse_number(self.v[k].get()) for k in ("width", "height"))
        unit = self.t(UNIT_KEYS[self.v["unit"].get()])
        self.size_label.configure(text=self.t("size_summary", w=fmt_num(w), h=fmt_num(h), unit=unit) if w and h else "")
        self.orient_note.configure(text=self.t("orient_note") if self.v["preset"].get() in PRESETS else "")
        dpi = parse_number(self.v["dpi"].get())
        self.quality_note.configure(text=self.t("quality_note", dpi=int(dpi)) if dpi and dpi == int(dpi) else "")
        plan = self.current_plan()
        if plan is None:
            self.summary_var.set(self.t("summary_none") if not self.src_size else "")
            for lab in (self.crop_note, self.hint, self.scale_note):
                lab.configure(text="")
            self._view = None
            self.draw_stage()
            return
        tw, th, crop, passes = plan
        cw, ch = crop[2] - crop[0], crop[3] - crop[1]
        scale = max(tw / cw, th / ch)
        key, level = quality_hint(scale, passes)
        self.summary_var.set(self.t("summary_out", w=tw, h=th, mp=tw * th / 1e6))
        self.hint.configure(text="● " + self.t(key), foreground=HINT_COLORS[level])
        self.scale_note.configure(text=self.t("scale_note", scale=scale) if passes else "")
        self.crop_note.configure(text=self.t("crop_note") if (cw, ch) != self.src_size else "")
        self.draw_stage()

    # -- the stage -------------------------------------------------------------------------------
    def draw_stage(self):
        c = self.stage
        if not hasattr(self, "hint"):
            return
        c.delete("all")
        cw, ch = max(c.winfo_width(), 2), max(c.winfo_height(), 2)
        if not self.images:
            self.mode = "empty"
            self._draw_empty(cw, ch)
        elif self.compare and self.preview_images:
            self.mode = "compare"
            c.configure(cursor="sb_h_double_arrow")
            self._draw_compare(cw, ch)
        else:
            self.mode = "source"
            c.configure(cursor="crosshair")
            self._draw_source(cw, ch)

    def _draw_empty(self, cw, ch):
        c = self.stage
        c.configure(cursor="")
        cx, cy = cw / 2, ch / 2 - 40
        # a picture glyph
        c.create_rectangle(cx - 44, cy - 66, cx + 44, cy - 10, outline=STAGE_DIM, width=3)
        c.create_oval(cx + 12, cy - 54, cx + 28, cy - 38, outline=STAGE_DIM, width=3)
        c.create_line(cx - 44, cy - 10, cx - 18, cy - 38, cx - 2, cy - 22, cx + 12, cy - 34, cx + 44, cy - 10,
                      fill=STAGE_DIM, width=3, joinstyle="round")
        c.create_text(cx, cy + 18, text=self.t("empty_title"), fill=STAGE_FG, font=self.h2, width=wrap_at(cw - 60),
                      justify="center")
        c.create_text(cx, cy + 62, text=self.t("empty_text"), fill=STAGE_DIM, width=wrap_at(cw - 80, 460), justify="center")
        c.create_window(cx, cy + 118, window=self.open_btn)
        c.create_text(cx, cy + 162, text=self.t("empty_hint"), fill=STAGE_DIM, font=self.small, width=wrap_at(cw - 80, 460),
                      justify="center")

    def _strip(self, cw, ch):
        """The area the picture may use between the top and bottom strips."""
        return 20, BAND, cw - 40, max(ch - 2 * BAND, 10)

    def _draw_source(self, cw, ch):
        c = self.stage
        plan = self.current_plan()
        x0, y0, aw, ah = self._strip(cw, ch)
        name = os.path.basename(self.images[0])
        info = self.t("file_info", name=name, w=self.src_size[0], h=self.src_size[1])
        if len(self.images) > 1:
            info += "   " + self.t("files_more", n=len(self.images) - 1)
        c.create_text(20, BAND / 2, anchor="w", text=info, fill=STAGE_FG, width=wrap_at(cw - 220, 900))
        c.create_window(cw - 20, BAND / 2, anchor="e", window=self.change_btn)
        sw, sh = self.src_size
        crop = plan[2] if plan else (0, 0, sw, sh)
        fw, fh = self.full_thumb.size  # the thumbnail covers the whole source: crop it in proportion
        box = (round(crop[0] * fw / sw), round(crop[1] * fh / sh), round(crop[2] * fw / sw), round(crop[3] * fh / sh))
        size = fit_box((box[2] - box[0], box[3] - box[1]), (aw, ah))
        key = (tuple(self.images[:1]), box, size)
        if not self._view or self._view[0] != key:
            from PIL import ImageTk
            view = self.full_thumb.crop(box).resize(size)
            self._view = (key, ImageTk.PhotoImage(view), size)
        ox, oy = x0 + (aw - size[0]) / 2, y0 + (ah - size[1]) / 2
        self._origin = (ox, oy)
        self.preview_px = (min(PREVIEW_MAX[0], max(int(cw) - 40, 160)), min(PREVIEW_MAX[1], max(int(ch) - 2 * BAND, 120)))
        c.create_image(ox, oy, anchor="nw", image=self._view[1])
        if plan:
            bx0, by0, bx1, by1 = marker_box(self.center, self.preview_px, plan[:2], size)
            c.create_rectangle(ox + bx0 - 1, oy + by0 - 1, ox + bx1 + 1, oy + by1 + 1, outline="black")
            c.create_rectangle(ox + bx0, oy + by0, ox + bx1, oy + by1, outline=MARK, width=2)
            c.create_text(cw / 2, ch - BAND / 2, text=self.t("stage_hint"), fill=STAGE_DIM, font=self.small)

    def _draw_compare(self, cw, ch):
        from PIL import ImageTk
        c = self.stage
        result, original = self.preview_images
        pw, ph = result.size
        x0, y0, aw, ah = self._strip(cw, ch)
        ox, oy = x0 + max((aw - pw) / 2, 0), y0 + max((ah - ph) / 2, 0)
        sx = round(self.split * pw)
        self._compare_photo = ImageTk.PhotoImage(compare_image(original, result, self.split))
        c.create_image(ox, oy, anchor="nw", image=self._compare_photo)
        self._cmp = (ox, oy, pw, ph)
        lx = ox + sx
        c.create_line(lx, oy, lx, oy + ph, fill="white", width=2)
        c.create_oval(lx - 14, oy + ph / 2 - 14, lx + 14, oy + ph / 2 + 14, fill="white", outline="#555555")
        c.create_text(lx, oy + ph / 2, text="◂▸", fill="#333333", font=self.small)
        for text, x, anchor in ((self.t("before"), ox + 8, "nw"), (self.t("after"), ox + pw - 8, "ne")):
            c.create_text(x + 1, oy + 9, anchor=anchor, text=text, fill="black", font=self.bold)
            c.create_text(x, oy + 8, anchor=anchor, text=text, fill="white", font=self.bold)
        c.create_text(20, BAND / 2, anchor="w", text=self.t("compare_hint"), fill=STAGE_DIM, width=wrap_at(cw - 260, 900))
        c.create_window(cw - 20, BAND / 2, anchor="e", window=self.back_btn)

    def on_stage_click(self, event):
        if self.mode == "compare":
            ox, oy, pw, ph = self._cmp
            self.split = min(max((event.x - ox) / pw, 0.0), 1.0)
            self.draw_stage()
        elif self.mode == "source" and self._view and self.current_plan():
            ox, oy = self._origin
            w, h = self._view[2]
            self.center = (min(max((event.x - ox) / w, 0), 1), min(max((event.y - oy) / h, 0), 1))
            self.draw_stage()

    def on_back(self):
        self.compare = False
        self.draw_stage()

    # -- running ---------------------------------------------------------------------------------
    def set_status(self, key, kw):
        """Show status text `key`. The state is kept as keys, not text, so it follows a language
        change: kw may carry msg_key (+ msg_kw) for a message that is itself a translation key."""
        self.status_state = (key, kw)
        shown = dict(kw)
        if "msg_key" in shown:
            shown["msg"] = self.t(shown.pop("msg_key"), **shown.pop("msg_kw", {}))
        text = self.t(key, **shown)
        if self.eta and key in ("working", "working_file"):
            text += "  ·  " + self.t(self.eta[0], **self.eta[1])
        self.status_var.set(text)

    def collect(self, preview):
        """The options for enhance(), or None after telling the user what is wrong."""
        if not self.images:
            return self.fail("need_image")
        w, h, dpi = (parse_number(self.v[k].get()) for k in ("width", "height", "dpi"))
        if not w or not h:
            return self.fail("need_size")
        if not dpi or dpi != int(dpi):
            return self.fail("need_dpi")
        engine, device = PROCESSORS[self.v["processor"].get()]
        model = self.v["model"].get()
        try:
            recipe = E.model_recipe(model, round(self.v["denoise"].get(), 2) if model == "general" else None, self.models_dir)
        except ValueError as e:
            self.set_status("error", {"msg": str(e)})
            return None
        faces = self.v["faces"].get()
        if faces and not has_vision():
            return self.fail("faces_unavailable")
        return dict(size=size_text(w, h), unit=self.v["unit"].get(), dpi=int(dpi), recipe=recipe,
                    faces=faces, face_strength=round(self.v["face_strength"].get(), 2), models_dir=self.models_dir,
                    device_pref=device, tile=256, engine=engine, bits=16 if self.v["bits16"].get() else 8,
                    cmyk_profile=self._cmyk_path or None, intent="relative",
                    compress=self.v["compress"].get(), preview=preview)

    def fail(self, key, **kw):
        """Show the error text `key` in the status bar. Returns None, so callers can `return self.fail(...)`."""
        self.set_status("error", {"msg_key": key, "msg_kw": kw})
        return None

    def with_weights(self, recipe, then, extra=()):
        """Run `then()` once the model files are on disk, offering to download missing ones first.
        `extra` names further files (the face model); asking about it carries its licence note."""
        names = [os.path.basename(p) for p, _ in recipe] + list(extra)
        lacking = weights.missing(self.models_dir, names)
        if not lacking:
            return then()
        mb = sum(weights.FILES[n][2] for n in lacking if n in weights.FILES) / 2 ** 20
        question = self.t("weights_msg", mb=mb) + (self.t("faces_license") if weights.GFPGAN_FILE in lacking else "")
        if not messagebox.askyesno(self.t("weights_title"), question, parent=self.root):
            return self.fail("weights_declined")

        def fetch():
            for n in lacking:
                weights.download(n, self.models_dir, progress=lambda d, t, n=n: self.queue.put(
                    ("progress", d / t, ("downloading", {"name": n, "pct": int(100 * d / t)}))), cancel=self.cancel_ev.is_set)
        self.start(fetch, lambda _: then())

    def start(self, work, on_done):
        self.cancel_ev = threading.Event()
        self.t0, self.eta = time.monotonic(), None
        self.set_busy(True)
        self.progress_var.set(0)

        def run():
            try:
                self.queue.put(("done", work()))
            except InterruptedError:
                self.queue.put(("cancelled", None))
            except SystemExit as e:  # enhance() reports user-level problems this way
                self.queue.put(("error", str(e.code)))
            except Exception as e:
                self.queue.put(("error", f"{type(e).__name__}: {e}"))
        threading.Thread(target=run, daemon=True).start()
        self._on_done = on_done
        self.root.after(60, self.poll)

    def estimate(self, frac):
        """Time left as an ("eta_sec"|"eta_min", kw) pair once there is enough to go on, else None."""
        spent = time.monotonic() - self.t0
        if frac < 0.03 or spent < 4:
            return None
        left = spent * (1 - frac) / frac
        return ("eta_sec", {"s": max(int(left), 1)}) if left < 90 else ("eta_min", {"m": round(left / 60)})

    def poll(self):
        keep = True
        try:
            while True:
                kind, a, *rest = self.queue.get_nowait()
                if kind == "progress":
                    self.progress_var.set(a)
                    self.eta = self.estimate(a)
                    self.set_status(*(rest[0] if rest else ("working", {"pct": int(100 * a)})))
                else:
                    keep = False
                    self.eta = None
                    self.set_busy(False)
                    if kind == "done":
                        self.progress_var.set(1)
                        self._on_done(a)
                    elif kind == "cancelled":
                        self.progress_var.set(0)
                        self.set_status("cancelled", {})
                    else:
                        self.progress_var.set(0)
                        self.set_status("error", {"msg": a})
                    break
        except queue.Empty:
            pass
        if keep and self.busy:
            self.root.after(60, self.poll)

    def set_busy(self, busy):
        self.busy = busy
        for b in (self.preview_btn, self.save_btn):
            b.state(["disabled" if busy else "!disabled"])
        self.cancel_btn.state(["!disabled" if busy else "disabled"])
        if busy:
            self.progress.grid()
            self.cancel_btn.pack(side="left", padx=4, before=self.preview_btn)
            self.reveal_btn.pack_forget()
        else:
            self.progress.grid_remove()
            self.cancel_btn.pack_forget()

    def on_cancel(self):
        self.cancel_ev.set()

    def progress_cb(self, frac):
        self.queue.put(("progress", frac))

    def on_preview(self):
        if self.busy:
            return
        self.set_status("ready", {})
        opts = self.collect(preview=(self.center, self.preview_px))
        if opts is None:
            return
        src = self.images[0]
        out = os.path.join(self.tmpdir, "preview.png")
        opts.update(bits=8, cmyk_profile=None, compress=False)
        gen = self.option_gen

        def work():
            from PIL import Image, ImageOps

            import color
            E.enhance(src, out, progress=self.progress_cb, cancel=self.cancel_ev.is_set, **opts)
            result = Image.open(out)
            result.load()
            raw = Image.open(src)
            img, _ = color.to_working_rgb(ImageOps.exif_transpose(raw), raw.info.get("icc_profile"))
            tw, th, crop, _ = E.plan_print(img.size, opts["size"], opts["unit"], opts["dpi"])
            x0, y0, x1, y1 = E.preview_region(tw, th, *opts["preview"])
            cw, ch = crop[2] - crop[0], crop[3] - crop[1]
            box = (crop[0] + x0 * cw / tw, crop[1] + y0 * ch / th, crop[0] + x1 * cw / tw, crop[1] + y1 * ch / th)
            original = img.resize(result.size, Image.LANCZOS, box=box)  # the same area, enlarged the plain way
            return result, original

        def done(images):
            self.set_status("ready", {})
            if gen != self.option_gen:  # the settings changed while it ran: this is not their preview
                return
            self.preview_images, self.compare, self.split = images, True, 0.5
            self.draw_stage()
        plan = self.current_plan()
        ai = bool(plan and plan[3])
        self.with_weights(opts["recipe"] if ai else [], lambda: self.start(work, done),
                          [weights.GFPGAN_FILE] if ai and opts["faces"] else [])

    def on_save(self):
        if self.busy:
            return
        opts = self.collect(preview=None)
        if opts is None:
            return
        tiff = opts["bits"] == 16 or bool(opts["cmyk_profile"])
        if len(self.images) == 1:
            ext = ".tif" if tiff else ".png"
            stem = os.path.splitext(os.path.basename(self.images[0]))[0]
            dest = filedialog.asksaveasfilename(parent=self.root, title=self.t("save_title"), defaultextension=ext,
                                                initialdir=self.s["last_dir"] or None, initialfile=f"{stem}-print{ext}",
                                                filetypes=SAVE_TYPES)
        else:
            dest = filedialog.askdirectory(parent=self.root, title=self.t("choose_output"),
                                           initialdir=self.s["last_dir"] or None)
        if dest:
            self.run_enhance(opts, dest)

    def run_enhance(self, opts, dest):
        """Write the print(s): `dest` is a file for one picture, a folder otherwise."""
        tiff = opts["bits"] == 16 or bool(opts["cmyk_profile"])
        renamed = False
        try:
            if len(self.images) == 1 and not os.path.isdir(dest):
                dest, renamed = save_path(dest, tiff)
                outs = E.output_paths(self.images, dest)
            else:
                outs = E.output_paths(self.images, os.path.join(dest, ""), ".tif" if tiff else ".png")
            err = (E.check_output_options(outs[0], opts["bits"], opts["cmyk_profile"])
                   or E.check_engine_options(opts["engine"], opts["bits"], opts["device_pref"]))
            if err:
                raise ValueError(err)
        except ValueError as e:
            return self.set_status("error", {"msg": str(e)})
        self.s["last_dir"] = os.path.dirname(outs[0])
        jobs = list(zip(self.images, outs))
        state = {"i": 1, "n": len(jobs), "name": ""}

        def on_job(i, n, src, dst):
            state.update(i=i, n=n, name=os.path.basename(src))

        def progress(frac):
            overall = (state["i"] - 1 + frac) / state["n"]
            self.queue.put(("progress", overall, ("working_file" if state["n"] > 1 else "working",
                                                  {**state, "pct": int(100 * frac)})))

        def work():
            return E.run_batch(jobs, False, on_job=on_job, progress=progress, cancel=self.cancel_ev.is_set, **opts)

        def done(result):
            ok, _, failed = result
            self.last_output = outs[0] if len(outs) == 1 else os.path.dirname(outs[0])
            self.reveal_btn.pack(side="left", padx=8)
            if renamed:
                self.set_status("tiff_renamed", {})
            else:
                self.set_status("done" if not failed else "done_skipped", {"n": ok, "k": len(failed)})
        plan = self.current_plan()
        ai = bool(plan and plan[3])
        self.with_weights(opts["recipe"] if ai else [], lambda: self.start(work, done),
                          [weights.GFPGAN_FILE] if ai and opts["faces"] else [])

    def on_reveal(self):
        if self.last_output:
            reveal(self.last_output)

    # -- shutdown --------------------------------------------------------------------------------
    def close(self):
        self.cancel_ev.set()
        self.s.update({k: self.v[k].get() for k in self.v}, lang=self.lang)
        self.s["denoise"] = round(float(self.s["denoise"]), 2)
        self.s["face_strength"] = round(float(self.s["face_strength"]), 2)
        try:
            save_settings(self.s, self.settings_path)
        except OSError:
            pass
        shutil.rmtree(self.tmpdir, ignore_errors=True)
        self.root.destroy()


def main():
    args = sys.argv[1:]
    if "--selftest" in args:
        import selftest
        sys.exit(selftest.run())
    if "--version" in args:
        print(f"mac-image-enhancer {E.__version__}")
        return
    root = tk.Tk()
    root.minsize(1040, 700)
    root.geometry("1120x740")
    app = App(root)
    paths = [a for a in args if not a.startswith("-") and os.path.isfile(a)]
    if paths:
        app.load_images(paths)
    root.mainloop()


if __name__ == "__main__":
    main()
