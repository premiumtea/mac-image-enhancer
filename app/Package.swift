// swift-tools-version: 5.9
import PackageDescription

// The macOS app: a SwiftUI window (Liquid Glass on macOS 26) that runs the Python engine
// (enhance.py, bundled as a command-line tool) for the actual upscaling.
let package = Package(
    name: "MacImageEnhancer",
    platforms: [.macOS(.v13)],
    products: [.executable(name: "MacImageEnhancer", targets: ["MacImageEnhancer"])],
    targets: [
        .executableTarget(name: "MacImageEnhancer", path: "Sources/MacImageEnhancer"),
        .testTarget(name: "MacImageEnhancerTests", dependencies: ["MacImageEnhancer"], path: "Tests/MacImageEnhancerTests"),
    ]
)
