# PyInstaller spec for the engine: enhance.py as a command-line tool, "mac-image-enhancer-engine".
# The SwiftUI app runs it as a child process (see packaging/build_swift_app.sh, which copies the folder this builds
# into the app as Contents/Resources/engine). The model weights are NOT bundled: the app downloads them on first use.
import glob
import importlib.util
import os
import sys

from PyInstaller.utils.hooks import collect_dynamic_libs, collect_submodules

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))
sys.path.insert(0, ROOT)

# spandrel imports torchvision, whose operators live in native libraries. PyInstaller's collect_dynamic_libs only
# takes lib*.so, so torchvision's _C_stable.so / image_stable.so are listed by hand. Without them every model load fails
# with "operator torchvision::nms does not exist"; the built engine's --selftest is what catches that.
_tv = importlib.util.find_spec("torchvision")
TORCHVISION_NATIVES = collect_dynamic_libs("torchvision") + (
    [(f, "torchvision") for f in glob.glob(os.path.join(list(_tv.submodule_search_locations)[0], "*.so"))] if _tv else [])

a = Analysis(
    [os.path.join(ROOT, "enhance.py")],
    pathex=[ROOT],
    binaries=TORCHVISION_NATIVES,
    datas=[],
    hiddenimports=["color", "weights", "selftest", "faces", "tifffile", "objc", "Foundation", "Vision", "Quartz"]
    + collect_submodules("spandrel"),
    # coremltools is not bundled, so --engine ane is unavailable; the window needs no Tk any more
    excludes=["coremltools", "tkinter", "matplotlib", "IPython", "pytest", "torch.utils.tensorboard"],
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="mac-image-enhancer-engine", console=True, target_arch="arm64")
coll = COLLECT(exe, a.binaries, a.datas, name="mac-image-enhancer-engine")
