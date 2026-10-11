**Mac Image Enhancer** is a native macOS app that enlarges a picture for printing with
[Real-ESRGAN](https://github.com/xinntao/Real-ESRGAN), on your own Mac. Tell it the paper size and quality, see the real
result for any area at 100% next to the plain enlargement, then save the print. On macOS 26 the window uses Apple's
Liquid Glass.

## What is new in __VERSION__

- **Fixed: saving several pictures at once saved only the first one**, while saying "Done". All of them are saved now.
- Several pictures: a strip of small pictures under the main one chooses which is shown and previewed.
- Light Mode: the window follows the system appearance (it was dark only).
- More paper sizes: 4×6, 5×7, 8×10 and 11×14 inches, A5.
- JPEG quality (Advanced). JPEG prints are now saved at quality 95 without colour subsampling; before, Pillow's default
  (75, colours at half resolution) was used, which is poor for a print.
- The Neural Engine (about 3× faster on big prints) is in the app: Advanced > Processor. The first use converts the model
  (a few seconds).
- Accessibility: every control has a name for VoiceOver, the preview frame and the before/after line work with the
  keyboard (arrow keys) and with VoiceOver's adjust.
- Fixed earlier in 0.1.1: the window staying on "working" after a failed job, and the language menu not redrawing.

## Install

1. Download `MacImageEnhancer-__VERSION__-arm64.dmg`, open it, and drag the app to Applications.
2. **This build is not signed with an Apple Developer ID and is not notarized**, so macOS stops it the first time.
   - macOS 15 and later: try to open the app once, then System Settings > Privacy & Security > scroll down > **Open Anyway**.
   - macOS 14 and earlier: right-click the app > Open > Open.
3. The first time you press Preview or Save, the app offers to download the AI model files (64 MB, from the Real-ESRGAN
   releases, checked against a SHA-256 before use). Nothing else is downloaded.

Check the download: `shasum -a 256 -c SHA256SUMS.txt` in the folder with both files.

## Good to know

- Apple Silicon only. Needs macOS 13 or later; it has been tried on macOS 26 only. On macOS 13 to 15 the glass becomes
  frosted material, which has not been looked at yet.
- Optional **face recovery** (a switch in the window) needs a further 349 MB download and *invents* detail, so compare
  with the original before printing. Its model has licence conditions (parts are for non-commercial use): read `NOTICE`
  before using it commercially.
- The Thai, Chinese and French texts are drafts; corrections are welcome.
- Everything the app does can also be done from the command line: see the README.

Licence: MIT. Built on Real-ESRGAN (BSD-3-Clause), spandrel (MIT), PyTorch, Pillow, NumPy and tifffile; see `NOTICE`.
