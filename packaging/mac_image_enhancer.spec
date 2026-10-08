# PyInstaller spec for "Mac Image Enhancer.app". Built by packaging/build_app.sh; run from the repo root.
# The model weights are NOT bundled: the app downloads them on first use (see weights.py / NOTICE).
import glob
import importlib.util
import os
import sys

from PyInstaller.utils.hooks import collect_dynamic_libs, collect_submodules

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))
BUILD = os.path.join(ROOT, "build")
sys.path.insert(0, ROOT)
import enhance  # noqa: E402  (only for the version)

NAME = "Mac Image Enhancer"

# spandrel imports torchvision, whose operators live in native libraries. PyInstaller's
# collect_dynamic_libs only takes lib*.so, so torchvision's _C_stable.so / image_stable.so are
# listed by hand. Without them every model load fails with "operator torchvision::nms does not
# exist"; the built app's `--selftest` is what catches that.
_tv = importlib.util.find_spec("torchvision")
TORCHVISION_NATIVES = collect_dynamic_libs("torchvision") + (
    [(f, "torchvision") for f in glob.glob(os.path.join(list(_tv.submodule_search_locations)[0], "*.so"))] if _tv else [])

a = Analysis(
    [os.path.join(ROOT, "gui.py")],
    pathex=[ROOT],
    binaries=TORCHVISION_NATIVES,
    datas=[(os.path.join(ROOT, "LICENSE"), "."), (os.path.join(ROOT, "NOTICE"), "."),
           (os.path.join(BUILD, "THIRD_PARTY_LICENSES.txt"), ".")],
    hiddenimports=["enhance", "color", "weights", "i18n", "selftest", "faces", "PIL.ImageTk", "PIL._tkinter_finder",
                   "tifffile", "objc", "Foundation", "Vision", "CoreML", "Quartz"] + collect_submodules("spandrel"),
    # coremltools is not bundled, so --engine ane is unavailable in the .app; the rest are dev-only
    excludes=["coremltools", "matplotlib", "IPython", "pytest", "tkinter.test", "torch.utils.tensorboard"],
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="mac-image-enhancer-gui", console=False,
          target_arch="arm64")
coll = COLLECT(exe, a.binaries, a.datas, name=NAME)
app = BUNDLE(
    coll,
    name=f"{NAME}.app",
    icon=os.path.join(BUILD, "MacImageEnhancer.icns"),
    bundle_identifier="org.mac-image-enhancer.MacImageEnhancer",  # change to an identifier you own before a signed release
    info_plist={
        "CFBundleDisplayName": NAME,
        "CFBundleShortVersionString": enhance.__version__,
        "CFBundleVersion": enhance.__version__,
        "LSMinimumSystemVersion": "13.0",
        "NSHighResolutionCapable": True,
        "NSHumanReadableCopyright": "Copyright (c) 2026 mac-image-enhancer contributors. MIT License.",
        "LSApplicationCategoryType": "public.app-category.photography",
    },
)
