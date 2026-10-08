#!/usr/bin/env python3
"""Gather the license files of the installed packages the app bundles: collect_licenses.py OUT.txt

BSD and similar licenses require their notice to travel with binaries, and the .app contains
these packages. The text comes from each package's own metadata, nothing is written from memory.
"""
import importlib.metadata as md
import sys

PACKAGES = ["torch", "spandrel", "numpy", "pillow", "tifffile", "sympy", "networkx", "jinja2", "mpmath", "fsspec",
            "filelock", "markupsafe", "typing_extensions", "einops", "safetensors", "setuptools",
            "pyobjc-core", "pyobjc-framework-Cocoa", "pyobjc-framework-Quartz", "pyobjc-framework-CoreML",
            "pyobjc-framework-Vision"]  # PyObjC: reaches Apple Vision for face recovery
NAMES = ("licen", "copying", "notice")  # file names that carry license text


def main(dest):
    lines, missing = [], []
    for name in PACKAGES:
        try:
            dist = md.distribution(name)
        except md.PackageNotFoundError:
            continue  # not installed here, so not bundled
        texts = []
        for f in dist.files or []:
            low = f.name.lower()
            if any(low.startswith(n) for n in NAMES) and ".dist-info" in str(f) + "/":
                try:
                    texts.append((str(f), dist.locate_file(f).read_bytes().decode("utf-8", "replace")))
                except OSError:
                    pass
        meta = dist.metadata
        lines += ["=" * 78, f"{meta['Name']} {meta['Version']}  ({meta.get('License-Expression') or meta.get('License') or 'see below'})",
                  meta.get("Home-page") or "", "=" * 78, ""]
        if not texts:
            missing.append(name)
            lines += ["(the package ships no license file; see its project page and the SPDX identifier above)", ""]
        for path, text in texts:
            lines += [f"--- {path}", text.strip(), ""]
    with open(dest, "w") as f:
        f.write("Licenses of the Python packages bundled in this application.\n"
                "mac-image-enhancer itself: see LICENSE and NOTICE.\n\n" + "\n".join(lines))
    print(f"wrote {dest} ({len(PACKAGES) - len(missing)} packages with license text; none shipped by: {', '.join(missing) or '-'})")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "build/THIRD_PARTY_LICENSES.txt")
