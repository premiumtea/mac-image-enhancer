import AppKit
import XCTest
@testable import MacImageEnhancer

/// The window's whole flows through the real engine, with a tiny made-up model so they take seconds:
/// open a picture, Preview (before/after), Save, and Cancel. Skipped where there is no engine or no torch.
@MainActor
final class FlowTests: XCTestCase {
    var dir: URL!
    var model: AppModel!

    override func setUp() async throws {
        guard let cmd = EngineCommand.locate() else { throw XCTSkip("no engine here") }
        dir = FileManager.default.temporaryDirectory.appendingPathComponent("flow-\(UUID().uuidString)")
        let models = dir.appendingPathComponent("models")
        try FileManager.default.createDirectory(at: models, withIntermediateDirectories: true)
        // tiny random weights under the general model's file name, made by the engine's own Python
        let make = Process()
        make.executableURL = cmd.executable
        make.arguments = cmd.prefixArgs.isEmpty ? ["-c", "pass"] : [cmd.executable.path == cmd.prefixArgs[0] ? "-c" : "-c", """
        import sys, torch
        from spandrel.architectures.Compact.__arch.SRVGG import SRVGGNetCompact
        torch.manual_seed(0)
        net = SRVGGNetCompact(num_feat=8, num_conv=2, upscale=4, act_type="prelu")
        torch.save({"params": net.state_dict()}, sys.argv[1])
        """, models.appendingPathComponent("realesr-general-x4v3.pth").path]
        make.standardError = FileHandle.nullDevice
        try make.run()
        make.waitUntilExit()
        guard make.terminationStatus == 0 else { throw XCTSkip("no torch/spandrel for the engine's Python") }
        setenv("MAC_IMAGE_ENHANCER_MODELS", models.path, 1)

        let pic = dir.appendingPathComponent("pic.png")
        try NSBitmapImageRep(cgImage: noisy(40, 30)).representation(using: .png, properties: [:])!.write(to: pic)
        model = AppModel(l10n: L10n(lang: "en"), defaults: UserDefaults(suiteName: "flow-\(UUID().uuidString)")!, engine: cmd, loadInfo: false)
        model.load([pic])
        try await wait { self.model.source != nil }
        model.preset = "custom"
        model.widthText = "2"
        model.unit = .inch
        model.dpi = 100
        model.model = .general
        model.denoise = 1.0
        model.processor = .cpu
        // (loadInfo: false above: the tiny weights file is not the real size, so the engine would offer to download them)
    }

    override func tearDown() async throws {
        unsetenv("MAC_IMAGE_ENHANCER_MODELS")
        if let dir { try? FileManager.default.removeItem(at: dir) }
    }

    func noisy(_ w: Int, _ h: Int) -> CGImage {
        var px = [UInt8](repeating: 0, count: w * h * 4)
        var g = SystemRandomNumberGenerator()
        for i in 0..<px.count { px[i] = i % 4 == 3 ? 255 : UInt8.random(in: 0...255, using: &g) }
        let ctx = CGContext(data: &px, width: w, height: h, bitsPerComponent: 8, bytesPerRow: w * 4, space: CGColorSpaceCreateDeviceRGB(),
                            bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue)!
        return ctx.makeImage()!
    }

    func wait(timeout: TimeInterval = 150, _ cond: @escaping () -> Bool) async throws {
        let t0 = Date()
        while !cond() {
            if Date().timeIntervalSince(t0) > timeout { XCTFail("timed out waiting"); throw CancellationError() }
            try await Task.sleep(nanoseconds: 50_000_000)
        }
    }

    func testPreviewThenSaveThenCancel() async throws {
        XCTAssertEqual(model.plan?.width, 200)  // 2 in x 100 dpi, the height follows the 4:3 picture
        XCTAssertEqual(model.plan?.height, 150)

        // Preview: the real result next to the plain enlargement, the size of the whole (small) print
        model.startPreview()
        XCTAssertEqual(model.phase, .preview)
        try await wait { self.model.phase == .idle }
        XCTAssertTrue(model.compare, model.statusText)
        XCTAssertEqual(model.preview?.result.size, NSSize(width: 200, height: 150))
        XCTAssertEqual(model.preview?.plain.size, NSSize(width: 200, height: 150))
        XCTAssertEqual(model.status.key, "ready")

        // changing a setting while a comparison is open closes it; a preview that finishes after one is dropped
        model.dpi = 150
        XCTAssertFalse(model.compare)
        model.startPreview()
        model.dpi = 100
        try await wait { self.model.phase == .idle }
        XCTAssertFalse(model.compare)

        // Save: one picture, to the file a person chose; 16-bit forces TIFF and says so
        let out = dir.appendingPathComponent("print.png")
        let o = try XCTUnwrap(model.collect())
        model.runSave(o, destination: out, single: true)
        XCTAssertEqual(model.phase, .save)
        try await wait { self.model.phase == .idle }
        XCTAssertEqual(model.status.key, "done", model.statusText)
        XCTAssertEqual(model.lastOutput, out)
        let img = NSBitmapImageRep(data: try Data(contentsOf: out))
        XCTAssertEqual([img?.pixelsWide, img?.pixelsHigh], [200, 150])

        model.bits16 = true
        let deep = dir.appendingPathComponent("deep.png")
        model.runSave(try XCTUnwrap(model.collect()), destination: deep, single: true)
        try await wait { self.model.phase == .idle }
        XCTAssertEqual(model.status.key, "tiff_renamed")
        XCTAssertTrue(FileManager.default.fileExists(atPath: dir.appendingPathComponent("deep.tif").path))
        XCTAssertFalse(FileManager.default.fileExists(atPath: deep.path))
        model.bits16 = false

        // Cancel: a big print, stopped once it is under way; nothing is left behind
        model.extraEngineArguments = ["--tile", "16"]  // thousands of small steps: plenty left to cancel after the first one
        model.widthText = "40"  // 4000 x 3000 px
        let big = dir.appendingPathComponent("big.tif")
        model.bits16 = true
        model.runSave(try XCTUnwrap(model.collect()), destination: big, single: true)
        try await wait { self.model.phase == .save && self.model.progress > 0 }
        model.cancel()
        try await wait(timeout: 60) { self.model.phase == .idle }
        XCTAssertEqual(model.status.key, "cancelled", model.statusText)
        XCTAssertFalse(FileManager.default.fileExists(atPath: big.path))
        XCTAssertTrue(((try? FileManager.default.contentsOfDirectory(atPath: dir.path)) ?? []).allSatisfy { !$0.hasSuffix(".partial") })

        // a failing job reports the engine's own words
        model.bits16 = false
        model.widthText = "2"
        try FileManager.default.removeItem(at: model.images[0])
        model.startPreview()
        try await wait { self.model.phase == .idle }
        XCTAssertTrue(model.status.isError)
    }
}
