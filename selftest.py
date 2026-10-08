"""Does this installation really work? Used by `enhance.py --selftest`, `gui.py --selftest`,
and to check a built .app, where a missing library would otherwise only show up in use.

Imports every dependency, runs a real (tiny, randomly weighted) model through the whole
pipeline to a TIFF and a PNG, and builds the window. No model files and no network needed.
"""
import importlib
import os
import sys
import tempfile


def run(window=True, out=print):
    """Run the checks, printing one line each -> exit code (0 = all passed)."""
    failures = []

    def check(name, fn):
        try:
            detail = fn()
            out(f"ok    {name}" + (f"  {detail}" if detail else ""))
        except BaseException as e:  # a failing check must not stop the others
            failures.append(name)
            out(f"FAIL  {name}: {type(e).__name__}: {e}")

    def versions():
        parts = []
        for mod in ("torch", "spandrel", "PIL", "numpy", "tifffile"):
            m = importlib.import_module(mod)
            parts.append(f"{mod} {getattr(m, '__version__', '?')}")
        return ", ".join(parts)

    def pipeline():
        import numpy as np
        import torch
        from PIL import Image
        from spandrel.architectures.Compact.__arch.SRVGG import SRVGGNetCompact
        from spandrel.architectures.ESRGAN.__arch.RRDB import RRDBNet

        import enhance as E
        # the two network families the real models use: Compact (general-x4v3) and RRDBNet (x4plus)
        archs = {"Compact": lambda: SRVGGNetCompact(num_feat=8, num_conv=2, upscale=4, act_type="prelu"),
                 "RRDBNet": lambda: RRDBNet(in_nc=3, out_nc=3, num_filters=16, num_blocks=1, scale=4)}
        with tempfile.TemporaryDirectory() as d:
            src = os.path.join(d, "in.png")
            Image.fromarray((np.random.default_rng(0).random((30, 40, 3)) * 255).astype(np.uint8)).save(src)
            for arch, make in archs.items():
                torch.manual_seed(0)
                w = os.path.join(d, f"{arch}.pth")
                torch.save({"params": make().state_dict()}, w)
                for name in ("out.png", "out.tif"):
                    E.enhance(src, os.path.join(d, name), "2", "in", 100, [(w, 1.0)], "cpu", 32)
                    size = Image.open(os.path.join(d, name)).size
                    assert size == (200, 150), (arch, name, size)
        gpu = E.pick_device("auto")
        return (f"{' and '.join(archs)}: 40x30 -> 200x150 as PNG and TIFF "
                f"(ran on the CPU; GPU here: {gpu if gpu.type != 'cpu' else 'none'})")

    def models_dir():
        import weights
        d = weights.default_models_dir()
        return f"models folder: {d} ({'present' if os.path.isdir(d) else 'not created yet'})"

    def real_weights():
        """If the real model files are on disk, load each one and run a tile: they use a different
        key layout from the tiny test models, which spandrel has to convert."""
        import numpy as np
        import torch

        import enhance as E
        import weights
        d = weights.default_models_dir()
        found = [n for n in weights.FILES if n != weights.GFPGAN_FILE  # the face model has its own check
                 and os.path.isfile(os.path.join(d, n)) and not weights.missing(d, [n])]
        if not found:
            return "no model files downloaded yet: skipped"
        dev = E.pick_device("auto")  # the GPU when there is one: that is the path the app really uses
        for n in found:
            model = E.load_model([(os.path.join(d, n), 1.0)], dev)
            out = E.upscale(np.random.default_rng(0).integers(0, 255, (24, 24, 3), dtype=np.uint8), model, dev, 24)
            assert out.shape == (24 * model.scale, 24 * model.scale, 3), (n, out.shape)
            assert out.std() > 1, f"{n}: the output is flat, the model did not run properly on the {dev}"
        return f"loaded and ran on the {dev}: " + ", ".join(found)

    def faces_stack():
        """Face recovery is optional, so a missing Vision is reported, not failed. When it is there, run a
        real Vision request, and if the GFPGAN weights are on disk run the network (the same two things that
        break in a built app when a library is left out)."""
        import numpy as np
        import torch
        from PIL import Image

        import enhance as E
        import faces as F
        import weights
        try:
            import Vision  # noqa: F401
        except ImportError:
            return "Apple Vision (pyobjc-framework-Vision) is not installed: face recovery is unavailable"
        try:
            assert F.detect_faces(Image.new("RGB", (96, 96), (120, 120, 120))) == []  # a real request, no face in it
        except RuntimeError as e:
            if "Apple Vision failed" not in str(e):
                raise
            # the framework loaded and answered, so the install is fine; this Mac just cannot run Vision (seen on a
            # GitHub runner: a virtual machine without GPU or Neural Engine answers "unexpected condition")
            return f"Vision is installed but cannot run here (a virtual machine?): {str(e)[:90]}"
        d = weights.default_models_dir()
        if weights.missing(d, [weights.GFPGAN_FILE]):
            return "Vision request ran; the GFPGAN weights are not downloaded: network not run"
        dev = E.pick_device("auto")
        restorer = F.Restorer(os.path.join(d, weights.GFPGAN_FILE), dev)
        crop = Image.fromarray(np.random.default_rng(0).integers(0, 255, (512, 512, 3), dtype=np.uint8))
        a, b = restorer(crop), restorer(crop)
        assert a.shape == (512, 512, 3) and a.std() > 1 and np.array_equal(a, b), "GFPGAN output flat or not repeatable"
        return f"Vision request ran; GFPGAN restored a crop on the {dev}, the same twice"

    def gui_window():
        import tkinter as tk

        import gui
        root = tk.Tk()
        root.withdraw()
        try:
            app = gui.App(root, settings_path=os.path.join(tempfile.mkdtemp(), "s.json"))
            root.update()
            assert app.root.title() == "Mac Image Enhancer"
            app.close()
        finally:
            try:
                root.destroy()
            except Exception:
                pass
        return f"Tk {tk.TkVersion}"

    check("dependencies import", versions)
    check("pipeline on a tiny model", pipeline)
    check("models folder", models_dir)
    check("real model files", real_weights)
    check("face recovery", faces_stack)
    if window:
        check("window builds", gui_window)
    out("selftest passed" if not failures else f"selftest FAILED: {', '.join(failures)}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(run())
