# Mac Image Enhancer

An AI print-size image upscaler for Apple Silicon Macs. Tell it how large the print is and at
what DPI; it works out the pixels (`pixels = inches × DPI`), enlarges the picture with
Real-ESRGAN in tiles on your Mac's GPU or Neural Engine, and writes a file ready to print:
PNG, JPEG, 16-bit TIFF, or CMYK TIFF through your printer's ICC profile.

- **See the real result before you wait for it.** Click a spot on the picture and press
  Preview: the area is computed exactly as it will be in the final print, shown at 100%.
- **Big prints, small memory.** Prints are rendered in bands and TIFF is streamed to disk, so
  RAM follows `--mem`, not the size of the print.
- **Batches that can be resumed.** Many pictures in one go; run it again after an
  interruption and only the unfinished ones are done.
- **Optional face recovery** (GFPGAN): blurry faces are re-created sharply, keeping the picture's own
  colours, in the preview and the print alike. It invents detail, so read "Good to know" first.
- **English, Thai, Chinese and French** interface (drafts of the last three; corrections welcome).

Apple Silicon only. Developed and tested on an M2 Pro Mac mini (macOS 26); the model runs on
the GPU (MPS), optionally on the Neural Engine, with a CPU fallback.

## Install

There is no published release yet. From a checkout:

```sh
brew install python-tk@3.12                 # only for the window; the command line does not need it
/opt/homebrew/bin/python3.12 -m venv .venv
.venv/bin/pip install -e .                  # torch, spandrel, pillow, numpy, tifffile
.venv/bin/pip install coremltools           # optional: --engine ane (Neural Engine, about 3x faster)
.venv/bin/pip install pyobjc-framework-Vision   # optional: --faces (Apple Vision finds the faces)
.venv/bin/mac-image-enhancer --download-models    # one time: the Real-ESRGAN weights, checked against a SHA-256
.venv/bin/mac-image-enhancer --download-models faces  # optional, 349 MB: GFPGAN for --faces (read its licence note first)
```

The weights are never shipped with this project. They are downloaded from the Real-ESRGAN
releases into `models/` (or `~/Library/Application Support/mac-image-enhancer/models` for an
installed copy). The window offers to download them the first time they are needed.

`packaging/build_app.sh` builds `Mac Image Enhancer.app` and a `.dmg` (see below).

## Use

The window (three steps, no settings form):

```sh
.venv/bin/mac-image-enhancer-gui
```

1. **Choose a picture** (or drop pictures on the app icon, or use Open With in Finder), then pick a **paper
   size** (A4 to A0, 24×36″, or your own width and height).
2. Pick a **print quality**. A coloured note tells you in plain words whether the picture will stay sharp at that
   size, and how far it is being stretched.
3. Press **Save**. If you want to see it first, click the part of the picture you care about and press
   **Preview**: the result for that area is shown at 100%, with a line to drag between before and after.

Face recovery (a switch), the picture type, processor, 16-bit colour and CMYK are under **Advanced…**.

The command line:

```sh
mac-image-enhancer photo.jpg --size 60x40 --unit cm --dpi 200 -o print.png
mac-image-enhancer photo.jpg --size 60 --dpi 200 --preview 0.5,0.5 -o look.png    # just a 100% crop of the middle
mac-image-enhancer shots/*.jpg --size 30x20 --dpi 300 -o prints/ --resume          # a batch, resumable
mac-image-enhancer photo.jpg --size 60 --dpi 300 --bits 16 -o print.tif            # 16-bit
mac-image-enhancer photo.jpg --size 60 --dpi 300 --cmyk-profile printer.icc -o print.tif
mac-image-enhancer logo.png --size 40 --model general --denoise 0.3 -o sign.png    # text and graphics
mac-image-enhancer portrait.jpg --size 40 --dpi 200 --faces -o print.png           # restore the faces too
```

| Option | What it does |
|---|---|
| `--size W[xH] --unit cm\|mm\|in\|ft --dpi N` | the print size. With only `W`, the height follows the picture; with both, the picture is cropped from the centre to fit |
| `--model photo\|general`, `--denoise 0..1` | `photo` is Real-ESRGAN x4plus; `general` (x4v3) is safer for text and graphics and has a noise-removal blend |
| `--engine gpu\|gpu16\|ane` | fp32 on the GPU (exact, the default), fp16 on the GPU (about 1.2× faster), or Core ML on the Neural Engine (about 3× faster, needs coremltools). The fp16 engines differ slightly from `gpu` |
| `--device auto\|cpu\|gpu` | which processor torch uses |
| `--bits 16`, `--cmyk-profile ICC`, `--intent …`, `--tiff-compress` | 16-bit RGB TIFF; CMYK TIFF through a profile; deflate the TIFF (default: uncompressed, which every RIP reads) |
| `--faces`, `--face-strength 0..1`, `--face-color 0..1`, `--face-min-size PX` | restore faces with GFPGAN: how far to blend them in, how much of the picture's own colour they keep (default all), and the narrowest face to touch (default 32 px) |
| `--preview FX,FY --preview-size WxH` | render only a crop at 100% |
| `--mem MB` | working memory per band (default 1024); an estimate, not a hard limit |
| `--resume` | skip outputs already made by an identical job |
| `--selftest` | check that the installation works |

## Good to know

- **The preview is the print.** It runs the same code on the same tiles as the full run. It
  matches the full result to within one level (of 255) on about 0.01% of pixels, because of how
  Pillow rounds a resampling box.
- **CMYK and 16-bit are separate.** Pillow's colour engine is 8-bit, so a CMYK file is 8-bit; a
  16-bit file is RGB. CMYK input is converted through its embedded profile to sRGB, which can clip
  very saturated inks.
- **fp16 and the Neural Engine** are not bit-identical to the fp32 GPU path (about 52–60 dB PSNR
  against it). The Neural Engine pads picture borders differently, which measured closer to a
  reference made with real surrounding pixels.
- **Face recovery invents detail.** GFPGAN does not recover a face, it draws a plausible one. Tested
  against a known original: with the face 53 px wide in the picture it stays recognisably the same
  person, at 35 px it is plausible, at 26 px it becomes a different, younger-looking face. So faces
  narrower than 32 px are left alone, and the picture's own colours are kept (GFPGAN turned brown eyes
  blue in testing). Always compare the face with the original (the window shows both), and note that
  PSNR against the original goes *down* with it even where it looks better. It runs only when the print
  is larger than the picture, needs macOS (Apple Vision), and gives the same result every time.
  **Its licence has conditions** (parts of GFPGAN are for non-commercial use only; the weights are
  trained on FFHQ): see `NOTICE` before using it commercially. Nothing of it is shipped.
- **Not done yet:** resuming a print part-way (only whole finished outputs are skipped); a free-disk check. PNG and JPEG outputs are assembled in RAM, so use TIFF for huge prints.
- **The `.app` does not include the Neural Engine option** (coremltools is not bundled). It does include
  what face recovery needs apart from the 349 MB weights, which the window offers to download.

## The .app and .dmg

```sh
.venv/bin/pip install pyinstaller
packaging/build_app.sh          # writes dist/Mac Image Enhancer.app and dist/MacImageEnhancer-<version>-arm64.dmg
```

The app is signed **ad hoc**, which is what Apple Silicon needs to run a locally built app. It is
not signed with a Developer ID and not notarized, so a copy downloaded from the internet is
stopped by Gatekeeper: open it with right-click → Open the first time. A signed, notarized
release needs an Apple Developer account (`SIGN_ID=... packaging/build_app.sh`, then notarytool).
`packaging/homebrew/mac-image-enhancer.rb` is an untested cask template for when a release exists.

## Development

```sh
.venv/bin/python test_enhance.py    # the engine, colour, batches, preview (add coremltools to test Core ML)
.venv/bin/python test_gui.py        # interface text; the window part needs tkinter and a display
.venv/bin/python test_faces.py      # face recovery; MAC_IMAGE_ENHANCER_FACE_SAMPLE=portrait.jpg also runs the real Vision + GFPGAN
```

`CLAUDE.md` holds the design notes, measurements and known limits of every part.

## Licence and credits

MIT, see `LICENSE`. This is an independent, clean-room project: it reuses ideas that are free to
use and no code, text or assets of any other upscaler application.

It stands on [Real-ESRGAN](https://github.com/xinntao/Real-ESRGAN) (BSD-3-Clause; the networks and
the pre-trained weights this program downloads) and [spandrel](https://github.com/chaiNNer-org/spandrel)
(MIT; loads them), and uses PyTorch, NumPy, Pillow and tifffile. Optional face recovery uses
[GFPGAN](https://github.com/TencentARC/GFPGAN), with the alignment convention of
[facexlib](https://github.com/xinntao/facexlib) (MIT) and Apple Vision. Their licences, and the
conditions on GFPGAN, are in `NOTICE`.
