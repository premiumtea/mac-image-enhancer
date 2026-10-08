# mac-image-enhancer

Open-source AI print-size image upscaler for macOS / Apple Silicon (MPS).
Clean-room reimplementation of the *idea* of "ARM AI Image Enhancer"
(github.com/spnprint-ARM/arm-ai-image-enhancer: Windows-only, **no license**).
Goal: do it better than the original, release as open source (MIT).

## Clean-room rules (do not break)
- **Never read, fetch, or copy the original repo's source, strings, translations, or assets.**
  No LICENSE there = all rights reserved. Build only from the feature spec below
  plus upstream open-source docs: Real-ESRGAN (BSD-3), spandrel (MIT), GFPGAN (Apache-2.0),
  facexlib (MIT), LaMa (Apache-2.0).
- Own names, structure, UI text, translations, logo. Credit Real-ESRGAN + spandrel in a
  NOTICE file before publishing. Ideas, features and formulas (pixels = inches x DPI) are free to use.

## Feature spec (behavior only)
AI upscale (2x/4x/8x via tiled passes); physical print size + DPI -> pixel dimensions;
live preview; optional face recovery; processing-device choice (AUTO/CPU/GPU); multilingual
UI (en/th/zh/fr, our own strings); canvas expansion = experimental, skip for now.

## Status
`enhance.py`: CLI, tiled Real-ESRGAN via spandrel, MPS -> CPU fallback, `plan_passes` hybrid
policy (1 pass up to 6x else 2; the 1.5 factor is a tunable), EXIF orientation honored,
ICC kept for RGB, DPI tag written, `--preview` renders one region only, prints are rendered in
bands (memory follows `--mem`, not print size) and TIFF is streamed to disk, batch (`image...
-o DIR|template`) + `--resume`. `--engine gpu|gpu16|ane`. `color.py`: ICC/CMYK helpers (Pillow ImageCms).
`weights.py`: models folder + pinned-SHA-256 downloads. `faces.py`: optional face recovery (Vision + GFPGAN). `i18n.py`: en/th/zh/fr interface text.
`gui.py`: the Tk window. `selftest.py`: `--selftest` of any install or built app. `packaging/`: icon,
licence collector, PyInstaller spec, `build_app.sh`, cask template. `pyproject.toml`, `README.md`,
`LICENSE` (MIT), `NOTICE`, `.github/workflows/`.
`test_enhance.py`: stdlib + Pillow checks; torch/tifffile/CMYK-profile sections skip if missing.
`test_gui.py`: interface text (no display needed) + the window driven with a tiny model (needs tkinter + display).
`test_faces.py`: face recovery geometry, pasting, pipeline with stand-in detector/restorer; `MAC_IMAGE_ENHANCER_FACE_SAMPLE=portrait.jpg` also runs real Vision + GFPGAN.
Verified on this Mac mini (M2 Pro): tests pass, MPS works, MPS vs CPU max diff 1/255.

## Run
    .venv/bin/python test_enhance.py
    .venv/bin/python test_gui.py                       # text always; the window part needs tkinter + a display
    .venv/bin/python gui.py                            # the window (python-tk@3.12 is installed)
    .venv/bin/python enhance.py --download-models      # fetch missing weights, SHA-256 checked (`faces` = the 349 MB GFPGAN)
    .venv/bin/python enhance.py in.jpg --size 40 --dpi 200 --faces -o out.png   # face recovery (read NOTICE first)
    .venv/bin/python enhance.py --selftest             # also: "dist/Mac Image Enhancer.app/Contents/MacOS/mac-image-enhancer-gui" --selftest
    PYTHONPATH=<dir with pyinstaller> packaging/build_app.sh   # dist/Mac Image Enhancer.app + .dmg
    .venv/bin/python enhance.py in.jpg --size 20x15 --unit cm --dpi 150 -o out.png
    .venv/bin/python enhance.py in.jpg --size 20x15 --model general --denoise 0.5 -o out.png
    .venv/bin/python enhance.py in.jpg --size 20x15 --bits 16 -o out.tif
    .venv/bin/python enhance.py in.jpg --size 20x15 --cmyk-profile printer.icc -o out.tif
    .venv/bin/python enhance.py in.jpg --size 100 --dpi 150 --preview 0.5,0.5 -o look.png  # 100% crop
    .venv/bin/python enhance.py shots/*.jpg --size 30x20 --dpi 300 -o prints/ --resume      # batch
    .venv/bin/python enhance.py big.jpg --size 300 --dpi 150 --mem 2048 -o banner.tif       # huge: stream
    .venv/bin/python enhance.py in.jpg --size 60 --dpi 200 --engine ane -o out.png          # ~3x faster
Setup if venv is missing: `/opt/homebrew/bin/python3.12 -m venv .venv &&
.venv/bin/pip install torch spandrel pillow numpy tifffile` (tifffile writes every TIFF; add
coremltools for `--engine ane`). Weights (gitignored):
`models/RealESRGAN_x4plus.pth`, sha256 4fa0d38905f75ac06eb49a7951b426670021be3018265fd191d2125df9d682f1,
from github.com/xinntao/Real-ESRGAN/releases/download/v0.1.0/RealESRGAN_x4plus.pth

## Roadmap (agreed order 1 -> 3 -> 2, then 4-6)
1. Model per image type + denoise knob: add realesr-general-x4v3 and its wdn variant
   (v0.2.5.0 release, ~5 MB each), blend state dicts for denoise strength. Reason: x4plus is
   trained on photos and distorts text/graphics (seen on test image: "3", "a" warped).
   **Done** (`--model photo|general`, `--denoise 0..1`, `model_recipe`/`blend_state_dicts`,
   tested with synthetic SRVGGNetCompact weights). Real weights downloaded 2026-10-08 into
   `models/` (v0.2.5.0, 4885111 bytes each, sha256 recorded from our own download, not checked
   against an upstream value):
   `realesr-general-x4v3.pth` 8dc7edb9ac80ccdc30c3a5dca6616509367f05fbc184ad95b731f05bece96292,
   `realesr-general-wdn-x4v3.pth` 1641f8c4464b9f097c9fdda5589273713f67cf59f3d909e0bd688f0cee269dca.
   Verified: denoise 0 / 0.5 / 1 all run on MPS; general 0.5 MPS vs CPU max diff 1/255.
   **Still open:** the original test image with the warped "3"/"a" is not in the project, so
   photo vs general on that failure is unconfirmed. On a synthetic Helvetica text image (our own,
   with noise) both render legibly with no warping; photo shows a slight halo around glyphs and
   denoise 0 keeps paper grain. Default model stays `photo` and DEFAULT_DENOISE 0.5 until the
   real image is compared.
2. Preview of the real result on a selected region at 100% (incl. face recovery). **Done.**
   **Done, including face recovery (see below).** `--preview FX,FY [--preview-size WxH]` (default 800x600) writes
   just that crop of the print to `-o`, in the same format/color path as the full run. How:
   `render()` walks backwards from the crop: `resize_window` (Lanczos reach) -> `pass_windows`
   (tile-aligned region + padding per AI pass, on the SAME tile grid as a full run) -> only those
   tiles run; `upscale(origin=, full=, region=)` works on a window and asserts if padding is
   missing. A full print is just the whole-image region through the same code (verified
   bit-identical to the pre-refactor output, real model: 1-pass, 2-pass, 16-bit, shrink).
   Guarantee: AI stage is bit-identical to the full run (CPU test, 1 and 2 passes, 8/16-bit);
   the final Lanczos can differ by +-1 level on ~0.01% of samples (16-bit: <=2 units of 65535)
   because Pillow keeps `resize(box=)` coordinates as float32 (reproduced with Pillow alone:
   exactly representable boxes, e.g. scale 2/4/0.5, give 0 differences). Measured, real model:
   100 cm @150 dpi from a 1500x1000 source: full 20.0 s, preview 5.5 s (~2-3 s of that is
   torch import + model load), crop differs by <=1 level in 0.006% of samples.
   GUI region *selection* (click) is in `gui.py` (item 6); the CLI takes a centre + size.
   **Face recovery** (`faces.py`, `--faces`, "Restore faces" in the window). Approved by the user
   2026-10-08 as opt-in with the licence conditions disclosed; installed pyobjc-framework-Vision
   (~8 MB) into .venv and downloaded GFPGANv1.4.pth (348,632,874 B, sha256 e2cd4703...be5ad, pinned in
   `weights.py`, group `faces`, NOT in `all`). Pipeline: Apple Vision finds faces + landmarks on the
   picture (no detector weights; facexlib would have pulled opencv/numba and 200+ MB) -> a similarity
   transform maps pupils + middle of the lips onto the FFHQ template (facexlib's numbers, read from its
   MIT source) -> 512 crop -> GFPGAN (spandrel `GFPGANv1Clean`, fp32 only, 0.14 s/face on MPS) ->
   `keep_chroma` -> enlarged by the tile engine (x4) when the print shows the face >1.25x larger than
   512 px -> pasted per pixel through a soft oval mask in `render_bands`. Because the paste is per
   pixel and each face's restoration depends on nothing but the source picture, bands and previews
   equal the full print: verified on the real model (previews of 4 areas <=1 level, 10 bands with faces
   across the seams identical to one band, two runs of a job identical) and with stand-ins in
   `test_faces.py`; `build_assets(region=)` restores only the faces a preview shows.
   Things measured, not assumed: (1) GFPGAN is NOT deterministic by default (StyleGAN2 random noise:
   runs differ by up to 13 levels, even on CPU) -> `randomize_noise=False` (MPS vs CPU then agree to 1
   level; 50 dB from the random version); without it preview != print. (2) It turned brown eyes blue
   -> luminance from GFPGAN, colour from the picture (YCbCr), default `--face-color 1`. (3) Vision's
   nose tip and mouth corners sit 17-20 px from the FFHQ template's on an aligned face, pupils and the
   lips' centre within a few px -> 3-point alignment (residual ~2 px instead of 7-21). (4) Against
   ground truth (astronaut photo shrunk, blurred, JPEG'd, printed back at 512): face 53 px wide ->
   sharper, same person, PSNR 1.9 dB LOWER than Real-ESRGAN alone (23.9 vs 25.8); 35 px plausible;
   26 px a different, younger face (PSNR 19.0 vs 20.1); 17 px both broken -> faces narrower than 32 px
   are left alone (`--face-min-size`), since a clean wrong face is worse than a visibly damaged one.
   (5) Vision gave an 86 px "face" with confidence 1.0 on a jacket, and the same small face twice ->
   `plausible_layout` (eye distance / box width 0.28-0.65, mouth 0.65-1.6 eye distances below, tilt
   <=75 deg) and `drop_overlaps` (IoU, and a smaller box inside a larger one goes: a first version
   dropped the larger instead, caught by a test). Zero detections on 5 face-free pictures.
   `pointsInImageOfSize_` returns a bare C array: iterating it ran off the end (SIGBUS); index by
   `pointCount()`. Real portraits used (scratchpad only): NASA astronaut (scikit-image), Grace Hopper
   (Pillow tests), both public domain; no multi-face real photo was available, so multi-face is tested
   with a collage of the two.
   Limits: only when the print is an enlargement; faces are restored at 512 px (x4-enlarged by the tile
   engine for big prints, so detail beyond 512 is Real-ESRGAN's); 16-bit prints get an 8-bit face area;
   macOS only; mask is a fixed oval (a face-contour mask from Vision's `faceContour` would follow beards
   and jaws better, not tried); fidelity metrics go down while sharpness goes up, so "better" is a
   judgement the user must make by eye with the original beside it (the window shows both).
   **Licence (see NOTICE): GFPGAN is Apache-2.0 "except for the third-party components", which include
   StyleGAN2 (NVIDIA licence: "non-commercially" = research or evaluation only) and DFDNet (CC BY-NC-SA 4.0);
   the weights are trained on FFHQ. Unknown whether that reaches the weights; not legal advice; off by
   default, nothing shipped, the window repeats the warning in the download prompt.**
3. Print color management: CMYK/ICC via ImageCms, 16-bit. **Done** (`color.py` + `enhance.py`):
   CMYK input -> sRGB through its embedded profile (relative colorimetric + BPC; untagged CMYK
   falls back to Pillow's naive conversion with a warning); `--cmyk-profile ICC [--intent ...]`
   writes a CMYK TIFF (LZW, profile + DPI embedded); `--bits 16` writes a 16-bit RGB TIFF via
   tifffile (zlib, ICC + DPI embedded; model output kept as uint16, Lanczos done in float32).
   Bad option combos / bad profile fail before any AI work. No CMYK profile is bundled: the
   user supplies their printer's; tests use macOS `Generic CMYK Profile.icc` and skip without it.
   Verified with the real model: 16-bit file has ~23k distinct levels per channel (not upcast
   8-bit), `sips` reads it as 16-bit RGB / CMYK + profile at 150 dpi; CMYK round trip of the
   test image changes colors by 2.5 levels on average (saturated red G +12, normal gamut cost).
   **Limits (known, not hidden):** CMYK and 16-bit are mutually exclusive (Pillow's ImageCms is
   8-bit); the working space for CMYK input is sRGB, so saturated inks get clipped (a
   `--work-profile` would fix it); 16-bit *input* is read as 8-bit by Pillow (no tifffile
   reader yet) so 16-bit output only helps later color work, it cannot add detail; untagged RGB
   stays untagged on output; RGBA alpha is still dropped (not composited); no soft-proof or
   gamut warning. 8-bit vs 16-bit outputs (real model, text test image): 99% of pixels within
   ~1 level, 0.1% differ by >2, max ~9, all at hard black/white edges. Cause (checked by
   squeezing the range off 0/255: max drops to 1.08): Pillow's two-pass 8-bit resize clips
   Lanczos overshoot between passes; the 16-bit path doesn't.
4. Big prints without RAM blowup: stream tiles to disk, batch + resume.
   **Done, with limits.** Rendering: `enhance()` renders the print in full-width bands
   (`render_bands` -> `render(region=band)`, the machinery `--preview` uses), band height from
   `--mem MB` (default 1024) via `band_rows_for`. TIFF (tifffile, always) is streamed strip by strip,
   BigTIFF past 3 GB; bands are rounded to whole strips and `write_tiff` raises otherwise (deflated
   strips cannot be re-cut, found by mutation test). PNG/JPEG cannot stream in Pillow: the finished
   8-bit print is assembled in RAM (warns past 2 GB; use .tif). Output goes to `.<name>.partial` and
   is renamed at the end: a crash or Ctrl-C leaves no truncated file and an existing output survives
   until replaced whole (SIGINT and SIGKILL mid-batch both tested with the real model).
   Batch: `image... -o DIR | file | 'dir/{stem}.tif'`; weights load once per batch; a bad input is
   reported and the rest carry on (exit 1); colliding outputs or an output that is its own input are
   refused. `--resume` skips an output whose job fingerprint (`job_params`: input name+size+mtime,
   size/unit/dpi, model files, tile, bits, CMYK profile/intent, compress, ALGO_VERSION) matches the
   record in `.mac-image-enhancer-jobs.json` next to the outputs; every run writes that record. Bump
   `ALGO_VERSION` whenever the pixels a job produces change.
   Measured (real model, M2 Pro): 209 Mpx print (17717x11812 from 4000x2667, 1 pass): old code numpy
   peak 1860 MB / RSS 3.94 GB / 223 s; new `--mem 256` (7 bands, TIFF): 581 MB / 0.89 GB / 310 s
   (+39%: seam tiles are recomputed per band). 10000x6667 from 1500x1000 (2 passes): numpy peak
   1627 -> 1193 MB and RSS 3.66 -> 2.39 GB at the default budget (only 2 bands there, so a modest
   gain). Both match the old single-shot output to +-1 level on 0.002-0.003% of samples.
   **Limits:** (1) `peak memory footprint` has a floor bands cannot touch: the Metal driver reserves
   ~2.1 GB as soon as tiles run at `--tile 256` (1.1 GB at 128 or 64; speed and seam effect of
   smaller tiles NOT measured), so footprint stayed 4.9-7.7 GB; only RSS/numpy memory follows `--mem`
   (footprint also swings by ~1 GB between identical runs). (2) `--mem` is an estimate: numpy peak
   was ~1.2x the budget at 1024 and ~2.3x at 256 (fixed overhead + Pillow temporaries unmodeled); a
   tiny budget costs time (+57% at `--mem 64` on a small job). (3) No mid-print resume: an
   interrupted print restarts at its first band; only finished outputs are skipped. (4) No free-disk
   check. (5) A TIFF killed by SIGKILL/power loss leaves `.<name>.partial`, overwritten by the next
   run of that output. (6) Pixels can differ by +-1 level on ~0.01% of samples depending on band
   layout (TIFF and PNG round bands differently): same Pillow float32 `box` cause as the preview.
   (7) Two batches writing into one directory at once can lose manifest records.
   **Behavior changes made here:** TIFF is uncompressed by default (was LZW for 8-bit/CMYK via
   Pillow, zlib for 16-bit); `--tiff-compress` = deflate (LZW would need imagecodecs); tifffile is
   required for any TIFF; `-o` defaults to out.tif for `--bits 16`/CMYK; each run leaves a hidden
   `.mac-image-enhancer-jobs.json` beside its outputs.
5. Speed: fp16 on MPS (check artifacts) / Core ML.
   **Done: `--engine {gpu,gpu16,ane}`, default `gpu` (unchanged: bit-identical to before).**
   Per 288x288 tile (256 + pad 16), RRDBNet x4plus, M2 Pro: fp32 MPS 704 ms; fp16 MPS 570 (1.24x);
   bf16 598; Core ML on the Neural Engine 218 (3.2x). Batching 4 tiles: no gain per tile (723 ms),
   3x GPU memory. channels_last: 3x SLOWER (2113 ms). ANE and GPU at once is slower than ANE alone
   (2.8-3.2 vs 4.6 tiles/s: they contend), so no hybrid.
   End to end, 4000x2667 from 600x400 (2 passes): gpu 47.5 s, gpu16 41.5 s, ane 26.3 s; peak
   footprint 3.59 / 2.61 / 1.11 GB (the ANE needs no ~2.1 GB Metal reservation: that is the floor
   item 4 could not lower). 10000x6667 from 1500x1000: gpu 307-346 s -> ane 108.8 s, footprint 7.1 ->
   3.2 GB. ANE start-up costs ~6-10 s (coremltools import + load), so a tiny job can be slower than
   gpu (4-tile job: 6.7 s vs 3.8 s).
   Quality / artifacts: 3 natural photos (incl. a sky gradient), fp16-MPS vs fp32: PSNR 58-61 dB,
   max 4-5 levels, no added noise or banding; stress tiles (white, black, checkerboards, saturated
   bars, near-white/black gradients): no NaN/inf, <=1.9 levels. ANE vs torch fp32 with identical
   padding: 55.9 dB, max 4. Whole 2-pass job vs gpu: ane 51.6 dB (max 26), gpu16 53.1 dB (max 17).
   **Borders:** Core ML needs a fixed input, so border tiles (smaller than 288) are reflect-padded
   right/bottom and the output cropped. That changes pixels near the image edge vs `gpu`, which
   feeds variable-size windows (max diff 142, mostly the bottom/right ~300 px), but against a
   reference upscaled WITH real surrounding context, reflect padding is closer: error bottom 2.16
   vs gpu 2.54, right 1.05 vs 1.32, interior equal (0.71-0.77). So `gpu` could adopt reflect padding
   too; not done because it would change the default output.
   Core ML details: `coreml_package` converts once per (weights content, tile size, coremltools
   version) into `models/coreml/` via torch.export + coremltools (fp16 mlprogram, ~15 s, 33 MB for
   x4plus; torch.jit.trace gives identical packages but is deprecated and slower). `--engine ane`
   needs `pip install coremltools`, which is NOT in .venv yet: development used a scratch `--target`
   install (`PYTHONPATH=<dir>`); coremltools 9.0 documents torch only up to 2.7 and we run 2.14, it
   works. ANE helps only the heavy `photo` model: `general` finishes that 4000x2667 job in 6 s on
   gpu already (ane 6.0 s). Limits: ane/gpu16 refuse `--bits 16` (fp16 keeps ~11 bits) and
   `--device cpu`; ane is fixed to one tile size (`--tile 128` = another package); the engine is part
   of the `--resume` fingerprint; ane output is deterministic run to run.
6. Distribution: GUI (Tkinter needs `brew install python-tk@3.12`), .app/.dmg, Homebrew, CI,
   LICENSE (MIT) + NOTICE. **Done except what needs the user's accounts (Open, below).**
   LICENSE: MIT, "mac-image-enhancer contributors" (the user's choice). NOTICE: full BSD-3 text (Real-ESRGAN,
   (c) 2021 Xintao Wang) and MIT text (spandrel, (c) 2024 The ChaiNNer Organization), fetched from
   the upstream repos, not from memory (spandrel's wheel ships no licence file). It says the weights
   are downloaded not shipped, and that upstream states no separate weights licence.
   `weights.py`: models dir = $MAC_IMAGE_ENHANCER_MODELS, else ./models beside the code, else
   ~/Library/Application Support/mac-image-enhancer/models (what pip installs and the .app use);
   `download()` pins SHA-256 (the values recorded from our own downloads, equal to the files in
   models/), writes `.partial`, renames after the check; `enhance.py --download-models`.
   Engine hooks the window needed: `enhance(progress=, cancel=)` (`count_tiles` plans the tile total
   exactly, = what render runs, tested), cancel raises InterruptedError and cleans up, `run_batch(on_job=)`
   where cancel stops the whole batch, `plan_print` (size fields -> px, crop, passes; shared by CLI and
   GUI), `--device gpu`.
   `gui.py` (Tk 9.1; `brew install python-tk@3.12` was approved and run 2026-10-08, which also moved
   python@3.12 to 3.12.15). **Redesigned 2026-10-08 for ordinary end users** (the user asked for a window that is
   nice to look at and use, to ship as a package): the stage on the left is empty (glyph + "Choose a picture"),
   the picture with the yellow preview marker (a click = a `--preview` centre), or the before/after comparison
   of the real preview at 100% with a draggable line; the right panel is three numbered steps: 1 paper size
   (chips A4..A0 and 24x36", or Custom; the sheet turns to the picture's orientation; typing a width makes the
   height follow the picture until a height is typed, otherwise the picture is cropped to fit), 2 quality
   (Standard/Good/Fine = 150/200/300 DPI, plus a coloured pill telling how far the picture is stretched:
   <=1x sharp, <=4x good, <=8x soft, else "bigger original would help"), 3 options (face recovery switch with its
   warning; Advanced window: picture type + noise removal, processor, DPI, 16-bit, CMYK profile, TIFF compress).
   Bottom bar: result size, progress + time left (extrapolated after 4 s), Preview, Save (default button).
   Save asks for a file name (one picture) or a folder (several); 16-bit/CMYK force `.tif` and say so;
   "Show in Finder" afterwards. Also: menu bar + shortcuts (⌘O/⌘S/⌘P), About, Finder "Open With"/Dock drops
   via `::tk::mac::OpenDocument` (Info.plist declares the image types), argv paths, first-run language from
   macOS (`defaults read -g AppleLanguages`), settings in Application Support (validated on load).
   Tk has no drag-and-drop, hence the Dock drop + Open button. In-stage buttons and the switch are drawn on
   canvases: ttk buttons on the dark canvas drew a light box around themselves, and the system's own
   "Switch.TCheckbutton"/"Accent.TButton" styles are not usable here (Save uses `default="active"`).
   System secondary-text colours come out plain white through `winfo_rgb` (alpha ignored): greys and pills are
   explicit per light/dark. `i18n.py` strings are our own; th/zh/fr are drafts for native review (tests check
   key + placeholder parity and that gui.py uses every string). Status text is kept as keys so it follows a
   language change. The window is never shorter than the steps need in the current language (`fit_window`).
   **How the window is looked at:** Tk windows can be created on this Mac mini and `test_gui.py` drives the real
   window (preview, compare, single/batch save, 16-bit, cancel, weights prompt, faces, advanced, settings, all
   languages), but `screencapture` and CGWindowList capture both fail here (no display). So
   `.github/workflows/screenshots.yml` (manual: Actions > Screenshots) starts the window on a macos-14 runner,
   runs `packaging/screenshots.py` (real weights downloaded in the job, made-up landscape as the picture) and uploads
   PNGs in light and dark mode: `gh workflow run screenshots.yml`, then `gh run download <id> -n screenshots`.
   That found real bugs the geometry audit could not: panel width changing with the language (grid_propagate
   on a frame whose children are packed), the last button cut off in French with the face note open, halos
   around ttk buttons. Not yet looked at: the built .app itself (release.yml now has a manual run that
   launches it and screenshots it).
   Packaging: `pyproject.toml` (setuptools >= 77, flat `py-modules`, scripts `mac-image-enhancer` and
   `mac-image-enhancer-gui`, extra `ane`; the wheel is 40 KB and holds only the modules, LICENSE and NOTICE;
   installed outside the checkout it uses the Application Support models dir). `packaging/build_app.sh`:
   icon (own logo, `make_icon.py`) + `THIRD_PARTY_LICENSES.txt` (`collect_licenses.py`, from installed
   metadata) -> PyInstaller (`mac_image_enhancer.spec`) -> ad hoc codesign -> .dmg. Result: app 557 MB, dmg
   207 MB (no weights, no coremltools). The bundle shipped broken at first: `selftest.py` found
   "operator torchvision::nms does not exist" because torchvision's `_C_stable.so`/`image_stable.so`
   were missing (PyInstaller's `collect_dynamic_libs` only takes `lib*.so`); the spec now lists them.
   The built app's `--selftest` passes with and without weights: both network families (Compact,
   RRDBNet), PNG + TIFF, and the real weights loaded and run on the MPS GPU inside the bundle.
   The dmg mounts and the signature verifies from it. `spctl --assess` REJECTS the app (ad hoc).
   CI: `ci.yml` (macos-14 + ubuntu-24.04: the three test files + selftest; green since 2026-10-08) and
   `release.yml` (v* tag -> dmg -> GitHub release; also a manual run that only builds, checks, screenshots the
   launched app and uploads the dmg as an artifact). `screenshots.yml` is manual. Homebrew: `packaging/homebrew/mac-image-enhancer.rb` is a cask TEMPLATE
   (needs OWNER + a released dmg's sha256), untested.
   **Open (needs the user):** CI and the release workflow have never run (they run on the first push); the cask needs a released dmg; an Apple
   Developer ID for signing + notarization (until then a downloaded app needs right-click > Open);
   the bundle id `org.mac-image-enhancer.MacImageEnhancer` is a placeholder; the .app has no `--engine ane`
   (coremltools not bundled; deciding to bundle it adds ~100 MB, untested); the bundle was only run on
   this machine (macOS 26, M2 Pro), so `LSMinimumSystemVersion` 13.0 is a guess.

## Notes
- Work and test here on the Mac (MPS). Linux CI/NAS has no MPS: CPU-only checks.
- Ask the user before downloading model files or other large assets.
- Git repo on branch `main`, remote `origin` = https://github.com/premiumtea/mac-image-enhancer (public, created 2026-10-08
  with the user's gh login; the token has the `workflow` scope, needed to push .github/workflows). The project was
  renamed from "Mac Enhancer" to "Mac Image Enhancer" before the first push, because the user said the old name did not
  say it handles images (CLI `mac-image-enhancer`, env `MAC_IMAGE_ENHANCER_MODELS`, Application Support folder
  `mac-image-enhancer`, bundle id `org.mac-image-enhancer.MacImageEnhancer`). The local folder is still
  `/Users/wolf/mac-enhancer` (the .venv has absolute paths: rename it only together with a new venv).
  `.gitignore` excludes .venv, models, build/, dist/, images and test outputs. Commits use the user's own git identity.
- No display on this Mac: Tk windows run (test_gui.py) but cannot be photographed; use the screenshots workflow (see the gui.py paragraph).
- CI timing trap: a test that presses Cancel after a delay races a fast CPU; press it from inside the first progress report.
- dist/ (app + dmg, ~760 MB) is gitignored build output, reproducible with packaging/build_app.sh.
