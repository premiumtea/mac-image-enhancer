#!/usr/bin/env python3
"""Mac Image Enhancer: the Tk front end for enhance.py.

Open pictures, set the print size and DPI, click the picture to choose an area, press
Preview to see the real result for that area at 100%, then Enhance to write the prints.
Everything the picture shows is computed by enhance.py itself, so the preview is the
print, not an approximation of it.

Needs tkinter (brew install python-tk@3.12) besides the packages enhance.py needs.
"""
import importlib.util
import json
import os
import queue
import shutil
import sys
import tempfile
import threading
import tkinter as tk
from tkinter import filedialog, font, messagebox, ttk

import enhance as E
import faces as face_lib
import i18n
import weights

SETTINGS_PATH = os.path.join(weights.app_support_dir(), "settings.json")
DEFAULTS = {"lang": "en", "unit": "cm", "dpi": "150", "width": "30", "height": "20", "keep_aspect": True,
            "model": "photo", "denoise": 0.5, "processor": "auto", "format": "png", "bits16": False,
            "compress": False, "last_dir": "", "faces": False, "face_strength": 1.0}
UNITS = ("cm", "mm", "in", "ft")
FORMATS = ("png", "tiff", "jpeg")
IMAGE_TYPES = [("Images", "*.jpg *.jpeg *.png *.tif *.tiff *.bmp *.webp"), ("All files", "*.*")]
THUMB_MAX = (520, 300)  # the source picture's box, in screen px
PREVIEW_PX = (640, 480)  # the preview crop, in print px (shown 1:1)
# processor choice -> (enhance engine, enhance device preference)
PROCESSORS = {"auto": ("gpu", "auto"), "cpu": ("gpu", "cpu"), "gpu": ("gpu", "gpu"),
              "gpu16": ("gpu16", "gpu"), "ane": ("ane", "auto")}


# ---- logic without widgets (tested without a display) ----------------------------------------

CHOICES = {"lang": tuple(i18n.LANGUAGES), "unit": UNITS, "format": FORMATS, "model": ("photo", "general"),
           "processor": tuple(PROCESSORS)}


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


def parse_number(text):
    """A positive number typed by a person ('12.5' or '12,5'), else None."""
    try:
        v = float(str(text).strip().replace(",", "."))
    except ValueError:
        return None
    return v if v > 0 and v == v and v != float("inf") else None


def size_text(width, height, keep_aspect):
    """The --size string for the two fields: 'W' lets the height follow the picture."""
    return f"{width:g}" if keep_aspect else f"{width:g}x{height:g}"


def output_ext(fmt, bits16, cmyk_profile):
    """16-bit colour and CMYK only exist in TIFF, so they decide the format."""
    return ".tif" if bits16 or cmyk_profile else {"png": ".png", "tiff": ".tif", "jpeg": ".jpg"}[fmt]


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


# ---- the window --------------------------------------------------------------------------------

class App:
    def __init__(self, root, settings_path=SETTINGS_PATH, models_dir=None):
        self.root, self.settings_path = root, settings_path
        self.models_dir = models_dir or weights.default_models_dir()
        self.s = load_settings(settings_path)
        self.lang = self.s["lang"] if self.s["lang"] in i18n.LANGUAGES else "en"
        self.tmpdir = tempfile.mkdtemp(prefix="mac-image-enhancer-")
        self.images, self.index, self.src_size = [], 0, None
        self.thumb_photo = self.thumb_size = self.preview_images = self.preview_photo = self.full_thumb = None
        self._cmyk_path = ""
        self.center = (0.5, 0.5)
        self.queue, self.cancel_ev, self.busy = queue.Queue(), threading.Event(), False
        self._labels = []  # (widget, translation key, option) for relabelling when the language changes
        self.status_state = ("ready", {})
        self._build()
        self.relabel()
        self.update_plan()
        root.protocol("WM_DELETE_WINDOW", self.close)

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
        self._fill_choices()
        self.set_status(*self.status_state)
        self.update_plan()
        self.draw_preview()

    # -- widgets ---------------------------------------------------------------------------------
    def _build(self):
        r = self.root
        self.v = {k: (tk.BooleanVar if isinstance(self.s[k], bool) else tk.DoubleVar if k in ("denoise", "face_strength") else tk.StringVar)(
            value=self.s[k]) for k in DEFAULTS if k not in ("lang", "last_dir")}
        self.lang_var, self.cmyk = tk.StringVar(value=i18n.LANGUAGES[self.lang]), tk.StringVar(value="")
        self.progress_var, self.status_var = tk.DoubleVar(value=0), tk.StringVar()
        main = ttk.Frame(r, padding=10)
        main.grid(row=0, column=0, sticky="nsew")
        r.columnconfigure(0, weight=1)
        r.rowconfigure(0, weight=1)
        main.columnconfigure(1, weight=1)
        main.rowconfigure(0, weight=1)
        left, right = ttk.Frame(main), ttk.Frame(main)
        left.grid(row=0, column=0, sticky="ns", padx=(0, 12))
        right.grid(row=0, column=1, sticky="nsew")

        top = ttk.Frame(left)
        top.pack(fill="x")
        self._reg(ttk.Button(top, command=self.on_open), "open_images").pack(side="left")
        self.lang_box = ttk.Combobox(top, textvariable=self.lang_var, state="readonly", width=9,
                                     values=list(i18n.LANGUAGES.values()))
        self.lang_box.pack(side="right")
        self._reg(ttk.Label(top), "language").pack(side="right", padx=(0, 4))
        self.lang_box.bind("<<ComboboxSelected>>", self.on_language)
        self.images_label = ttk.Label(left, wraplength=300, justify="left")
        self.images_label.pack(fill="x", pady=(6, 8))

        size = self._reg(ttk.LabelFrame(left, padding=8), "section_size", "text")
        size.pack(fill="x", pady=4)
        grid = ttk.Frame(size)
        grid.pack(fill="x")
        self.entries = {}
        for row, (key, label) in enumerate((("width", "width"), ("height", "height"), ("dpi", "dpi"))):
            self._reg(ttk.Label(grid), label).grid(row=row, column=0, sticky="w", pady=2)
            e = ttk.Entry(grid, textvariable=self.v[key], width=8)
            e.grid(row=row, column=1, sticky="w", padx=6)
            self.entries[key] = e
            self.v[key].trace_add("write", lambda *_: self.update_plan())
        self.unit_box = ttk.Combobox(grid, textvariable=self.v["unit"], values=UNITS, state="readonly", width=4)
        self.unit_box.grid(row=0, column=2, rowspan=2, padx=4)
        self.unit_box.bind("<<ComboboxSelected>>", lambda e: self.update_plan())
        self._reg(ttk.Checkbutton(size, variable=self.v["keep_aspect"], command=self.update_plan), "keep_aspect"
                  ).pack(anchor="w", pady=(6, 2))
        self.bold = font.nametofont("TkDefaultFont").copy()
        self.bold.configure(weight="bold")
        self.plan_px = ttk.Label(size, font=self.bold)
        self.plan_scale, self.plan_crop = ttk.Label(size, wraplength=290), ttk.Label(size, wraplength=290, foreground="gray40")
        for w in (self.plan_px, self.plan_scale, self.plan_crop):
            w.pack(anchor="w")

        qual = self._reg(ttk.LabelFrame(left, padding=8), "section_quality")
        qual.pack(fill="x", pady=4)
        self._reg(ttk.Label(qual), "model").grid(row=0, column=0, sticky="w")
        self.model_box = ttk.Combobox(qual, state="readonly", width=24)
        self.model_box.grid(row=0, column=1, sticky="w", padx=6, pady=2)
        self.model_box.bind("<<ComboboxSelected>>", self.on_model)
        self._reg(ttk.Label(qual), "denoise").grid(row=1, column=0, sticky="w")
        self.denoise = ttk.Scale(qual, from_=0, to=1, variable=self.v["denoise"])
        self.denoise.grid(row=1, column=1, sticky="ew", padx=6, pady=2)
        self._reg(ttk.Label(qual), "processor").grid(row=2, column=0, sticky="w")
        self.proc_box = ttk.Combobox(qual, state="readonly", width=24)
        self.proc_box.grid(row=2, column=1, sticky="w", padx=6, pady=2)
        self.proc_box.bind("<<ComboboxSelected>>", self.on_processor)
        self.faces_check = self._reg(ttk.Checkbutton(qual, variable=self.v["faces"], command=self.on_faces), "faces")
        self.faces_check.grid(row=3, column=0, columnspan=2, sticky="w", pady=(6, 0))
        self._reg(ttk.Label(qual), "face_strength").grid(row=4, column=0, sticky="w")
        self.face_scale = ttk.Scale(qual, from_=0, to=1, variable=self.v["face_strength"])
        self.face_scale.grid(row=4, column=1, sticky="ew", padx=6, pady=2)
        self.faces_note = ttk.Label(qual, wraplength=290, foreground="gray40", justify="left")
        self.faces_note.grid(row=5, column=0, columnspan=2, sticky="w", pady=(2, 0))

        out = self._reg(ttk.LabelFrame(left, padding=8), "section_output")
        out.pack(fill="x", pady=4)
        self._reg(ttk.Label(out), "format").grid(row=0, column=0, sticky="w")
        self.fmt_box = ttk.Combobox(out, textvariable=self.v["format"], values=FORMATS, state="readonly", width=8)
        self.fmt_box.grid(row=0, column=1, sticky="w", padx=6, pady=2)
        self.bits16 = self._reg(ttk.Checkbutton(out, variable=self.v["bits16"]), "bits16")
        self.bits16.grid(row=1, column=0, columnspan=3, sticky="w")
        self.compress = self._reg(ttk.Checkbutton(out, variable=self.v["compress"]), "tiff_compress")
        self.compress.grid(row=2, column=0, columnspan=3, sticky="w")
        self._reg(ttk.Label(out), "cmyk").grid(row=3, column=0, columnspan=3, sticky="w", pady=(4, 0))
        self.cmyk_label = ttk.Label(out, textvariable=self.cmyk, wraplength=200, foreground="gray40")
        self.cmyk_label.grid(row=4, column=0, columnspan=2, sticky="w")
        self._reg(ttk.Button(out, command=self.on_profile), "choose_profile").grid(row=4, column=2, padx=4)

        self.image_canvas = tk.Canvas(right, width=THUMB_MAX[0], height=THUMB_MAX[1], highlightthickness=1,
                                      highlightbackground="gray60", background="#2b2b2b", cursor="crosshair")
        self.image_canvas.pack(anchor="w")
        self.image_canvas.bind("<Button-1>", self.on_click)
        self.image_canvas.bind("<B1-Motion>", self.on_click)
        self.hint = ttk.Label(right, foreground="gray40")
        self.hint.pack(anchor="w", pady=(2, 6))
        bar = ttk.Frame(right)
        bar.pack(fill="x")
        self.preview_title = ttk.Label(bar, font=self.bold)
        self.preview_title.pack(side="left")
        self.show = tk.StringVar(value="result")
        for value, key in (("original", "show_original"), ("result", "show_result")):
            self._reg(ttk.Radiobutton(bar, variable=self.show, value=value, command=self.draw_preview), key
                      ).pack(side="right", padx=4)
        holder = ttk.Frame(right)
        holder.pack(fill="both", expand=True)
        self.preview_canvas = tk.Canvas(holder, background="#2b2b2b", highlightthickness=1, highlightbackground="gray60")
        sy = ttk.Scrollbar(holder, orient="vertical", command=self.preview_canvas.yview)
        sx = ttk.Scrollbar(holder, orient="horizontal", command=self.preview_canvas.xview)
        self.preview_canvas.configure(xscrollcommand=sx.set, yscrollcommand=sy.set)
        holder.rowconfigure(0, weight=1)
        holder.columnconfigure(0, weight=1)
        self.preview_canvas.grid(row=0, column=0, sticky="nsew")
        self.preview_canvas.bind("<Configure>", lambda e: self.draw_preview())
        sy.grid(row=0, column=1, sticky="ns")
        sx.grid(row=1, column=0, sticky="ew")

        bottom = ttk.Frame(main)
        bottom.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        bottom.columnconfigure(0, weight=1)
        ttk.Progressbar(bottom, variable=self.progress_var, maximum=1.0).grid(row=0, column=0, sticky="ew")
        ttk.Label(bottom, textvariable=self.status_var).grid(row=1, column=0, sticky="w", pady=(2, 0))
        btns = ttk.Frame(bottom)
        btns.grid(row=0, column=1, rowspan=2, padx=(10, 0))
        self.preview_btn = self._reg(ttk.Button(btns, command=self.on_preview), "preview_btn")
        self.enhance_btn = self._reg(ttk.Button(btns, command=self.on_enhance), "enhance_btn")
        self.cancel_btn = self._reg(ttk.Button(btns, command=self.on_cancel), "cancel_btn")
        for b in (self.preview_btn, self.enhance_btn, self.cancel_btn):
            b.pack(side="left", padx=3)
        self.cancel_btn.state(["disabled"])
        for var in (self.v["bits16"], self.v["format"]):
            var.trace_add("write", lambda *_: self.sync_output_controls())

    def _fill_choices(self):
        """Comboboxes whose entries are translated: rebuilt, keeping the current choice."""
        models = {"photo": self.t("model_photo"), "general": self.t("model_general")}
        self.model_box.configure(values=list(models.values()))
        self.model_box.set(models[self.v["model"].get()])
        procs = {"auto": "proc_auto", "cpu": "proc_cpu", "gpu": "proc_gpu", "gpu16": "proc_gpu16",
                 "ane": "proc_ane" if has_coreml() else "proc_ane_missing"}
        self.proc_box.configure(values=[self.t(k) for k in procs.values()])
        self.proc_box.set(self.t(procs[self.v["processor"].get()]))
        self._proc_keys, self._model_keys = list(procs), list(models)
        self.denoise.state(["!disabled" if self.v["model"].get() == "general" else "disabled"])
        self.face_scale.state(["!disabled" if self.v["faces"].get() else "disabled"])
        self.faces_note.configure(text=self.t("faces_note", px=face_lib.MIN_FACE_PX) if self.v["faces"].get() else "")
        self.sync_output_controls()
        if self.cmyk.get() == "":
            self.cmyk.set(self.t("no_profile"))
            self._cmyk_path = ""

    def sync_output_controls(self):
        tiff = self.v["bits16"].get() or self.v["format"].get() == "tiff" or bool(getattr(self, "_cmyk_path", ""))
        self.compress.state(["!disabled" if tiff else "disabled"])
        self.bits16.state(["!disabled"])

    # -- events ----------------------------------------------------------------------------------
    def on_language(self, _=None):
        names = list(i18n.LANGUAGES.values())
        self.lang = list(i18n.LANGUAGES)[names.index(self.lang_var.get())]
        if not self._cmyk_path:
            self.cmyk.set("")
        self.relabel()

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
            self.status_state = ("ane_note", {})
            self.set_status(*self.status_state)

    def on_faces(self):
        on = self.v["faces"].get()
        self.face_scale.state(["!disabled" if on else "disabled"])
        self.faces_note.configure(text=self.t("faces_note", px=face_lib.MIN_FACE_PX) if on else "")
        if on and not has_vision():
            self.fail("faces_unavailable")

    def on_profile(self):
        path = filedialog.askopenfilename(filetypes=[("ICC profile", "*.icc *.icm"), ("All files", "*.*")])
        self.set_profile(path)

    def set_profile(self, path):
        self._cmyk_path = path or ""
        self.cmyk.set(os.path.basename(path) if path else self.t("no_profile"))
        self.sync_output_controls()

    def on_open(self):
        paths = filedialog.askopenfilenames(filetypes=IMAGE_TYPES, initialdir=self.s["last_dir"] or None)
        if paths:
            self.load_images(list(paths))

    def load_images(self, paths):
        from PIL import Image, ImageOps

        import color
        self.images, self.index = list(paths), 0
        self.s["last_dir"] = os.path.dirname(paths[0])
        raw = Image.open(paths[0])
        w, h = raw.size
        if raw.getexif().get(0x0112, 1) in (5, 6, 7, 8):
            w, h = h, w
        self.src_size = (w, h)
        if raw.format == "JPEG":
            raw.draft("RGB", (THUMB_MAX[0] * 2, THUMB_MAX[1] * 2))  # decode a small version: much faster
        img, _ = color.to_working_rgb(ImageOps.exif_transpose(raw), raw.info.get("icc_profile"))
        self.full_thumb = img.copy()
        self.full_thumb.thumbnail((THUMB_MAX[0] * 2, THUMB_MAX[1] * 2))
        self.center = (0.5, 0.5)
        self.preview_images = None
        self.draw_preview()
        self.update_plan()

    def current_plan(self):
        """(tw, th, crop, passes) for the fields as they stand, or None while they are not valid."""
        if not self.src_size:
            return None
        w, dpi = parse_number(self.v["width"].get()), parse_number(self.v["dpi"].get())
        if self.v["keep_aspect"].get():
            h = w * self.src_size[1] / self.src_size[0] if w else None
            if w and h:
                self.entries["height"].state(["disabled"])
                text = f"{h:.2f}".rstrip("0").rstrip(".")
                if self.v["height"].get() != text:  # setting it fires update_plan again: only when it changes
                    self.v["height"].set(text)
        else:
            self.entries["height"].state(["!disabled"])
            h = parse_number(self.v["height"].get())
        if not (w and h and dpi) or dpi != int(dpi):
            return None
        try:
            return E.plan_print(self.src_size, size_text(w, h, self.v["keep_aspect"].get()), self.v["unit"].get(), int(dpi))
        except ValueError:
            return None

    def update_plan(self, *_):
        if not hasattr(self, "plan_px"):
            return
        if not self.src_size:
            self.images_label.configure(text=self.t("no_image"))
            for w in (self.plan_px, self.plan_scale, self.plan_crop):
                w.configure(text="")
            self.hint.configure(text="")
            self.preview_title.configure(text=self.t("preview_title"))
            self.draw_source(None)
            return
        self.images_label.configure(text=self.t("images_loaded", n=len(self.images), name=os.path.basename(self.images[0])))
        plan = self.current_plan()
        self.hint.configure(text=self.t("source_info", w=self.src_size[0], h=self.src_size[1]) + "   " + self.t("source_hint"))
        self.preview_title.configure(text=self.t("preview_title"))
        if plan is None:
            for w in (self.plan_px, self.plan_scale, self.plan_crop):
                w.configure(text="")
            self.draw_source(None)
            return
        tw, th, crop, passes = plan
        cw, ch = crop[2] - crop[0], crop[3] - crop[1]
        self.plan_px.configure(text=self.t("result_px", w=tw, h=th))
        self.plan_scale.configure(text=self.t("scale_ai", scale=max(tw / cw, th / ch), passes=passes) if passes
                                  else self.t("scale_none"))
        self.plan_crop.configure(text=self.t("crop_note") if (cw, ch) != self.src_size else "")
        self.draw_source(plan)

    def draw_source(self, plan):
        c = self.image_canvas
        c.delete("all")
        if plan is None or not self.src_size:
            return
        tw, th, crop, _ = plan
        sw, sh = self.src_size
        full_w, full_h = self.full_thumb.size  # the thumbnail covers the whole source: crop it in proportion
        box = (round(crop[0] * full_w / sw), round(crop[1] * full_h / sh), round(crop[2] * full_w / sw), round(crop[3] * full_h / sh))
        view = self.full_thumb.crop(box)
        view.thumbnail(THUMB_MAX)
        from PIL import ImageTk
        self.thumb_photo = ImageTk.PhotoImage(view)
        self.thumb_size = view.size
        c.configure(width=view.size[0], height=view.size[1])
        c.create_image(0, 0, anchor="nw", image=self.thumb_photo)
        x0, y0, x1, y1 = marker_box(self.center, PREVIEW_PX, (tw, th), view.size)
        c.create_rectangle(x0, y0, x1, y1, outline="#ffd60a", width=2)
        c.create_rectangle(x0 - 1, y0 - 1, x1 + 1, y1 + 1, outline="black")

    def on_click(self, event):
        if not self.src_size or not getattr(self, "thumb_size", None):
            return
        w, h = self.thumb_size
        self.center = (min(max(event.x / w, 0), 1), min(max(event.y / h, 0), 1))
        self.draw_source(self.current_plan())

    # -- running ---------------------------------------------------------------------------------
    def set_status(self, key, kw):
        """Show status text `key`. The state is kept as keys, not text, so it follows a language
        change: kw may carry msg_key (+ msg_kw) for a message that is itself a translation key."""
        self.status_state = (key, kw)
        shown = dict(kw)
        if "msg_key" in shown:
            shown["msg"] = self.t(shown.pop("msg_key"), **shown.pop("msg_kw", {}))
        self.status_var.set(self.t(key, **shown))

    def collect(self, preview):
        """The options for enhance(), or None after telling the user what is wrong."""
        if not self.images:
            return self.fail("need_image")
        w, dpi = parse_number(self.v["width"].get()), parse_number(self.v["dpi"].get())
        h = parse_number(self.v["height"].get())
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
        return dict(size=size_text(w, h, self.v["keep_aspect"].get()), unit=self.v["unit"].get(), dpi=int(dpi), recipe=recipe,
                    faces=faces, face_strength=round(self.v["face_strength"].get(), 2), models_dir=self.models_dir,
                    device_pref=device, tile=256, engine=engine, bits=16 if self.v["bits16"].get() else 8,
                    cmyk_profile=getattr(self, "_cmyk_path", "") or None, intent="relative",
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

    def poll(self):
        keep = True
        try:
            while True:
                kind, a, *rest = self.queue.get_nowait()
                if kind == "progress":
                    self.progress_var.set(a)
                    self.set_status(*(rest[0] if rest else ("working", {"pct": int(100 * a)})))
                else:
                    keep = False
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
        for b in (self.preview_btn, self.enhance_btn):
            b.state(["disabled" if busy else "!disabled"])
        self.cancel_btn.state(["!disabled" if busy else "disabled"])

    def on_cancel(self):
        self.cancel_ev.set()

    def progress_cb(self, frac):
        self.queue.put(("progress", frac))

    def on_preview(self):
        if self.busy:
            return
        opts = self.collect(preview=(self.center, PREVIEW_PX))
        if opts is None:
            return
        src = self.images[self.index]
        out = os.path.join(self.tmpdir, "preview.png")
        opts.update(bits=8, cmyk_profile=None, compress=False)

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
            self.preview_images = images
            self.show.set("result")
            self.draw_preview()
            self.set_status("ready", {})
        plan = self.current_plan()
        ai = bool(plan and plan[3])
        self.with_weights(opts["recipe"] if ai else [], lambda: self.start(work, done),
                          [weights.GFPGAN_FILE] if ai and opts["faces"] else [])

    def draw_preview(self):
        c = self.preview_canvas
        c.delete("all")
        if not self.preview_images:  # nothing yet: say what to do
            c.configure(scrollregion=(0, 0, 1, 1))
            c.create_text(c.winfo_width() / 2, c.winfo_height() / 2, text=self.t("preview_empty"), fill="gray70",
                          width=max(c.winfo_width() - 40, 100), justify="center")
            return
        from PIL import ImageTk
        img = self.preview_images[0 if self.show.get() == "result" else 1]
        self.preview_photo = ImageTk.PhotoImage(img)
        c.create_image(0, 0, anchor="nw", image=self.preview_photo)
        c.configure(scrollregion=(0, 0, img.width, img.height))

    def on_enhance(self):
        if self.busy:
            return
        opts = self.collect(preview=None)
        if opts is None:
            return
        folder = filedialog.askdirectory(title=self.t("choose_output"), initialdir=self.s["last_dir"] or None)
        if folder:
            self.run_enhance(opts, folder)

    def run_enhance(self, opts, folder):
        ext = output_ext(self.v["format"].get(), opts["bits"] == 16, opts["cmyk_profile"])
        try:
            outs = E.output_paths(self.images, os.path.join(folder, ""), ext)
            err = (E.check_output_options(outs[0], opts["bits"], opts["cmyk_profile"])
                   or E.check_engine_options(opts["engine"], opts["bits"], opts["device_pref"]))
            if err:
                raise ValueError(err)
        except ValueError as e:
            return self.set_status("error", {"msg": str(e)})
        self.s["last_dir"] = folder
        jobs = list(zip(self.images, outs))
        state = {"i": 1, "n": len(jobs), "name": ""}

        def on_job(i, n, src, dst):
            state.update(i=i, n=n, name=os.path.basename(src))

        def progress(frac):
            self.queue.put(("progress", frac, ("working_file", {**state, "pct": int(100 * frac)})))

        def work():
            return E.run_batch(jobs, False, on_job=on_job, progress=progress, cancel=self.cancel_ev.is_set, **opts)

        def done(result):
            ok, _, failed = result
            self.set_status("done" if not failed else "done_skipped", {"n": ok, "k": len(failed)})
        plan = self.current_plan()
        ai = bool(plan and plan[3])
        self.with_weights(opts["recipe"] if ai else [], lambda: self.start(work, done),
                          [weights.GFPGAN_FILE] if ai and opts["faces"] else [])

    # -- shutdown --------------------------------------------------------------------------------
    def close(self):
        self.cancel_ev.set()
        self.s.update({k: self.v[k].get() for k in self.v}, lang=self.lang)
        self.s["denoise"] = round(float(self.s["denoise"]), 2)
        try:
            save_settings(self.s, self.settings_path)
        except OSError:
            pass
        shutil.rmtree(self.tmpdir, ignore_errors=True)
        self.root.destroy()


def main():
    if "--selftest" in sys.argv[1:]:
        import selftest
        sys.exit(selftest.run())
    if "--version" in sys.argv[1:]:
        print(f"mac-image-enhancer {E.__version__}")
        return
    root = tk.Tk()
    root.minsize(980, 640)
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
