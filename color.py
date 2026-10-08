"""Print color management: ICC-aware CMYK <-> RGB through LittleCMS (Pillow ImageCms).

The AI model works on RGB, so CMYK input is converted to sRGB first and CMYK output
is produced from the finished RGB at the very end. Pillow's color engine is 8-bit.
"""
import functools
import io
import sys

from PIL import ImageCms

INTENTS = {
    "relative": ImageCms.Intent.RELATIVE_COLORIMETRIC,  # the usual choice for photos
    "perceptual": ImageCms.Intent.PERCEPTUAL,
    "saturation": ImageCms.Intent.SATURATION,
    "absolute": ImageCms.Intent.ABSOLUTE_COLORIMETRIC,  # simulates paper white, for proofs
}


def _icc(profile):
    return ImageCms.ImageCmsProfile(profile).tobytes()


def _convert(img, src, dst, in_mode, out_mode, intent):
    # Black point compensation is only meaningful for relative colorimetric.
    flags = ImageCms.Flags.BLACKPOINTCOMPENSATION if intent == "relative" else ImageCms.Flags.NONE
    t = ImageCms.buildTransform(src, dst, in_mode, out_mode, INTENTS[intent], flags)
    return ImageCms.applyTransform(img, t)


@functools.cache
def srgb_icc():
    # cached: createProfile stamps the creation time into the header, so two calls
    # a second apart would otherwise give different bytes for the same profile
    return _icc(ImageCms.createProfile("sRGB"))


def to_working_rgb(img, icc=None):
    """Any Pillow mode -> (RGB image, ICC bytes describing those RGB pixels or None).

    RGB keeps its own profile. CMYK goes through its embedded profile to sRGB
    (relative colorimetric + black point compensation); without one the pixels
    have no defined meaning, so we fall back to Pillow's flat naive conversion.
    Other modes (gray, palette, RGBA) are plain-converted and their profile dropped.
    """
    if img.mode == "RGB":
        return img, icc
    if img.mode != "CMYK":
        return img.convert("RGB"), None
    if icc:
        try:
            src = ImageCms.ImageCmsProfile(io.BytesIO(icc))
            return _convert(img, src, ImageCms.createProfile("sRGB"), "CMYK", "RGB", "relative"), srgb_icc()
        except ImageCms.PyCMSError as e:
            print(f"warning: unusable embedded CMYK profile ({e}); converting without it", file=sys.stderr)
    else:
        print("warning: untagged CMYK input; converting without a profile, colors will look flat",
              file=sys.stderr)
    return img.convert("RGB"), None


def load_cmyk_profile(path):
    """Open an output CMYK profile -> (profile, raw bytes). ValueError if it isn't one."""
    try:
        profile = ImageCms.getOpenProfile(path)
    except (ImageCms.PyCMSError, OSError) as e:
        raise ValueError(f"cannot open ICC profile {path}: {e}") from e
    space = profile.profile.xcolor_space.strip()
    if space != "CMYK":
        raise ValueError(f"{path} has color space {space}, not CMYK")
    with open(path, "rb") as f:
        return profile, f.read()


def rgb_to_cmyk(img, src_icc, cmyk, intent="relative"):
    """RGB image -> (CMYK image, destination profile bytes to embed).

    `src_icc` describes the RGB pixels; without it sRGB is assumed.
    `cmyk` is what load_cmyk_profile returned.
    """
    profile, icc = cmyk
    src = ImageCms.ImageCmsProfile(io.BytesIO(src_icc)) if src_icc else ImageCms.createProfile("sRGB")
    return _convert(img, src, profile, "RGB", "CMYK", intent), icc
