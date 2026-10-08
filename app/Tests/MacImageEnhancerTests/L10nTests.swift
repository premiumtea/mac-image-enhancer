import XCTest
@testable import MacImageEnhancer

final class L10nTests: XCTestCase {
    func testEveryLanguageHasEveryKey() {
        let en = Set(Strings.table["en"]!.keys)
        XCTAssertGreaterThan(en.count, 80)
        for (code, table) in Strings.table {
            XCTAssertEqual(Set(table.keys), en, code)
        }
        XCTAssertEqual(Strings.languages.map { $0.code }, ["en", "th", "zh", "fr"])
    }

    func testPlaceholders() {
        XCTAssertEqual(L10n.text(lang: "fr", "done", ["n": 3]), "Terminé. 3 fichier(s) enregistré(s).")
        XCTAssertEqual(L10n.text(lang: "en", "summary_out", ["w": 3543, "h": 2657, "mp": 9.4143]), "Result: 3543 × 2657 px  (9.4 megapixels)")
        XCTAssertEqual(L10n.text(lang: "en", "quality_note", ["dpi": 200]), "200 DPI: higher makes a bigger file and takes longer.")
        XCTAssertEqual(L10n.text(lang: "en", "weights_msg", ["mb": 63.93]).prefix(60), "The AI model files are not on this Mac yet.\n\nDownload 64 MB ")
        XCTAssertEqual(L10n.text(lang: "xx", "ready"), "Ready")  // unknown language: English
        XCTAssertEqual(L10n.text(lang: "en", "no_such_key"), "no_such_key")
        XCTAssertEqual(L10n.text(lang: "en", "need_image"), "Open a picture first.")  // no placeholders, none needed
        XCTAssertEqual(L10n.format("{a} and {b:.0f} and {missing}", ["a": "x", "b": 2.6]), "x and 3 and {missing}")
    }
}
