"""Face recovery: find faces (Apple Vision), restore each with GFPGAN, paste it back into the print.

The plan, in the order things happen in enhance():
  1. detect_faces() on the source picture: a box and five landmarks per face (eyes, nose, mouth).
  2. build_assets(): each face is warped to an aligned 512x512 crop, restored by GFPGAN, and, when the
     print shows it larger than the crop, enlarged by the same tile engine that enlarges the picture.
  3. paste(): after a band of the print is rendered, every face that touches it is blended in through a
     soft mask. This step is per pixel and needs nothing but the finished face, so a preview of one
     area is identical to that area of the full print, however the print is cut into bands.

Alignment follows the FFHQ convention GFPGAN was trained with: a similarity transform (rotation, uniform
scale, translation) maps the five landmarks onto the template of facexlib (MIT, github.com/xinntao/facexlib).
Pillow's Image.transform works in continuous pixel coordinates with pixel centres at +0.5, the same as
Vision's, so no half-pixel correction is needed anywhere.

GFPGAN, its weights and the data they were trained on carry licence conditions: see NOTICE.
"""
import io
import sys

import numpy as np

FACE_SIZE = 512
# The FFHQ landmarks in a 512 x 512 crop, from facexlib: left eye, right eye, nose tip, left and right mouth
# corner. Only the eyes and the middle of the mouth are used: Vision defines the nose tip and the mouth
# corners differently from the detector the template came from (measured: 17-20 px apart on an aligned
# face), while pupils and the lips' centre agree to a few px. facexlib offers the same 3-point variant.
FFHQ_TEMPLATE5 = np.array([[192.98138, 239.94708], [318.90277, 240.1936], [256.63416, 314.01935],
                           [201.26117, 371.41043], [313.08905, 371.15118]])
FFHQ_TEMPLATE = np.array([FFHQ_TEMPLATE5[0], FFHQ_TEMPLATE5[1], FFHQ_TEMPLATE5[3:].mean(0)])
BORDER_GRAY = (135, 133, 132)  # what lies outside the picture when a face is warped near its edge
MIN_CONFIDENCE = 0.5
MIN_DETECT_PX = 8  # smaller boxes are noise, not faces
# A face narrower than this in the source is not restored by default. Measured against ground truth: at 53 px
# GFPGAN's result is sharper and still recognisably the same person, at 35 px it is plausible, at 26 px it
# is a different, younger-looking face, and at 17 px everything is broken. A clean but wrong face is worse
# than an obviously damaged one, so the default stays where the results can be trusted.
MIN_FACE_PX = 32
DETECT_MAX_SIDE = 2048  # Vision gets a copy no larger than this; coordinates are scaled back


class FaceRecoveryUnavailable(RuntimeError):
    """Apple Vision (pyobjc-framework-Vision) is not available here."""


# ---- geometry (pure numpy) ------------------------------------------------------------------------

def similarity_transform(src, dst):
    """Least-squares similarity (rotation, uniform scale, translation) taking points `src` to `dst`
    (Umeyama's method). Returns the 2x3 matrix M with dst ~ src @ M[:, :2].T + M[:, 2]."""
    src, dst = np.asarray(src, float), np.asarray(dst, float)
    mu_s, mu_d = src.mean(0), dst.mean(0)
    s, d = src - mu_s, dst - mu_d
    cov = d.T @ s / len(src)
    u, sig, vt = np.linalg.svd(cov)
    fix = np.eye(2)
    if np.linalg.det(u) * np.linalg.det(vt) < 0:  # a reflection is not a rotation
        fix[1, 1] = -1
    rot = u @ fix @ vt
    scale = (sig * np.diag(fix)).sum() / (s ** 2).sum(1).mean()
    out = np.zeros((2, 3))
    out[:, :2] = scale * rot
    out[:, 2] = mu_d - scale * rot @ mu_s
    return out


def apply_affine(m, pts):
    return np.asarray(pts, float) @ m[:, :2].T + m[:, 2]


def invert_affine(m):
    lin = np.linalg.inv(m[:, :2])
    out = np.zeros((2, 3))
    out[:, :2] = lin
    out[:, 2] = -lin @ m[:, 2]
    return out


def compose(second, first):
    """The affine map that does `first`, then `second` (both 2x3)."""
    out = np.zeros((2, 3))
    out[:, :2] = second[:, :2] @ first[:, :2]
    out[:, 2] = second[:, :2] @ first[:, 2] + second[:, 2]
    return out


def uniform_scale(m):
    """How much the map enlarges lengths on average (exact for a similarity)."""
    return float(np.sqrt(abs(np.linalg.det(m[:, :2]))))


def affine_box(m, w, h):
    """Bounding box (x0, y0, x1, y1) of the w x h rectangle after map m."""
    c = apply_affine(m, [(0, 0), (w, 0), (0, h), (w, h)])
    return c[:, 0].min(), c[:, 1].min(), c[:, 0].max(), c[:, 1].max()


def face_mask(size=FACE_SIZE, feather=0.4):
    """Soft oval over the face part of an aligned crop, float32 0..1: 1 in the middle, falling to 0
    at the edge. Hair, neck and background keep the picture's own pixels."""
    yy, xx = np.mgrid[0:size, 0:size].astype(np.float32) + 0.5
    k = size / FACE_SIZE
    r = np.sqrt(((xx - 256 * k) / (188 * k)) ** 2 + ((yy - 285 * k) / (228 * k)) ** 2)
    t = np.clip((1 - r) / feather, 0, 1)
    return (t * t * (3 - 2 * t)).astype(np.float32)  # smoothstep


def landmarks3(regions):
    """The three landmarks used for alignment from named landmark regions (each an array of x, y with
    the origin at the TOP left): the two pupils and the middle of the outer lips, left to right as in
    the picture. A pupil is the single point Vision gives when it has one, else the eye outline's mean."""
    eyes = []
    for pupil, outline in (("leftPupil", "leftEye"), ("rightPupil", "rightEye")):
        p = regions.get(pupil)
        eyes.append(np.asarray(p)[0] if p is not None and len(p) else np.mean(regions[outline], 0))
    eyes.sort(key=lambda q: q[0])
    return np.array([eyes[0], eyes[1], np.mean(regions["outerLips"], 0)], float)


# ---- finding faces (Apple Vision) ---------------------------------------------------------------------

class Face:
    def __init__(self, box, points, confidence):
        self.box, self.points, self.confidence = box, points, confidence  # source px; points: 3x2

    def __repr__(self):
        x0, y0, x1, y1 = (round(v) for v in self.box)
        return f"Face(box=({x0}, {y0}, {x1}, {y1}), confidence={self.confidence:.2f})"


def plausible_layout(points, box):
    """Does a detection's layout look like a human face? Vision gave confidence 1.0 to an 86 px 'face' on a
    dark jacket in a badly degraded picture, but its landmarks were out of proportion. A real face has the
    eyes about 0.4 of the face box apart (FFHQ: 126 of a 322 px box) and the mouth below them by about
    1.04 eye distances (131 / 126); this allows a wide margin around both for pose and expression."""
    left, right, mouth = points
    eye_dist = np.hypot(*(right - left))
    width = box[2] - box[0]
    if eye_dist <= 0 or width <= 0:
        return False
    tilt = abs(np.degrees(np.arctan2(right[1] - left[1], right[0] - left[0])))
    down = (mouth[1] - (left[1] + right[1]) / 2) / eye_dist  # mouth below the eyes, in eye distances
    return 0.28 <= eye_dist / width <= 0.65 and 0.65 <= down <= 1.6 and tilt <= 75


def iou(a, b):
    """Intersection over union of two boxes (x0, y0, x1, y1)."""
    w = min(a[2], b[2]) - max(a[0], b[0])
    h = min(a[3], b[3]) - max(a[1], b[1])
    if w <= 0 or h <= 0:
        return 0.0
    inter = w * h
    return inter / ((a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter)


def drop_overlaps(faces, threshold=0.3):
    """Remove duplicate detections. Of two boxes that overlap (IoU over `threshold`) the more confident
    stays; and a face never contains another whole face, so a smaller box whose centre lies inside a
    larger one goes, whatever its confidence. (Vision reported one small face twice in testing, which
    pasted a second, offset face over the first.) Biggest first."""
    kept = []
    for f in sorted(faces, key=lambda f: (-f.confidence, -(f.box[2] - f.box[0]))):
        if not any(iou(f.box, k.box) > threshold for k in kept):
            kept.append(f)

    def nested(f):
        cx, cy = (f.box[0] + f.box[2]) / 2, (f.box[1] + f.box[3]) / 2
        return any(g is not f and g.box[2] - g.box[0] > f.box[2] - f.box[0]
                   and g.box[0] <= cx <= g.box[2] and g.box[1] <= cy <= g.box[3] for g in kept)
    return sorted((f for f in kept if not nested(f)), key=lambda f: -(f.box[2] - f.box[0]))


def detect_faces(img):
    """Faces in a PIL RGB picture, biggest first. Needs macOS with pyobjc-framework-Vision."""
    try:
        import Foundation
        import Vision
    except ImportError as e:
        raise FaceRecoveryUnavailable("face recovery needs Apple Vision: pip install pyobjc-framework-Vision "
                                      "(macOS only)") from e
    w, h = img.size
    k = min(1.0, DETECT_MAX_SIDE / max(w, h))
    small = img if k == 1.0 else img.resize((round(w * k), round(h * k)))
    buf = io.BytesIO()
    small.save(buf, "PNG", compress_level=1)
    raw = buf.getvalue()
    handler = Vision.VNImageRequestHandler.alloc().initWithData_options_(
        Foundation.NSData.dataWithBytes_length_(raw, len(raw)), {})
    req = Vision.VNDetectFaceLandmarksRequest.alloc().init()
    ok, err = handler.performRequests_error_([req], None)
    if not ok:
        raise RuntimeError(f"Apple Vision failed: {err}")
    sw, sh = small.size
    faces = []
    for obs in req.results() or []:
        lm = obs.landmarks()
        if lm is None or obs.confidence() < MIN_CONFIDENCE:
            continue
        regions = {}
        for name in ("leftEye", "rightEye", "leftPupil", "rightPupil", "outerLips"):
            region = getattr(lm, name)()
            if region is None or region.pointCount() < 1:
                if name in ("leftPupil", "rightPupil"):
                    continue  # optional: landmarks3 falls back to the eye outline
                break
            raw_pts = region.pointsInImageOfSize_((sw, sh))  # a bare C array: it must be indexed, never iterated
            pts = np.array([(float(raw_pts[i][0]), float(raw_pts[i][1])) for i in range(region.pointCount())])
            pts[:, 1] = sh - pts[:, 1]  # Vision's origin is bottom left
            regions[name] = pts / k
        else:
            bb = obs.boundingBox()
            box = (bb.origin.x * sw / k, (1 - bb.origin.y - bb.size.height) * sh / k,
                   (bb.origin.x + bb.size.width) * sw / k, (1 - bb.origin.y) * sh / k)
            pts = landmarks3(regions)
            if box[2] - box[0] >= MIN_DETECT_PX and plausible_layout(pts, box):
                faces.append(Face(box, pts, float(obs.confidence())))
    return drop_overlaps(faces)


# ---- restoring -----------------------------------------------------------------------------------------

def align(img, face):
    """-> (512 x 512 PIL crop, M): the face warped to the FFHQ template, and the source -> crop map."""
    from PIL import Image
    m = similarity_transform(face.points, FFHQ_TEMPLATE)
    crop = img.transform((FACE_SIZE, FACE_SIZE), Image.AFFINE, tuple(invert_affine(m).ravel()),
                         resample=Image.BILINEAR, fillcolor=BORDER_GRAY)
    return crop, m


def keep_chroma(restored, original, amount=1.0):
    """GFPGAN invents plausible detail, and with it colours: on a test portrait it turned brown eyes
    blue. Keep its luminance (the detail) but take the colour from the picture itself, `amount` 1 =
    entirely, 0 = GFPGAN's own. restored: uint8 array; original: PIL RGB crop. Returns a uint8 array."""
    from PIL import Image
    if amount <= 0:
        return restored
    ry, oy = Image.fromarray(restored).convert("YCbCr"), original.convert("YCbCr")
    y, cb, cr = ry.split()
    cb, cr = (Image.blend(a, b, amount) for a, b in ((cb, oy.split()[1]), (cr, oy.split()[2])))
    return np.asarray(Image.merge("YCbCr", (y, cb, cr)).convert("RGB"))


class Restorer:
    """GFPGAN through spandrel. fp32 only: spandrel reports no half-precision support for it."""

    def __init__(self, path, device):
        import functools

        import enhance as E
        self.model, self.device = E.load_model([(path, 1.0)], device), device
        # StyleGAN2 injects fresh random noise in every layer unless told not to, so two runs on the same
        # face differ by up to ~13 levels (even on the CPU): a print could not be reproduced and a preview
        # would not match it. The fixed noise stored in the weights makes it deterministic (MPS and CPU agree
        # to 1 level) and costs 50 dB PSNR against the random version, i.e. only the finest texture.
        net = self.model.model
        net.forward = functools.partial(net.forward, randomize_noise=False)

    def __call__(self, crop):
        """512 x 512 PIL RGB -> restored 512 x 512 uint8 array."""
        import torch
        x = torch.from_numpy(np.asarray(crop, np.float32) / 255.0).permute(2, 0, 1)[None]
        with torch.inference_mode():
            y = self.model(x.to(self.device))[0].permute(1, 2, 0).clamp(0, 1).float().cpu().numpy()
        return (y * 255.0 + 0.5).astype(np.uint8)


class Asset:
    """One finished face, ready to paste: the restored crop (enlarged by `r`), its mask, and the map
    from that enlarged crop to the print's pixels."""

    def __init__(self, image, mask, to_print, box):
        self.image, self.mask, self.to_print, self.box = image, mask, to_print, box  # PIL RGB, PIL L, 2x3, print px


def build_assets(img, faces, restorer, print_size, enlarge=None, cancel=None, keep_color=1.0, region=None):
    """Restore each face of `img` (PIL RGB, the picture as it enters the AI passes).

    print_size = (tw, th), the print in px. `enlarge(uint8 array) -> uint8 array`, if given, is the
    tile engine's x4 pass: used on the restored crop when the print shows it more than 1.25x larger
    than 512 px, so a big print does not just stretch a 512 px face. keep_color: see keep_chroma.
    `region` (x0, y0, x1, y1 in print px), if given, limits the work to the faces that touch it: a
    preview restores only the faces it shows, and each comes out exactly as in the full print.
    """
    from PIL import Image
    sx, sy = print_size[0] / img.width, print_size[1] / img.height
    to_print = np.array([[sx, 0, 0], [0, sy, 0]], float)
    out = []
    base_mask = face_mask()
    for face in faces:
        if cancel and cancel():
            raise InterruptedError("cancelled")
        m = similarity_transform(face.points, FFHQ_TEMPLATE)
        if region is not None:
            bx0, by0, bx1, by1 = affine_box(compose(to_print, invert_affine(m)), FACE_SIZE, FACE_SIZE)
            if bx1 + 2 < region[0] or bx0 - 2 > region[2] or by1 + 2 < region[1] or by0 - 2 > region[3]:
                continue
        crop, m = align(img, face)
        restored = keep_chroma(restorer(crop), crop, keep_color)
        out_per_crop = np.sqrt(sx * sy) / uniform_scale(m)  # print px per crop px
        r = 1
        if enlarge is not None and out_per_crop > 1.25:
            restored = enlarge(restored)
            r = restored.shape[0] // FACE_SIZE
        size = FACE_SIZE * r
        mask = base_mask if r == 1 else face_mask(size)
        # crop_r px -> crop px -> source px -> print px
        scale_back = np.array([[1 / r, 0, 0], [0, 1 / r, 0]], float)
        b = compose(to_print, compose(invert_affine(m), scale_back))
        out.append(Asset(Image.fromarray(restored), Image.fromarray((mask * 255 + 0.5).astype(np.uint8)), b,
                         affine_box(b, size, size)))
    return out


# ---- pasting (pure numpy + Pillow, no model needed) ---------------------------------------------------

def paste(band, origin, assets, strength=1.0):
    """Blend the faces into `band`, a uint8 or uint16 HxWx3 piece of the print whose top-left sits at
    `origin` (x, y) in print px. Returns a new array; faces that do not touch the band are skipped.

    Each output pixel looks up the restored face and the mask through the inverse map, so the result
    for a pixel does not depend on which band, or which preview area, it was rendered in.
    """
    from PIL import Image
    h, w = band.shape[:2]
    ox, oy = origin
    top = float(np.iinfo(band.dtype).max)
    out = band
    for a in assets:
        x0, y0 = max(int(np.floor(a.box[0])) - 1, ox), max(int(np.floor(a.box[1])) - 1, oy)
        x1, y1 = min(int(np.ceil(a.box[2])) + 1, ox + w), min(int(np.ceil(a.box[3])) + 1, oy + h)
        if x1 <= x0 or y1 <= y0:
            continue
        # window pixel (x, y) is print pixel (x0 + x, y0 + y); the inverse map takes it to the crop
        inv = invert_affine(a.to_print)
        shifted = inv.copy()
        shifted[:, 2] = inv[:, :2] @ [x0, y0] + inv[:, 2]
        coeffs = tuple(shifted.ravel())
        face = np.asarray(a.image.transform((x1 - x0, y1 - y0), Image.AFFINE, coeffs, Image.BICUBIC), np.float32)
        mask = np.asarray(a.mask.transform((x1 - x0, y1 - y0), Image.AFFINE, coeffs, Image.BILINEAR), np.float32) / 255.0
        alpha = (mask * strength)[..., None]
        if out is band:
            out = band.copy()
        win = out[y0 - oy:y1 - oy, x0 - ox:x1 - ox].astype(np.float32)
        face *= top / 255.0
        out[y0 - oy:y1 - oy, x0 - ox:x1 - ox] = np.clip(win + (face - win) * alpha + 0.5, 0, top).astype(band.dtype)
    return out
