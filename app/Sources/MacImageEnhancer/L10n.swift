import Foundation
import SwiftUI

/// Interface text. The tables come from i18n.py (see packaging/gen_swift.py); English is the fallback.
final class L10n: ObservableObject {
    @Published var lang: String

    init(lang: String) { self.lang = Strings.table[lang] != nil ? lang : "en" }

    /// The language macOS is set to, if we have it ("th-TH" -> "th", Chinese -> "zh"), else English.
    static func systemLanguage() -> String {
        for tag in Locale.preferredLanguages {
            let code = tag.lowercased().replacingOccurrences(of: "_", with: "-").split(separator: "-").first.map(String.init) ?? ""
            if Strings.table[code] != nil { return code }
        }
        return "en"
    }

    func t(_ key: String, _ args: [String: Any] = [:]) -> String {
        Self.text(lang: lang, key, args)
    }

    static func text(lang: String, _ key: String, _ args: [String: Any] = [:]) -> String {
        let raw = Strings.table[lang]?[key] ?? Strings.table["en"]?[key] ?? key
        return args.isEmpty ? raw : format(raw, args)
    }

    /// Fills Python-style placeholders: {name}, {name:.1f}.
    static func format(_ template: String, _ args: [String: Any]) -> String {
        guard let re = try? NSRegularExpression(pattern: #"\{(\w+)(?::\.(\d+)f)?\}"#) else { return template }
        var out = ""
        var last = template.startIndex
        let ns = template as NSString
        for m in re.matches(in: template, range: NSRange(location: 0, length: ns.length)) {
            let r = Range(m.range, in: template)!
            out += template[last..<r.lowerBound]
            let name = ns.substring(with: m.range(at: 1))
            let digits = m.range(at: 2).location != NSNotFound ? Int(ns.substring(with: m.range(at: 2))) : nil
            if let v = args[name] {
                if let d = digits, let x = (v as? Double) ?? (v as? Int).map(Double.init) {
                    out += String(format: "%.\(d)f", x)
                } else {
                    out += "\(v)"
                }
            } else {
                out += template[r]
            }
            last = r.upperBound
        }
        out += template[last...]
        return out
    }
}
