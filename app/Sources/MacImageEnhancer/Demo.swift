import AppKit
import Foundation

/// Scenarios for taking screenshots on a machine with a display (see packaging/screenshots_app.sh):
/// MAC_IMAGE_ENHANCER_DEMO=empty|source|compare|saving|advanced|faces and MAC_IMAGE_ENHANCER_DEMO_IMAGE=/path.jpg.
enum Demo {
    @MainActor static func runIfRequested(_ model: AppModel) {
        let env = ProcessInfo.processInfo.environment
        guard let scenario = env["MAC_IMAGE_ENHANCER_DEMO"], !scenario.isEmpty else { return }
        if let lang = env["MAC_IMAGE_ENHANCER_DEMO_LANG"], Strings.table[lang] != nil { model.l10n.lang = lang }
        Task { @MainActor in
            try? await Task.sleep(nanoseconds: 800_000_000)
            // fit the window to the screen, as the system does for a person, and bring it to the front
            if let w = NSApp.windows.first(where: { $0.isVisible }), let area = (w.screen ?? NSScreen.main)?.visibleFrame {
                let size = CGSize(width: min(1120, area.width), height: min(740, area.height))
                w.setFrame(NSRect(x: area.minX, y: area.maxY - size.height, width: size.width, height: size.height), display: true)
                w.makeKeyAndOrderFront(nil)
            }
            NSApp.activate(ignoringOtherApps: true)
            if scenario != "empty", let path = env["MAC_IMAGE_ENHANCER_DEMO_IMAGE"] {
                model.preset = "custom"
                model.widthText = "45"
                model.heightText = "33.8"
                model.load([URL(fileURLWithPath: path)])
                try? await Task.sleep(nanoseconds: 1_200_000_000)
                model.center = CGPoint(x: 0.62, y: 0.55)
            }
            switch scenario {
            case "faces": model.faces = true
            case "advanced": model.showAdvanced = true
            case "saving":
                model.phase = .save
                model.progress = 0.42
                model.etaText = model.t("eta_min", ["m": 2])
                model.status = Status(key: "working_file", args: ["i": 2, "n": 5, "name": "holiday.jpg", "pct": 42])
            case "compare":
                model.startPreview()
            default: break
            }
            // a log for whoever runs this without looking: what the app thinks is going on
            var last = ""
            for _ in 0..<600 {
                let line = "phase=\(model.phase) compare=\(model.compare) status=\(model.statusText) plan=\(String(describing: model.plan.map { "\($0.width)x\($0.height) passes \($0.passes)" }))"
                if line != last { FileHandle.standardError.write(Data(("demo: " + line + "\n").utf8)); last = line }
                try? await Task.sleep(nanoseconds: 500_000_000)
            }
        }
    }
}
