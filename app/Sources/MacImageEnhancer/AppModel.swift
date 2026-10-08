import AppKit
import Combine
import SwiftUI
import UniformTypeIdentifiers

enum PictureModel: String, CaseIterable, Identifiable {
    case photo, general
    var id: String { rawValue }
    var stringKey: String { "model_" + rawValue }
}

enum Processor: String, CaseIterable, Identifiable {
    case auto, cpu, gpu, gpu16, ane
    var id: String { rawValue }
    var engine: String { self == .gpu16 ? "gpu16" : self == .ane ? "ane" : "gpu" }
    var device: String { self == .cpu ? "cpu" : (self == .gpu || self == .gpu16) ? "gpu" : "auto" }
    var stringKey: String { "proc_" + rawValue }
}

enum Phase { case idle, preview, save, download }

/// A line for the status area. It keeps text *keys*, so it follows a change of language.
struct Status {
    var key: String
    var args: [String: Any] = [:]
    var msgKey: String? = nil
    var msgArgs: [String: Any] = [:]
    var isError: Bool { key == "error" }
    static let ready = Status(key: "ready")
}

struct PreviewResult {
    let result: NSImage
    let plain: NSImage
}

struct PendingDownload {
    let groups: [String]
    let bytes: Int
    let includesFaces: Bool
    let then: () -> Void
}

/// What the engine is asked to do, checked and ready.
struct JobOptions {
    var args: [String]
    var needsAI: Bool
    var groups: [String]
    var tiff: Bool
}

@MainActor
final class AppModel: ObservableObject {
    let l10n: L10n
    private let defaults: UserDefaults
    var engineCommand: EngineCommand?

    // MARK: the choices (saved between runs)
    @Published var preset: String
    // (a text field writes its text back when it loses focus, even if unchanged: that is not typing)
    @Published var widthText: String { didSet { if !quiet && widthText != oldValue { sizeEdited(.width) } } }
    @Published var heightText: String { didSet { if !quiet && heightText != oldValue { sizeEdited(.height) } } }
    @Published var unit: Unit { didSet { optionChanged() } }
    @Published var dpi: Int { didSet { optionChanged() } }
    @Published var model: PictureModel { didSet { optionChanged() } }
    @Published var denoise: Double { didSet { optionChanged() } }
    @Published var processor: Processor
    @Published var faces: Bool { didSet { optionChanged() } }
    @Published var faceStrength: Double { didSet { optionChanged() } }
    @Published var bits16: Bool
    @Published var cmykPath: String?
    @Published var compress: Bool
    var lastDir: String?

    // MARK: the picture and what is shown of it
    @Published var images: [URL] = []
    @Published var source: SourceImage?
    @Published var center = CGPoint(x: 0.5, y: 0.5)
    @Published var stageSize = CGSize(width: 700, height: 520)
    @Published var preview: PreviewResult?
    @Published var compare = false
    @Published var split = 0.5
    @Published var dropTargeted = false

    // MARK: what is running
    @Published var phase: Phase = .idle
    @Published var progress = 0.0
    @Published var status = Status.ready
    @Published var etaText: String?
    @Published var lastOutput: URL?
    @Published var pendingDownload: PendingDownload?
    @Published var showAdvanced = false
    @Published var info: EngineInfo?

    private var quiet = false
    private var heightManual = false
    private var optionGen = 0
    private var startedAt = Date()
    private var current: EngineRun?
    private var cancelRequested = false
    private var bag = Set<AnyCancellable>()
    let tempDir: URL

    var busy: Bool { phase != .idle }
    var backingScale: CGFloat { NSScreen.main?.backingScaleFactor ?? 2 }

    // MARK: setup

    init(l10n: L10n, defaults: UserDefaults = .standard, engine: EngineCommand? = EngineCommand.locate(), loadInfo: Bool = true) {
        self.l10n = l10n
        self.defaults = defaults
        self.engineCommand = engine
        let s = Settings.load(from: defaults)
        preset = s.preset
        widthText = s.width
        heightText = s.height
        unit = Unit(rawValue: s.unit) ?? .cm
        dpi = s.dpi
        model = PictureModel(rawValue: s.model) ?? .photo
        denoise = s.denoise
        processor = Processor(rawValue: s.processor) ?? .auto
        faces = s.faces
        faceStrength = s.faceStrength
        bits16 = s.bits16
        compress = s.compress
        lastDir = s.lastDir
        tempDir = FileManager.default.temporaryDirectory.appendingPathComponent("mac-image-enhancer-\(ProcessInfo.processInfo.processIdentifier)")
        try? FileManager.default.createDirectory(at: tempDir, withIntermediateDirectories: true)
        objectWillChange.debounce(for: .seconds(1), scheduler: RunLoop.main).sink { [weak self] in self?.persist() }.store(in: &bag)
        applyPreset()
        if loadInfo { refreshInfo() }
    }

    func refreshInfo() {
        guard let cmd = engineCommand else { return }
        Task {
            if let i = try? await Engine.info(command: cmd) { info = i }
        }
    }

    func persist() {
        Settings(lang: l10n.lang, preset: preset, width: widthText, height: heightText, unit: unit.rawValue, dpi: dpi,
                 model: model.rawValue, denoise: denoise, processor: processor.rawValue, faces: faces,
                 faceStrength: faceStrength, bits16: bits16, compress: compress, lastDir: lastDir).save(to: defaults)
    }

    func shutdown() {
        current?.cancel()
        persist()
        try? FileManager.default.removeItem(at: tempDir)
    }

    // MARK: text

    func t(_ key: String, _ args: [String: Any] = [:]) -> String { l10n.t(key, args) }

    var statusText: String {
        var args = status.args
        if let k = status.msgKey { args["msg"] = l10n.t(k, status.msgArgs) }
        return l10n.t(status.key, args)
    }

    func setStatus(_ key: String, _ args: [String: Any] = [:]) { status = Status(key: key, args: args) }
    @discardableResult func fail(_ msgKey: String, _ msgArgs: [String: Any] = [:]) -> Bool {
        status = Status(key: "error", msgKey: msgKey, msgArgs: msgArgs)
        return false
    }
    func failRaw(_ message: String) { status = Status(key: "error", args: ["msg": message]) }

    // MARK: the size

    var sourceSize: (w: Int, h: Int)? { source.map { ($0.pixelWidth, $0.pixelHeight) } }

    var plan: PrintPlan? {
        guard let s = source, let w = PrintMath.parseNumber(widthText), let h = PrintMath.parseNumber(heightText) else { return nil }
        return PrintMath.plan(sourceWidth: s.pixelWidth, sourceHeight: s.pixelHeight, width: w, height: h, unit: unit, dpi: dpi)
    }

    var widthValue: Double? { PrintMath.parseNumber(widthText) }
    var heightValue: Double? { PrintMath.parseNumber(heightText) }

    var isLandscape: Bool { (sourceSize.map { $0.w > $0.h } ?? false) }

    private enum Side { case width, height }

    private func setQuietly(_ body: () -> Void) {
        quiet = true
        body()
        quiet = false
    }

    func selectPreset(_ id: String) {
        preset = id
        heightManual = false
        applyPreset()
        optionChanged()
    }

    /// Puts the chosen paper size in the fields, turned to match the picture.
    func applyPreset() {
        guard let p = Preset.all.first(where: { $0.id == preset }) else { return }
        let (w, h) = p.size(forSource: sourceSize)
        setQuietly {
            widthText = PrintMath.formatNumber(w)
            heightText = PrintMath.formatNumber(h)
            unit = p.unit
        }
    }

    /// A size field was typed in: the size is now the person's own. Until a height is typed it follows the
    /// picture's proportions, so the whole picture is printed.
    private func sizeEdited(_ side: Side) {
        if preset != "custom" { preset = "custom" }
        if side == .height {
            heightManual = true
        } else if !heightManual, let s = sourceSize, let w = PrintMath.parseNumber(widthText) {
            setQuietly { heightText = PrintMath.formatNumber(w * Double(s.h) / Double(s.w)) }
        }
        optionChanged()
    }

    /// Anything the picture depends on changed: an open comparison no longer shows it, and a running preview must not show up as if it did.
    func optionChanged() {
        optionGen += 1
        if compare {
            compare = false
            preview = nil
        }
    }

    func setUnit(_ u: Unit) {
        // converting the numbers would hide what the person typed: the unit just changes
        unit = u
    }

    // MARK: opening pictures

    func load(_ urls: [URL]) {
        let files = urls.filter { ImageTools.isImage($0) || (try? $0.resourceValues(forKeys: [.isRegularFileKey]).isRegularFile) == true }
        guard let first = files.first else { return }
        Task {
            let loaded = await Task.detached { ImageTools.load(url: first) }.value
            guard let img = loaded else {
                failRaw("\(first.lastPathComponent)")
                return
            }
            images = files
            source = img
            lastDir = first.deletingLastPathComponent().path
            center = CGPoint(x: 0.5, y: 0.5)
            preview = nil
            compare = false
            lastOutput = nil
            setStatus("ready")
            if Preset.all.contains(where: { $0.id == preset }) {
                applyPreset()
            } else if !heightManual, let w = PrintMath.parseNumber(widthText) {
                setQuietly { heightText = PrintMath.formatNumber(w * Double(img.pixelHeight) / Double(img.pixelWidth)) }
            }
            optionChanged()
        }
    }

    func chooseImages() {
        let panel = NSOpenPanel()
        panel.allowsMultipleSelection = true
        panel.canChooseDirectories = false
        panel.allowedContentTypes = [.image]
        if let d = lastDir { panel.directoryURL = URL(fileURLWithPath: d) }
        if panel.runModal() == .OK { load(panel.urls) }
    }

    func chooseProfile() {
        let panel = NSOpenPanel()
        panel.allowsMultipleSelection = false
        panel.canChooseDirectories = false
        panel.allowedContentTypes = ["icc", "icm"].compactMap { UTType(filenameExtension: $0) }
        if panel.runModal() == .OK, let u = panel.url {
            cmykPath = u.path
            bits16 = false
        }
    }

    // MARK: what the engine is asked

    /// The preview area in print pixels: what the stage can show at true size, within limits.
    var previewPx: (w: Int, h: Int) {
        let s = Double(backingScale)
        return (Int(min(max(stageSize.width * s, 240), 1280)), Int(min(max(stageSize.height * s, 180), 960)))
    }

    func collect() -> JobOptions? {
        guard let img = images.first else { fail("need_image"); return nil }
        guard let w = widthValue, let h = heightValue else { fail("need_size"); return nil }
        guard dpi >= 1 else { fail("need_dpi"); return nil }
        guard engineCommand != nil else { fail("engine_missing"); return nil }
        if faces && info?.vision == false { fail("faces_unavailable"); return nil }
        var a = [img.path, "--size", "\(PrintMath.g(w))x\(PrintMath.g(h))", "--unit", unit.rawValue, "--dpi", "\(dpi)",
                 "--model", model.rawValue, "--device", processor.device, "--engine", processor.engine, "--json"]
        if model == .general { a += ["--denoise", String(format: "%.2f", denoise)] }
        if faces { a += ["--faces", "--face-strength", String(format: "%.2f", faceStrength)] }
        if bits16 { a += ["--bits", "16"] }
        if let c = cmykPath { a += ["--cmyk-profile", c] }
        if compress { a += ["--tiff-compress"] }
        let needsAI = (plan?.passes ?? 0) > 0
        return JobOptions(args: a, needsAI: needsAI, groups: needsAI ? [model.rawValue] + (faces ? ["faces"] : []) : [], tiff: bits16 || cmykPath != nil)
    }

    // MARK: running the engine

    private enum Outcome { case done([String], skipped: Int, failed: [String]), cancelled, failed(String) }

    private func runEngine(_ arguments: [String], handle: (EngineEvent) -> Void) async -> Outcome {
        guard let cmd = engineCommand else { return .failed(t("engine_missing")) }
        let run: EngineRun
        do { run = try EngineRun(command: cmd, arguments: arguments) } catch { return .failed(error.localizedDescription) }
        current = run
        var terminal: EngineEvent?
        for await ev in run.events {
            handle(ev)
            switch ev {
            case .done, .error, .cancelled: terminal = ev
            default: break
            }
        }
        let code = await run.waitUntilExit()
        current = nil
        switch terminal {
        case .done(let outputs, let skipped, let failed): return .done(outputs, skipped: skipped, failed: failed)
        case .cancelled: return .cancelled
        case .error(let m): return .failed(m)
        default:
            if cancelRequested { return .cancelled }
            return code == 0 ? .done([], skipped: 0, failed: []) : .failed(run.stderrTail.split(separator: "\n").last.map(String.init) ?? "exit code \(code)")
        }
    }

    private func begin(_ p: Phase) {
        phase = p
        progress = 0
        etaText = nil
        cancelRequested = false
        startedAt = Date()
        lastOutput = nil
    }

    private func end() {
        phase = .idle
        etaText = nil
    }

    /// Time left, once there is enough to go on.
    func estimate(fraction: Double, spent: TimeInterval) -> String? {
        guard fraction >= 0.03, spent >= 4 else { return nil }
        let left = spent * (1 - fraction) / fraction
        return left < 90 ? t("eta_sec", ["s": max(Int(left), 1)]) : t("eta_min", ["m": Int((left / 60).rounded())])
    }

    private func advance(_ fraction: Double, statusKey: String, args: [String: Any]) {
        progress = fraction
        etaText = estimate(fraction: fraction, spent: Date().timeIntervalSince(startedAt))
        setStatus(statusKey, args)
    }

    func cancel() {
        cancelRequested = true
        current?.cancel()
    }

    /// Runs `then` once the model files the job needs are on this Mac; asks before downloading missing ones.
    private func ensureWeights(_ o: JobOptions, then: @escaping () -> Void) {
        let lacking = o.groups.filter { !(info?.groups[$0]?.missing.isEmpty ?? true) }
        if lacking.isEmpty { then(); return }
        let bytes = lacking.reduce(0) { $0 + (info?.groups[$1]?.missingBytes ?? 0) }
        pendingDownload = PendingDownload(groups: lacking, bytes: bytes, includesFaces: lacking.contains("faces"), then: then)
    }

    func answerDownload(_ yes: Bool) {
        guard let p = pendingDownload else { return }
        pendingDownload = nil
        guard yes else { fail("weights_declined"); return }
        begin(.download)
        Task {
            for g in p.groups {
                let outcome = await runEngine(["--download-models", g, "--json"]) { ev in
                    if case .download(let name, let done, let total) = ev, total > 0 {
                        advance(Double(done) / Double(total), statusKey: "downloading", args: ["name": name, "pct": Int(100 * done / total)])
                    }
                }
                switch outcome {
                case .done: continue
                case .cancelled: end(); setStatus("cancelled"); return
                case .failed(let m): end(); failRaw(m); return
                }
            }
            end()
            if let cmd = engineCommand, let i = try? await Engine.info(command: cmd) { info = i }
            setStatus("ready")
            p.then()
        }
    }

    // MARK: preview

    func startPreview() {
        guard phase == .idle, source != nil else {
            if source == nil { fail("need_image") }
            return
        }
        setStatus("ready")
        guard var o = collect() else { return }
        let gen = optionGen
        let (pw, ph) = previewPx
        let tag = UUID().uuidString.prefix(8)
        let resultURL = tempDir.appendingPathComponent("preview-\(tag).png")
        let plainURL = tempDir.appendingPathComponent("plain-\(tag).png")
        // a preview is always 8-bit RGB
        o.args = strip(o.args, flags: ["--bits", "--cmyk-profile"], switches: ["--tiff-compress"])
        o.args += ["--preview", String(format: "%.4f,%.4f", center.x, center.y), "--preview-size", "\(pw)x\(ph)",
                   "--preview-plain", plainURL.path, "-o", resultURL.path]
        let args = o.args
        ensureWeights(o) { [self] in
            begin(.preview)  // right away, not inside the task: a second click must find the window busy
            Task {
                let outcome = await runEngine(args) { ev in
                    if case .progress(let f) = ev { advance(f, statusKey: "working", args: ["pct": Int(100 * f)]) }
                }
                end()
                switch outcome {
                case .done:
                    setStatus("ready")
                    if gen == optionGen, let r = ImageTools.loadPixels(resultURL), let p = ImageTools.loadPixels(plainURL) {
                        preview = PreviewResult(result: r, plain: p)
                        split = 0.5
                        compare = true
                    }
                case .cancelled: setStatus("cancelled")
                case .failed(let m): failRaw(m)
                }
                try? FileManager.default.removeItem(at: resultURL)
                try? FileManager.default.removeItem(at: plainURL)
            }
        }
    }

    private func strip(_ args: [String], flags: Set<String>, switches: Set<String>) -> [String] {
        var out: [String] = []
        var skip = false
        for a in args {
            if skip { skip = false; continue }
            if flags.contains(a) { skip = true; continue }
            if switches.contains(a) { continue }
            out.append(a)
        }
        return out
    }

    func backToPicking() {
        compare = false
    }

    // MARK: saving

    func save() {
        guard phase == .idle else { return }
        guard let o = collect() else { return }
        if images.count == 1 {
            let panel = NSSavePanel()
            let stem = images[0].deletingPathExtension().lastPathComponent
            let ext = o.tiff ? "tif" : "png"
            panel.title = t("save_title")
            panel.nameFieldStringValue = "\(stem)-print.\(ext)"
            panel.allowedContentTypes = [.png, .tiff, .jpeg]
            panel.canCreateDirectories = true
            if let d = lastDir { panel.directoryURL = URL(fileURLWithPath: d) }
            if panel.runModal() == .OK, let u = panel.url { runSave(o, destination: u, single: true) }
        } else {
            let panel = NSOpenPanel()
            panel.title = t("choose_output")
            panel.canChooseFiles = false
            panel.canChooseDirectories = true
            panel.canCreateDirectories = true
            panel.allowsMultipleSelection = false
            if let d = lastDir { panel.directoryURL = URL(fileURLWithPath: d) }
            if panel.runModal() == .OK, let u = panel.url { runSave(o, destination: u, single: false) }
        }
    }

    func runSave(_ o: JobOptions, destination: URL, single: Bool) {
        var out = destination.path + "/"
        var renamed = false
        if single {
            let fixed = OutputName.fix(destination.path, tiffNeeded: o.tiff)
            out = fixed.path
            renamed = fixed.renamed
        }
        lastDir = (single ? destination.deletingLastPathComponent() : destination).path
        let args = o.args + ["-o", out]
        ensureWeights(o) { [self] in
            begin(.save)
            Task {
                var job = (i: 1, n: images.count, name: images.first?.lastPathComponent ?? "")
                let outcome = await runEngine(args) { ev in
                    switch ev {
                    case .job(let i, let n, let src, _): job = (i, n, URL(fileURLWithPath: src).lastPathComponent)
                    case .progress(let f):
                        let overall = (Double(job.i - 1) + f) / Double(max(job.n, 1))
                        if job.n > 1 {
                            advance(overall, statusKey: "working_file", args: ["i": job.i, "n": job.n, "name": job.name, "pct": Int(100 * f)])
                        } else {
                            advance(overall, statusKey: "working", args: ["pct": Int(100 * f)])
                        }
                    default: break
                    }
                }
                end()
                switch outcome {
                case .done(let outputs, _, let failed):
                    progress = 1
                    lastOutput = single ? URL(fileURLWithPath: outputs.first ?? out) : destination
                    if renamed { setStatus("tiff_renamed") }
                    else { setStatus(failed.isEmpty ? "done" : "done_skipped", ["n": max(job.n - failed.count, 0), "k": failed.count]) }
                case .cancelled: progress = 0; setStatus("cancelled")
                case .failed(let m): progress = 0; failRaw(m)
                }
            }
        }
    }

    func reveal() {
        guard let u = lastOutput else { return }
        var isDir: ObjCBool = false
        if FileManager.default.fileExists(atPath: u.path, isDirectory: &isDir), isDir.boolValue {
            NSWorkspace.shared.open(u)
        } else {
            NSWorkspace.shared.activateFileViewerSelecting([u])
        }
    }
}

/// The file name a person typed in the save dialog: an extension we can write, and .tif when 16-bit colour or CMYK is on.
enum OutputName {
    static let writable: Set<String> = ["png", "tif", "tiff", "jpg", "jpeg"]

    static func fix(_ path: String, tiffNeeded: Bool) -> (path: String, renamed: Bool) {
        let url = URL(fileURLWithPath: path)
        let ext = url.pathExtension.lowercased()
        if tiffNeeded {
            if ext == "tif" || ext == "tiff" { return (path, false) }
            let stem = ext.isEmpty ? path : url.deletingPathExtension().path
            return (stem + ".tif", !ext.isEmpty)
        }
        return writable.contains(ext) ? (path, false) : (path + ".png", false)
    }
}

/// The choices kept between runs.
struct Settings {
    var lang: String?
    var preset = "A4"
    var width = "21"
    var height = "29.7"
    var unit = "cm"
    var dpi = 200
    var model = "photo"
    var denoise = 0.5
    var processor = "auto"
    var faces = false
    var faceStrength = 1.0
    var bits16 = false
    var compress = false
    var lastDir: String?

    private static let key = "settings.v1"

    static func load(from d: UserDefaults) -> Settings {
        var s = Settings()
        guard let saved = d.dictionary(forKey: key) else { return s }
        func str(_ k: String) -> String? { saved[k] as? String }
        s.lang = str("lang").flatMap { Strings.table[$0] != nil ? $0 : nil }
        if let v = str("preset"), v == "custom" || Preset.all.contains(where: { $0.id == v }) { s.preset = v }
        if let v = str("width"), PrintMath.parseNumber(v) != nil { s.width = v }
        if let v = str("height"), PrintMath.parseNumber(v) != nil { s.height = v }
        if let v = str("unit"), Unit(rawValue: v) != nil { s.unit = v }
        if let v = saved["dpi"] as? Int, (1...2400).contains(v) { s.dpi = v }
        if let v = str("model"), PictureModel(rawValue: v) != nil { s.model = v }
        if let v = saved["denoise"] as? Double, (0...1).contains(v) { s.denoise = v }
        if let v = str("processor"), Processor(rawValue: v) != nil { s.processor = v }
        if let v = saved["faces"] as? Bool { s.faces = v }
        if let v = saved["faceStrength"] as? Double, (0...1).contains(v) { s.faceStrength = v }
        if let v = saved["bits16"] as? Bool { s.bits16 = v }
        if let v = saved["compress"] as? Bool { s.compress = v }
        s.lastDir = str("lastDir")
        return s
    }

    func save(to d: UserDefaults) {
        var m: [String: Any] = ["preset": preset, "width": width, "height": height, "unit": unit, "dpi": dpi, "model": model,
                                "denoise": (denoise * 100).rounded() / 100, "processor": processor, "faces": faces,
                                "faceStrength": (faceStrength * 100).rounded() / 100, "bits16": bits16, "compress": compress]
        if let l = lang { m["lang"] = l }
        if let l = lastDir { m["lastDir"] = l }
        d.set(m, forKey: Self.key)
    }
}
