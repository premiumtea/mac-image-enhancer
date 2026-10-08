import SwiftUI

/// The floating capsule under the picture: the size of the result, Preview and Save; or progress while working.
struct BottomBar: View {
    @EnvironmentObject var model: AppModel

    var body: some View {
        HStack(spacing: 14) {
            if model.busy { BusyContent() } else { ResultContent() }
            Spacer(minLength: 8)
            if model.busy {
                Button { model.cancel() } label: { Text(verbatim: model.t("cancel_btn")).font(.system(size: 14, weight: .medium)).padding(.horizontal, 10) }
                    .glassButton().controlSize(.large)
            } else {
                if model.lastOutput != nil {
                    Button { model.reveal() } label: { Text(verbatim: model.t("reveal_btn")).font(.system(size: 13, weight: .medium)) }
                        .glassButton().controlSize(.large)
                }
                Button { model.startPreview() } label: { Text(verbatim: model.t("preview_btn")).font(.system(size: 14, weight: .medium)).padding(.horizontal, 10) }
                    .glassButton().controlSize(.large).disabled(model.source == nil)
                Button { model.save() } label: { Text(verbatim: model.t("save_btn")).font(.system(size: 14, weight: .bold)).padding(.horizontal, 14).lineLimit(1) }
                    .glassButton(prominent: true).tint(Theme.accent).controlSize(.large).disabled(model.source == nil)
                    .foregroundStyle(model.source == nil ? Color.white.opacity(0.4) : Theme.accentInk)
                    .layoutPriority(2)
            }
        }
        .padding(.leading, 24).padding(.trailing, 10)
        .frame(height: 64)
        .liquidGlass(Capsule())
    }
}

struct ResultContent: View {
    @EnvironmentObject var model: AppModel

    var body: some View {
        VStack(alignment: .leading, spacing: 2) {
            if let p = model.plan {
                Text(verbatim: model.t("summary_out", ["w": p.width, "h": p.height, "mp": p.megapixels]))
                    .font(.system(size: 15, weight: .semibold)).monospacedDigit().lineLimit(1).minimumScaleFactor(0.6)
            } else {
                Text(verbatim: model.t("summary_none")).font(.system(size: 15, weight: .semibold))
            }
            if model.status.key != "ready" {
                Text(verbatim: model.statusText).font(.system(size: 11))
                    .foregroundStyle(model.status.isError ? Theme.bad : Theme.secondary).lineLimit(2)
            }
        }
    }
}

struct BusyContent: View {
    @EnvironmentObject var model: AppModel

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack {
                Text(verbatim: model.statusText).font(.system(size: 13, weight: .semibold)).monospacedDigit().lineLimit(1)
                Spacer(minLength: 8)
                if let eta = model.etaText { Text(verbatim: eta).font(.system(size: 12)).foregroundStyle(Theme.secondary).lineLimit(1) }
            }
            ProgressView(value: model.progress).progressViewStyle(.linear).tint(Theme.accent)
        }
        .frame(maxWidth: 380)
    }
}
