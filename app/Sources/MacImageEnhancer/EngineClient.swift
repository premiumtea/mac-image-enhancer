import Foundation

/// What `enhance.py --info` says: the engine's version, optional features and which weight files are missing.
struct EngineInfo: Decodable {
    struct Group: Decodable {
        let files: [String]
        let missing: [String]
        let missingBytes: Int
    }
    let version: String
    let modelsDir: String
    let groups: [String: Group]
    let faceMinPx: Int
    let coreml: Bool
    let vision: Bool

    static func decode(_ data: Data) throws -> EngineInfo {
        let d = JSONDecoder()
        d.keyDecodingStrategy = .convertFromSnakeCase
        return try d.decode(EngineInfo.self, from: data)
    }
}

/// One line of the engine's `--json` output.
enum EngineEvent: Equatable {
    case job(i: Int, n: Int, src: String, dst: String)
    case progress(Double)
    case download(name: String, done: Int, total: Int)
    case done(outputs: [String], skipped: Int, failed: [String])
    case error(String)
    case cancelled

    init?(line: String) {
        guard let data = line.data(using: .utf8),
              let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let event = obj["event"] as? String else { return nil }
        func int(_ k: String) -> Int { (obj[k] as? NSNumber)?.intValue ?? 0 }
        switch event {
        case "job": self = .job(i: int("i"), n: int("n"), src: obj["src"] as? String ?? "", dst: obj["dst"] as? String ?? "")
        case "progress": self = .progress((obj["fraction"] as? NSNumber)?.doubleValue ?? 0)
        case "download": self = .download(name: obj["name"] as? String ?? "", done: int("done"), total: int("total"))
        case "done": self = .done(outputs: obj["outputs"] as? [String] ?? [], skipped: int("skipped"), failed: obj["failed"] as? [String] ?? [])
        case "error": self = .error(obj["message"] as? String ?? "")
        case "cancelled": self = .cancelled
        default: return nil
        }
    }
}

/// How to start the engine: the bundled command-line tool, or (development) the checkout's Python.
struct EngineCommand {
    let executable: URL
    let prefixArgs: [String]

    /// 1. $MAC_IMAGE_ENHANCER_ENGINE ("/path/to/python|/path/to/enhance.py": executable first, then its arguments)
    /// 2. the tool inside the app bundle: Contents/Resources/engine/mac-image-enhancer-engine
    /// 3. a source checkout: .venv/bin/python enhance.py above the running binary
    static func locate() -> EngineCommand? {
        if let spec = ProcessInfo.processInfo.environment["MAC_IMAGE_ENHANCER_ENGINE"], !spec.isEmpty {
            let parts = spec.split(separator: "|", omittingEmptySubsequences: false).map(String.init)
            return EngineCommand(executable: URL(fileURLWithPath: parts[0]), prefixArgs: Array(parts.dropFirst()))
        }
        if let url = Bundle.main.url(forResource: "mac-image-enhancer-engine", withExtension: nil, subdirectory: "engine") {
            return EngineCommand(executable: url, prefixArgs: [])
        }
        var dir = URL(fileURLWithPath: CommandLine.arguments[0]).resolvingSymlinksInPath().deletingLastPathComponent()
        for _ in 0..<10 {
            let script = dir.appendingPathComponent("enhance.py")
            let python = dir.appendingPathComponent(".venv/bin/python")
            if FileManager.default.fileExists(atPath: script.path), FileManager.default.isExecutableFile(atPath: python.path) {
                return EngineCommand(executable: python, prefixArgs: [script.path])
            }
            dir.deleteLastPathComponent()
        }
        return nil
    }
}

enum EngineError: LocalizedError {
    case notFound
    case failed(String)
    var errorDescription: String? {
        switch self {
        case .notFound: return "The engine (the part that enlarges pictures) was not found."
        case .failed(let m): return m
        }
    }
}

/// A running engine process. Its output arrives as `events`; `cancel()` asks it to stop cleanly (SIGTERM).
///
/// The output is read with a readability handler and split into lines here, not with `FileHandle.bytes`: with that, a
/// process that was over almost as soon as it started could leave the stream open for good (found by the flow tests on
/// a CI runner: the window stayed "working" forever). As a second guard, once the process has ended what is left in the
/// pipe is read without waiting and the stream finished, even if the pipe never reports its end (a pipe's end only comes
/// when every copy of its write side is closed, and a copy can be held by another process started at the same moment).
final class EngineRun {
    let events: AsyncStream<EngineEvent>
    private let process = Process()
    private let reader: FileHandle
    private let continuation: AsyncStream<EngineEvent>.Continuation
    private let lock = NSLock()
    private var tail = ""
    private var pending = Data()
    private var finished = false

    /// The last of what the engine wrote to stderr: the explanation when it dies without saying why.
    var stderrTail: String { lock.lock(); defer { lock.unlock() }; return tail }
    var exitCode: Int32 { process.terminationStatus }

    init(command: EngineCommand, arguments: [String]) throws {
        let out = Pipe(), err = Pipe()
        process.executableURL = command.executable
        process.arguments = command.prefixArgs + arguments
        process.standardOutput = out
        process.standardError = err
        process.standardInput = FileHandle.nullDevice
        var env = ProcessInfo.processInfo.environment
        env["PYTHONUNBUFFERED"] = "1"
        process.environment = env
        var cont: AsyncStream<EngineEvent>.Continuation!
        events = AsyncStream { cont = $0 }
        continuation = cont
        reader = out.fileHandleForReading
        err.fileHandleForReading.readabilityHandler = { [weak self] h in
            let data = h.availableData
            guard !data.isEmpty, let self else { return }
            self.lock.lock()
            self.tail = String((self.tail + String(decoding: data, as: UTF8.self)).suffix(4000))
            self.lock.unlock()
        }
        reader.readabilityHandler = { [weak self] h in self?.received(h.availableData) }
        process.terminationHandler = { [weak self] _ in
            DispatchQueue.global().asyncAfter(deadline: .now() + 0.5) { self?.drainAndFinish() }
        }
        try process.run()
    }

    /// Some output (or, when empty, the end of it): complete lines become events.
    private func received(_ data: Data) {
        lock.lock()
        defer { lock.unlock() }
        guard !finished else { return }
        if data.isEmpty {  // the end of the pipe
            if let line = String(data: pending, encoding: .utf8), let ev = EngineEvent(line: line) { continuation.yield(ev) }
            pending = Data()
            finished = true
            continuation.finish()
            reader.readabilityHandler = nil
            return
        }
        pending.append(data)
        while let nl = pending.firstIndex(of: 0x0A) {
            let line = String(decoding: pending[pending.startIndex..<nl], as: UTF8.self)
            pending = Data(pending[pending.index(after: nl)...])
            if let ev = EngineEvent(line: line) { continuation.yield(ev) }
        }
    }

    /// The process is over, so everything it wrote is already in the pipe: take it without waiting for an end that may
    /// never be reported, and close the stream.
    private func drainAndFinish() {
        lock.lock()
        let done = finished
        lock.unlock()
        if done { return }
        reader.readabilityHandler = nil
        let fd = reader.fileDescriptor
        _ = fcntl(fd, F_SETFL, fcntl(fd, F_GETFL) | O_NONBLOCK)
        var buffer = [UInt8](repeating: 0, count: 65536)
        while true {
            let n = read(fd, &buffer, buffer.count)
            if n <= 0 { break }  // 0: the end; -1: nothing more to read right now
            received(Data(buffer[0..<n]))
        }
        received(Data())
    }

    func waitUntilExit() async -> Int32 {
        await withCheckedContinuation { c in
            DispatchQueue.global().async { [process] in
                process.waitUntilExit()
                c.resume(returning: process.terminationStatus)
            }
        }
    }

    /// SIGTERM, which the engine turns into a clean stop; SIGKILL if it has not stopped after a while.
    func cancel() {
        guard process.isRunning else { return }
        process.terminate()
        let pid = process.processIdentifier
        DispatchQueue.global().asyncAfter(deadline: .now() + 10) { [process] in
            if process.isRunning { kill(pid, SIGKILL) }
        }
    }
}

enum Engine {
    /// Runs `--info` and decodes it.
    static func info(command: EngineCommand) async throws -> EngineInfo {
        let p = Process()
        p.executableURL = command.executable
        p.arguments = command.prefixArgs + ["--info"]
        let out = Pipe()
        p.standardOutput = out
        p.standardError = FileHandle.nullDevice
        try p.run()
        let data = await Task.detached { out.fileHandleForReading.readDataToEndOfFile() }.value
        p.waitUntilExit()
        guard p.terminationStatus == 0 else { throw EngineError.failed("the engine exited with code \(p.terminationStatus)") }
        return try EngineInfo.decode(data)
    }
}
