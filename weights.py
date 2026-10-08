"""Where the Real-ESRGAN weight files live, and how to fetch them (stdlib only).

The weights are never shipped with mac-image-enhancer: they are downloaded, at the user's
request, from the Real-ESRGAN GitHub releases and checked against the SHA-256 recorded
here (taken from the files this project was developed and tested with).
"""
import hashlib
import os
import urllib.error
import urllib.request

RELEASES = "https://github.com/xinntao/Real-ESRGAN/releases/download"
PHOTO_FILE = "RealESRGAN_x4plus.pth"
GENERAL_FILE = "realesr-general-x4v3.pth"
GENERAL_WDN_FILE = "realesr-general-wdn-x4v3.pth"  # weaker-denoise twin of GENERAL_FILE
GFPGAN_FILE = "GFPGANv1.4.pth"  # optional: face recovery (see NOTICE for its licence conditions)

# file name -> (download URL, sha256, size in bytes)
FILES = {
    PHOTO_FILE: (f"{RELEASES}/v0.1.0/{PHOTO_FILE}",
                 "4fa0d38905f75ac06eb49a7951b426670021be3018265fd191d2125df9d682f1", 67040989),
    GENERAL_FILE: (f"{RELEASES}/v0.2.5.0/{GENERAL_FILE}",
                   "8dc7edb9ac80ccdc30c3a5dca6616509367f05fbc184ad95b731f05bece96292", 4885111),
    GENERAL_WDN_FILE: (f"{RELEASES}/v0.2.5.0/{GENERAL_WDN_FILE}",
                       "1641f8c4464b9f097c9fdda5589273713f67cf59f3d909e0bd688f0cee269dca", 4885111),
    GFPGAN_FILE: ("https://github.com/TencentARC/GFPGAN/releases/download/v1.3.0/GFPGANv1.4.pth",
                  "e2cd4703ab14f4d01fd1383a8a8b266f9a5833dacee8e6a79d3bf21a1b6be5ad", 348632874),
}
# what each --model needs (the general model's denoise blend uses both of its files). "all" is the two
# upscalers only: the 349 MB face model is fetched only when asked for by name.
GROUPS = {"photo": [PHOTO_FILE], "general": [GENERAL_FILE, GENERAL_WDN_FILE], "faces": [GFPGAN_FILE],
          "all": [PHOTO_FILE, GENERAL_FILE, GENERAL_WDN_FILE]}


def app_support_dir():
    return os.path.join(os.path.expanduser("~/Library/Application Support"), "mac-image-enhancer")


def default_models_dir():
    """$MAC_IMAGE_ENHANCER_MODELS, else models/ beside this file (a source checkout), else the
    per-user folder (pip install, or the .app where nothing sits beside the code)."""
    env = os.environ.get("MAC_IMAGE_ENHANCER_MODELS")
    if env:
        return env
    beside = os.path.join(os.path.dirname(os.path.abspath(__file__)), "models")
    return beside if os.path.isdir(beside) else os.path.join(app_support_dir(), "models")


def missing(models_dir, names):
    """The names among `names` that are absent from models_dir or have the wrong size."""
    out = []
    for n in names:
        p = os.path.join(models_dir, n)
        if not os.path.isfile(p) or (n in FILES and os.path.getsize(p) != FILES[n][2]):
            out.append(n)
    return out


def sha256_of(path):
    with open(path, "rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def download(name, models_dir, progress=None, cancel=None, files=None):
    """Fetch one weight file into models_dir -> its path.

    progress(done, total) is called as bytes arrive; cancel() -> True aborts with
    InterruptedError. The file is checked against its pinned SHA-256 and only then moved
    into place, so a damaged or partial download never looks like a weight file.
    """
    url, digest, size = (files or FILES)[name]
    os.makedirs(models_dir, exist_ok=True)
    dest = os.path.join(models_dir, name)
    tmp = dest + ".partial"
    h = hashlib.sha256()
    try:
        with urllib.request.urlopen(url, timeout=30) as r, open(tmp, "wb") as f:
            total = int(r.headers.get("Content-Length") or size)
            done = 0
            while chunk := r.read(1 << 20):
                if cancel and cancel():
                    raise InterruptedError("download cancelled")
                f.write(chunk)
                h.update(chunk)
                done += len(chunk)
                if progress:
                    progress(done, total)
        if h.hexdigest() != digest:
            raise ValueError(f"{name}: checksum mismatch (got {h.hexdigest()[:12]}..., expected {digest[:12]}...); "
                             "the download was damaged or upstream changed the file")
        os.replace(tmp, dest)
    except urllib.error.URLError as e:
        raise OSError(f"could not download {name} from {url}: {e.reason}") from e
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
    return dest
