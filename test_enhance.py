"""Run: python3 test_enhance.py  (stdlib only, no torch needed)"""
import os

from enhance import (GENERAL_FILE, GENERAL_WDN_FILE, PHOTO_FILE, aspect_crop_box,
                     blend_state_dicts, check_output_options, model_recipe, plan_passes,
                     target_pixels, tile_boxes)

# print size + DPI -> pixels
assert target_pixels(100, 50, "cm", 150) == (5906, 2953)
assert target_pixels(10, 5, "in", 300) == (3000, 1500)
assert target_pixels(1, 1, "ft", 100) == (1200, 1200)

# tiles cover every pixel exactly once
assert sum((x1 - x0) * (y1 - y0) for x0, y0, x1, y1 in tile_boxes(1000, 700, 256)) == 1000 * 700

# centered aspect crop
assert aspect_crop_box(1000, 1000, 2.0) == (0, 250, 1000, 750)
assert aspect_crop_box(1000, 500, 1.0) == (250, 0, 750, 500)
assert aspect_crop_box(1000, 500, 2.0) == (0, 0, 1000, 500)
# an extreme proportion keeps at least one pixel (it used to give an empty crop and divide by zero in plan_print)
assert aspect_crop_box(2, 3000, 5.0) == (0, 1499, 2, 1500) or aspect_crop_box(2, 3000, 5.0)[3] - aspect_crop_box(2, 3000, 5.0)[1] >= 1
assert aspect_crop_box(3000, 2, 0.001)[2] - aspect_crop_box(3000, 2, 0.001)[0] >= 1

# plan_passes: properties any sane policy must satisfy
try:
    needs = [0.5, 1, 2, 4, 6, 16, 40]
    passes = [plan_passes(n) for n in needs]
    assert all(isinstance(p, int) and p >= 0 for p in passes), passes
    assert passes == sorted(passes), f"not monotonic: {passes}"
    assert plan_passes(1) == 0, "no AI needed when not enlarging"
    assert plan_passes(4) >= 1
    print("plan_passes ok:", dict(zip(needs, passes)))
except NotImplementedError:
    print("plan_passes: pending (your turn)")

# model_recipe: which files, which blend weights
def names(r):
    return [(os.path.basename(p), w) for p, w in r]

assert names(model_recipe("photo")) == [(PHOTO_FILE, 1.0)]
assert names(model_recipe("general", 1.0)) == [(GENERAL_FILE, 1.0)]  # no wdn file needed
assert names(model_recipe("general", 0.0)) == [(GENERAL_WDN_FILE, 1.0)]  # no general file needed
assert names(model_recipe("general", 0.25)) == [(GENERAL_FILE, 0.25), (GENERAL_WDN_FILE, 0.75)]
assert names(model_recipe("general")) == [(GENERAL_FILE, 0.5), (GENERAL_WDN_FILE, 0.5)]  # default
for bad in (lambda: model_recipe("general", 1.5), lambda: model_recipe("general", -0.1),
            lambda: model_recipe("photo", 0.5), lambda: model_recipe("nope")):
    try:
        bad()
        raise AssertionError("expected ValueError")
    except ValueError:
        pass

# blend_state_dicts: weighted sum, key mismatch rejected
assert blend_state_dicts([({"a": 2.0, "b": 10.0}, 0.25), ({"a": 6.0, "b": 20.0}, 0.75)]) == {"a": 5.0, "b": 17.5}
try:
    blend_state_dicts([({"a": 1.0}, 0.5), ({"b": 1.0}, 0.5)])
    raise AssertionError("expected ValueError")
except ValueError:
    pass
print("model_recipe/blend ok")

# Real load -> blend -> tiled upscale path, with tiny random SRVGGNetCompact weights
# (the same architecture as realesr-general-x4v3; no download needed).
try:
    import tempfile

    import torch
    from PIL import Image
    from spandrel.architectures.Compact.__arch.SRVGG import SRVGGNetCompact

    from enhance import enhance, load_model

    def tiny(seed):
        torch.manual_seed(seed)
        return SRVGGNetCompact(num_feat=8, num_conv=2, upscale=4, act_type="prelu")

    with tempfile.TemporaryDirectory() as d:
        a, b = tiny(0), tiny(1)
        torch.save({"params": a.state_dict()}, os.path.join(d, GENERAL_FILE))
        torch.save({"params": b.state_dict()}, os.path.join(d, GENERAL_WDN_FILE))
        recipe = model_recipe("general", 0.25, d)
        m = load_model(recipe, torch.device("cpu"))
        key = "body.0.weight"
        want = a.state_dict()[key] * 0.25 + b.state_dict()[key] * 0.75
        assert torch.allclose(m.model.state_dict()[key], want, atol=1e-6), "blend not applied"
        # endpoints must equal the pure files (no blend side effects)
        m1 = load_model(model_recipe("general", 1.0, d), torch.device("cpu"))
        assert torch.equal(m1.model.state_dict()[key], a.state_dict()[key])

        src, dst = os.path.join(d, "in.png"), os.path.join(d, "out.png")
        Image.new("RGB", (40, 30), "gray").save(src)
        enhance(src, dst, "8", "cm", 50, recipe, "cpu", 16)  # 40px -> 158px: needs AI
        out = Image.open(dst)
        assert out.size == (157, 118), out.size
    print("synthetic general-model pipeline ok")
except ImportError as e:
    print(f"synthetic model pipeline: skipped ({e.name} missing)")

# output option combinations are rejected up front
assert check_output_options("a.png") is None
assert check_output_options("a.tif", 16) is None
assert check_output_options("A.TIFF", 8, "p.icc") is None
assert "tif" in check_output_options("a.png", 16)
assert "tif" in check_output_options("a.jpg", 8, "p.icc")
assert "16-bit" in check_output_options("a.tif", 16, "p.icc")
print("check_output_options ok")

# Print color management (CMYK <-> RGB through ICC). CMYK cases need a CMYK profile, which
# Pillow cannot create; use macOS's own if present (never bundled), otherwise skip them.
CMYK_ICC = "/System/Library/ColorSync/Profiles/Generic CMYK Profile.icc"
try:
    import tempfile

    from PIL import Image, ImageCms

    import color
    from enhance import INTENT_NAMES, enhance

    assert set(INTENT_NAMES) == set(color.INTENTS), "CLI intent names drifted from color.INTENTS"
    srgb = color.srgb_icc()

    # non-CMYK modes: RGB keeps its profile, others are plain-converted and lose it
    rgb = Image.new("RGB", (4, 4), (10, 20, 30))
    assert color.to_working_rgb(rgb, b"icc") == (rgb, b"icc")
    out, icc = color.to_working_rgb(Image.new("L", (4, 4), 99), b"gray-icc")
    assert out.mode == "RGB" and out.getpixel((0, 0)) == (99, 99, 99) and icc is None

    # untagged CMYK has no defined colors: naive conversion, no profile claimed
    plain = Image.new("CMYK", (4, 4), (255, 0, 0, 0))
    out, icc = color.to_working_rgb(plain, None)
    assert out.getpixel((0, 0)) == plain.convert("RGB").getpixel((0, 0)) and icc is None

    with tempfile.TemporaryDirectory() as d:
        # a non-CMYK or missing profile is refused with a clear error
        rgb_icc = os.path.join(d, "srgb.icc")
        open(rgb_icc, "wb").write(srgb)
        for bad in (rgb_icc, os.path.join(d, "missing.icc")):
            try:
                color.load_cmyk_profile(bad)
                raise AssertionError("expected ValueError")
            except ValueError:
                pass
        # ...and enhance() refuses it (or bad option combos) before touching the input
        for kw in ({"cmyk_profile": rgb_icc}, {"bits": 16, "cmyk_profile": rgb_icc}):
            try:
                enhance(os.path.join(d, "nope.jpg"), os.path.join(d, "o.tif"), "2", "cm", 100,
                        [("unused.pth", 1.0)], "cpu", 256, **kw)
                raise AssertionError("expected SystemExit")
            except SystemExit:
                pass

        if not os.path.exists(CMYK_ICC):
            print("cmyk conversion: skipped (no system CMYK profile)")
        else:
            cmyk = color.load_cmyk_profile(CMYK_ICC)
            assert cmyk[1] == open(CMYK_ICC, "rb").read()

            # CMYK in -> sRGB: profile-aware, so it differs from the naive formula
            def px(v):
                im = Image.new("CMYK", (4, 4), v)
                out, icc = color.to_working_rgb(im, cmyk[1])
                assert out.mode == "RGB" and icc == srgb
                return out.getpixel((0, 0)), im.convert("RGB").getpixel((0, 0))
            (paper, _), (k100, _), (c100, c100_naive) = px((0, 0, 0, 0)), px((0, 0, 0, 255)), px((255, 0, 0, 0))
            assert min(paper) >= 250, paper
            assert 5 <= max(k100) <= 40, k100  # printed black is not RGB black, but is dark
            assert c100[1] < 200 and c100_naive[1] == 255, (c100, c100_naive)  # ink cyan is duller

            # RGB -> CMYK -> back: in-gamut colors survive, every intent works
            for name in INTENT_NAMES:
                for color_in in ((128, 128, 128), (224, 172, 150)):
                    c, icc = color.rgb_to_cmyk(Image.new("RGB", (4, 4), color_in), srgb, cmyk, name)
                    assert c.mode == "CMYK" and icc == cmyk[1]
                    if name == "absolute":
                        continue  # paper-white simulation shifts colors on purpose
                    back, _ = color.to_working_rgb(c, cmyk[1])
                    err = max(abs(a - b) for a, b in zip(back.getpixel((0, 0)), color_in))
                    assert err <= 6, (name, color_in, back.getpixel((0, 0)))

            # end to end (shrinking path, so no weights): RGB -> CMYK TIFF with profile + dpi
            src, dst = os.path.join(d, "in.png"), os.path.join(d, "out.tif")
            Image.new("RGB", (200, 100), (224, 172, 150)).save(src, icc_profile=srgb)
            enhance(src, dst, "2", "cm", 100, [("unused.pth", 1.0)], "cpu", 256, cmyk_profile=CMYK_ICC)
            out = Image.open(dst)
            assert out.mode == "CMYK" and out.info["icc_profile"] == cmyk[1], out.mode
            assert round(out.info["dpi"][0]) == 100 and out.info["compression"] == "raw"  # default: uncompressed
            plain_bytes = out.tobytes()  # load now: the next run replaces this file
            enhance(src, dst, "2", "cm", 100, [("unused.pth", 1.0)], "cpu", 256, cmyk_profile=CMYK_ICC,
                    compress=True)
            zipped = Image.open(dst)
            assert zipped.info["compression"] == "tiff_adobe_deflate" and zipped.tobytes() == plain_bytes

            # and the reverse: tagged CMYK TIFF in -> sRGB PNG, tagged as such
            cin, cout = os.path.join(d, "cmyk.tif"), os.path.join(d, "rgb.png")
            Image.new("CMYK", (200, 100), (0, 0, 0, 0)).save(cin, icc_profile=cmyk[1])
            enhance(cin, cout, "2", "cm", 100, [("unused.pth", 1.0)], "cpu", 256)
            out = Image.open(cout)
            assert out.mode == "RGB" and min(out.getpixel((5, 5))) >= 250
            assert out.info["icc_profile"] == srgb
    print("color management ok")
except ImportError as e:
    print(f"color management: skipped ({e.name} missing)")

# 16-bit TIFF: real 16-bit data from the model (not an upcast of 8-bit), tags intact
try:
    import tempfile

    import numpy as np
    import tifffile
    import torch
    from PIL import Image
    from spandrel.architectures.Compact.__arch.SRVGG import SRVGGNetCompact

    import color
    from enhance import enhance, load_model, resize16, upscale

    torch.manual_seed(0)
    net = SRVGGNetCompact(num_feat=8, num_conv=2, upscale=4, act_type="prelu")
    srgb = color.srgb_icc()
    with tempfile.TemporaryDirectory() as d:
        wpath = os.path.join(d, "tiny.pth")
        torch.save({"params": net.state_dict()}, wpath)
        recipe = [(wpath, 1.0)]
        model = load_model(recipe, torch.device("cpu"))

        # upscale keeps/chooses dtype by `bits`, whatever the input depth
        for dtype in (np.uint8, np.uint16):
            for bits, want in ((8, np.uint8), (16, np.uint16)):
                assert upscale(np.zeros((8, 8, 3), dtype), model, torch.device("cpu"), 8, bits=bits).dtype == want
        assert resize16(np.full((8, 8, 3), 255, np.uint8), (4, 4)).max() == 65535  # 8-bit white -> 16-bit white

        # smooth gradient input: banding would show up as few distinct 16-bit levels
        g = np.tile(np.linspace(40, 200, 80, dtype=np.float32), (60, 1))
        Image.fromarray(np.stack([g, g * 0.8, g * 0.6], -1).astype(np.uint8)).save(
            os.path.join(d, "in.png"), icc_profile=srgb)
        d16, d8 = os.path.join(d, "o16.tif"), os.path.join(d, "o8.png")
        enhance(os.path.join(d, "in.png"), d16, "8", "cm", 50, recipe, "cpu", 32, bits=16)
        enhance(os.path.join(d, "in.png"), d8, "8", "cm", 50, recipe, "cpu", 32)
        a16 = tifffile.imread(d16)
        assert a16.dtype == np.uint16 and a16.shape == (118, 157, 3), (a16.dtype, a16.shape)
        assert np.any(a16 % 257), "16-bit file only holds upcast 8-bit values"
        with tifffile.TiffFile(d16) as tf:
            page = tf.pages[0]
            assert page.tags["XResolution"].value == (50, 1) and page.tags["ResolutionUnit"].value == 2
            assert bytes(page.tags["InterColorProfile"].value) == srgb, "ICC lost in 16-bit TIFF"
        # same picture as the 8-bit path to within quantization
        a8 = np.asarray(Image.open(d8)).astype(int)
        diff = np.abs(a16.astype(int) / 257.0 - a8)
        assert diff.max() <= 2.0, diff.max()

        # shrinking path (no AI) also yields 16-bit
        enhance(os.path.join(d, "in.png"), d16, "1", "cm", 50, recipe, "cpu", 32, bits=16)
        assert tifffile.imread(d16).dtype == np.uint16
    print("16-bit pipeline ok")
except ImportError as e:
    print(f"16-bit pipeline: skipped ({e.name} missing)")

# plan_print: the size fields -> pixels, crop and AI passes (what the CLI and the window both use)
from enhance import plan_print

# 60 x 40 cm at 150 dpi = 3543 x 2362 px (23.62 in x 150, 15.75 in x 150); a 3:2 picture needs no crop
assert plan_print((1500, 1000), "60x40", "cm", 150) == (3543, 2362, (0, 0, 1500, 1000), 1)  # 2.4x: one pass
assert plan_print((1500, 1000), "60", "cm", 150) == (3543, 2362, (0, 0, 1500, 1000), 1)  # height follows the picture
# a square picture for a 3:2 print: cropped from the centre to 1000 x 667
assert plan_print((1000, 1000), "60x40", "cm", 150) == (3543, 2362, (0, 166, 1000, 833), 1)
assert plan_print((1500, 1000), "30x20", "cm", 300)[3] == 1 and plan_print((300, 200), "60x40", "cm", 150)[3] == 2  # 11.8x
assert plan_print((1500, 1000), "10x6.67", "cm", 100)[3] == 0  # smaller than the picture: no AI
for bad in ("0", "-5", "5x", "x5", "abc", "1x2x3", "5x0"):
    try:
        plan_print((100, 100), bad)
        raise AssertionError(f"expected ValueError for {bad!r}")
    except ValueError:
        pass
try:
    plan_print((100, 100), "0.001", "cm", 1)  # rounds to 0 pixels
    raise AssertionError("expected ValueError")
except ValueError:
    pass
print("plan_print ok")

# Preview of a region: planning helpers (pure)
from enhance import TILE_PAD, parse_preview, pass_windows, preview_region, resize_window

assert preview_region(1000, 800, (0.5, 0.5), (200, 100)) == (400, 350, 600, 450)
assert preview_region(1000, 800, (0, 0), (200, 100)) == (0, 0, 200, 100)  # shifted inside
assert preview_region(1000, 800, (1, 1), (200, 100)) == (800, 700, 1000, 800)
assert preview_region(100, 80, (0.5, 0.5), (800, 600)) == (0, 0, 100, 80)  # bigger than the print
assert parse_preview("0.25,0.75", "640x480") == ((0.25, 0.75), (640, 480))
for bad in (("0.5", "10x10"), ("1.5,0.5", "10x10"), ("0.5,0.5", "10"), ("0.5,0.5", "0x10"), ("a,b", "1x1")):
    try:
        parse_preview(*bad)
        raise AssertionError(f"expected ValueError for {bad}")
    except ValueError:
        pass

# resize_window: 1200x900 -> 600x450 (scale 2). Region (100,50)-(300,150) maps to
# box (200,100)-(600,300); the window adds the filter reach 3*2+1 = 7px, clipped to the image.
assert resize_window((100, 50, 300, 150), (600, 450), (1200, 900)) == \
    ((200.0, 100.0, 600.0, 300.0), (193, 93, 607, 307))
assert resize_window((0, 0, 600, 450), (600, 450), (1200, 900))[1] == (0, 0, 1200, 900)  # whole image
assert resize_window((0, 0, 10, 10), (2400, 1800), (1200, 900))[1] == (0, 0, 9, 9)  # upscale: reach 3+1

# pass_windows, by hand: 100x80 image, x4 model, tile 32, pad 8, need output x130..250 / y70..150.
# x: input 32..63 -> tiles 32..64; y: input 17..38 -> tiles 0..64. Padding grows each by 8 (clipped).
assert pass_windows((130, 70, 250, 150), [(100, 80)], 4, 32, 8) == [((32, 0, 64, 64), (24, 0, 72, 72))]
# invariants on two passes with awkward sizes: aligned regions, windows chained, coverage kept
for win in ((0, 0, 1280, 960), (333, 211, 700, 650), (1270, 950, 1280, 960)):
    sizes = [(80, 60), (320, 240)]
    plan = pass_windows(win, sizes, 4, 32, 8)
    for (rx0, ry0, rx1, ry1), (nx0, ny0, nx1, ny1), (w, h) in zip(*zip(*plan), sizes):
        assert rx0 % 32 == 0 and ry0 % 32 == 0 and (rx1 % 32 == 0 or rx1 == w) and (ry1 % 32 == 0 or ry1 == h)
        assert 0 <= nx0 <= rx0 < rx1 <= nx1 <= w and 0 <= ny0 <= ry0 < ry1 <= ny1 <= h
    assert plan[1][0][0] * 4 <= win[0] and plan[1][0][2] * 4 >= min(win[2], 1280)  # last pass covers window
    assert plan[0][0][0] * 4 <= plan[1][1][0] and plan[0][0][2] * 4 >= plan[1][1][2]  # pass 1 feeds pass 2's needs
print("preview planning ok")

# Preview == that crop of the full print. Needs torch (CPU, tiny random SRVGGNetCompact).
try:
    import random
    import tempfile

    import numpy as np
    import torch
    from PIL import Image
    from spandrel.architectures.Compact.__arch.SRVGG import SRVGGNetCompact

    from enhance import enhance, load_model, render, upscale

    torch.manual_seed(0)
    net = SRVGGNetCompact(num_feat=8, num_conv=2, upscale=4, act_type="prelu")
    cpu = torch.device("cpu")
    rng = np.random.default_rng(0)
    src = (rng.random((30, 40, 3)) * 255).astype(np.uint8)  # noise: any wrong pixel shows up
    with tempfile.TemporaryDirectory() as d:
        wpath = os.path.join(d, "tiny.pth")
        torch.save({"params": net.state_dict()}, wpath)
        model = load_model([(wpath, 1.0)], cpu)

        # AI stage alone: a tile-aligned window of one pass is bit-identical to the full pass
        full = upscale(src, model, cpu, 16, pad=4)
        part = upscale(src[:, 8:], model, cpu, 16, 4, origin=(8, 0), full=(40, 30), region=(16, 0, 40, 30))
        assert part.shape == (30 * 4, 24 * 4, 3) and np.array_equal(part, full[:, 16 * 4:]), "window != full pass"
        try:  # a window that lacks a tile's padding must fail loudly, not give subtly wrong pixels
            upscale(src[:, 14:], model, cpu, 16, 4, origin=(14, 0), full=(40, 30), region=(16, 0, 40, 30))
            raise AssertionError("expected the padding guard to trip")
        except AssertionError as e:
            assert "padding" in str(e), e

        def regions(w, h, n=14):
            r = random.Random(1)
            boxes = [(0, 0, 9, 7), (w - 9, h - 7, w, h), (0, h - 7, 9, h), (w - 9, 0, w, 7), (0, 0, w, h)]
            for _ in range(n):
                bw, bh = r.randint(1, w // 2), r.randint(1, h // 2)
                x, y = r.randint(0, w - bw), r.randint(0, h - bh)
                boxes.append((x, y, x + bw, y + bh))
            return boxes

        for passes, size in ((1, (40 * 4, 30 * 4)), (2, (40 * 16, 30 * 16)),  # 1:1 final resize: exact
                             (1, (150, 110)), (2, (500, 400)), (0, (25, 19))):  # real Lanczos: +-1 allowed
            exact = size[0] % 40 == 0 and size[1] % 30 == 0 and passes
            for bits in (8, 16):
                whole = (0, 0) + size
                full = render(src, size, whole, passes, model, cpu, 16, bits)
                assert full.shape == (size[1], size[0], 3) and full.dtype == (np.uint16 if bits == 16 else np.uint8)
                flipped = total = 0
                for r in regions(*size):
                    pv = render(src, size, r, passes, model, cpu, 16, bits)
                    crop = full[r[1]:r[3], r[0]:r[2]]
                    assert pv.shape == crop.shape, (passes, size, r, pv.shape, crop.shape)
                    diff = np.abs(pv.astype(int) - crop.astype(int))
                    if exact:
                        assert not diff.any(), f"passes={passes} bits={bits} region={r}: preview != full crop"
                    else:
                        # Pillow keeps resize(box=) coordinates as float32, so a real Lanczos resize
                        # may differ slightly: 8-bit by one level on ~0.03% of samples (measured),
                        # 16-bit by a couple of units, under 1/32 of an 8-bit level (257 units/level)
                        assert diff.max() <= (8 if bits == 16 else 1), (passes, size, bits, r, diff.max())
                        flipped, total = flipped + (diff > 0).sum(), total + diff.size
                if not exact and bits == 8:
                    assert flipped / total < 0.005, (passes, size, flipped / total)

        # through enhance(): saved preview = region of the full file, size and dpi right
        src_png, full_png, pv_png = (os.path.join(d, n) for n in ("in.png", "full.png", "pv.png"))
        Image.fromarray(src).save(src_png)
        recipe = [(wpath, 1.0)]
        enhance(src_png, full_png, "5", "cm", 100, recipe, "cpu", 16)  # 197x148 px, 1 pass
        enhance(src_png, pv_png, "5", "cm", 100, recipe, "cpu", 16, preview=((0.25, 0.5), (60, 40)))
        full_a, pv_img = np.asarray(Image.open(full_png)).astype(int), Image.open(pv_png)
        x0, y0, x1, y1 = preview_region(197, 148, (0.25, 0.5), (60, 40))
        assert pv_img.size == (60, 40) and round(pv_img.info["dpi"][0]) == 100
        assert np.abs(np.asarray(pv_img).astype(int) - full_a[y0:y1, x0:x1]).max() <= 1
    print("preview == full crop ok")
except ImportError as e:
    print(f"preview exactness: skipped ({e.name} missing)")

# ---- big prints (bands, streaming) and batch/resume ---------------------------------------
import time

import enhance as E
from enhance import (band_rows_for, job_done, job_fingerprint, load_manifest, manifest_path,
                     output_paths, plan_bands, record_job, rows_per_strip)

# plan_bands: exact cover, aligned to `step`, only the last band may be short
for rows, per, step in ((1000, 300, 1), (1000, 300, 64), (7, 100, 1), (1000, 10, 64), (5, 3, 4)):
    bands = plan_bands(rows, per, step)
    assert bands[0][0] == 0 and bands[-1][1] == rows and all(a[1] == b[0] for a, b in zip(bands, bands[1:]))
    assert all((y1 - y0) % step == 0 for y0, y1 in bands[:-1]), (rows, per, step, bands)
assert plan_bands(1000, 300, 64) == [(0, 256), (256, 512), (512, 768), (768, 1000)]

# band_rows_for: more memory -> more rows, wider print -> fewer, never below 1; 16-bit costs more
assert band_rows_for(5000, 8000, 1.0, 8, 1 << 30) > band_rows_for(5000, 8000, 1.0, 8, 1 << 28) > 1
assert band_rows_for(20000, 8000, 1.0, 8, 1 << 30) < band_rows_for(5000, 8000, 1.0, 8, 1 << 30)
assert band_rows_for(5000, 8000, 1.0, 16, 1 << 30) < band_rows_for(5000, 8000, 1.0, 8, 1 << 30)
assert band_rows_for(10 ** 6, 10 ** 6, 1.0, 16, 1) == 1
assert rows_per_strip(1000, 3, 1) == (1 << 20) // 3000 and rows_per_strip(10 ** 9, 3, 2) == 1

# output_paths: file / directory / template, and the ways it can go wrong
import tempfile as _tf
with _tf.TemporaryDirectory() as d:
    a, b = os.path.join(d, "a.jpg"), os.path.join(d, "sub", "b.png")
    assert output_paths([a], None) == ["out.png"] and output_paths([a], None, ".tif") == ["out.tif"]
    assert output_paths([a], "x.tif") == ["x.tif"]
    assert output_paths([a, b], os.path.join(d, "o") + "/") == [os.path.join(d, "o", "a.png"), os.path.join(d, "o", "b.png")]
    assert output_paths([a, b], os.path.join(d, "o", "{stem}_big.tif")) == \
        [os.path.join(d, "o", "a_big.tif"), os.path.join(d, "o", "b_big.tif")]
    assert output_paths([a], d, ".tif") == [os.path.join(d, "a.tif")]  # existing directory
    for bad in (lambda: output_paths([a, b], None), lambda: output_paths([a, b], "one.png"),
                lambda: output_paths([a, os.path.join(d, "x", "a.png")], os.path.join(d, "o") + "/"),  # same stem
                lambda: output_paths([a], a), lambda: output_paths([a], os.path.join(d, "{stem}.jpg"))):  # own input
        try:
            bad()
            raise AssertionError("expected ValueError")
        except ValueError:
            pass

    # fingerprints and the manifest
    fp = job_fingerprint({"size": "20x15", "dpi": 150})
    assert fp == job_fingerprint({"dpi": 150, "size": "20x15"}) and fp != job_fingerprint({"size": "20x15", "dpi": 300})
    out = os.path.join(d, "o.png")
    assert not job_done(out, fp)
    open(out, "wb").write(b"x")
    assert not job_done(out, fp)  # file exists, but no record of who wrote it
    record_job(out, fp)
    assert job_done(out, fp) and not job_done(out, "other") and load_manifest(manifest_path(out)) == {"o.png": fp}
    os.remove(out)
    assert not job_done(out, fp)  # record without the file does not count
    open(manifest_path(out), "w").write("{not json")
    assert load_manifest(manifest_path(out)) == {} and not job_done(out, fp)  # damaged manifest = empty
print("bands/paths/manifest ok")

# write_tiff: strips streamed from bands come back identical through independent readers
try:
    import numpy as np
    import tifffile
    from PIL import Image

    rng = np.random.default_rng(3)
    with _tf.TemporaryDirectory() as d:
        for channels, dtype in ((3, np.uint8), (3, np.uint16), (4, np.uint8)):
            top = np.iinfo(dtype).max
            full = rng.integers(0, top, (37, 50, channels), dtype=dtype)
            for compress in (False, True):
                p = os.path.join(d, "t.tif")
                bands = (full[y:y + 8] for y in range(0, 37, 8))  # rps 4: bands of 8 = multiples; last is 5
                E.write_tiff(p, bands, 50, 37, channels, dtype, 4, 300, b"", compress)
                assert np.array_equal(tifffile.imread(p), full), (channels, dtype, compress)
                with tifffile.TiffFile(p) as tf:
                    pg = tf.pages[0]
                    assert pg.rowsperstrip == 4 and pg.tags["XResolution"].value == (300, 1)
                    assert pg.photometric.name == ("SEPARATED" if channels == 4 else "RGB")
                if dtype == np.uint8:
                    assert np.array_equal(np.asarray(Image.open(p)), full)  # Pillow agrees
        # a band that is not a whole number of strips is only allowed last: otherwise the file
        # would be corrupt (compressed strips cannot be re-cut), so it must fail loudly instead
        for compress in (False, True):
            try:
                E.write_tiff(os.path.join(d, "bad.tif"), (full[y:y + 8] for y in range(0, 37, 8)), 50, 37, 4,
                             np.uint8, 3, 72, None, compress)  # rps 3, bands of 8
                raise AssertionError("expected ValueError")
            except ValueError as e:
                assert "last band" in str(e)
        # BigTIFF kicks in past BIGTIFF_AT
        old = E.BIGTIFF_AT
        E.BIGTIFF_AT = 1000
        try:
            E.write_tiff(os.path.join(d, "big.tif"), iter([full[:37]]), 50, 37, 4, np.uint8, 37, 72, None, False)
        finally:
            E.BIGTIFF_AT = old
        with tifffile.TiffFile(os.path.join(d, "big.tif")) as tf:
            assert tf.is_bigtiff
    print("write_tiff streaming ok")
except ImportError as e:
    print(f"write_tiff: skipped ({e.name} missing)")

# Bands, atomic writes, batch + resume, with the tiny model on CPU
try:
    import contextlib
    import subprocess
    import sys
    import tracemalloc

    import numpy as np
    import tifffile
    import torch
    from PIL import Image
    from spandrel.architectures.Compact.__arch.SRVGG import SRVGGNetCompact

    torch.manual_seed(0)
    net = SRVGGNetCompact(num_feat=8, num_conv=2, upscale=4, act_type="prelu")
    rng = np.random.default_rng(5)

    @contextlib.contextmanager
    def patched(obj, name, value):
        old = getattr(obj, name)
        setattr(obj, name, value)
        try:
            yield
        finally:
            setattr(obj, name, old)

    real_render, real_enhance, real_load = E.render, E.enhance, E.load_model

    with _tf.TemporaryDirectory() as d:
        wpath = os.path.join(d, "tiny.pth")
        torch.save({"params": net.state_dict()}, wpath)
        recipe = [(wpath, 1.0)]

        def make(name, w=40, h=30):
            p = os.path.join(d, name)
            Image.fromarray((rng.random((h, w, 3)) * 255).astype(np.uint8)).save(p)
            return p
        a, b = make("a.png"), make("b.png", 36, 36)
        tiny_strips = patched(E, "STRIP_BYTES", 6000)  # 3-4 row strips, so small bands stay strip-aligned

        # Many bands == one band. A 1:1 final resize (40x30 -> 640x480 is exactly 2 passes) must match
        # bit for bit; a real Lanczos (-> 500x375) only to +-1, the Pillow float32 box quirk.
        with tiny_strips:
            for inches, exact in (("6.4", True), ("5", False)):
                kw = dict(size=inches, unit="in", dpi=100, recipe=recipe, device_pref="cpu", tile=16)
                one, many = os.path.join(d, "one.tif"), os.path.join(d, "many.tif")
                enhance(a, one, mem_mb=1024, **kw)
                x = tifffile.imread(one).astype(int)
                # budgets whose natural band height is NOT a multiple of the strip height (3-4 rows)
                # must still give a valid image: bands are rounded to whole strips
                for mem, compress in ((0.2, False), (0.21, False), (0.13, False), (0.21, True), (0.13, True)):
                    enhance(a, many, mem_mb=mem, compress=compress, **kw)
                    y = tifffile.imread(many).astype(int)
                    assert x.shape == y.shape == ((480, 640, 3) if exact else (375, 500, 3))
                    assert not (x != y).any() if exact else np.abs(x - y).max() <= 1, (exact, mem, compress)

            # the bands really are separate renders: contiguous, top to bottom, full width, several of them
            regions = []
            with patched(E, "render", lambda *args, **kw: regions.append(args[2]) or real_render(*args, **kw)):
                enhance(a, os.path.join(d, "m.tif"), "6.4", "in", 100, recipe, "cpu", 16, mem_mb=0.2)
            assert len(regions) > 5, len(regions)
            assert regions[0][1] == 0 and regions[-1][3] == 480
            assert all(p[3] == q[1] for p, q in zip(regions, regions[1:]))
            assert {(r[0], r[2]) for r in regions} == {(0, 640)}

            # Memory follows the band, not the print: peak numpy allocation, many bands vs one
            def peak(mem_mb):
                tracemalloc.start()
                enhance(a, os.path.join(d, "mem.tif"), "6.4", "in", 100, recipe, "cpu", 16, mem_mb=mem_mb)
                _, p = tracemalloc.get_traced_memory()
                tracemalloc.stop()
                return p
            p_one, p_many = peak(1024), peak(0.2)
            assert p_many < 0.6 * p_one, (p_many, p_one)

            # Atomic: a failure mid-print leaves no partial file, and an existing output stays whole
            good = os.path.join(d, "keep.tif")
            enhance(a, good, "1.2", "in", 100, recipe, "cpu", 16)
            before = open(good, "rb").read()
            for target, existed in ((good, True), (os.path.join(d, "fresh.tif"), False)):
                seen = []

                def explode(*args, **kw):
                    seen.append(1)
                    if len(seen) == 2:
                        raise RuntimeError("boom")
                    return real_render(*args, **kw)
                with patched(E, "render", explode):
                    try:
                        enhance(a, target, "6.4", "in", 100, recipe, "cpu", 16, mem_mb=0.2)
                        raise AssertionError("expected RuntimeError")
                    except RuntimeError:
                        pass
                assert os.path.exists(target) == existed
            assert open(good, "rb").read() == before, "an existing output was damaged by a failed run"
            assert not [f for f in os.listdir(d) if f.endswith(".partial")], os.listdir(d)

        # Batch: one bad input does not stop the rest; weights load once; manifest records the good ones
        outdir = os.path.join(d, "out")
        bad = os.path.join(d, "bad.png")
        open(bad, "w").write("not an image")
        opts = dict(size="1.2", unit="in", dpi=100, recipe=recipe, device_pref="cpu", tile=16, bits=8,
                    cmyk_profile=None, intent="relative", preview=None, compress=False, mem_mb=1024)
        jobs = [(a, os.path.join(outdir, "a.png")), (bad, os.path.join(outdir, "bad.png")),
                (b, os.path.join(outdir, "b.png"))]
        loads, ran = [], []
        E._MODELS.clear()  # the runs above already cached these weights
        with patched(E, "load_model", lambda *x: loads.append(1) or real_load(*x)), \
                patched(E, "enhance", lambda src, dst, **kw: ran.append(os.path.basename(src)) or real_enhance(src, dst, **kw)):
            assert E.run_batch(jobs, **opts) == (2, 0, [bad])
            assert len(loads) == 1, "weights should load once per batch"
            assert sorted(f for f in os.listdir(outdir) if not f.startswith(".")) == ["a.png", "b.png"]
            assert set(load_manifest(os.path.join(outdir, E.MANIFEST))) == {"a.png", "b.png"}

            # resume: finished outputs are skipped, only the unfinished input is attempted again
            ran.clear()
            assert E.run_batch(jobs, resume=True, **opts) == (0, 2, [bad]) and ran == ["bad.png"]
            # ...but not when anything that shapes the output changed
            ran.clear()
            assert E.run_batch(jobs[::2], resume=True, **{**opts, "dpi": 150}) == (2, 0, []) and ran == ["a.png", "b.png"]
            ran.clear()
            assert E.run_batch(jobs[::2], resume=True, **{**opts, "dpi": 150}) == (0, 2, [])  # now recorded
            # changed input (new content, new mtime) redoes only that one
            time.sleep(0.01)
            make("a.png")
            ran.clear()
            assert E.run_batch(jobs[::2], resume=True, **{**opts, "dpi": 150}) == (1, 1, []) and ran == ["a.png"]
            # a deleted output is redone
            os.remove(jobs[2][1])
            ran.clear()
            assert E.run_batch(jobs[::2], resume=True, **{**opts, "dpi": 150}) == (1, 1, []) and ran == ["b.png"]
            # without --resume everything is redone
            ran.clear()
            assert E.run_batch(jobs[::2], **{**opts, "dpi": 150}) == (2, 0, []) and ran == ["a.png", "b.png"]
            # previews are never recorded or skipped
            pv = {**opts, "preview": ((0.5, 0.5), (20, 20))}
            ran.clear()
            before = load_manifest(os.path.join(outdir, E.MANIFEST))
            pdir = os.path.join(d, "pv")
            pjobs = [(a, os.path.join(pdir, "a.png"))]
            assert E.run_batch(pjobs, resume=True, **pv) == (1, 0, []) and E.run_batch(pjobs, resume=True, **pv) == (1, 0, [])
            assert not os.path.exists(os.path.join(pdir, E.MANIFEST)) and before == load_manifest(os.path.join(outdir, E.MANIFEST))
            assert Image.open(pjobs[0][1]).size == (20, 20)
            # a missing input is just another failed job, whether or not it is being resumed
            gone = os.path.join(d, "gone.png")
            for resume in (False, True):
                assert E.run_batch([(gone, os.path.join(outdir, "gone.png")), jobs[0]], resume=resume, **opts)[2] == [gone]
            # a lone failing job raises (traceback), instead of being swallowed
            try:
                E.run_batch([(bad, os.path.join(d, "x.png"))], **opts)
                raise AssertionError("expected an exception")
            except AssertionError:
                raise
            except Exception:
                pass

        # The CLI end to end: batch into a directory, resume, and the ways to get the arguments wrong
        cli = [sys.executable, "enhance.py"]
        base = ["--weights", wpath, "--device", "cpu", "--tile", "16", "--size", "1.2", "--unit", "in", "--dpi", "100"]
        here = os.path.dirname(os.path.abspath(__file__))
        cdir = os.path.join(d, "cli") + "/"

        def run(*args):
            return subprocess.run(cli + list(args), capture_output=True, text=True, cwd=here)
        r = run(a, b, *base, "-o", cdir)
        assert r.returncode == 0 and "done 2, skipped 0, failed 0" in r.stderr, r.stderr[-400:]
        assert sorted(f for f in os.listdir(cdir) if not f.startswith(".")) == ["a.png", "b.png"]
        r = run(a, b, *base, "-o", cdir, "--resume")
        assert r.returncode == 0 and r.stderr.count("skip (already done)") == 2 and "done 0, skipped 2" in r.stderr, r.stderr
        r = run(a, bad, *base, "-o", os.path.join(d, "cli2", "{stem}.tif"))
        assert r.returncode == 1 and "FAILED" in r.stderr and "done 1, skipped 0, failed 1" in r.stderr, r.stderr[-400:]
        assert tifffile.imread(os.path.join(d, "cli2", "a.tif")).shape == (90, 120, 3)  # 1.2in @100dpi wide, a 40x30 source
        for args in ((a, b), (a, b, "-o", os.path.join(d, "one.png")), (a, "-o", a),
                     (a, b, "-o", cdir, "--resume", "--preview", "0.5,0.5"), (a, "-o", cdir, "--mem", "0")):
            r = run(*args, *base)
            assert r.returncode == 2, (args, r.returncode, r.stderr[-300:])
    print("bands + batch/resume ok")
except ImportError as e:
    print(f"bands/batch: skipped ({e.name} missing)")

# ---- engines: gpu (fp32 torch), gpu16 (fp16 torch), ane (Core ML) ---------------------------
from enhance import ENGINE_NAMES, as_engine, check_engine_options, enhance, render, upscale

assert ENGINE_NAMES == ("gpu", "gpu16", "ane")
assert check_engine_options("gpu") is None and check_engine_options("gpu", 16, "cpu") is None  # gpu: always fine
for eng in ("gpu16", "ane"):
    assert check_engine_options(eng, 8, "auto") is None
    assert "16-bit" in check_engine_options(eng, 16)  # fp16 keeps ~11 bits: pointless for 16-bit output
    assert "cpu" in check_engine_options(eng, 8, "cpu")


class NearestX4:
    """A stand-in tile engine in plain numpy: nearest-neighbour x4. Deterministic and exact, so
    it shows the window/preview plumbing is independent of whichever engine computes the tiles."""
    scale = 4

    def __init__(self):
        self.shapes = []

    def run_tile(self, tile):
        self.shapes.append(tile.shape[:2])
        return np.repeat(np.repeat(tile, 4, axis=0), 4, axis=1)


try:
    import numpy as np

    fake = NearestX4()
    assert as_engine(fake, None) is fake  # an engine passes through; a model gets wrapped (next test)
    img = (np.random.default_rng(2).random((30, 40, 3)) * 255).astype(np.uint8)
    full = upscale(img, fake, None, 16, pad=4)
    assert full.shape == (120, 160, 3) and np.array_equal(full, np.repeat(np.repeat(img, 4, 0), 4, 1))
    # 40x30 image, tile 16, pad 4: windows are x [0,20) [12,36) [28,40) and y [0,20) [12,30), handed over
    # exactly as cut (no padding to a fixed size; border tiles simply smaller)
    assert set(fake.shapes) == {(h, w) for h in (20, 18) for w in (20, 24, 12)}, set(fake.shapes)
    part = upscale(img[:, 8:], fake, None, 16, 4, origin=(8, 0), full=(40, 30), region=(16, 0, 40, 30))
    assert np.array_equal(part, full[:, 16 * 4:])  # a window equals the full pass for any engine
    # and the whole render/preview path works through an engine, with no torch involved
    big = render(img, (160, 120), (0, 0, 160, 120), 1, fake, None, 16, 8)
    for r in ((0, 0, 20, 10), (100, 90, 160, 120), (33, 17, 97, 80)):
        assert np.array_equal(render(img, (160, 120), r, 1, fake, None, 16, 8), big[r[1]:r[3], r[0]:r[2]])
    print("engine plumbing ok")
except ImportError as e:
    print(f"engine plumbing: skipped ({e.name} missing)")

# the engine is part of a job's fingerprint: switching it must invalidate --resume
with _tf.TemporaryDirectory() as d:
    probe = os.path.join(d, "x.png")
    open(probe, "wb").write(b"x")
    o = dict(size="5", unit="cm", dpi=100, recipe=[("w.pth", 1.0)], tile=16, bits=8, cmyk_profile=None,
             intent="relative", compress=False)
    fps = {e: job_fingerprint(E.job_params(probe, {**o, "engine": e})) for e in ENGINE_NAMES}
    assert len(set(fps.values())) == 3 and fps["gpu"] == job_fingerprint(E.job_params(probe, o))  # default = gpu

# Real engines, with the tiny model (torch; Core ML parts also need coremltools)
try:
    import torch
    from spandrel.architectures.Compact.__arch.SRVGG import SRVGGNetCompact

    torch.manual_seed(0)
    net = SRVGGNetCompact(num_feat=8, num_conv=2, upscale=4, act_type="prelu")
    rng = np.random.default_rng(7)
    photo = (rng.random((40, 56, 3)) * 255).astype(np.uint8)
    with _tf.TemporaryDirectory() as d:
        wpath = os.path.join(d, "tiny.pth")
        torch.save({"params": net.state_dict()}, wpath)
        recipe = [(wpath, 1.0)]
        src = os.path.join(d, "in.png")
        Image.fromarray(photo).save(src)
        cpu = torch.device("cpu")

        # the torch engine is exactly the old behavior, and the engine cache keys on the engine
        eng = E.TorchEngine(E.load_model(recipe, cpu), cpu)
        assert np.array_equal(upscale(photo, eng, None, 16, 4), upscale(photo, E.load_model(recipe, cpu), cpu, 16, 4))
        E._MODELS.clear()
        assert E.get_engine(recipe, "gpu", cpu) is E.get_engine(recipe, "gpu", cpu)
        assert E.get_engine(recipe, "gpu16", cpu) is not E.get_engine(recipe, "gpu", cpu)
        assert next(E.get_engine(recipe, "gpu16", cpu).model.parameters()).dtype == torch.float16

        # gpu16 on a GPU (skipped on machines without one): close to fp32, never NaN
        if E.mps_usable():  # not is_available(): a virtual machine can report MPS and still fail to allocate
            a8, b8 = os.path.join(d, "g.png"), os.path.join(d, "g16.png")
            kw = dict(size="2", unit="in", dpi=100, recipe=recipe, device_pref="auto", tile=16)
            enhance(src, a8, engine="gpu", **kw)
            enhance(src, b8, engine="gpu16", **kw)
            x, y = np.asarray(Image.open(a8)).astype(int), np.asarray(Image.open(b8)).astype(int)
            assert x.shape == y.shape and np.abs(x - y).max() <= 6, np.abs(x - y).max()
            # gpu16 refuses to run on the CPU instead of silently crawling
            try:
                enhance(src, a8, engine="gpu16", **{**kw, "device_pref": "cpu"})
                raise AssertionError("expected SystemExit")
            except SystemExit as e:
                assert "cpu" in str(e)
        print("torch engines ok")

        try:
            import coremltools  # noqa: F401
        except ImportError:
            print("core ml engine: skipped (coremltools not installed)")
        else:
            cache = os.path.join(d, "coreml")
            size = 16 + 2 * TILE_PAD
            path = E.coreml_package(recipe, size, cache)
            assert os.path.isdir(path) and path.startswith(cache) and path.endswith(".mlpackage")
            m0 = os.stat(path).st_mtime_ns
            real_load = E.load_model
            loads = []
            with patched(E, "load_model", lambda *a: loads.append(1) or real_load(*a)):
                assert E.coreml_package(recipe, size, cache) == path and not loads  # cached: no reconversion
                assert E.coreml_package(recipe, size + 8, cache) != path  # another tile size, another package
            assert os.stat(path).st_mtime_ns == m0 and not [f for f in os.listdir(cache) if ".tmp" in f]
            # keyed by the weights' content, not their name: different weights in a file of the same name
            os.makedirs(os.path.join(d, "alt"))
            torch.manual_seed(1)
            torch.save({"params": SRVGGNetCompact(num_feat=8, num_conv=2, upscale=4, act_type="prelu").state_dict()},
                       os.path.join(d, "alt", "tiny.pth"))
            assert E.coreml_package([(os.path.join(d, "alt", "tiny.pth"), 1.0)], size, cache) != path
            assert E.coreml_package([(wpath, 0.5)], size, cache) != path  # a different blend weight too

            ane = E.CoreMLEngine(path)
            assert ane.scale == 4 and ane.size == size and as_engine(ane, None) is ane
            tile = rng.random((size, size, 3)).astype(np.float32)  # a full-size tile: no padding involved
            ref = E.TorchEngine(E.load_model(recipe, cpu), cpu)
            diff = np.abs(ane.run_tile(tile) - ref.run_tile(tile))
            assert diff.max() < 0.03 and diff.mean() < 0.003, (diff.max(), diff.mean())  # fp16 vs fp32: a few levels
            for shape in ((20, 30), (size, 5), (1, 7), (1, 1)):  # smaller tiles (borders) are padded and cropped back
                r = ane.run_tile(rng.random((*shape, 3)).astype(np.float32))
                assert r.shape == (shape[0] * 4, shape[1] * 4, 3) and r.dtype == np.float32 and 0 <= r.min() and r.max() <= 1

            # the AI stage is deterministic on the Neural Engine, so windows equal the full pass here too
            whole = upscale(photo, ane, None, 16)
            part = upscale(photo, ane, None, 16, region=(16, 0, 56, 40))  # tiles right of x=16 only
            assert np.array_equal(part, whole[:, 16 * 4:])
            # end to end, with its own cache so the test never touches models/coreml
            with patched(E, "COREML_DIR", cache):
                E._MODELS.clear()
                out = os.path.join(d, "ane.png")
                enhance(src, out, "2", "in", 100, recipe, "auto", 16, engine="ane")
                gpu_out = os.path.join(d, "gpu.png")
                enhance(src, gpu_out, "2", "in", 100, recipe, "cpu", 16, engine="gpu")
                x, y = np.asarray(Image.open(out)).astype(int), np.asarray(Image.open(gpu_out)).astype(int)
                tw, th = target_pixels(2, 2 * 40 / 56, "in", 100)  # a 56x40 source, 2 in wide at 100 dpi
                assert x.shape == y.shape == (th, tw, 3)
                # preview == crop of the full ANE print (+-1: the Pillow float32 box quirk)
                pv = os.path.join(d, "pv.png")
                enhance(src, pv, "2", "in", 100, recipe, "auto", 16, engine="ane", preview=((0.5, 0.5), (40, 30)))
                x0, y0, x1, y1 = preview_region(tw, th, (0.5, 0.5), (40, 30))
                assert np.abs(np.asarray(Image.open(pv)).astype(int) - x[y0:y1, x0:x1]).max() <= 1
            print("core ml engine ok")
except ImportError as e:
    print(f"real engines: skipped ({e.name} missing)")

# ---- weights: where they live, and downloading them (file:// URLs: no network, no 67 MB) --------
import hashlib
import importlib.util
import pathlib

import weights as W

assert set(W.GROUPS["all"]) | set(W.GROUPS["faces"]) == set(W.FILES) and not set(W.GROUPS["all"]) & set(W.GROUPS["faces"])
assert set(W.GROUPS["general"]) == {GENERAL_FILE, GENERAL_WDN_FILE}  # "all" leaves out the 349 MB face model
assert all(len(sha) == 64 and size > 0 and url.startswith(("https://github.com/xinntao/Real-ESRGAN/", "https://github.com/TencentARC/GFPGAN/"))
           for url, sha, size in W.FILES.values())

with _tf.TemporaryDirectory() as d:
    # where the models directory is: env var, else beside the code, else the per-user folder
    old_env, old_home = os.environ.get("MAC_IMAGE_ENHANCER_MODELS"), os.environ.get("HOME")
    try:
        os.environ["MAC_IMAGE_ENHANCER_MODELS"] = os.path.join(d, "mine")
        assert W.default_models_dir() == os.path.join(d, "mine")
        del os.environ["MAC_IMAGE_ENHANCER_MODELS"]
        lone = os.path.join(d, "lone")  # a copy of weights.py with no models/ beside it, like a pip install or the .app
        os.makedirs(lone)
        shutil_copy = __import__("shutil").copy
        shutil_copy(W.__file__, lone)
        spec = importlib.util.spec_from_file_location("weights_lone", os.path.join(lone, "weights.py"))
        lone_mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(lone_mod)
        os.environ["HOME"] = os.path.join(d, "home")
        assert lone_mod.default_models_dir() == os.path.join(d, "home", "Library", "Application Support", "mac-image-enhancer", "models")
        os.makedirs(os.path.join(lone, "models"))
        assert lone_mod.default_models_dir() == os.path.join(lone, "models")  # a checkout's models/ wins
    finally:
        for k, v in (("MAC_IMAGE_ENHANCER_MODELS", old_env), ("HOME", old_home)):
            os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)

    # missing(): absent files and files of the wrong size both count
    mdir = os.path.join(d, "models")
    os.makedirs(mdir)
    assert W.missing(mdir, W.GROUPS["general"]) == W.GROUPS["general"]
    open(os.path.join(mdir, GENERAL_FILE), "wb").write(b"short")
    assert W.missing(mdir, [GENERAL_FILE]) == [GENERAL_FILE]
    open(os.path.join(mdir, "custom.pth"), "wb").write(b"x")
    assert W.missing(mdir, ["custom.pth"]) == []  # a name we do not know is only checked for existing

    # download(): from a file:// "server"
    payload = os.urandom(3 * (1 << 20) + 123)
    src_file = os.path.join(d, "served.pth")
    open(src_file, "wb").write(payload)
    url = pathlib.Path(src_file).as_uri()
    digest = hashlib.sha256(payload).hexdigest()
    fake = {"w.pth": (url, digest, len(payload))}
    seen = []
    path = W.download("w.pth", mdir, progress=lambda done, total: seen.append((done, total)), files=fake)
    assert open(path, "rb").read() == payload and path == os.path.join(mdir, "w.pth")
    assert seen[-1] == (len(payload), len(payload)) and [s[0] for s in seen] == sorted(s[0] for s in seen) and len(seen) >= 3
    assert not [f for f in os.listdir(mdir) if f.endswith(".partial")]

    def refused(exc, **kw):
        try:
            W.download("w.pth", os.path.join(d, "fresh"), files=kw.pop("files"), **kw)
            raise AssertionError(f"expected {exc.__name__}")
        except exc as e:
            return str(e)
    msg = refused(ValueError, files={"w.pth": (url, "0" * 64, len(payload))})  # wrong checksum: nothing is kept
    assert "checksum" in msg and not os.listdir(os.path.join(d, "fresh"))
    refused(InterruptedError, files=fake, cancel=lambda: True)  # cancelled: nothing is kept either
    assert not os.listdir(os.path.join(d, "fresh"))
    assert "could not download" in refused(OSError, files={"w.pth": (pathlib.Path(d, "nope").as_uri(), digest, 1)})
    # a failed download must not damage a good file already there
    before = open(path, "rb").read()
    try:
        W.download("w.pth", mdir, files={"w.pth": (url, "1" * 64, len(payload))})
    except ValueError:
        pass
    assert open(path, "rb").read() == before
print("weights ok")

# the real weights in this checkout, when present, match the pinned checksums
present = [n for n in W.FILES if not W.missing(W.default_models_dir(), [n])]  # the 349 MB face model is optional
for name in present:
    assert W.sha256_of(os.path.join(W.default_models_dir(), name)) == W.FILES[name][1], name
if present:
    print(f"pinned checksums match the weights in models/ ({len(present)} present)")

# ---- progress / cancel hooks ---------------------------------------------------------------
try:
    import numpy as np

    from enhance import count_tiles

    fake = NearestX4()
    img = (np.random.default_rng(4).random((33, 47, 3)) * 255).astype(np.uint8)
    for passes, size, region in ((1, (188, 132), (0, 0, 188, 132)), (1, (188, 132), (50, 30, 140, 100)),
                                 (2, (400, 300), (0, 0, 400, 300)), (2, (400, 300), (120, 80, 330, 260)),
                                 (1, (120, 90), (0, 0, 120, 90)), (0, (20, 15), (0, 0, 20, 15))):
        calls = []
        render(img, size, region, passes, fake, None, 16, 8, lambda: calls.append(1))
        want = count_tiles([region], size, (47, 33), passes, 4 if passes else 1, 16)
        assert len(calls) == want, (passes, size, region, len(calls), want)  # the plan matches the run
    print("count_tiles ok")
except ImportError as e:
    print(f"hooks: skipped ({e.name} missing)")

try:
    import torch
    from spandrel.architectures.Compact.__arch.SRVGG import SRVGGNetCompact

    torch.manual_seed(0)
    net = SRVGGNetCompact(num_feat=8, num_conv=2, upscale=4, act_type="prelu")
    with _tf.TemporaryDirectory() as d:
        wpath = os.path.join(d, "tiny.pth")
        torch.save({"params": net.state_dict()}, wpath)
        src = os.path.join(d, "in.png")
        Image.fromarray((np.random.default_rng(6).random((40, 56, 3)) * 255).astype(np.uint8)).save(src)
        kw = dict(recipe=[(wpath, 1.0)], device_pref="cpu", tile=16)
        out = os.path.join(d, "o.tif")

        fractions = []
        enhance(src, out, "6.4", "in", 100, progress=fractions.append, **kw)  # 2 passes, several tiles
        assert len(fractions) > 10 and fractions == sorted(fractions) and abs(fractions[-1] - 1.0) < 1e-9, fractions[-3:]
        # in bands too: the fraction still runs 0 -> 1 across all of them
        fractions.clear()
        with patched(E, "STRIP_BYTES", 6000):
            enhance(src, out, "6.4", "in", 100, progress=fractions.append, mem_mb=0.2, **kw)
        assert fractions == sorted(fractions) and abs(fractions[-1] - 1.0) < 1e-9
        # no AI at all (shrinking): progress counts bands instead of tiles
        fractions.clear()
        enhance(src, out, "0.3", "in", 100, progress=fractions.append, **kw)
        assert fractions and fractions[-1] == 1.0

        # cancel part-way: InterruptedError, no output, no partial file, and an old output survives
        enhance(src, out, "1.2", "in", 100, **kw)
        before = open(out, "rb").read()
        n = []

        def cancel_after(k):
            def f():
                n.append(1)
                return len(n) > k
            return f
        for k in (0, 3):
            n.clear()
            try:
                enhance(src, out, "6.4", "in", 100, cancel=cancel_after(k), **kw)
                raise AssertionError("expected InterruptedError")
            except InterruptedError:
                pass
            assert open(out, "rb").read() == before and not [f for f in os.listdir(d) if f.endswith(".partial")]
        fresh = os.path.join(d, "fresh.tif")
        try:
            enhance(src, fresh, "6.4", "in", 100, cancel=lambda: True, **kw)
        except InterruptedError:
            pass
        assert not os.path.exists(fresh)
    print("progress/cancel ok")

    if E.mps_usable():
        assert E.pick_device("gpu").type == "mps" and E.pick_device("auto").type == "mps"
    assert E.pick_device("cpu").type == "cpu"

    # MPS reported as available but unusable (a CI virtual machine): the CPU is chosen, not a crash later
    with patched(E, "_MPS_OK", None), patched(torch.backends.mps, "is_available", lambda: True), \
            patched(torch, "zeros", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("MPS backend out of memory"))):
        assert not E.mps_usable() and E.pick_device("auto").type in ("cpu", "cuda")
        assert E._MPS_OK is False  # remembered: the probe is not repeated on every call
    E._MPS_OK = None  # the real answer is probed again on the next use
except ImportError as e:
    print(f"progress/cancel: skipped ({e.name} missing)")

# CLI: --preview-size alone, or a bad --preview, is rejected before any work
import subprocess
import sys

r = subprocess.run([sys.executable, "enhance.py", "--help"], capture_output=True, text=True,
                   cwd=os.path.dirname(os.path.abspath(__file__)))
assert r.returncode == 0 and "--preview" in r.stdout and "100%" in r.stdout, r.stderr[-300:]  # help text renders

for extra in (["--preview-size", "100x100"], ["--preview", "2,0.5"], ["--preview", "0.5,0.5", "--preview-size", "x"]):
    r = subprocess.run([sys.executable, "enhance.py", "nope.png", "--size", "5"] + extra,
                       capture_output=True, text=True, cwd=os.path.dirname(os.path.abspath(__file__)))
    assert r.returncode == 2 and "preview" in r.stderr, (extra, r.returncode, r.stderr)
for extra in (["--download-models", "bogus"], ["--device", "tpu"]):
    r = subprocess.run([sys.executable, "enhance.py", "nope.png", "--size", "5"] + extra,
                       capture_output=True, text=True, cwd=os.path.dirname(os.path.abspath(__file__)))
    assert r.returncode == 2 and "invalid choice" in r.stderr, (extra, r.returncode, r.stderr[-200:])
for extra in (["--engine", "ane", "--device", "cpu"], ["--engine", "gpu16", "--bits", "16", "-o", "x.tif"],
              ["--engine", "turbo"]):
    r = subprocess.run([sys.executable, "enhance.py", "nope.png", "--size", "5"] + extra,
                       capture_output=True, text=True, cwd=os.path.dirname(os.path.abspath(__file__)))
    assert r.returncode == 2 and "engine" in r.stderr, (extra, r.returncode, r.stderr[-200:])  # before any work
print("preview cli ok")

# ---- the machine interface the macOS app uses: --json, --info, --preview-plain, SIGTERM ------------
try:
    import json as _json
    import signal as _signal
    import tempfile as _tmp

    import numpy as np
    import torch
    from PIL import Image
    from spandrel.architectures.Compact.__arch.SRVGG import SRVGGNetCompact

    here = os.path.dirname(os.path.abspath(__file__))
    torch.manual_seed(0)
    net = SRVGGNetCompact(num_feat=8, num_conv=2, upscale=4, act_type="prelu")
    with _tmp.TemporaryDirectory() as d:
        # --info: no torch needed, says what is missing and how many bytes it is
        mdir = os.path.join(d, "models")
        r = subprocess.run([sys.executable, "enhance.py", "--info", "--models-dir", mdir], capture_output=True, text=True, cwd=here)
        info = _json.loads(r.stdout)
        assert r.returncode == 0 and info["version"] == __import__("enhance").__version__ and info["models_dir"] == mdir, r.stderr
        assert info["groups"]["photo"]["missing"] == [PHOTO_FILE] and info["groups"]["photo"]["missing_bytes"] == 67040989
        assert info["groups"]["faces"]["missing_bytes"] == 348632874 and isinstance(info["vision"], bool) and info["face_min_px"] == 32
        os.makedirs(mdir)
        open(os.path.join(mdir, PHOTO_FILE), "wb").write(b"x" * 67040989)  # right size: counts as present
        r = subprocess.run([sys.executable, "enhance.py", "--info", "--models-dir", mdir], capture_output=True, text=True, cwd=here)
        assert _json.loads(r.stdout)["groups"]["photo"]["missing"] == []

        wpath = os.path.join(d, "tiny.pth")
        torch.save({"params": net.state_dict()}, wpath)
        a, b = os.path.join(d, "a.png"), os.path.join(d, "b.png")
        rng = np.random.default_rng(8)
        Image.fromarray((rng.random((30, 40, 3)) * 255).astype(np.uint8)).save(a)
        Image.fromarray((rng.random((40, 40, 3)) * 255).astype(np.uint8)).save(b)
        base = ["--weights", wpath, "--device", "cpu", "--tile", "16", "--size", "1.2", "--unit", "in", "--dpi", "100", "--json"]

        def events(proc_out):
            return [_json.loads(line) for line in proc_out.splitlines()]  # every stdout line must be JSON
        out_dir = os.path.join(d, "out") + "/"
        r = subprocess.run([sys.executable, "enhance.py", a, b, *base, "-o", out_dir], capture_output=True, text=True, cwd=here)
        ev = events(r.stdout)
        assert r.returncode == 0, r.stderr[-300:]
        assert [e["i"] for e in ev if e["event"] == "job"] == [1, 2] and ev[-1]["event"] == "done" and len(ev[-1]["outputs"]) == 2
        fr = [e["fraction"] for e in ev if e["event"] == "progress"]
        assert len(fr) > 4 and all(0 <= f <= 1 for f in fr) and fr[-1] == 1.0
        segment, segments = [], []  # the fraction runs forward within a job and starts again with the next one
        for e in ev:
            if e["event"] == "job" and segment:
                segments.append(segment)
                segment = []
            elif e["event"] == "progress":
                segment.append(e["fraction"])
        segments.append(segment)
        assert len(segments) == 2 and all(sg == sorted(sg) and sg[-1] == 1.0 for sg in segments), segments
        # a failure is an event too, not just stderr text, and the exit code says so
        r = subprocess.run([sys.executable, "enhance.py", a, "--weights", os.path.join(d, "missing.pth"), "--device", "cpu",
                            "--size", "1.2", "--unit", "in", "--dpi", "100", "--json", "-o", os.path.join(d, "x.png")],
                           capture_output=True, text=True, cwd=here)
        ev = events(r.stdout)
        assert r.returncode == 1 and ev[-1]["event"] == "error" and ev[-1]["message"], (r.stdout, r.stderr[-200:])
        # --preview-plain: the same area, enlarged the plain way, the same size as the AI preview
        pv, plain = os.path.join(d, "pv.png"), os.path.join(d, "plain.png")
        r = subprocess.run([sys.executable, "enhance.py", a, *base, "--preview", "0.5,0.5", "--preview-size", "60x50", "-o", pv,
                            "--preview-plain", plain], capture_output=True, text=True, cwd=here)
        assert r.returncode == 0, r.stderr[-300:]
        ai, pl = Image.open(pv), Image.open(plain)
        assert ai.size == pl.size == (60, 50) and np.abs(np.asarray(ai, int) - np.asarray(pl, int)).mean() > 1
        r = subprocess.run([sys.executable, "enhance.py", a, b, *base, "--preview-plain", plain, "-o", out_dir], capture_output=True,
                           text=True, cwd=here)
        assert r.returncode == 2 and "preview-plain" in r.stderr  # needs --preview and one image
        # SIGTERM is a clean cancel: a "cancelled" event, exit 130, nothing half-written
        big = os.path.join(d, "big")
        os.makedirs(big)
        proc = subprocess.Popen([sys.executable, "enhance.py", a, "--weights", wpath, "--device", "cpu", "--tile", "16", "--size", "40",
                                 "--unit", "in", "--dpi", "100", "--json", "-o", os.path.join(big, "big.tif")],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, cwd=here)
        seen = []
        for line in proc.stdout:
            seen.append(_json.loads(line))
            if seen[-1]["event"] == "progress":
                proc.send_signal(_signal.SIGTERM)
                break
        rest = proc.stdout.read()
        proc.wait(timeout=60)
        seen += [_json.loads(line) for line in rest.splitlines()]
        assert proc.returncode == 130 and seen[-1]["event"] == "cancelled", (proc.returncode, seen[-2:])
        assert os.listdir(big) == [] or all(f.startswith(".") and not f.endswith(".partial") for f in os.listdir(big)), os.listdir(big)
    print("engine json interface ok")
except ImportError as e:
    print(f"engine json interface: skipped ({e.name} missing)")

# EXIF orientation + ICC survive (needs Pillow; shrinking path, so no weights/AI)
try:
    import os
    import tempfile

    from PIL import Image, ImageCms

    from enhance import enhance

    with tempfile.TemporaryDirectory() as d:
        src, dst = os.path.join(d, "in.jpg"), os.path.join(d, "out.png")
        exif = Image.Exif()
        exif[0x0112] = 6  # "rotate 90 CW to display": stored landscape, shown portrait
        icc = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()
        Image.new("RGB", (200, 100), "white").save(src, exif=exif.tobytes(), icc_profile=icc)
        enhance(src, dst, "2", "cm", 100, [("unused.pth", 1.0)], "cpu", 256)
        out = Image.open(dst)
        assert out.height > out.width, f"orientation ignored: {out.size}"
        assert out.info.get("icc_profile") == icc, "ICC profile lost"
        assert round(out.info["dpi"][0]) == 100
    print("orientation/icc/dpi ok")
except ImportError:
    print("orientation/icc: skipped (no Pillow)")

print("ok")
