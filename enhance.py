#!/usr/bin/env python3
"""Print-size AI upscaler for Apple Silicon (MPS), CPU fallback.

    python3 enhance.py photo.jpg --size 100x50 --unit cm --dpi 150 -o out.png
    python3 enhance.py shots/*.jpg --size 30x20 --dpi 300 -o prints/ --resume   # batch

Needs: pip install torch spandrel pillow numpy tifffile
Weights: Real-ESRGAN .pth files; fetch them once with  python3 enhance.py --download-models
"""
import argparse
import hashlib
import json
import math
import os
import sys

__version__ = "0.1.0"

# Some ops may be missing on MPS; let torch fall back to CPU for them.
os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")

import weights
from weights import GENERAL_FILE, GENERAL_WDN_FILE, PHOTO_FILE

MODELS_DIR = weights.default_models_dir()
COREML_DIR = os.path.join(MODELS_DIR, "coreml")  # converted models, built on first use of --engine ane
DEFAULT_DENOISE = 0.5
TIFF_EXTS = (".tif", ".tiff")
TILE_PAD = 16  # context px around each AI tile, so seams fall outside the crop
LANCZOS_SUPPORT = 3  # Pillow's Lanczos filter radius, in output-scale px
DEFAULT_PREVIEW_SIZE = "800x600"
DEFAULT_MEM_MB = 1024  # working-memory budget per band, see band_rows_for
STRIP_BYTES = 1 << 20  # target TIFF strip size
BIGTIFF_AT = 3 << 30  # raw bytes above which a TIFF needs the 64-bit BigTIFF layout
RAM_WARN_BYTES = 2 << 30  # PNG/JPEG outputs are assembled in RAM; warn past this
MANIFEST = ".mac-image-enhancer-jobs.json"  # per output dir: file name -> job fingerprint, for --resume
ALGO_VERSION = 1  # bump when the pixels a job produces change: invalidates --resume
ENGINE_NAMES = ("gpu", "gpu16", "ane")  # fp32 torch (exact), fp16 torch, Core ML on the Neural Engine
INTENT_NAMES = ("relative", "perceptual", "saturation", "absolute")  # keys of color.INTENTS
INCHES_PER = {"in": 1.0, "cm": 1 / 2.54, "mm": 1 / 25.4, "ft": 12.0}


# ---- pure helpers (no torch/PIL, covered by test_enhance.py) ----------------

def target_pixels(w, h, unit="cm", dpi=150):
    """Physical print size + DPI -> pixel dimensions."""
    k = INCHES_PER[unit] * dpi
    return round(w * k), round(h * k)


def aspect_crop_box(w, h, ratio):
    """Centered crop box (l, t, r, b) of a w x h image to width/height == ratio."""
    if w / h > ratio:
        nw = round(h * ratio)
        x0 = (w - nw) // 2
        return x0, 0, x0 + nw, h
    nh = round(w / ratio)
    y0 = (h - nh) // 2
    return 0, y0, w, y0 + nh


def plan_print(src_size, size, unit="cm", dpi=150, model_scale=4):
    """Everything the size fields decide, for a source of `src_size` (w, h) px.

    `size` is "WIDTH" (height follows the picture's proportions) or "WIDTHxHEIGHT", in `unit`.
    Returns (tw, th, crop_box, passes): the print in pixels, the centered crop of the source
    that has the print's proportions, and how many AI passes it takes.
    """
    sw, sh = src_size
    parts = [float(p) for p in size.lower().split("x")]
    if len(parts) > 2 or not all(p > 0 for p in parts):
        raise ValueError(f"size must be WIDTH or WIDTHxHEIGHT with positive numbers, got {size!r}")
    w_phys = parts[0]
    h_phys = parts[1] if len(parts) == 2 else w_phys * sh / sw
    tw, th = target_pixels(w_phys, h_phys, unit, dpi)
    if tw < 1 or th < 1:
        raise ValueError(f"{size} {unit} at {dpi} DPI is less than one pixel")
    crop = aspect_crop_box(sw, sh, tw / th)  # ponytail: center-crop to the target aspect instead of stretching
    cw, ch = crop[2] - crop[0], crop[3] - crop[1]
    return tw, th, crop, plan_passes(max(tw / cw, th / ch), model_scale)


def tile_boxes(w, h, tile):
    """Non-overlapping (x0, y0, x1, y1) boxes covering a w x h image."""
    for y in range(0, h, tile):
        for x in range(0, w, tile):
            yield x, y, min(x + tile, w), min(y + tile, h)


def plan_passes(scale_needed, model_scale=4):
    """How many AI passes to run (each multiplies size by `model_scale`)
    before the final exact-size Lanczos resize.

    scale_needed = target_px / source_px (the larger of the two axes).
    """
    if scale_needed <= 1:
        return 0  # shrinking or same size: no AI needed
    # ponytail: 1.5x Lanczos on top of a sharp 4x is barely visible, and a
    # second pass costs 16x the pixels. Cap at 2 passes; tune 1.5 per taste.
    return 1 if scale_needed <= model_scale * 1.5 else 2


def ceil_div(a, b):
    return -(-a // b)


def parse_preview(center, size):
    """'FX,FY' (fractions of the print) and 'WxH' (px) -> ((fx, fy), (w, h))."""
    try:
        (fx, fy), (w, h) = ([float(p) for p in t.lower().split(sep)] for t, sep in ((center, ","), (size, "x")))
    except ValueError:
        raise ValueError(f"expected --preview FX,FY and --preview-size WxH, got {center!r} / {size!r}") from None
    if not (0 <= fx <= 1 and 0 <= fy <= 1):
        raise ValueError(f"--preview center must be fractions within 0..1, got {center!r}")
    if w < 1 or h < 1:
        raise ValueError(f"--preview-size must be positive, got {size!r}")
    return (fx, fy), (round(w), round(h))


def preview_region(tw, th, center=(0.5, 0.5), size=(800, 600)):
    """Pixel box (x0, y0, x1, y1) of a `size` crop of a tw x th print, centered on the
    fractional point `center`, shifted as needed to stay inside the print."""
    w, h = min(size[0], tw), min(size[1], th)
    x0 = min(max(round(center[0] * tw - w / 2), 0), tw - w)
    y0 = min(max(round(center[1] * th - h / 2), 0), th - h)
    return x0, y0, x0 + w, y0 + h


def resize_window(region, out_size, in_size):
    """What a Lanczos resize in_size -> out_size needs to produce `region` of its output.

    region = (x0, y0, x1, y1) in output px. Returns (box, window), both in input px:
    `box` is the exact source area the region maps to (floats, for Pillow's resize(box=)),
    `window` is the whole-pixel area to keep: the box plus the filter's reach, so the
    region comes out identical to the same crop of a full resize.
    """
    (x0, y0, x1, y1), (tw, th), (w, h) = region, out_size, in_size
    sx, sy = w / tw, h / th
    box = (x0 * sx, y0 * sy, x1 * sx, y1 * sy)
    mx = math.ceil(LANCZOS_SUPPORT * max(sx, 1)) + 1  # +1: slack for Pillow's rounding
    my = math.ceil(LANCZOS_SUPPORT * max(sy, 1)) + 1
    window = (max(math.floor(box[0]) - mx, 0), max(math.floor(box[1]) - my, 0),
              min(math.ceil(box[2]) + mx, w), min(math.ceil(box[3]) + my, h))
    return box, window


def pass_windows(window, sizes, scale, tile, pad):
    """Work backwards from `window`, the area needed after the last AI pass.

    sizes[k] = (w, h) of the image entering pass k. Returns [(region, needs)] in pass
    order: `region` is the tile-aligned area of that pass's input to run (its output
    covers the window, on the same tile grid as a full run), `needs` is the area of
    that input which must exist: the region plus the tiles' padding.
    """
    plan = []
    for w, h in reversed(sizes):
        lo_hi = []
        for lo, hi, limit in ((window[0], window[2], w), (window[1], window[3], h)):
            a = lo // scale // tile * tile
            b = min(ceil_div(ceil_div(hi, scale), tile) * tile, limit)  # to input px, then to tile
            lo_hi.append((a, b, max(a - pad, 0), min(b + pad, limit)))
        (ax, bx, nx0, nx1), (ay, by, ny0, ny1) = lo_hi
        plan.append(((ax, ay, bx, by), (nx0, ny0, nx1, ny1)))
        window = plan[-1][1]  # the previous pass must deliver exactly this
    return plan[::-1]


def model_recipe(kind, denoise=None, models_dir=MODELS_DIR):
    """Which weight files to load, as [(path, blend_weight)] summing to 1.

    photo   : x4plus, trained on photos (can warp text/graphics). No denoise knob.
    general : realesr-general-x4v3 for mixed content incl. text/graphics.
              denoise 1.0 = strongest smoothing, 0.0 = keep grain/detail; values
              in between blend the general and wdn weights (as upstream does).
    """
    if kind == "photo":
        if denoise is not None:
            raise ValueError("denoise only applies to the 'general' model")
        return [(os.path.join(models_dir, PHOTO_FILE), 1.0)]
    if kind != "general":
        raise ValueError(f"unknown model kind: {kind!r}")
    d = DEFAULT_DENOISE if denoise is None else denoise
    if not 0.0 <= d <= 1.0:
        raise ValueError(f"denoise must be within 0..1, got {d}")
    parts = [(os.path.join(models_dir, GENERAL_FILE), d),
             (os.path.join(models_dir, GENERAL_WDN_FILE), 1.0 - d)]
    return [(p, w) for p, w in parts if w > 0]  # skip files that contribute nothing


def blend_state_dicts(parts):
    """Weighted sum of state dicts [(sd, weight)]; keys must match exactly."""
    keys = set(parts[0][0])
    for sd, _ in parts[1:]:
        if set(sd) != keys:
            raise ValueError("cannot blend: state dicts have different keys")
    return {k: sum(sd[k] * w for sd, w in parts) for k in parts[0][0]}


def plan_bands(rows, per_band, step=1):
    """Split `rows` output rows into top-to-bottom bands of about `per_band` rows, each a
    multiple of `step` except possibly the last: [(y0, y1), ...]."""
    per_band = max(step, per_band // step * step)
    return [(y, min(y + per_band, rows)) for y in range(0, rows, per_band)]


def band_rows_for(out_w, pre_w, pre_per_out, bits, mem_bytes, channels=3):
    """Output rows one band may hold within roughly `mem_bytes`.

    A row costs its finished pixels (twice: the Lanczos result and its source copy) plus
    the pre-resize rows it depends on: `pre_per_out` of them (>1 when the last step shrinks).
    An estimate, not a limit: the floor is one tile row of the last AI pass.
    """
    bps = 2 if bits == 16 else 1
    per_row = out_w * channels * bps * 2 + pre_w * 3 * bps * max(pre_per_out, 1.0)
    return max(int(mem_bytes // per_row), 1)


def rows_per_strip(width, channels, itemsize):
    """TIFF strip height that makes strips about STRIP_BYTES."""
    return max(1, STRIP_BYTES // (width * channels * itemsize))


def output_paths(inputs, out, default_ext=".png"):
    """One output path per input. `out` is a file (one input only), a directory (existing,
    or ending in /), or a template containing {stem} (the input's name without extension)."""
    stems = [os.path.splitext(os.path.basename(p))[0] for p in inputs]
    if out is None:
        if len(inputs) > 1:
            raise ValueError("several inputs need -o DIR (or a template such as out/{stem}.tif)")
        paths = ["out" + default_ext]
    elif "{stem}" in out:
        paths = [out.replace("{stem}", s) for s in stems]
    elif out.endswith(("/", os.sep)) or os.path.isdir(out):
        paths = [os.path.join(out, s + default_ext) for s in stems]
    elif len(inputs) == 1:
        paths = [out]
    else:
        raise ValueError(f"-o {out!r} is one file but there are {len(inputs)} inputs; "
                         "give a directory or a template such as out/{stem}.tif")
    real = [os.path.realpath(p) for p in paths]
    if len(set(real)) != len(real):
        dup = sorted({p for p, r in zip(paths, real) if real.count(r) > 1})
        raise ValueError(f"these inputs would write the same output file: {', '.join(dup)}")
    src_real = {os.path.realpath(i) for i in inputs}
    clash = [p for p, r in zip(paths, real) if r in src_real]
    if clash:
        raise ValueError(f"output would overwrite its own input: {clash[0]}")
    return paths


def job_fingerprint(parts):
    """Short stable hash of everything that decides an output's pixels and metadata."""
    return hashlib.sha256(json.dumps(parts, sort_keys=True, default=str).encode()).hexdigest()[:16]


def manifest_path(out):
    return os.path.join(os.path.dirname(os.path.abspath(out)), MANIFEST)


def load_manifest(path):
    """{output file name: fingerprint}; a missing or damaged manifest counts as empty."""
    try:
        with open(path) as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def record_job(out, fingerprint):
    path = manifest_path(out)
    data = load_manifest(path)
    data[os.path.basename(out)] = fingerprint
    with open(path + ".tmp", "w") as f:
        json.dump(data, f, indent=1, sort_keys=True)
    os.replace(path + ".tmp", path)


def job_done(out, fingerprint):
    """True if `out` exists and was written by a job with exactly this fingerprint."""
    return os.path.isfile(out) and load_manifest(manifest_path(out)).get(os.path.basename(out)) == fingerprint


def check_face_options(faces, strength=1.0, keep_color=1.0, min_px=None):
    """Error message if the face-recovery options make no sense, else None."""
    if not 0.0 <= strength <= 1.0:
        return f"--face-strength must be within 0..1, got {strength}"
    if not 0.0 <= keep_color <= 1.0:
        return f"--face-color must be within 0..1, got {keep_color}"
    if min_px is not None and min_px < 8:
        return f"--face-min-size must be at least 8 px, got {min_px}"
    return None


def check_output_options(out, bits=8, cmyk_profile=None):
    """Error message if these output options cannot work together, else None."""
    ext = os.path.splitext(out)[1].lower()
    if bits == 16 and cmyk_profile:
        return "16-bit output cannot be combined with CMYK (the ICC engine behind CMYK is 8-bit)"
    if (bits == 16 or cmyk_profile) and ext not in TIFF_EXTS:
        what = "16-bit" if bits == 16 else "CMYK"
        return f"{what} output needs a .tif/.tiff file, got {ext or 'no extension'}"
    return None


def check_engine_options(engine, bits=8, device_pref="auto"):
    """Error message if --engine cannot work with the other options, else None."""
    if engine == "gpu":
        return None
    if bits == 16:
        return f"--engine {engine} computes in fp16, which keeps about 11 bits: use --engine gpu for 16-bit output"
    if device_pref == "cpu":
        return f"--engine {engine} runs on the GPU or Neural Engine, not with --device cpu"
    return None


# ---- torch side (imports are lazy so the helpers above stay light) ----------

_MPS_OK = None


def mps_usable():
    """Can the Metal GPU really be used? torch says MPS is "available" inside virtual machines (the GitHub
    macOS runners, macOS guests under a hypervisor) where the first allocation then fails with "MPS backend
    out of memory"; asking is_available() alone sent such machines to a GPU that does not work. So try a
    tiny allocation, once, and fall back to the CPU when it fails."""
    global _MPS_OK
    if _MPS_OK is None:
        import torch
        _MPS_OK = False
        if torch.backends.mps.is_available():
            try:
                torch.zeros(16, device="mps").cpu()
                _MPS_OK = True
            except Exception:
                pass
    return _MPS_OK


def pick_device(prefer="auto"):
    import torch
    if prefer != "cpu":
        if mps_usable():
            return torch.device("mps")
        if torch.cuda.is_available():
            return torch.device("cuda")
        if prefer == "gpu":
            sys.exit("--device gpu: no GPU (MPS or CUDA) is available here; use --device auto or cpu")
    return torch.device("cpu")


def load_model(recipe, device):
    from spandrel import ModelLoader
    loader = ModelLoader()
    parts = [(loader.load_state_dict_from_file(p), w) for p, w in recipe]
    sd = parts[0][0] if len(parts) == 1 else blend_state_dicts(parts)
    return loader.load_from_state_dict(sd).to(device).eval()


class TorchEngine:
    """Runs a spandrel model on one tile at a time with torch (MPS, CUDA or CPU)."""

    def __init__(self, model, device):
        self.model, self.device, self.scale = model, device, model.scale

    def run_tile(self, tile):
        """HxWx3 float32 in 0..1 -> (H*scale)x(W*scale)x3 float32 in 0..1."""
        import torch
        t = torch.from_numpy(tile).permute(2, 0, 1)[None]
        with torch.inference_mode():
            return self.model(t.to(self.device, self.model.dtype))[0].permute(1, 2, 0).clamp(0, 1).float().cpu().numpy()


class CoreMLEngine:
    """Runs a model converted to Core ML (fp16) on the Neural Engine.

    The converted model has a fixed input size, so a smaller tile (an image border) is
    reflect-padded on the right and bottom, as Real-ESRGAN itself pads borders, and the
    output cropped back.
    """

    def __init__(self, path):
        ct = require_coremltools()
        self.ml = ct.models.MLModel(path, compute_units=ct.ComputeUnit.CPU_AND_NE)
        spec = self.ml.get_spec().description
        self.name = spec.input[0].name
        self.size = spec.input[0].type.multiArrayType.shape[2]
        self.scale = spec.output[0].type.multiArrayType.shape[2] // self.size

    def run_tile(self, tile):
        import numpy as np
        h, w = tile.shape[:2]
        if (h, w) != (self.size, self.size):
            tile = np.pad(tile, ((0, self.size - h), (0, self.size - w), (0, 0)),
                          mode="reflect" if min(h, w) > 1 else "edge")
        x = np.ascontiguousarray(tile.transpose(2, 0, 1)[None])
        y = next(iter(self.ml.predict({self.name: x}).values()))[0]
        s = self.scale
        return np.clip(y[:, :h * s, :w * s].transpose(1, 2, 0), 0, 1).astype(np.float32)


def as_engine(model, device):
    """`model` is a tile engine already, or a spandrel model to run with torch on `device`."""
    return model if hasattr(model, "run_tile") else TorchEngine(model, device)


def upscale(arr, model, device, tile=256, pad=TILE_PAD, bits=8, origin=(0, 0), full=None, region=None, hook=None):
    """One tiled AI pass on an HxWx3 uint8/uint16 array -> array with `bits` per channel.

    Each tile is padded so seams fall outside the crop. `arr` may be just a window of the
    image: `origin` is its top-left in the full image, `full` the image's (w, h) and
    `region` the tile-aligned (x0, y0, x1, y1) to compute, all in full-image px. The
    result covers `region` scaled by model.scale and equals that crop of a full run.
    `hook`, if given, is called after every tile (progress; it may raise to cancel).
    """
    import numpy as np

    engine = as_engine(model, device)
    s = engine.scale
    top = 65535.0 if bits == 16 else 255.0
    src = arr.astype(np.float32)
    src /= float(np.iinfo(arr.dtype).max)  # in place: no second full-size float copy
    ax, ay = origin
    w, h = full or (arr.shape[1], arr.shape[0])
    rx0, ry0, rx1, ry1 = region or (0, 0, w, h)
    assert rx0 % tile == 0 and ry0 % tile == 0, "region must sit on the tile grid"
    out = np.zeros(((ry1 - ry0) * s, (rx1 - rx0) * s, 3), dtype=np.uint16 if bits == 16 else np.uint8)
    for bx0, by0, bx1, by1 in tile_boxes(rx1 - rx0, ry1 - ry0, tile):
        x0, y0, x1, y1 = rx0 + bx0, ry0 + by0, rx0 + bx1, ry0 + by1
        px0, py0 = max(x0 - pad, 0), max(y0 - pad, 0)
        px1, py1 = min(x1 + pad, w), min(y1 + pad, h)
        assert px0 >= ax and py0 >= ay and px1 <= ax + src.shape[1] and py1 <= ay + src.shape[0], \
            "window is missing tile padding"
        r = engine.run_tile(src[py0 - ay:py1 - ay, px0 - ax:px1 - ax])
        ox, oy = (x0 - px0) * s, (y0 - py0) * s
        r = r[oy:oy + (y1 - y0) * s, ox:ox + (x1 - x0) * s]
        out[by0 * s:by1 * s, bx0 * s:bx1 * s] = (r * top + 0.5).astype(out.dtype)
        if hook:
            hook()
    return out


def count_tiles(regions, size, src_size, passes, scale, tile):
    """How many AI tiles rendering each output region in `regions` takes: a plan, not a run
    (the same windows render() will use), so progress can be shown as a fraction."""
    w, h = src_size
    sizes = [(w * scale ** k, h * scale ** k) for k in range(passes)]
    total = 0
    for region in regions:
        _, win = resize_window(region, size, (w * scale ** passes, h * scale ** passes))
        for (rx0, ry0, rx1, ry1), _ in pass_windows(win, sizes, scale, tile, TILE_PAD):
            total += ceil_div(rx1 - rx0, tile) * ceil_div(ry1 - ry0, tile)
    return total


def resize16(arr, size, box=None):
    """Lanczos-resize an HxWx3 uint8/uint16 array to a uint16 one, channel by channel
    in float32 (Pillow has no 16-bit RGB mode). `box` as in Pillow's resize()."""
    import numpy as np
    from PIL import Image

    k = 65535.0 / np.iinfo(arr.dtype).max
    chans = [np.asarray(Image.fromarray(arr[..., c].astype(np.float32) * k).resize(size, Image.LANCZOS, box=box))
             for c in range(3)]
    return (np.clip(np.stack(chans, axis=-1), 0, 65535) + 0.5).astype(np.uint16)


def render(arr, size, region, passes, model, device, tile, bits=8, hook=None):
    """Pixels `region` (x0, y0, x1, y1 in output px) of the finished `size` print.

    Only what the region depends on is computed (tiles of each AI pass, then the Lanczos
    window), so a small region is cheap and still identical to that crop of the full
    print. The full print is simply the whole-image region.
    """
    import numpy as np
    from PIL import Image

    h, w = arr.shape[:2]
    s = model.scale if passes else 1
    sizes = [(w * s ** k, h * s ** k) for k in range(passes)]
    box, win = resize_window(region, size, (w * s ** passes, h * s ** passes))
    patch, (ox, oy) = arr, (0, 0)  # `patch` holds the part of the current image at (ox, oy)
    for k, (reg, (nx0, ny0, nx1, ny1)) in enumerate(pass_windows(win, sizes, s, tile, TILE_PAD)):
        patch = patch[ny0 - oy:ny1 - oy, nx0 - ox:nx1 - ox]
        patch = upscale(patch, model, device, tile, TILE_PAD, bits, (nx0, ny0), sizes[k], reg, hook)
        ox, oy = reg[0] * s, reg[1] * s
    patch = patch[win[1] - oy:win[3] - oy, win[0] - ox:win[2] - ox]
    rel = (box[0] - win[0], box[1] - win[1], box[2] - win[0], box[3] - win[1])
    out_size = (region[2] - region[0], region[3] - region[1])
    if bits == 16:
        return resize16(patch, out_size, rel)
    return np.asarray(Image.fromarray(patch).resize(out_size, Image.LANCZOS, box=rel))


def require_tifffile():
    try:
        import tifffile
    except ImportError:
        sys.exit("TIFF output needs tifffile: pip install tifffile")
    return tifffile


def pillow_format(dst):
    """Pillow's format name for dst's extension, or None."""
    from PIL import Image
    return Image.registered_extensions().get(os.path.splitext(dst)[1].lower())


def require_coremltools():
    try:
        import coremltools
    except ImportError:
        sys.exit("--engine ane needs coremltools: pip install coremltools")
    return coremltools


def coreml_package(recipe, size, cache_dir=None):
    """Path of the Core ML version of this model for `size` x `size` input tiles, converting
    it (about a minute, once) if it is not cached. Cached by the weights' content, so a
    different denoise blend or weights file gets its own package."""
    import hashlib

    import torch

    ct = require_coremltools()
    cache_dir = cache_dir or COREML_DIR  # read now, so tests (and callers) can point it elsewhere
    digests = []
    for p, w in recipe:
        with open(p, "rb") as f:
            digests.append([os.path.basename(p), hashlib.file_digest(f, "sha256").hexdigest(), w])
    key = job_fingerprint({"model": digests, "size": size, "coremltools": ct.__version__, "via": "export"})
    name = "+".join(os.path.splitext(os.path.basename(p))[0] for p, _ in recipe)
    path = os.path.join(cache_dir, f"{name}-{size}-{key}.mlpackage")
    if not os.path.isdir(path):
        import shutil
        print(f"converting {name} for the Neural Engine ({size}x{size} tiles); one time, takes a few seconds",
              file=sys.stderr)
        net = load_model(recipe, torch.device("cpu")).model.eval()
        with torch.inference_mode():  # torch.export, not the deprecated jit.trace: faster, same package
            program = torch.export.export(net, (torch.rand(1, 3, size, size),)).run_decompositions({})
        ml = ct.convert(program, inputs=[ct.TensorType(shape=(1, 3, size, size), name="x")],
                        convert_to="mlprogram", compute_precision=ct.precision.FLOAT16,
                        minimum_deployment_target=ct.target.macOS13)
        os.makedirs(cache_dir, exist_ok=True)
        tmp = path + ".tmp.mlpackage"
        shutil.rmtree(tmp, ignore_errors=True)
        ml.save(tmp)
        os.replace(tmp, path)  # a half-written package never sits at the cached path
    return path


_MODELS = {}


def get_engine(recipe, engine="gpu", device=None, tile=256):
    """The tile engine for `engine`, remembering the last one so a batch loads it only once.
    gpu: spandrel model in fp32 on `device`; gpu16: the same in fp16; ane: Core ML."""
    if engine == "ane":
        path = coreml_package(recipe, tile + 2 * TILE_PAD)
        key, make = ("ane", path), lambda: CoreMLEngine(path)
    else:
        key = (tuple((p, w, os.path.getsize(p), os.stat(p).st_mtime_ns) for p, w in recipe), str(device), engine)
        make = lambda: load_model(recipe, device).half() if engine == "gpu16" else load_model(recipe, device)
    if key not in _MODELS:
        _MODELS.clear()
        _MODELS[key] = make()
    return _MODELS[key]


def get_model(recipe, device):
    """The fp32 torch model for `device`, cached (see get_engine)."""
    return get_engine(recipe, "gpu", device)


def write_tiff(dst, bands, width, height, channels, dtype, rps, dpi, icc, compress):
    """Stream `bands` (iterator of rows x width x channels arrays, each a multiple of `rps`
    rows except the last) into a TIFF as strips, without ever holding the whole image."""
    import zlib

    import numpy as np

    tifffile = require_tifffile()
    le = np.dtype(dtype).newbyteorder("<")

    def strips():
        short = False
        for band in bands:
            if short:  # a deflated strip cannot be re-cut, so this would write a corrupt file
                raise ValueError("only the last band may be shorter than a whole number of strips")
            short = len(band) % rps != 0
            for y in range(0, len(band), rps):
                raw = np.ascontiguousarray(band[y:y + rps], dtype=le).tobytes()
                yield zlib.compress(raw, 3) if compress else raw

    big = width * height * channels * le.itemsize > BIGTIFF_AT
    with tifffile.TiffWriter(dst, bigtiff=big) as tw:
        tw.write(strips(), shape=(height, width, channels), dtype=le, rowsperstrip=rps,
                 photometric="separated" if channels == 4 else "rgb",
                 compression="zlib" if compress else None, resolution=(dpi, dpi),
                 resolutionunit="inch", iccprofile=icc, metadata=None)


def write_pillow(dst, fmt, bands, width, height, dpi, icc):
    """PNG/JPEG/...: Pillow cannot stream, so the finished 8-bit RGB print is assembled in RAM."""
    import numpy as np
    from PIL import Image

    full = np.empty((height, width, 3), dtype=np.uint8)
    y = 0
    for band in bands:
        full[y:y + len(band)] = band
        y += len(band)
    Image.fromarray(full).save(dst, format=fmt, dpi=(dpi, dpi), icc_profile=icc)


def enhance(src, dst, size, unit, dpi, recipe, device_pref, tile,
            bits=8, cmyk_profile=None, intent="relative", preview=None, compress=False,
            mem_mb=DEFAULT_MEM_MB, engine="gpu", progress=None, cancel=None,
            faces=False, face_strength=1.0, face_color=1.0, face_min=None, models_dir=None):
    import numpy as np
    from PIL import Image, ImageOps

    import color

    # Fail on bad output options before the slow part, not after it.
    err = check_output_options(dst, bits, cmyk_profile) or check_engine_options(engine, bits, device_pref)
    err = err or check_face_options(faces, face_strength, face_color, face_min)
    if err:
        sys.exit(err)
    if faces:
        face_models = models_dir or MODELS_DIR
        lacking = weights.missing(face_models, [weights.GFPGAN_FILE])
        if lacking:
            sys.exit(f"face recovery needs {os.path.join(face_models, weights.GFPGAN_FILE)}\n"
                     "fetch it with:  python3 enhance.py --download-models faces  "
                     "(349 MB from github.com/TencentARC/GFPGAN; read its licence terms in NOTICE first)")
    if engine == "ane":
        require_coremltools()
    is_tiff = os.path.splitext(dst)[1].lower() in TIFF_EXTS
    fmt = None
    if is_tiff:
        require_tifffile()
    elif not (fmt := pillow_format(dst)):
        sys.exit(f"don't know how to write {os.path.splitext(dst)[1] or dst!r}; use .png, .jpg or .tif")
    try:
        cmyk = color.load_cmyk_profile(cmyk_profile) if cmyk_profile else None
    except ValueError as e:
        sys.exit(str(e))

    raw = Image.open(src)
    icc = raw.info.get("icc_profile")
    img = ImageOps.exif_transpose(raw)  # phone photos: honor orientation tag
    img, icc = color.to_working_rgb(img, icc)  # CMYK/gray/palette -> RGB, profile kept or converted
    tw, th, crop, passes = plan_print((img.width, img.height), size, unit, dpi)
    img = img.crop(crop)

    # preview: just this crop of the print, at 100%, computed the same way as the full one
    region = (0, 0, tw, th) if preview is None else preview_region(tw, th, *preview)
    if preview is not None:
        print(f"preview x={region[0]}..{region[2]} y={region[1]}..{region[3]} of {tw}x{th}px",
              file=sys.stderr)

    arr = np.asarray(img)
    model = device = None
    if passes:
        missing = [p for p, _ in recipe if not os.path.exists(p)]
        if missing:
            lines = [f"weights not found: {p}" for p in missing]
            lines.append("fetch them with:  python3 enhance.py --download-models  "
                         "(from github.com/xinntao/Real-ESRGAN, checked against a pinned SHA-256)")
            sys.exit("\n".join(lines))
        device = None if engine == "ane" else pick_device(device_pref)
        if engine == "gpu16" and device.type == "cpu":
            sys.exit("--engine gpu16 needs a GPU (MPS or CUDA); this machine only has the CPU")
        used = " + ".join(f"{w:g}*{os.path.basename(p)}" for p, w in recipe)
        print(f"{'engine=ane' if device is None else f'device={device} engine={engine}'} passes={passes} "
              f"target={tw}x{th}px model={used}", file=sys.stderr)
        model = get_engine(recipe, engine, device, tile)

    # Face recovery (optional): find the faces in the picture, restore each with GFPGAN and keep them
    # ready to be pasted into every band. Only worth doing when the print is an enlargement.
    assets = []
    if faces and not passes:
        print("face recovery skipped: the print is not larger than the picture", file=sys.stderr)
    elif faces:
        import faces as face_lib
        try:
            found = face_lib.detect_faces(img)
        except face_lib.FaceRecoveryUnavailable as e:
            sys.exit(str(e))
        smallest = face_lib.MIN_FACE_PX if face_min is None else face_min
        big = [f for f in found if f.box[2] - f.box[0] >= smallest]
        print(f"faces found: {len(found)}" + (f" ({len(found) - len(big)} narrower than {smallest} px in the "
              "picture, left alone: too small to restore truthfully)" if len(big) < len(found) else ""),
              file=sys.stderr)
        found = big
        if found:
            gfp_device = device if device is not None else pick_device(device_pref)
            restorer = face_lib.Restorer(os.path.join(face_models, weights.GFPGAN_FILE), gfp_device)
            assets = face_lib.build_assets(
                img, found, restorer, (tw, th), cancel=cancel, keep_color=face_color, region=region,
                enlarge=lambda crop: upscale(crop, model, device, tile, bits=8))
            del restorer
            print(f"faces restored: {len(assets)}", file=sys.stderr)

    # The print is rendered in full-width bands, top to bottom, and each band is written
    # out before the next is computed, so memory follows the band, not the print.
    out_w, out_h = region[2] - region[0], region[3] - region[1]
    channels = 4 if cmyk else 3
    dtype = np.uint16 if bits == 16 else np.uint8
    rps = rows_per_strip(out_w, channels, np.dtype(dtype).itemsize)
    scale = model.scale if passes else 1
    rows = band_rows_for(out_w, img.width * scale ** passes, img.height * scale ** passes / th, bits,
                         mem_mb * (1 << 20), channels)
    bands = plan_bands(out_h, rows, rps if is_tiff else 1)
    if not is_tiff and out_w * out_h * 3 > RAM_WARN_BYTES:
        print(f"warning: {fmt} output is assembled in RAM (~{out_w * out_h * 3 / 2 ** 30:.1f} GB); "
              "use a .tif output to stream huge prints to disk", file=sys.stderr)

    # progress(fraction 0..1) and cancel() -> bool serve the GUI: the fraction counts AI tiles
    # (planned up front with count_tiles), or finished bands when no AI runs. Cancelling raises
    # InterruptedError, and the temporary file below is removed as for any failure.
    band_regions = [(region[0], region[1] + y0, region[2], region[1] + y1) for y0, y1 in bands]
    total_tiles = count_tiles(band_regions, (tw, th), (img.width, img.height), passes, scale, tile) if passes else 0
    tiles_done = [0]

    def tile_done():
        tiles_done[0] += 1
        if progress and total_tiles:
            progress(min(tiles_done[0] / total_tiles, 1.0))
        if cancel and cancel():
            raise InterruptedError("cancelled")

    def render_bands():
        for i, (y0, y1) in enumerate(bands, 1):
            if cancel and cancel():
                raise InterruptedError("cancelled")
            band = render(arr, (tw, th), band_regions[i - 1], passes, model, device, tile, bits, tile_done)
            if assets:  # per pixel, so a band, or a preview of one area, comes out as in the whole print
                import faces as face_lib
                band = face_lib.paste(band, (band_regions[i - 1][0], band_regions[i - 1][1]), assets, face_strength)
            if cmyk:
                band = np.asarray(color.rgb_to_cmyk(Image.fromarray(band), icc, cmyk, intent)[0])
            if len(bands) > 1:
                print(f"  band {i}/{len(bands)}  rows {y1}/{out_h}", file=sys.stderr)
            if progress and not total_tiles:
                progress(i / len(bands))
            yield band

    # Written under a temporary name and renamed at the end: a crash or Ctrl-C can leave
    # no truncated file behind, and an existing output survives until it is replaced whole.
    os.makedirs(os.path.dirname(os.path.abspath(dst)), exist_ok=True)
    tmp = os.path.join(os.path.dirname(os.path.abspath(dst)), "." + os.path.basename(dst) + ".partial")
    try:
        out_icc = cmyk[1] if cmyk else icc
        if is_tiff:
            write_tiff(tmp, render_bands(), out_w, out_h, channels, dtype, rps, dpi, out_icc, compress)
        else:
            write_pillow(tmp, fmt, render_bands(), out_w, out_h, dpi, out_icc)
        os.replace(tmp, dst)
    except BaseException:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise


def job_params(src, o):
    """What decides a job's output, for its fingerprint. `o` holds enhance()'s options."""
    def ident(path):
        st = os.stat(path) if path and os.path.exists(path) else None
        return [os.path.basename(path) if path else None, st.st_size if st else None]

    st = os.stat(src)
    return {"algo": ALGO_VERSION, "pad": TILE_PAD, "src": [os.path.basename(src), st.st_size, st.st_mtime_ns],
            "size": o["size"].lower(), "unit": o["unit"], "dpi": o["dpi"], "tile": o["tile"], "bits": o["bits"],
            "model": [[*ident(p), w] for p, w in o["recipe"]], "cmyk": ident(o["cmyk_profile"]),
            "intent": o["intent"] if o["cmyk_profile"] else None, "compress": o["compress"],
            "engine": o.get("engine", "gpu"),
            "faces": [o.get("face_strength", 1.0), o.get("face_color", 1.0), o.get("face_min")] if o.get("faces") else None}


def run_batch(jobs, resume=False, on_job=None, **opts):
    """Run [(src, dst)] one after another with the same options -> (done, skipped, failed).

    With several jobs a failing input is reported and the rest carry on; a lone job raises
    as usual. With `resume`, an output already written by an identical job is skipped, so
    re-running the same command after an interruption only does the unfinished work.
    Previews are never recorded or skipped. `on_job(i, n, src, dst)` is called as each job
    starts; cancelling (InterruptedError from the cancel hook) stops the whole batch.
    """
    done = skipped = 0
    failed = []
    track = opts.get("preview") is None
    for i, (src, dst) in enumerate(jobs, 1):
        if on_job:
            on_job(i, len(jobs), src, dst)
        try:
            fp = job_fingerprint(job_params(src, opts)) if track else None
            if resume and track and job_done(dst, fp):
                print(f"skip (already done): {dst}", file=sys.stderr)
                skipped += 1
                continue
            enhance(src, dst, **opts)
        except InterruptedError:
            raise
        except Exception as e:
            if len(jobs) == 1:
                raise
            print(f"FAILED {src}: {type(e).__name__}: {e}", file=sys.stderr)
            failed.append(src)
            continue
        if track:
            record_job(dst, fp)
        done += 1
    return done, skipped, failed


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--version", action="version", version=f"mac-image-enhancer {__version__}")
    ap.add_argument("--selftest", action="store_true", help="check that this installation works, then exit")
    ap.add_argument("images", nargs="*", metavar="image", help="one or more input images (a batch)")
    ap.add_argument("--size", help="WIDTH or WIDTHxHEIGHT in --unit (required with an image)")
    ap.add_argument("--unit", choices=INCHES_PER, default="cm")
    ap.add_argument("--dpi", type=int, default=150)
    ap.add_argument("--model", choices=["photo", "general"], default="photo",
                    help="photo: Real-ESRGAN x4plus; general: x4v3, safer for text/graphics")
    ap.add_argument("--denoise", type=float, default=None, metavar="0..1",
                    help=f"general model only: 1 = smoothest, 0 = keep grain (default {DEFAULT_DENOISE})")
    ap.add_argument("--models-dir", default=MODELS_DIR, help="where the .pth weights live (default %(default)s)")
    ap.add_argument("--download-models", nargs="?", const="all", choices=list(weights.GROUPS), metavar="photo|general|all",
                    help="download the missing weights (checked against a pinned SHA-256) into --models-dir, "
                         "then continue if images were given")
    ap.add_argument("--weights", help="use this single .pth instead of --model/--denoise")
    ap.add_argument("--device", choices=["auto", "cpu", "gpu"], default="auto",
                    help="auto: the GPU if there is one, else the CPU; gpu: insist on the GPU")
    ap.add_argument("--engine", choices=ENGINE_NAMES, default="gpu",
                    help="gpu: fp32 on the GPU, exact (default); gpu16: fp16, ~1.2x faster; ane: Core ML on the "
                         "Neural Engine, ~3x faster (needs coremltools; converts the model on first use). "
                         "Not bit-identical to gpu: about 52-60 dB PSNR against it in tests")
    ap.add_argument("--tile", type=int, default=256)
    ap.add_argument("--bits", type=int, choices=[8, 16], default=8,
                    help="16: 16-bit RGB TIFF, avoids banding in later color work")
    ap.add_argument("--cmyk-profile", metavar="ICC",
                    help="write a CMYK TIFF through this output profile (e.g. your printer's FOGRA/SWOP)")
    ap.add_argument("--intent", choices=list(INTENT_NAMES), default="relative",
                    help="rendering intent for --cmyk-profile (relative uses black point compensation)")
    ap.add_argument("--preview", metavar="FX,FY",
                    help="render only a crop at 100%% instead of the whole print, centered at this "
                         "point as fractions of it (0.5,0.5 = middle); matches that crop of the "
                         "full result to within 1 level, but is much faster")
    ap.add_argument("--preview-size", default=DEFAULT_PREVIEW_SIZE, metavar="WxH",
                    help=f"size of the --preview crop in output px (default {DEFAULT_PREVIEW_SIZE})")
    ap.add_argument("--faces", action="store_true",
                    help="restore faces with GFPGAN (macOS, needs pyobjc-framework-Vision and "
                         "--download-models faces). It invents plausible detail: compare with the original, "
                         "and read the licence note in NOTICE before commercial use")
    ap.add_argument("--face-strength", type=float, default=1.0, metavar="0..1",
                    help="how far to blend the restored faces into the print (default 1)")
    ap.add_argument("--face-color", type=float, default=1.0, metavar="0..1",
                    help="how much of the picture's own colour the faces keep (default 1: GFPGAN once "
                         "turned brown eyes blue in testing; 0 lets it choose)")
    ap.add_argument("--face-min-size", type=int, default=None, metavar="PX",
                    help="smallest face to restore, as its width in the picture (default 32: below that the "
                         "result is a different-looking invented face, which is worse than a damaged one)")
    ap.add_argument("--tiff-compress", action="store_true",
                    help="deflate-compress TIFF output (default: uncompressed, readable by every RIP)")
    ap.add_argument("--mem", type=int, default=DEFAULT_MEM_MB, metavar="MB",
                    help="working memory per band in MB (default %(default)s); the print is rendered "
                         "in bands and TIFF output is streamed, so this, not the print size, sets RAM use")
    ap.add_argument("--resume", action="store_true",
                    help="skip inputs whose output was already written by an identical job "
                         "(recorded in %s next to the outputs)" % MANIFEST)
    ap.add_argument("-o", "--out", help="output file; for several inputs a directory or a template "
                                        "like 'out/{stem}.tif' (default out.png, or .tif for --bits 16/CMYK)")
    a = ap.parse_args()
    if a.selftest:
        import selftest
        sys.exit(selftest.run(window=False))
    if a.download_models:
        for name in weights.missing(a.models_dir, weights.GROUPS[a.download_models]):
            size = weights.FILES[name][2]
            print(f"downloading {name} ({size / 2 ** 20:.1f} MB) ...", file=sys.stderr)
            try:
                weights.download(name, a.models_dir)
            except (OSError, ValueError) as e:
                sys.exit(str(e))
        print(f"models ready in {a.models_dir}", file=sys.stderr)
        if not a.images:
            return
    if not a.images:
        ap.error("the following arguments are required: image")
    if not a.size:
        ap.error("--size is required")
    if a.mem < 1:
        ap.error("--mem must be at least 1")
    err = check_face_options(a.faces, a.face_strength, a.face_color, a.face_min_size)
    if err:
        ap.error(err)
    if not a.faces and (a.face_strength != 1.0 or a.face_color != 1.0 or a.face_min_size is not None):
        ap.error("--face-strength, --face-color and --face-min-size need --faces")
    err = check_engine_options(a.engine, a.bits, a.device)
    if err:
        ap.error(err)
    try:
        outs = output_paths(a.images, a.out, ".tif" if a.bits == 16 or a.cmyk_profile else ".png")
    except ValueError as e:
        ap.error(str(e))
    for out in outs:
        err = check_output_options(out, a.bits, a.cmyk_profile)
        if err:
            ap.error(err)
    if a.resume and a.preview is not None:
        ap.error("--resume applies to full prints, not --preview")
    preview = None
    if a.preview is not None:
        try:
            preview = parse_preview(a.preview, a.preview_size)
        except ValueError as e:
            ap.error(str(e))
    elif a.preview_size != DEFAULT_PREVIEW_SIZE:
        ap.error("--preview-size needs --preview")
    if a.weights:
        if a.denoise is not None:
            ap.error("--denoise cannot be combined with --weights")
        recipe = [(a.weights, 1.0)]
    else:
        try:
            recipe = model_recipe(a.model, a.denoise, a.models_dir)
        except ValueError as e:
            ap.error(str(e))
    done, skipped, failed = run_batch(
        list(zip(a.images, outs)), a.resume, size=a.size, unit=a.unit, dpi=a.dpi, recipe=recipe,
        device_pref=a.device, tile=a.tile, bits=a.bits, cmyk_profile=a.cmyk_profile, intent=a.intent,
        preview=preview, compress=a.tiff_compress, mem_mb=a.mem, engine=a.engine,
        faces=a.faces, face_strength=a.face_strength, face_color=a.face_color, face_min=a.face_min_size,
        models_dir=a.models_dir)
    if len(a.images) > 1:
        print(f"done {done}, skipped {skipped}, failed {len(failed)}", file=sys.stderr)
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
