# Homebrew cask for the .dmg. TEMPLATE, NOT TESTED: it needs a published GitHub release.
#
# To use it: upload dist/MacImageEnhancer-<version>-arm64.dmg to a release of
# github.com/premiumtea/mac-image-enhancer, and replace the sha256 with `shasum -a 256` of that file. Then host it in your own
# tap (a repo named homebrew-<something> with this file under Casks/) and run
#     brew install --cask <owner>/<tap>/mac-image-enhancer
# The app is only ad-hoc signed (see packaging/build_app.sh), so macOS will stop it at first launch:
# open it with right-click > Open, or install with --no-quarantine. As far as we know the official
# homebrew-cask repository expects signed and notarized apps; check its current policy before
# submitting there.
cask "mac-image-enhancer" do
  version "0.1.0"
  sha256 "REPLACE_WITH_THE_SHA256_OF_THE_RELEASED_DMG"

  url "https://github.com/premiumtea/mac-image-enhancer/releases/download/v#{version}/MacImageEnhancer-#{version}-arm64.dmg"
  name "Mac Image Enhancer"
  desc "AI print-size image upscaler for Apple Silicon"
  homepage "https://github.com/premiumtea/mac-image-enhancer"

  depends_on arch: :arm64
  depends_on macos: ">= :ventura"

  app "Mac Image Enhancer.app"

  zap trash: "~/Library/Application Support/mac-image-enhancer"
end
