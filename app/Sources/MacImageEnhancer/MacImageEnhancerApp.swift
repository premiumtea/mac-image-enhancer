import AppKit
import SwiftUI

enum AppInfo {
    static var version: String { Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String ?? "dev" }
}

final class AppDelegate: NSObject, NSApplicationDelegate {
    @MainActor static var model: AppModel?
    @MainActor static var waiting: [URL] = []

    /// Finder: "Open With", or pictures dropped on the Dock icon.
    func application(_ application: NSApplication, open urls: [URL]) {
        Task { @MainActor in
            if let m = AppDelegate.model { m.load(urls) } else { AppDelegate.waiting += urls }
        }
    }

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.activate(ignoringOtherApps: true)  // started from a shell, the app would otherwise stay behind and look inactive
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { true }

    func applicationWillTerminate(_ notification: Notification) {
        MainActor.assumeIsolated { AppDelegate.model?.shutdown() }
    }
}

@main
struct MacImageEnhancerApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) private var delegate
    @StateObject private var model: AppModel

    init() {
        let saved = Settings.load(from: .standard)
        let l10n = L10n(lang: saved.lang ?? L10n.systemLanguage())
        let m = AppModel(l10n: l10n)
        _model = StateObject(wrappedValue: m)
        AppDelegate.model = m
        if !AppDelegate.waiting.isEmpty { m.load(AppDelegate.waiting); AppDelegate.waiting = [] }
        Demo.runIfRequested(m)
    }

    var body: some Scene {
        Window("Mac Image Enhancer", id: "main") {
            ContentView().environmentObject(model)
        }
        .windowStyle(.hiddenTitleBar)
        .defaultSize(width: 1120, height: 740)
        .commands {
            CommandGroup(replacing: .newItem) {
                Button(model.t("menu_open")) { model.chooseImages() }.keyboardShortcut("o")
                Button(model.t("menu_save")) { model.save() }.keyboardShortcut("s").disabled(model.source == nil || model.busy)
                Button(model.t("menu_preview")) { model.startPreview() }.keyboardShortcut("p").disabled(model.source == nil || model.busy)
            }
            CommandGroup(replacing: .appInfo) {
                Button(model.t("menu_about")) { showAbout(model) }
            }
            CommandMenu(model.t("menu_language")) {
                ForEach(Strings.languages, id: \.code) { lang in
                    Button { model.l10n.lang = lang.code } label: {
                        if model.l10n.lang == lang.code { Label(lang.name, systemImage: "checkmark") } else { Text(verbatim: lang.name) }
                    }
                }
            }
        }
    }

    private func showAbout(_ model: AppModel) {
        let attrs: [NSAttributedString.Key: Any] = [.font: NSFont.systemFont(ofSize: 11), .foregroundColor: NSColor.labelColor]
        let body = model.t("about_body", ["version": AppInfo.version]).components(separatedBy: "\n\n").dropFirst().joined(separator: "\n\n")
        let credits = NSMutableAttributedString(string: body, attributes: attrs)
        if let notice = Bundle.main.url(forResource: "NOTICE", withExtension: nil) {  // the licences of what this is built on
            credits.append(NSAttributedString(string: "\n\n", attributes: attrs))
            credits.append(NSAttributedString(string: model.t("about_licenses"), attributes: attrs.merging([.link: notice]) { $1 }))
        }
        NSApp.orderFrontStandardAboutPanel(options: [.applicationName: "Mac Image Enhancer", .credits: credits])
    }
}
