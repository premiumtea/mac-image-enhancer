import Foundation

/// The units of a print size. Raw values are what the engine's --unit takes.
enum Unit: String, CaseIterable, Identifiable {
    case cm, mm, inch = "in", ft
    var id: String { rawValue }
    var inches: Double {
        switch self {
        case .cm: return 1 / 2.54
        case .mm: return 1 / 25.4
        case .inch: return 1
        case .ft: return 12
        }
    }
    var stringKey: String { "unit_" + rawValue }
}

/// Everything the size fields decide: the print in pixels, which part of the picture is printed, and how
/// many AI passes it takes. This must give the same numbers as `enhance.plan_print` (the tests compare
/// them with cases generated from the Python side).
struct PrintPlan: Equatable {
    var width: Int
    var height: Int
    /// The centred part of the picture that has the print's proportions: x0, y0, x1, y1 in picture pixels.
    var crop: (x0: Int, y0: Int, x1: Int, y1: Int)
    var passes: Int

    static func == (a: PrintPlan, b: PrintPlan) -> Bool {
        a.width == b.width && a.height == b.height && a.crop == b.crop && a.passes == b.passes
    }

    var cropSize: (w: Int, h: Int) { (crop.x1 - crop.x0, crop.y1 - crop.y0) }
    /// How much the printed part of the picture is enlarged (print pixels over picture pixels).
    var scale: Double { max(Double(width) / Double(cropSize.w), Double(height) / Double(cropSize.h)) }
    var megapixels: Double { Double(width) * Double(height) / 1e6 }
}

enum PrintMath {
    /// Python's round(): halves go to the even neighbour (Swift's default rounds them away from zero).
    static func round(_ x: Double) -> Int { Int(x.rounded(.toNearestOrEven)) }

    static func targetPixels(width: Double, height: Double, unit: Unit, dpi: Int) -> (Int, Int) {
        let k = unit.inches * Double(dpi)
        return (round(width * k), round(height * k))
    }

    static func aspectCrop(width w: Int, height h: Int, ratio: Double) -> (x0: Int, y0: Int, x1: Int, y1: Int) {
        if Double(w) / Double(h) > ratio {
            let nw = max(round(Double(h) * ratio), 1)
            let x0 = (w - nw) / 2
            return (x0, 0, x0 + nw, h)
        }
        let nh = max(round(Double(w) / ratio), 1)
        let y0 = (h - nh) / 2
        return (0, y0, w, y0 + nh)
    }

    /// One AI pass multiplies by 4; up to 6x one pass is enough (a plain resize does the rest), beyond that two.
    static func passes(scaleNeeded: Double, modelScale: Int = 4) -> Int {
        if scaleNeeded <= 1 { return 0 }
        return scaleNeeded <= Double(modelScale) * 1.5 ? 1 : 2
    }

    /// The number the engine will be given for a size field: C's %g, as Python's format spec `:g`.
    static func g(_ x: Double) -> String { String(format: "%g", x) }

    static func plan(sourceWidth sw: Int, sourceHeight sh: Int, width: Double, height: Double, unit: Unit, dpi: Int) -> PrintPlan? {
        guard sw > 0, sh > 0, width > 0, height > 0, dpi > 0 else { return nil }
        // the engine receives the sizes as text ("%g"), so the plan is made from what the text says
        guard let w = Double(g(width)), let h = Double(g(height)) else { return nil }
        let (tw, th) = targetPixels(width: w, height: h, unit: unit, dpi: dpi)
        guard tw >= 1, th >= 1 else { return nil }
        let crop = aspectCrop(width: sw, height: sh, ratio: Double(tw) / Double(th))
        let cw = crop.x1 - crop.x0, ch = crop.y1 - crop.y0
        let scale = max(Double(tw) / Double(cw), Double(th) / Double(ch))
        return PrintPlan(width: tw, height: th, crop: crop, passes: passes(scaleNeeded: scale))
    }

    /// How far the picture is stretched, as a person is told: the text key and a level.
    enum Level { case ok, care, bad }
    static func qualityHint(scale: Double, passes: Int) -> (key: String, level: Level) {
        if passes == 0 { return ("hint_sharp", .ok) }
        if scale <= 4 { return ("hint_good", .ok) }
        if scale <= 8 { return ("hint_stretch", .care) }
        return ("hint_huge", .bad)
    }

    /// The preview area as a rectangle inside the picture as shown, all as fractions (0...1) of it, the same
    /// convention as the engine's --preview centre. Kept inside the picture.
    static func markerRect(center: (x: Double, y: Double), previewPx: (w: Double, h: Double), plan: PrintPlan) -> (x: Double, y: Double, w: Double, h: Double) {
        let w = min(previewPx.w / Double(plan.width), 1), h = min(previewPx.h / Double(plan.height), 1)
        let x = min(max(center.x - w / 2, 0), 1 - w), y = min(max(center.y - h / 2, 0), 1 - h)
        return (x, y, w, h)
    }

    /// "42" / "29.7" / "0.5": a size for people, never "42.00000001".
    static func formatNumber(_ x: Double) -> String {
        var s = String(format: "%.2f", x)
        while s.hasSuffix("0") { s.removeLast() }
        if s.hasSuffix(".") { s.removeLast() }
        return s
    }

    /// A positive number typed by a person ("12.5" or "12,5"), else nil.
    static func parseNumber(_ text: String) -> Double? {
        let t = text.trimmingCharacters(in: .whitespaces).replacingOccurrences(of: ",", with: ".")
        guard let v = Double(t), v > 0, v.isFinite else { return nil }
        return v
    }
}

/// Paper sizes: short side, long side, unit.
struct Preset: Identifiable, Equatable {
    let id: String
    let label: String
    let short: Double
    let long: Double
    let unit: Unit

    static let all: [Preset] = [
        Preset(id: "A4", label: "A4", short: 21, long: 29.7, unit: .cm),
        Preset(id: "A3", label: "A3", short: 29.7, long: 42, unit: .cm),
        Preset(id: "A2", label: "A2", short: 42, long: 59.4, unit: .cm),
        Preset(id: "A1", label: "A1", short: 59.4, long: 84.1, unit: .cm),
        Preset(id: "A0", label: "A0", short: 84.1, long: 118.9, unit: .cm),
        Preset(id: "24x36", label: "24×36″", short: 24, long: 36, unit: .inch),
    ]

    /// The sheet turned to match the picture: a landscape picture gets a landscape sheet; with no picture it stands upright.
    func size(forSource source: (w: Int, h: Int)?) -> (width: Double, height: Double) {
        if let s = source, s.w > s.h { return (long, short) }
        return (short, long)
    }
}
