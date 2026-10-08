"""Run: python3 test_faces.py  (face recovery: geometry, pasting, the pipeline with stand-in detector and
restorer. With MAC_IMAGE_ENHANCER_FACE_SAMPLE=portrait.jpg, macOS and the face weights it also runs the real thing.)"""
import os
import tempfile

import numpy as np
from PIL import Image

import enhance as E
import faces as F
import weights as W

rng = np.random.default_rng(0)

# ---- geometry ------------------------------------------------------------------------------------------
pts = np.array([[10.0, 20.0], [50.0, 25.0], [30.0, 70.0]])


def known(scale, deg, tx, ty):
    a = np.radians(deg)
    return np.array([[scale * np.cos(a), -scale * np.sin(a), tx], [scale * np.sin(a), scale * np.cos(a), ty]])


for scale, deg, tx, ty in ((1.0, 0, 0, 0), (2.5, 30, 100, -40), (0.4, -75, 7, 8), (3.0, 179, -5, 5)):
    m = known(scale, deg, tx, ty)
    got = F.similarity_transform(pts, F.apply_affine(m, pts))
    assert np.allclose(got, m, atol=1e-9), (scale, deg, got, m)  # recovers a similarity exactly
    assert np.isclose(F.uniform_scale(got), scale)
# noisy points: the fit stays close, and a mirrored set is NOT answered with a reflection
noisy = F.apply_affine(known(2, 20, 10, 10), pts) + rng.normal(0, 0.3, pts.shape)
assert np.abs(F.similarity_transform(pts, noisy) - known(2, 20, 10, 10)).max() < 0.5
mirrored = pts * [-1, 1]
assert np.linalg.det(F.similarity_transform(mirrored, pts)[:, :2]) > 0  # always a rotation

m = known(1.7, 33, 12, -9)
assert np.allclose(F.apply_affine(F.invert_affine(m), F.apply_affine(m, pts)), pts)
m2 = known(0.6, -10, 3, 4)
assert np.allclose(F.apply_affine(F.compose(m2, m), pts), F.apply_affine(m2, F.apply_affine(m, pts)))  # second after first
assert F.affine_box(known(2, 0, 5, 7), 10, 4) == (5, 7, 25, 15)
x0, y0, x1, y1 = F.affine_box(known(1, 90, 0, 0), 10, 4)  # a 90 degree turn swaps the box's sides
assert np.allclose([x1 - x0, y1 - y0], [4, 10])

# the template, as facexlib has it: 5 points, and our 3 are its eyes and the middle of its mouth corners
assert F.FFHQ_TEMPLATE5.shape == (5, 2) and np.allclose(F.FFHQ_TEMPLATE[2], F.FFHQ_TEMPLATE5[3:].mean(0))
assert np.allclose(F.FFHQ_TEMPLATE[:2], F.FFHQ_TEMPLATE5[:2])

# the mask: 1 in the middle of the face, 0 at the edges and corners, smooth, and the same shape at any size
mask = F.face_mask()
assert mask.shape == (512, 512) and mask.dtype == np.float32 and 0 <= mask.min() and mask.max() <= 1
assert mask[285, 256] == 1.0 and mask[0, 0] == 0 and mask[511, 511] == 0 and mask[0, 256] == 0
assert (np.diff(mask[285, 256:]) <= 1e-6).all()  # only falls as it goes out from the centre
assert np.abs(np.diff(mask, axis=1)).max() < 0.05  # no hard edge anywhere
big = F.face_mask(2048)
assert np.abs(big[::4, ::4] - mask).max() < 0.02  # the same oval at 4x
print("geometry ok")

# ---- landmarks and detections ----------------------------------------------------------------------------
regions = {"leftEye": np.array([[0, 0], [10, 0], [5, 2.0]]), "rightEye": np.array([[40, 0], [50, 0], [45, 2.0]]),
           "outerLips": np.array([[10, 40.0], [30, 38], [50, 40], [30, 46]])}
three = F.landmarks3(regions)
assert np.allclose(three[0], [5, 2 / 3]) and np.allclose(three[1], [45, 2 / 3])  # no pupils given: the outline's mean
assert np.allclose(three[2], [30, 41])
regions["leftPupil"], regions["rightPupil"] = np.array([[6.0, 1.0]]), np.array([[44.0, 1.5]])
assert np.allclose(F.landmarks3(regions)[:2], [[6, 1], [44, 1.5]])  # pupils win when there are
swap = dict(regions, leftPupil=regions["rightPupil"], rightPupil=regions["leftPupil"])
assert F.landmarks3(swap)[0][0] < F.landmarks3(swap)[1][0]  # always the picture's left eye first

box = (84, 152, 406, 475)
assert F.plausible_layout(F.FFHQ_TEMPLATE, box)
bad = {"eyes far too close": F.FFHQ_TEMPLATE * [0.3, 1] + [180, 0], "mouth above the eyes": F.FFHQ_TEMPLATE[[0, 1, 2]] * [1, -1] + [0, 600],
       "face turned on its side": F.apply_affine(known(1, 90, 0, 0), F.FFHQ_TEMPLATE),
       "eyes huge for the box": F.FFHQ_TEMPLATE}
for name, p in bad.items():
    assert not F.plausible_layout(p, (200, 200, 230, 230) if name == "eyes huge for the box" else box), name

assert F.iou((0, 0, 10, 10), (0, 0, 10, 10)) == 1 and F.iou((0, 0, 10, 10), (20, 20, 30, 30)) == 0
assert abs(F.iou((0, 0, 10, 10), (5, 0, 15, 10)) - 1 / 3) < 1e-9
a = F.Face((100, 100, 200, 200), pts, 0.9)
dup = F.Face((110, 105, 205, 205), pts, 0.7)  # the same face, reported twice
inside = F.Face((140, 140, 160, 160), pts, 0.99)  # a small detection inside the big one
other = F.Face((400, 100, 480, 180), pts, 0.8)
kept = F.drop_overlaps([dup, a, other, inside])
assert a in kept and other in kept and dup not in kept
assert inside not in kept  # its centre lies inside the more confident box
assert [f.box[2] - f.box[0] for f in kept] == sorted((f.box[2] - f.box[0] for f in kept), reverse=True)  # biggest first
print("landmarks and detections ok")

# ---- keeping the picture's colours -------------------------------------------------------------------------
# skin-like colours: mild chroma (strong colours clip when converted back, which would move the luminance)
orig = Image.fromarray(np.clip(rng.integers(100, 150, (64, 64, 1)) + np.array([30, 10, -15]) + rng.integers(-6, 6, (64, 64, 3)),
                               0, 255).astype(np.uint8))
gray = np.repeat(rng.integers(90, 170, (64, 64, 1), dtype=np.uint8), 3, 2)
assert np.array_equal(F.keep_chroma(gray, orig, 0.0), gray)  # nothing kept: the restorer's own colours
full = F.keep_chroma(gray, orig, 1.0)
ycc_full, ycc_orig, ycc_gray = (np.asarray(Image.fromarray(a).convert("YCbCr")).astype(int) for a in (full, np.asarray(orig), gray))
assert np.abs(ycc_full[..., 0] - ycc_gray[..., 0]).max() <= 2  # the detail (luminance) comes from the restorer
assert np.abs(ycc_full[..., 1:] - ycc_orig[..., 1:]).max() <= 2  # the colour comes from the picture
assert np.abs(F.keep_chroma(gray, orig, 0.5).astype(int) - (full.astype(int) + gray) / 2).max() < 40  # in between
print("colour keeping ok")


# ---- pasting -----------------------------------------------------------------------------------------------
def asset(to_print, color=(250, 40, 40), size=64, mask_fn=None):
    img = Image.new("RGB", (size, size), color)
    mk = np.ones((size, size), np.float32) if mask_fn is None else mask_fn(size)
    return F.Asset(img, Image.fromarray((mk * 255 + 0.5).astype(np.uint8)), to_print, F.affine_box(to_print, size, size))


canvas = rng.integers(0, 255, (120, 200, 3), dtype=np.uint8)
a1 = asset(known(1.0, 0, 50, 30))  # a 64 px face placed at (50, 30)
out = F.paste(canvas, (0, 0), [a1])
assert out is not canvas and not np.array_equal(out, canvas) and (canvas == canvas.copy()).all()  # input untouched
assert (out[40:80, 60:100] == (250, 40, 40)).all()  # inside the face: its colour
assert np.array_equal(out[:25], canvas[:25]) and np.array_equal(out[:, 130:], canvas[:, 130:])  # far away: unchanged
assert F.paste(canvas, (0, 0), [a1], 0.0).tolist() == canvas.tolist()  # strength 0 changes nothing
half = F.paste(canvas, (0, 0), [a1], 0.5)[50, 80].astype(int)
assert np.abs(half - (canvas[50, 80].astype(int) + (250, 40, 40)) / 2).max() <= 1  # strength 0.5: halfway
assert F.paste(canvas, (0, 0), [asset(known(1, 0, 500, 500))]) is canvas  # a face off the band: the same array, no copy
# a band whose origin is not (0, 0): the same pixels as the whole canvas
assert np.array_equal(F.paste(canvas[20:100, 40:160], (40, 20), [a1]), out[20:100, 40:160])
# 16-bit
c16 = (canvas.astype(np.uint16) * 257)
o16 = F.paste(c16, (0, 0), [a1])
assert o16.dtype == np.uint16 and (o16[40:80, 60:100] == (250 * 257, 40 * 257, 40 * 257)).all()

# placement: a bright blob at (20, 30) of a 64 px face, shown through scale 2.5, a turn of 20 degrees and an offset,
# must land where the same map takes (20, 30)
yy, xx = np.mgrid[0:64, 0:64]
blob = (255 * np.exp(-((xx + 0.5 - 20) ** 2 + (yy + 0.5 - 30) ** 2) / 8)).astype(np.uint8)
blob_img = Image.fromarray(np.stack([blob] * 3, -1))
m = known(2.5, 20, 60, 25)
placed = F.Asset(blob_img, Image.fromarray(np.full((64, 64), 255, np.uint8)), m, F.affine_box(m, 64, 64))
res = F.paste(np.zeros((200, 260, 3), np.uint8), (0, 0), [placed])[..., 0].astype(float)
cy, cx = [(res * (g + 0.5)).sum() / res.sum() for g in np.mgrid[0:200, 0:260]]  # + 0.5: pixel centres, in the maps' coordinates
want = F.apply_affine(m, [(20, 30)])[0]
assert abs(cx - want[0]) < 0.3 and abs(cy - want[1]) < 0.3, ((cx, cy), want)  # sub-pixel: no half-pixel slip

# pasting into pieces == pasting into the whole (the property the bands and the previews rely on)
m = known(1.3, 12, 20, 15)
a2 = asset(m, (30, 200, 90), mask_fn=F.face_mask)
whole = F.paste(canvas, (0, 0), [a1, a2], 0.8)
for cuts in ((0, 120), (0, 37, 120), (0, 1, 2, 60, 119, 120)):
    pieces = [F.paste(canvas[y0:y1], (0, y0), [a1, a2], 0.8) for y0, y1 in zip(cuts, cuts[1:])]
    assert np.abs(np.concatenate(pieces).astype(int) - whole).max() <= 1, cuts
print("pasting ok")


# ---- building assets with stand-ins ----------------------------------------------------------------------
class FakeRestorer:
    def __init__(self):
        self.calls = 0

    def __call__(self, crop):
        self.calls += 1
        return np.full((512, 512, 3), 180, np.uint8)


def fake_face(cx, cy, eye=20):
    return F.Face((cx - 2 * eye, cy - 2 * eye, cx + 2 * eye, cy + 2 * eye),
                  np.array([[cx - eye / 2, cy - eye / 3], [cx + eye / 2, cy - eye / 3], [cx, cy + eye * 0.7]]), 0.99)


pic = Image.fromarray(rng.integers(0, 255, (200, 300, 3), dtype=np.uint8))
faces2 = [fake_face(60, 80), fake_face(240, 120)]
r = FakeRestorer()
got = F.build_assets(pic, faces2, r, (600, 400), keep_color=0.0)
assert len(got) == 2 and r.calls == 2 and all(a.image.size == (512, 512) for a in got)  # not enlarged: out per crop <= 1.25
r = FakeRestorer()
only_left = F.build_assets(pic, faces2, r, (600, 400), region=(0, 0, 200, 400), keep_color=0.0)
assert len(only_left) == 1 and r.calls == 1  # a region that shows one face restores one face
assert F.build_assets(pic, faces2, FakeRestorer(), (600, 400), region=(280, 0, 300, 20)) == []
enlarged = []
got = F.build_assets(pic, faces2[:1], FakeRestorer(), (6000, 4000), keep_color=0.0,
                     enlarge=lambda a: enlarged.append(a.shape) or np.repeat(np.repeat(a, 4, 0), 4, 1))
assert enlarged == [(512, 512, 3)] and got[0].image.size == (2048, 2048) and got[0].mask.size == (2048, 2048)  # big print: x4
small = F.build_assets(pic, faces2[:1], FakeRestorer(), (300, 200), keep_color=0.0, enlarge=lambda a: 1 / 0)  # 1:1 print: not asked
assert small[0].image.size == (512, 512)
try:
    F.build_assets(pic, faces2, FakeRestorer(), (600, 400), cancel=lambda: True)
    raise AssertionError("expected InterruptedError")
except InterruptedError:
    pass
# the enlarged crop lands exactly where the plain one would: same box on the print
plain = F.build_assets(pic, faces2[:1], FakeRestorer(), (6000, 4000), keep_color=0.0)[0]
assert np.allclose(plain.box, got[0].box, atol=1e-6)
print("assets ok")

# ---- the pipeline, with stand-in detector and restorer -----------------------------------------------------
try:
    import torch
    from spandrel.architectures.Compact.__arch.SRVGG import SRVGGNetCompact
except ImportError as e:
    print(f"pipeline: skipped ({e.name} missing)")
    print("ok")
    raise SystemExit(0)

import contextlib


@contextlib.contextmanager
def patched(obj, name, value):
    old = getattr(obj, name)
    setattr(obj, name, value)
    try:
        yield
    finally:
        setattr(obj, name, old)


torch.manual_seed(0)
net = SRVGGNetCompact(num_feat=8, num_conv=2, upscale=4, act_type="prelu")
with tempfile.TemporaryDirectory() as d:
    wpath = os.path.join(d, "tiny.pth")
    torch.save({"params": net.state_dict()}, wpath)
    mdir = os.path.join(d, "models")
    os.makedirs(mdir)
    with open(os.path.join(mdir, W.GFPGAN_FILE), "wb") as f:
        f.truncate(W.FILES[W.GFPGAN_FILE][2])  # a sparse file of the right size: no disk is used
    src = os.path.join(d, "in.png")
    Image.fromarray(rng.integers(0, 255, (60, 90, 3), dtype=np.uint8)).save(src)
    detected = [fake_face(30, 25, 10), fake_face(65, 38, 10)]  # 40 px wide faces in a 90 x 60 picture (the default minimum is 32)
    seen = {"restored": 0}

    class Stand(F.Restorer):
        def __init__(self, path, device):
            pass

        def __call__(self, crop):
            seen["restored"] += 1
            return np.full((512, 512, 3), (230, 60, 60), np.uint8)

    kw = dict(size="6.4", unit="in", dpi=100, recipe=[(wpath, 1.0)], device_pref="cpu", tile=16, models_dir=mdir)  # 90 -> 640 px
    out_plain, out_faces = os.path.join(d, "plain.tif"), os.path.join(d, "faces.tif")
    import tifffile
    with patched(F, "detect_faces", lambda img: detected), patched(F, "Restorer", Stand):
        E.enhance(src, out_plain, **kw)
        E.enhance(src, out_faces, faces=True, **kw, face_strength=1.0, face_color=0.0)
        plain, with_faces = tifffile.imread(out_plain).astype(int), tifffile.imread(out_faces).astype(int)
        assert seen["restored"] == 2
        changed = np.abs(plain - with_faces).max(axis=2) > 0
        ys, xs = np.where(changed)
        assert changed.any() and 0 < changed.mean() < 0.4  # faces changed, the rest of the print did not
        # each face's patch is the restorer's red (strength 1, colour not kept) where the mask is full
        for fc in detected:  # the middle of the mask (256, 285 in the crop), carried back to the print
            m = F.similarity_transform(fc.points, F.FFHQ_TEMPLATE)
            sx, sy = F.apply_affine(F.invert_affine(m), [(256, 285)])[0] * [640 / 90, plain.shape[0] / 60]
            assert abs(with_faces[int(sy), int(sx)] - (230, 60, 60)).max() <= 2, with_faces[int(sy), int(sx)]

        # --strength 0 is the plain print
        E.enhance(src, out_faces, faces=True, face_strength=0.0, **kw)
        assert np.array_equal(tifffile.imread(out_faces).astype(int), plain)

        # many bands == one band, with faces crossing the seams; and a preview == that crop of the print
        E.enhance(src, out_faces, faces=True, face_color=0.0, **kw)
        one = tifffile.imread(out_faces).astype(int)
        with patched(E, "STRIP_BYTES", 6000):
            E.enhance(src, out_faces, faces=True, face_color=0.0, mem_mb=0.2, **kw)
        assert np.abs(tifffile.imread(out_faces).astype(int) - one).max() <= 1
        th = one.shape[0]
        for center in ((0.33, 0.42), (0.72, 0.62), (0.5, 0.95)):
            before = seen["restored"]
            pv = os.path.join(d, "pv.png")
            E.enhance(src, pv, faces=True, face_color=0.0, preview=(center, (200, 150)), **kw)
            x0, y0, x1, y1 = E.preview_region(640, th, center, (200, 150))
            assert np.abs(np.asarray(Image.open(pv)).astype(int) - one[y0:y1, x0:x1]).max() <= 1, center
            assert seen["restored"] - before <= 2

        # not an enlargement: nothing to restore, and it says so
        seen["restored"] = 0
        E.enhance(src, os.path.join(d, "small.png"), faces=True, **{**kw, "size": "0.3"})
        assert seen["restored"] == 0

        # cancel while the faces are being restored: no output, no partial file
        gone = os.path.join(d, "never.tif")
        try:
            E.enhance(src, gone, faces=True, cancel=lambda: True, **kw)
            raise AssertionError("expected InterruptedError")
        except InterruptedError:
            pass
        assert not os.path.exists(gone) and not [f for f in os.listdir(d) if f.endswith(".partial")]

        # a face too small for the minimum is left alone, and --face-min-size changes that
        seen["restored"] = 0
        detected[:] = [fake_face(30, 25, 3)]  # a face 12 px wide: under the default minimum, over --face-min-size 8
        E.enhance(src, out_faces, faces=True, **kw)
        assert seen["restored"] == 0
        E.enhance(src, out_faces, faces=True, face_min=8, **{**kw, "size": "6.4"})
        assert seen["restored"] == 1

    # without the face weights: a clear message, before any work is done
    empty = os.path.join(d, "empty")
    try:
        E.enhance(src, os.path.join(d, "x.png"), faces=True, **{**kw, "models_dir": empty})
        raise AssertionError("expected SystemExit")
    except SystemExit as e:
        assert "--download-models faces" in str(e) and "NOTICE" in str(e)
    # without Apple Vision: a clear message too
    def no_vision(img):
        raise F.FaceRecoveryUnavailable("face recovery needs Apple Vision: pip install pyobjc-framework-Vision (macOS only)")
    with patched(F, "detect_faces", no_vision):
        try:
            E.enhance(src, os.path.join(d, "x.png"), faces=True, **kw)
            raise AssertionError("expected SystemExit")
        except SystemExit as e:
            assert "pyobjc-framework-Vision" in str(e)

# option checks and the job fingerprint
assert E.check_face_options(True, 1.0, 1.0) is None and E.check_face_options(True, 0.0, 0.0, 8) is None
assert "within 0..1" in E.check_face_options(True, 1.5, 1.0) and "within 0..1" in E.check_face_options(True, 1.0, -0.1)
assert "at least 8" in E.check_face_options(True, 1.0, 1.0, 4)
with tempfile.TemporaryDirectory() as d:
    probe = os.path.join(d, "x.png")
    open(probe, "wb").write(b"x")
    o = dict(size="5", unit="cm", dpi=100, recipe=[("w.pth", 1.0)], tile=16, bits=8, cmyk_profile=None, intent="relative",
             compress=False)
    fp = lambda **kw: E.job_fingerprint(E.job_params(probe, {**o, **kw}))
    assert len({fp(), fp(faces=True), fp(faces=True, face_strength=0.5), fp(faces=True, face_color=0.0),
                fp(faces=True, face_min=64)}) == 5
    assert fp(face_strength=0.5) == fp()  # the face options only matter when faces are on
print("pipeline with stand-ins ok")

# ---- the real thing, when there is something to run it on ---------------------------------------------------
sample = os.environ.get("MAC_IMAGE_ENHANCER_FACE_SAMPLE")
real_ok = (sample and os.path.exists(sample) and not W.missing(W.default_models_dir(), [W.GFPGAN_FILE])
           and not W.missing(W.default_models_dir(), [W.PHOTO_FILE]))
if real_ok:
    try:
        import Vision  # noqa: F401
    except ImportError:
        real_ok = False
if not real_ok:
    print("real detector and GFPGAN: skipped (set MAC_IMAGE_ENHANCER_FACE_SAMPLE=portrait.jpg; needs macOS, "
          "pyobjc-framework-Vision and both model files)")
else:
    img = Image.open(sample).convert("RGB")
    found = F.detect_faces(img)
    assert found and all(F.plausible_layout(f.points, f.box) for f in found), found
    assert all(np.array_equal(a.points, b.points) for a, b in zip(found, F.detect_faces(img)))  # detection repeats
    crop, m = F.align(img, found[0])
    assert np.abs(F.apply_affine(m, found[0].points) - F.FFHQ_TEMPLATE).max() < 4  # aligned onto the template
    rs = F.Restorer(os.path.join(W.default_models_dir(), W.GFPGAN_FILE), E.pick_device("auto"))
    one, two = rs(crop), rs(crop)
    assert np.array_equal(one, two), "GFPGAN must give the same face every time (randomize_noise=False)"
    with tempfile.TemporaryDirectory() as d:
        kw = dict(size="30", unit="cm", dpi=150, recipe=E.model_recipe("photo"), device_pref="auto", tile=256, faces=True)
        full, pv = os.path.join(d, "full.png"), os.path.join(d, "pv.png")
        E.enhance(sample, full, **kw)
        E.enhance(sample, os.path.join(d, "again.png"), **kw)
        assert np.array_equal(np.asarray(Image.open(full)), np.asarray(Image.open(os.path.join(d, "again.png")))), "not reproducible"
        fx, fy = (found[0].box[0] + found[0].box[2]) / 2 / img.width, (found[0].box[1] + found[0].box[3]) / 2 / img.height
        E.enhance(sample, pv, preview=((fx, fy), (320, 240)), **kw)
        a = np.asarray(Image.open(full)).astype(int)
        x0, y0, x1, y1 = E.preview_region(a.shape[1], a.shape[0], (fx, fy), (320, 240))
        assert np.abs(np.asarray(Image.open(pv)).astype(int) - a[y0:y1, x0:x1]).max() <= 1
    print(f"real detector and GFPGAN ok ({len(found)} face(s) in {os.path.basename(sample)})")
print("ok")
