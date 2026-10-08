import AppKit
import XCTest
@testable import MacImageEnhancer

/// A flat-colour picture of the given size.
func makeImage(_ w: Int, _ h: Int, red: CGFloat = 0.9, green: CGFloat = 0.2, blue: CGFloat = 0.1) -> CGImage {
    let ctx = CGContext(data: nil, width: w, height: h, bitsPerComponent: 8, bytesPerRow: 0, space: CGColorSpaceCreateDeviceRGB(),
                        bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue)!
    ctx.setFillColor(red: red, green: green, blue: blue, alpha: 1)
    ctx.fill(CGRect(x: 0, y: 0, width: w, height: h))
    return ctx.makeImage()!
}

@MainActor
final class AppModelTests: XCTestCase {
    var defaults: UserDefaults!
    let fakeEngine = EngineCommand(executable: URL(fileURLWithPath: "/bin/echo"), prefixArgs: [])

    override func setUp() {
        defaults = UserDefaults(suiteName: "test-\(UUID().uuidString)")
    }

    func makeModel(lang: String = "en", engine: EngineCommand? = nil) -> AppModel {
        AppModel(l10n: L10n(lang: lang), defaults: defaults, engine: engine)
    }

    func open(_ m: AppModel, _ w: Int, _ h: Int) {
        m.source = SourceImage(url: URL(fileURLWithPath: "/tmp/pic.jpg"), pixelWidth: w, pixelHeight: h, thumbnail: makeImage(w, h))
        m.images = [m.source!.url]
    }

    func testStartsOnA4Portrait() {
        let m = makeModel()
        XCTAssertEqual([m.preset, m.widthText, m.heightText, m.unit.rawValue, "\(m.dpi)"], ["A4", "21", "29.7", "cm", "200"])
        XCTAssertNil(m.plan)  // no picture, no plan
    }

    func testPaperTurnsToThePictureAndTypingMakesItCustom() {
        let m = makeModel()
        open(m, 40, 30)
        m.selectPreset("A4")
        XCTAssertEqual([m.widthText, m.heightText], ["29.7", "21"])  // a landscape picture gets a landscape sheet
        XCTAssertEqual(m.plan?.width, 2339)  // 29.7 cm at 200 dpi
        m.widthText = "10"
        XCTAssertEqual(m.preset, "custom")
        XCTAssertEqual(m.heightText, "7.5")  // follows the picture
        m.heightText = "5"  // now the person's own height: a width typed afterwards leaves it alone
        m.widthText = "12"
        XCTAssertEqual(m.heightText, "5")
        m.selectPreset("A3")  // a sheet takes both back
        XCTAssertEqual([m.widthText, m.heightText], ["42", "29.7"])
        m.selectPreset("custom")
        m.widthText = "20"
        XCTAssertEqual(m.heightText, "15")  // the picture's proportions again
    }

    func testChangingAnythingDropsAnOpenComparison() {
        let m = makeModel()
        open(m, 40, 30)
        let img = NSImage(size: NSSize(width: 4, height: 4))
        m.preview = PreviewResult(result: img, plain: img)
        m.compare = true
        m.dpi = 300
        XCTAssertFalse(m.compare)
        XCTAssertNil(m.preview)
        m.compare = true
        m.faces = true
        XCTAssertFalse(m.compare)
    }

    func testCollectRefusesWhatCannotWork() {
        let m = makeModel(engine: fakeEngine)
        XCTAssertNil(m.collect())
        XCTAssertEqual(m.statusText, "Error: Open a picture first.")
        open(m, 40, 30)
        m.widthText = "zero"
        XCTAssertNil(m.collect())
        XCTAssertEqual(m.statusText, "Error: Enter the print width and height as numbers greater than zero.")
        m.widthText = "29.7"
        m.heightText = "21"
        m.faces = true
        m.info = try? EngineInfo.decode(Data(#"{"version":"x","models_dir":"/m","groups":{},"face_min_px":32,"coreml":false,"vision":false}"#.utf8))
        XCTAssertNil(m.collect())
        XCTAssertEqual(m.statusText, "Error: Face recovery needs Apple Vision: install pyobjc-framework-Vision.")
        let noEngine = makeModel(engine: nil)
        open(noEngine, 40, 30)
        XCTAssertNil(noEngine.collect())
        XCTAssertTrue(noEngine.statusText.contains("missing"))
    }

    func testCollectBuildsTheEngineCommandLine() {
        let m = makeModel(engine: fakeEngine)
        open(m, 960, 640)
        m.preset = "custom"
        m.widthText = "45"
        m.heightText = "33.8"
        m.model = .general
        m.denoise = 0.25
        m.processor = .gpu16
        m.faces = true
        m.faceStrength = 0.5
        m.info = try? EngineInfo.decode(Data(#"{"version":"x","models_dir":"/m","groups":{},"face_min_px":32,"coreml":false,"vision":true}"#.utf8))
        let o = m.collect()!
        XCTAssertEqual(Array(o.args[1...]), ["--size", "45x33.8", "--unit", "cm", "--dpi", "200", "--model", "general", "--device", "gpu",
                                            "--engine", "gpu16", "--json", "--denoise", "0.25", "--faces", "--face-strength", "0.50"])
        XCTAssertEqual(o.groups, ["general", "faces"])  // 4x enlargement: the AI runs, so these files are needed
        XCTAssertFalse(o.tiff)
        m.bits16 = true
        m.processor = .auto
        XCTAssertTrue(m.collect()!.tiff)
        XCTAssertTrue(m.collect()!.args.contains("16"))
        // shrinking needs no AI, so no model files
        m.widthText = "5"
        m.heightText = "3.8"
        XCTAssertEqual(m.collect()!.groups, [])
    }

    func testSettingsRoundTripAndBadValuesAreDropped() {
        var s = Settings()
        s.preset = "A2"; s.width = "42"; s.dpi = 300; s.faces = true; s.faceStrength = 0.4; s.lang = "th"
        s.save(to: defaults)
        let back = Settings.load(from: defaults)
        XCTAssertEqual([back.preset, back.width, "\(back.dpi)", back.lang ?? ""], ["A2", "42", "300", "th"])
        XCTAssertTrue(back.faces); XCTAssertEqual(back.faceStrength, 0.4, accuracy: 1e-9)
        defaults.set(["preset": "A9", "unit": "parsec", "dpi": "many", "denoise": 7, "lang": "klingon", "width": "abc", "faces": "yes"], forKey: "settings.v1")
        XCTAssertEqual(Settings.load(from: defaults).preset, Settings().preset)
        XCTAssertEqual(Settings.load(from: defaults).unit, "cm")
        XCTAssertEqual(Settings.load(from: defaults).dpi, 200)
        XCTAssertNil(Settings.load(from: defaults).lang)
        XCTAssertEqual(Settings.load(from: defaults).width, "21")
        XCTAssertFalse(Settings.load(from: defaults).faces)
    }

    func testTimeLeft() {
        let m = makeModel()
        XCTAssertEqual(m.estimate(fraction: 0.5, spent: 30), "about 30 s left")
        XCTAssertEqual(m.estimate(fraction: 0.1, spent: 30), "about 5 min left")  // 270 s
        XCTAssertNil(m.estimate(fraction: 0.01, spent: 30))  // too early to say
        XCTAssertNil(m.estimate(fraction: 0.5, spent: 1))
    }

    func testStatusFollowsTheLanguage() {
        let m = makeModel(lang: "fr")
        m.fail("need_image")
        XCTAssertEqual(m.statusText, "Erreur : Ouvrez d’abord une image.")
        m.l10n.lang = "en"
        XCTAssertEqual(m.statusText, "Error: Open a picture first.")
    }

    func testOutputNames() {
        XCTAssertEqual(OutputName.fix("/x/a.png", tiffNeeded: false).path, "/x/a.png")
        XCTAssertEqual(OutputName.fix("/x/a.JPG", tiffNeeded: false).path, "/x/a.JPG")
        XCTAssertEqual(OutputName.fix("/x/a", tiffNeeded: false).path, "/x/a.png")
        XCTAssertEqual(OutputName.fix("/x/a.gif", tiffNeeded: false).path, "/x/a.gif.png")
        let r = OutputName.fix("/x/a.png", tiffNeeded: true)
        XCTAssertEqual(r.path, "/x/a.tif"); XCTAssertTrue(r.renamed)
        XCTAssertFalse(OutputName.fix("/x/a.tiff", tiffNeeded: true).renamed)
        XCTAssertFalse(OutputName.fix("/x/a", tiffNeeded: true).renamed)  // nothing was typed after the dot: nothing was renamed
    }
}

final class EngineTests: XCTestCase {
    func testEventLines() {
        XCTAssertEqual(EngineEvent(line: #"{"event": "progress", "fraction": 0.5}"#), .progress(0.5))
        XCTAssertEqual(EngineEvent(line: #"{"event": "job", "i": 2, "n": 3, "src": "/a.png", "dst": "/o/a.png"}"#), .job(i: 2, n: 3, src: "/a.png", dst: "/o/a.png"))
        XCTAssertEqual(EngineEvent(line: #"{"event": "download", "name": "x.pth", "done": 10, "total": 20}"#), .download(name: "x.pth", done: 10, total: 20))
        XCTAssertEqual(EngineEvent(line: #"{"event": "done", "outputs": ["/o/a.png"], "skipped": 0, "failed": []}"#), .done(outputs: ["/o/a.png"], skipped: 0, failed: []))
        XCTAssertEqual(EngineEvent(line: #"{"event": "error", "message": "boom"}"#), .error("boom"))
        XCTAssertEqual(EngineEvent(line: #"{"event": "cancelled"}"#), .cancelled)
        XCTAssertNil(EngineEvent(line: "device=mps engine=gpu passes=1"))  // a log line, not an event
        XCTAssertNil(EngineEvent(line: #"{"event": "mystery"}"#))
        XCTAssertNil(EngineEvent(line: ""))
    }

    func testInfoDecodes() throws {
        let json = #"{"version":"0.1.0","models_dir":"/m","groups":{"photo":{"files":["a.pth"],"missing":["a.pth"],"missing_bytes":67040989}},"face_min_px":32,"coreml":false,"vision":true}"#
        let info = try EngineInfo.decode(Data(json.utf8))
        XCTAssertEqual(info.groups["photo"]?.missingBytes, 67040989)
        XCTAssertTrue(info.vision); XCTAssertFalse(info.coreml); XCTAssertEqual(info.faceMinPx, 32)
    }

    /// With a real engine (a checkout's venv, or $MAC_IMAGE_ENHANCER_ENGINE): the whole round trip.
    func testRealEngine() async throws {
        guard let cmd = EngineCommand.locate() else { throw XCTSkip("no engine here") }
        let info = try await Engine.info(command: cmd)
        XCTAssertFalse(info.version.isEmpty)
        XCTAssertNotNil(info.groups["photo"])
        let run = try EngineRun(command: cmd, arguments: ["/no/such/picture.png", "--size", "5", "--json", "-o", NSTemporaryDirectory() + "x.png"])
        var events: [EngineEvent] = []
        for await e in run.events { events.append(e) }
        let code = await run.waitUntilExit()
        XCTAssertNotEqual(code, 0)
        guard case .error(let message)? = events.last else { return XCTFail("expected an error event, got \(events)") }
        XCTAssertFalse(message.isEmpty)
    }
}

final class ImageToolsTests: XCTestCase {
    func pixel(_ image: NSImage) -> [UInt8] {
        let cg = image.cgImage(forProposedRect: nil, context: nil, hints: nil)!
        let ctx = CGContext(data: nil, width: 1, height: 1, bitsPerComponent: 8, bytesPerRow: 4, space: CGColorSpaceCreateDeviceRGB(),
                            bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue)!
        ctx.draw(cg, in: CGRect(x: 0, y: 0, width: 1, height: 1))
        let p = ctx.data!.assumingMemoryBound(to: UInt8.self)
        return [p[0], p[1], p[2]]
    }

    func testLoadedPixelsSurviveDeletingTheFile() throws {
        let url = FileManager.default.temporaryDirectory.appendingPathComponent("tool-test-\(UUID().uuidString).png")
        let rep = NSBitmapImageRep(cgImage: makeImage(8, 6, red: 1, green: 0, blue: 0))
        try rep.representation(using: .png, properties: [:])!.write(to: url)
        let img = try XCTUnwrap(ImageTools.loadPixels(url))
        try FileManager.default.removeItem(at: url)  // the app deletes preview files as soon as they are loaded
        XCTAssertEqual(img.size, NSSize(width: 8, height: 6))
        let p = pixel(img)
        XCTAssertGreaterThan(p[0], 200); XCTAssertLessThan(p[1], 50)  // still red, not black
    }

    func testLoadReadsSizeAndOrientation() throws {
        let url = FileManager.default.temporaryDirectory.appendingPathComponent("tool-test-\(UUID().uuidString).png")
        try NSBitmapImageRep(cgImage: makeImage(40, 30)).representation(using: .png, properties: [:])!.write(to: url)
        defer { try? FileManager.default.removeItem(at: url) }
        let s = try XCTUnwrap(ImageTools.load(url: url))
        XCTAssertEqual([s.pixelWidth, s.pixelHeight], [40, 30])
        XCTAssertNil(ImageTools.load(url: URL(fileURLWithPath: "/etc/hosts")))  // not a picture
    }

    func testCropFollowsThePlan() {
        let thumb = makeImage(200, 150)  // a 400 x 300 picture, shown at half size
        let plan = PrintMath.plan(sourceWidth: 400, sourceHeight: 300, width: 10, height: 10, unit: .cm, dpi: 100)!  // square: crops the sides
        let c = ImageTools.cropped(thumb, source: (400, 300), plan: plan)
        XCTAssertEqual([c.width, c.height], [150, 150])
    }
}
