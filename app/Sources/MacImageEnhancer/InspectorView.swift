import SwiftUI

/// The glass panel on the right: size, quality, options.
struct InspectorView: View {
    @EnvironmentObject var model: AppModel

    var body: some View {
        VStack(alignment: .leading, spacing: 24) {
            Header()
            SizeSection()
            QualitySection()
            FacesSection()
            Spacer(minLength: 0)
            Button { model.showAdvanced = true } label: {
                HStack {
                    Text(verbatim: model.t("advanced_btn").replacingOccurrences(of: "…", with: ""))
                        .font(.system(size: 13, weight: .medium))
                    Spacer()
                    Image(systemName: "chevron.right").font(.system(size: 11, weight: .semibold)).foregroundStyle(Theme.secondary)
                }
                .padding(.horizontal, 18).frame(height: 44).contentShape(Capsule())
            }
            .buttonStyle(.plain).foregroundStyle(.white)
            .liquidGlass(Capsule(), interactive: true)
        }
        .padding(22)
        .frame(width: 316)
        .frame(maxHeight: .infinity)
        .liquidGlass(RoundedRectangle(cornerRadius: 28, style: .continuous))
    }
}

struct Header: View {
    @EnvironmentObject var model: AppModel

    var body: some View {
        HStack {
            HStack(spacing: 9) {
                Image(systemName: "photo").font(.system(size: 13, weight: .bold)).foregroundStyle(Color(red: 0.08, green: 0.08, blue: 0.11))
                    .frame(width: 26, height: 26).background(RoundedRectangle(cornerRadius: 8, style: .continuous).fill(.white))
                Text(verbatim: "Mac Image Enhancer").font(.system(size: 13, weight: .semibold)).lineLimit(1).minimumScaleFactor(0.8)
            }
            Spacer(minLength: 6)
            Menu {
                ForEach(Strings.languages, id: \.code) { lang in
                    Button { model.l10n.lang = lang.code } label: {
                        if model.l10n.lang == lang.code { Label(lang.name, systemImage: "checkmark") } else { Text(verbatim: lang.name) }
                    }
                }
            } label: {
                HStack(spacing: 5) {
                    Image(systemName: "globe").font(.system(size: 11))
                    Text(verbatim: model.l10n.lang.uppercased()).font(.system(size: 12, weight: .medium))
                }
                .padding(.horizontal, 10).frame(height: 28).background(Capsule().fill(Theme.chipFill))
            }
            .menuStyle(.button).buttonStyle(.plain).menuIndicator(.hidden).fixedSize()
        }
    }
}

struct SectionTitle: View {
    let text: String
    var body: some View {
        Text(verbatim: text).font(.system(size: 12, weight: .semibold)).foregroundStyle(Theme.secondary)
    }
}

struct Chip: View {
    let label: String
    let selected: Bool
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            Text(verbatim: label)
                .font(.system(size: 13, weight: selected ? .bold : .medium))
                .foregroundStyle(selected ? Color(red: 0.06, green: 0.06, blue: 0.08) : .white)
                .padding(.horizontal, 14).frame(height: 32)
                .background(Capsule().fill(selected ? Color.white : Theme.chipFill))
                .overlay(Capsule().strokeBorder(selected ? .clear : Theme.chipStroke, lineWidth: 1))
        }
        .buttonStyle(.plain)
    }
}

struct SizeSection: View {
    @EnvironmentObject var model: AppModel

    private func width(_ text: String) -> CGFloat { CGFloat(max(text.count, 2)) * 22 + 6 }

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            SectionTitle(text: model.t("section_size"))
            HStack(alignment: .firstTextBaseline, spacing: 6) {
                TextField("", text: $model.widthText)
                    .textFieldStyle(.plain).multilineTextAlignment(.trailing).frame(width: width(model.widthText))
                Text(verbatim: "×").foregroundStyle(Theme.secondary)
                TextField("", text: $model.heightText)
                    .textFieldStyle(.plain).frame(width: width(model.heightText))
                Menu {
                    ForEach(Unit.allCases) { u in
                        Button(model.t(u.stringKey)) { model.setUnit(u) }
                    }
                } label: {
                    Text(verbatim: model.t(model.unit.stringKey)).font(.system(size: 16)).foregroundStyle(Theme.secondary)
                }
                .menuStyle(.button).buttonStyle(.plain).menuIndicator(.hidden).fixedSize()
            }
            .font(.system(size: 40, weight: .light)).monospacedDigit().foregroundStyle(.white)
            .lineLimit(1).minimumScaleFactor(0.6)
            FlowLayout(spacing: 7) {
                ForEach(Preset.all) { p in
                    Chip(label: p.label, selected: model.preset == p.id) { model.selectPreset(p.id) }
                }
                Chip(label: model.t("preset_custom"), selected: model.preset == "custom") { model.selectPreset("custom") }
            }
        }
    }
}

struct QualitySection: View {
    @EnvironmentObject var model: AppModel
    private let levels: [(key: String, dpi: Int)] = [("quality_normal", 150), ("quality_good", 200), ("quality_fine", 300)]

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            SectionTitle(text: model.t("section_quality"))
            HStack(spacing: 0) {
                ForEach(levels, id: \.dpi) { l in
                    let on = model.dpi == l.dpi
                    Button { withAnimation(.snappy(duration: 0.2)) { model.dpi = l.dpi } } label: {
                        Text(verbatim: model.t(l.key))
                            .font(.system(size: 13, weight: on ? .bold : .medium))
                            .foregroundStyle(on ? Color(red: 0.06, green: 0.06, blue: 0.08) : .white.opacity(0.85))
                            .frame(maxWidth: .infinity).frame(height: 36)
                            .background { if on { Capsule().fill(.white).shadow(color: .black.opacity(0.3), radius: 4, y: 2) } }
                            .contentShape(Capsule())
                    }
                    .buttonStyle(.plain)
                }
            }
            .padding(4).background(Capsule().fill(Color.black.opacity(0.28)))
            if let plan = model.plan {
                let hint = PrintMath.qualityHint(scale: plan.scale, passes: plan.passes)
                HStack {
                    HStack(spacing: 8) {
                        Circle().fill(Theme.level(hint.level)).frame(width: 8, height: 8).shadow(color: Theme.level(hint.level), radius: 5)
                        Text(verbatim: model.t(hint.key)).font(.system(size: 13, weight: .semibold)).fixedSize(horizontal: false, vertical: true)
                    }
                    Spacer(minLength: 6)
                    if plan.passes > 0 {
                        Text(verbatim: String(format: "%.1f×", plan.scale)).font(.system(size: 12)).monospacedDigit().foregroundStyle(Theme.secondary)
                    }
                }
                StretchGauge(scale: plan.passes > 0 ? plan.scale : 1)
            }
            Text(verbatim: model.t("quality_note", ["dpi": model.dpi])).font(.system(size: 12)).foregroundStyle(Theme.secondary)
                .fixedSize(horizontal: false, vertical: true)
        }
    }
}

/// How far the picture is stretched: green up to 4x, amber to 8x, then red, with a marker at this print's enlargement.
struct StretchGauge: View {
    let scale: Double

    var body: some View {
        GeometryReader { g in
            let x = min(max(scale / 10, 0), 1) * g.size.width
            ZStack(alignment: .leading) {
                Capsule().fill(LinearGradient(stops: [
                    .init(color: Theme.ok, location: 0), .init(color: Theme.ok, location: 0.4),
                    .init(color: Theme.care, location: 0.4), .init(color: Theme.care, location: 0.8),
                    .init(color: Theme.bad, location: 0.8), .init(color: Theme.bad, location: 1)],
                    startPoint: .leading, endPoint: .trailing)).frame(height: 6)
                Circle().fill(.white).frame(width: 14, height: 14)
                    .shadow(color: .white.opacity(0.4), radius: 5).offset(x: x - 7)
            }
            .frame(height: 14)
        }
        .frame(height: 14)
        .animation(.snappy(duration: 0.25), value: scale)
    }
}

struct FacesSection: View {
    @EnvironmentObject var model: AppModel

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(spacing: 9) {
                Text(verbatim: model.t("faces")).font(.system(size: 14, weight: .semibold))
                Text(verbatim: model.t("faces_badge")).font(.system(size: 11, weight: .semibold)).foregroundStyle(Theme.care)
                    .padding(.horizontal, 8).padding(.vertical, 2).overlay(Capsule().strokeBorder(Theme.care.opacity(0.6), lineWidth: 1))
                Spacer(minLength: 4)
                Toggle("", isOn: $model.faces).labelsHidden().toggleStyle(.switch).tint(Theme.accent)
            }
            if model.faces {
                HStack(spacing: 10) {
                    Text(verbatim: model.t("face_strength")).font(.system(size: 12)).foregroundStyle(Theme.secondary)
                    Slider(value: $model.faceStrength, in: 0...1).tint(Theme.accent)
                }
                Text(verbatim: model.t("faces_note", ["px": model.info?.faceMinPx ?? 32])).font(.system(size: 12))
                    .foregroundStyle(Theme.secondary).fixedSize(horizontal: false, vertical: true)
            } else {
                Text(verbatim: model.t("faces_off_note")).font(.system(size: 12)).foregroundStyle(Theme.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
    }
}
