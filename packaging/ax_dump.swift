// What an assistive technology (VoiceOver, Voice Control) sees in a running app:
//
//   swiftc -O packaging/ax_dump.swift -o /tmp/ax
//   /tmp/ax MacImageEnhancer            # print every control with its names
//   /tmp/ax MacImageEnhancer --check    # exit 1 if a control that can be used has no name at all
//
// Needs the Accessibility permission for the app it is started from (a GitHub macOS runner has it).
import ApplicationServices
import AppKit

let args = CommandLine.arguments
guard args.count > 1, let app = NSWorkspace.shared.runningApplications.first(where: { $0.bundleIdentifier == args[1] || $0.localizedName == args[1] }) else {
    print("usage: ax <bundle id or name> [--check]"); exit(2)
}
let check = args.contains("--check")
guard AXIsProcessTrusted() else {
    print("not trusted for Accessibility: nothing to inspect (grant it to the app this was started from)")
    exit(check ? 0 : 3)
}

func attr(_ el: AXUIElement, _ name: String) -> AnyObject? {
    var v: CFTypeRef?
    return AXUIElementCopyAttributeValue(el, name as CFString, &v) == .success ? v : nil
}

let usable: Set<String> = ["AXButton", "AXCheckBox", "AXRadioButton", "AXPopUpButton", "AXMenuButton", "AXSlider", "AXTextField", "AXComboBox"]
let shown: Set<String> = usable.union(["AXImage", "AXStaticText"])
var unnamed: [String] = []
var count = 0

func walk(_ el: AXUIElement, _ depth: Int) {
    let role = attr(el, "AXRole") as? String ?? "?"
    if shown.contains(role) {
        var parts: [String] = []
        var named = false
        for n in ["AXTitle", "AXDescription", "AXLabel", "AXValue", "AXHelp", "AXIdentifier"] {
            if let v = attr(el, n), "\(v)" != "" {
                parts.append("\(n)=\(v)")
                if n == "AXTitle" || n == "AXDescription" || n == "AXLabel" { named = true }
            }
        }
        let subrole = attr(el, "AXSubrole") as? String ?? ""
        if usable.contains(role) && subrole.isEmpty {
            count += 1
            if !named { unnamed.append("\(role) \(parts.joined(separator: " | "))") }
        }
        if !check && !(role == "AXStaticText" && parts.isEmpty) {
            print(String(repeating: " ", count: depth) + "\(role) \(parts.joined(separator: " | "))")
        }
    }
    if let kids = attr(el, "AXChildren") as? [AXUIElement] { for k in kids { walk(k, depth + 1) } }
}

let root = AXUIElementCreateApplication(app.processIdentifier)
if let wins = attr(root, "AXWindows") as? [AXUIElement] { for w in wins { walk(w, 0) } }
if check {
    if unnamed.isEmpty { print("accessibility: all \(count) controls have a name") }
    else {
        print("accessibility: \(unnamed.count) of \(count) controls have no name:")
        unnamed.forEach { print("  " + $0) }
        exit(1)
    }
}
