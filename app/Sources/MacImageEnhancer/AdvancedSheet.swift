import SwiftUI

/// Settings most people never need: picture type, processor, resolution, 16-bit colour, CMYK.
struct AdvancedSheet: View {
    @EnvironmentObject var model: AppModel

    private var processors: [Processor] {
        Processor.allCases.filter { $0 != .ane || (model.info?.coreml ?? false) }
    }

    private var tiff: Bool { model.bits16 || model.cmykPath != nil }

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            Text(verbatim: model.t("advanced_title")).font(.system(size: 20, weight: .bold))

            VStack(alignment: .leading, spacing: 6) {
                Text(verbatim: model.t("model")).font(.system(size: 12, weight: .semibold)).foregroundStyle(.secondary)
                Picker("", selection: $model.model) {
                    ForEach(PictureModel.allCases) { m in Text(verbatim: model.t(m.stringKey)).tag(m) }
                }.pickerStyle(.segmented).labelsHidden()
            }
            VStack(alignment: .leading, spacing: 6) {
                Text(verbatim: model.t("denoise")).font(.system(size: 12, weight: .semibold)).foregroundStyle(.secondary)
                Slider(value: $model.denoise, in: 0...1).disabled(model.model != .general)
            }
            HStack(alignment: .bottom, spacing: 14) {
                VStack(alignment: .leading, spacing: 6) {
                    Text(verbatim: model.t("processor")).font(.system(size: 12, weight: .semibold)).foregroundStyle(.secondary)
                    Picker("", selection: $model.processor) {
                        ForEach(processors) { p in Text(verbatim: model.t(p.stringKey)).tag(p) }
                    }.labelsHidden()
                }
                VStack(alignment: .leading, spacing: 6) {
                    Text(verbatim: model.t("dpi_custom")).font(.system(size: 12, weight: .semibold)).foregroundStyle(.secondary)
                    TextField("", value: $model.dpi, format: .number.grouping(.never)).frame(width: 80).textFieldStyle(.roundedBorder)
                }
            }
            if model.processor == .ane {
                Text(verbatim: model.t("ane_note")).font(.system(size: 12)).foregroundStyle(.secondary)
            }
            Divider()
            Toggle(model.t("bits16"), isOn: $model.bits16).disabled(model.cmykPath != nil)
            HStack {
                Text(verbatim: model.t("cmyk"))
                Spacer()
                Text(verbatim: model.cmykPath.map { URL(fileURLWithPath: $0).lastPathComponent } ?? model.t("no_profile"))
                    .font(.system(size: 12)).foregroundStyle(.secondary).lineLimit(1).truncationMode(.middle).frame(maxWidth: 160)
                Button(model.t("choose_profile")) { model.chooseProfile() }
                if model.cmykPath != nil { Button { model.cmykPath = nil } label: { Image(systemName: "xmark") } }
            }
            Toggle(model.t("tiff_compress"), isOn: $model.compress).disabled(!tiff)
            Text(verbatim: model.t("tiff_note")).font(.system(size: 12)).foregroundStyle(.secondary)
            HStack {
                Spacer()
                Button(model.t("close_btn")) { model.showAdvanced = false }.keyboardShortcut(.defaultAction)
            }
        }
        .padding(24)
        .frame(width: 470)
        .preferredColorScheme(.dark)
        .tint(Theme.accent)
        .onAppear { DispatchQueue.main.async { NSApp.keyWindow?.makeFirstResponder(nil) } }
    }
}
