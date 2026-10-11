# Homebrew cask for the .dmg. NOT TESTED (never installed): version and sha256 below are those of the v0.2.0 release.
#
# To use it: upload dist/MacImageEnhancer-<version>-arm64.dmg to a release of
# github.com/premiumtea/mac-image-enhancer, and replace the sha256 with `shasum -a 256` of that file. Then host it in your own
# tap (a repo named homebrew-<something> with this file under Casks/) and run
#     brew install --cask <owner>/<tap>/mac-image-enhancer
# The app is only ad-hoc signed (see packaging/build_swift_app.sh), so macOS will stop it at first launch:
# open it with right-click > Open (macOS 15+: System Settings > Privacy & Security > Open Anyway), or install with --no-quarantine. As far as we know the official
# homebrew-cask repository expects signed and notarized apps; check its current policy before
# submitting there.
cask "mac-image-enhancer" do
  version "0.2.0"
  sha256 "b69afa4755ae8e8c7bfc3852eb3bd432e6c8d4634e44da3e9c729b160b964a22"

  url "https://github.com/premiumtea/mac-image-enhancer/releases/download/v#{version}/MacImageEnhancer-#{version}-arm64.dmg"
  name "Mac Image Enhancer"
  desc "AI print-size image upscaler for Apple Silicon"
  homepage "https://github.com/premiumtea/mac-image-enhancer"

  depends_on arch: :arm64
  depends_on macos: ">= :ventura"

  app "Mac Image Enhancer.app"

  zap trash: "~/Library/Application Support/mac-image-enhancer"
end
