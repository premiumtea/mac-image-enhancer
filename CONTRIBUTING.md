# Contributing to Mac Image Enhancer

Thank you for looking. This is a small project: a native macOS app (`app/`, SwiftUI) that runs a Python engine
(`enhance.py`) which does the enlarging. Anything from a typo to a new paper size is welcome.

## Ways to help that need no code

- **Try it and tell us what happened.** The app is brand new and was developed on one Mac. Open an issue with the
  "Bug report" form; the version (Mac Image Enhancer > About), your macOS version and a sentence on what you did are enough.
- **Check a translation.** The Thai, Chinese and French texts are drafts written for this project. They all live in
  `i18n.py` (one table per language). Native speakers: fix what reads wrong, open a pull request or an issue.
- **Use real pictures** (portraits, scans, logos, text) and report where the result is worse than the plain enlargement.

## Working on the code

You need a Mac with Apple Silicon, Python 3.12 and, for the window, Xcode 26.

```sh
/opt/homebrew/bin/python3.12 -m venv .venv
.venv/bin/pip install -e .
.venv/bin/mac-image-enhancer --download-models        # the Real-ESRGAN weights, checked against a SHA-256

.venv/bin/python test_enhance.py                      # the engine
.venv/bin/python test_i18n.py                         # interface text, and the Swift files generated from it
cd app && MAC_IMAGE_ENHANCER_ENGINE="$PWD/../.venv/bin/python|$PWD/../enhance.py" swift test
cd app && swift run                                   # the window, with this checkout's engine
```

Things worth knowing:

- **`i18n.py` is the only place interface text is written.** After changing it, run `python3 packaging/gen_swift.py`
  (it rewrites `Strings.generated.swift`). CI fails if the generated file is out of date.
- **The Swift code and `enhance.plan_print` must agree.** `gen_swift.py` also generates test cases from the Python
  side; do not edit `PlanVectors.generated.swift` by hand.
- **A bug fix comes with a test that fails without it.** The tests in `app/Tests/.../FlowTests.swift` drive the real
  engine with a tiny made-up model, so they take seconds.
- The window cannot be looked at on a Mac without a display. The "App screenshots" workflow (Actions tab) builds the app on
  a GitHub macOS 26 runner and uploads screenshots in light and dark mode, in several languages.
- **Clean-room rule:** this project reimplements the *idea* of a Windows upscaler without ever reading its code. Do not
  copy code, text or assets from other upscaler applications.

## Pull requests

Small and focused is easiest to review. Say what you changed and how you checked it. By contributing you agree that
your contribution is under the MIT licence of this project.
