import XCTest
@testable import MacImageEnhancer

final class PrintPlanTests: XCTestCase {
    /// Every case computed by enhance.plan_print must come out the same here (this file is generated: see packaging/gen_swift.py).
    func testMatchesPython() {
        XCTAssertGreaterThan(planVectors.count, 60)
        for (sw, sh, w, h, unit, dpi, tw, th, x0, y0, x1, y1, passes) in planVectors {
            let plan = PrintMath.plan(sourceWidth: sw, sourceHeight: sh, width: w, height: h, unit: Unit(rawValue: unit)!, dpi: dpi)
            XCTAssertNotNil(plan, "\(sw)x\(sh) \(w)x\(h) \(unit) \(dpi)")
            guard let p = plan else { continue }
            XCTAssertEqual([p.width, p.height, p.crop.x0, p.crop.y0, p.crop.x1, p.crop.y1, p.passes], [tw, th, x0, y0, x1, y1, passes],
                           "\(sw)x\(sh) \(w)x\(h) \(unit) \(dpi)")
        }
    }

    func testRoundsHalvesToEven() {
        XCTAssertEqual(PrintMath.round(50.5), 50)
        XCTAssertEqual(PrintMath.round(51.5), 52)
        XCTAssertEqual(PrintMath.round(2.4), 2)
    }

    func testBadInputGivesNoPlan() {
        XCTAssertNil(PrintMath.plan(sourceWidth: 40, sourceHeight: 30, width: 0, height: 5, unit: .cm, dpi: 150))
        XCTAssertNil(PrintMath.plan(sourceWidth: 0, sourceHeight: 30, width: 5, height: 5, unit: .cm, dpi: 150))
        XCTAssertNil(PrintMath.plan(sourceWidth: 40, sourceHeight: 30, width: 0.001, height: 0.001, unit: .mm, dpi: 72))  // under one pixel
    }

    func testStretchVerdict() {
        XCTAssertEqual(PrintMath.qualityHint(scale: 0.5, passes: 0).key, "hint_sharp")
        XCTAssertEqual(PrintMath.qualityHint(scale: 2, passes: 1).key, "hint_good")
        XCTAssertEqual(PrintMath.qualityHint(scale: 4, passes: 1).key, "hint_good")
        XCTAssertEqual(PrintMath.qualityHint(scale: 6, passes: 1).level, .care)
        XCTAssertEqual(PrintMath.qualityHint(scale: 8.5, passes: 2).level, .bad)
    }

    func testMarkerStaysInsideThePicture() {
        let plan = PrintMath.plan(sourceWidth: 1000, sourceHeight: 500, width: 100, height: 50, unit: .cm, dpi: 10)!  // 394 x 197 px print
        var m = PrintMath.markerRect(center: (0.5, 0.5), previewPx: (100, 50), plan: plan)
        XCTAssertEqual(m.x + m.w / 2, 0.5, accuracy: 1e-9)
        m = PrintMath.markerRect(center: (0, 0), previewPx: (100, 50), plan: plan)
        XCTAssertEqual(m.x, 0); XCTAssertEqual(m.y, 0)
        m = PrintMath.markerRect(center: (1, 1), previewPx: (100, 50), plan: plan)
        XCTAssertEqual(m.x + m.w, 1, accuracy: 1e-9); XCTAssertEqual(m.y + m.h, 1, accuracy: 1e-9)
        m = PrintMath.markerRect(center: (0.5, 0.5), previewPx: (5000, 5000), plan: plan)  // bigger than the print: all of it
        XCTAssertEqual([m.x, m.y, m.w, m.h], [0, 0, 1, 1])
    }

    func testPresetTurnsToThePicture() {
        let a4 = Preset.all[0]
        XCTAssertEqual(a4.size(forSource: (40, 30)).width, 29.7)  // landscape picture, landscape sheet
        XCTAssertEqual(a4.size(forSource: (30, 40)).width, 21)
        XCTAssertEqual(a4.size(forSource: nil).height, 29.7)
    }

    func testNumbers() {
        XCTAssertEqual(PrintMath.formatNumber(29.7), "29.7")
        XCTAssertEqual(PrintMath.formatNumber(42), "42")
        XCTAssertEqual(PrintMath.formatNumber(7.5000001), "7.5")
        XCTAssertEqual(PrintMath.parseNumber(" 12,5 "), 12.5)
        for bad in ["", "abc", "0", "-3", "nan", "inf"] { XCTAssertNil(PrintMath.parseNumber(bad), bad) }
        XCTAssertEqual(PrintMath.g(29.7), "29.7"); XCTAssertEqual(PrintMath.g(42), "42")
    }
}
