import SwiftUI

/// The left side: nothing yet, the picture with the preview frame, or the before/after comparison.
struct StageView: View {
    @EnvironmentObject var model: AppModel

    var body: some View {
        GeometryReader { geo in
            ZStack {
                if model.source == nil {
                    EmptyStage()
                } else if model.compare, let p = model.preview {
                    CompareStage(preview: p, area: geo.size)
                } else {
                    PictureStage(area: geo.size)
                }
            }
            .frame(width: geo.size.width, height: geo.size.height)
            .onAppear { model.stageSize = geo.size }
            .onChange(of: geo.size) { model.stageSize = $0 }
        }
    }
}

/// Scales `size` down or up to fit inside `area` (up to 4x).
func fitted(_ aspect: CGFloat, in area: CGSize) -> CGSize {
    guard aspect > 0, area.width > 0, area.height > 0 else { return CGSize(width: 1, height: 1) }
    var w = area.width, h = area.width / aspect
    if h > area.height { h = area.height; w = h * aspect }
    return CGSize(width: max(w, 1), height: max(h, 1))
}

struct EmptyStage: View {
    @EnvironmentObject var model: AppModel

    var body: some View {
        VStack(spacing: 18) {
            ZStack {
                Circle().fill(Color.clear).frame(width: 132, height: 132).liquidGlass(Circle())
                Image(systemName: "photo.on.rectangle.angled")
                    .font(.system(size: 50, weight: .light))
                    .foregroundStyle(.white.opacity(0.92))
            }
            Text(verbatim: model.t("empty_title"))
                .font(.system(size: 30, weight: .bold)).multilineTextAlignment(.center).foregroundStyle(.white)
            Text(verbatim: model.t("empty_text"))
                .font(.system(size: 15)).foregroundStyle(Theme.secondary).multilineTextAlignment(.center).frame(maxWidth: 440)
            Button { model.chooseImages() } label: {
                Text(verbatim: model.t("open_btn")).font(.system(size: 15, weight: .semibold)).padding(.horizontal, 14).padding(.vertical, 4)
            }
            .glassButton(prominent: true).tint(Theme.accent).controlSize(.large).foregroundStyle(Theme.accentInk)
            Text(verbatim: model.t("empty_hint")).font(.system(size: 12)).foregroundStyle(Theme.secondary.opacity(0.8))
        }
        .padding(.bottom, 24)
    }
}

/// The picture as it will be printed (cropped to the paper), with the frame that shows what Preview will compute.
struct PictureStage: View {
    @EnvironmentObject var model: AppModel
    let area: CGSize

    var body: some View {
        if let src = model.source {
            let plan = model.plan
            let crop = plan.map { ImageTools.cropped(src.thumbnail, source: (src.pixelWidth, src.pixelHeight), plan: $0) } ?? src.thumbnail
            let fit = fitted(CGFloat(crop.width) / CGFloat(crop.height), in: CGSize(width: area.width, height: max(area.height - 34, 50)))
            VStack(spacing: 12) {
                ZStack(alignment: .topLeading) {
                    Image(decorative: crop, scale: 1).resizable().frame(width: fit.width, height: fit.height)
                    if let plan {
                        MarkerOverlay(plan: plan, fit: fit)
                    }
                    PaperLabel(plan: plan).padding(16).frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .bottomLeading)
                }
                .frame(width: fit.width, height: fit.height)
                .clipShape(RoundedRectangle(cornerRadius: 22, style: .continuous))
                .overlay(RoundedRectangle(cornerRadius: 22, style: .continuous).strokeBorder(Color.white.opacity(0.14), lineWidth: 1))
                .shadow(color: .black.opacity(0.5), radius: 40, y: 22)
                .contentShape(Rectangle())
                .gesture(DragGesture(minimumDistance: 0).onChanged { v in
                    model.center = CGPoint(x: min(max(v.location.x / fit.width, 0), 1), y: min(max(v.location.y / fit.height, 0), 1))
                })
                Text(verbatim: model.t("stage_hint")).font(.system(size: 12)).foregroundStyle(Theme.secondary.opacity(0.85)).frame(height: 22)
            }
            .frame(width: area.width, height: area.height)
        }
    }
}

struct PaperLabel: View {
    @EnvironmentObject var model: AppModel
    let plan: PrintPlan?

    var text: String {
        let name = model.preset == "custom" ? model.t("preset_custom") : (Preset.all.first { $0.id == model.preset }?.label ?? model.preset)
        guard let p = plan else { return name }
        return name + " · " + model.t(p.width >= p.height ? "orient_landscape" : "orient_portrait")
    }

    var body: some View {
        Text(verbatim: text)
            .font(.system(size: 12, weight: .medium)).foregroundStyle(.white)
            .padding(.horizontal, 14).frame(height: 30)
            .liquidGlass(Capsule())
    }
}

/// The frame over the picture that marks the area Preview will compute, with everything outside it dimmed.
struct MarkerOverlay: View {
    @EnvironmentObject var model: AppModel
    let plan: PrintPlan
    let fit: CGSize

    var body: some View {
        let px = model.previewPx
        let m = PrintMath.markerRect(center: (Double(model.center.x), Double(model.center.y)), previewPx: (Double(px.w), Double(px.h)), plan: plan)
        let rect = CGRect(x: m.x * fit.width, y: m.y * fit.height, width: m.w * fit.width, height: m.h * fit.height)
        ZStack(alignment: .topLeading) {
            Color.black.opacity(0.48)
                .reverseMask {
                    RoundedRectangle(cornerRadius: 12, style: .continuous).frame(width: rect.width, height: rect.height)
                        .position(x: rect.midX, y: rect.midY)
                }
            RoundedRectangle(cornerRadius: 12, style: .continuous).strokeBorder(.white, lineWidth: 2)
                .frame(width: rect.width, height: rect.height).position(x: rect.midX, y: rect.midY)
            HStack(spacing: 6) {
                Image(systemName: "magnifyingglass").font(.system(size: 11, weight: .bold))
                Text(verbatim: model.t("marker_label")).font(.system(size: 12, weight: .semibold))
            }
            .foregroundStyle(Color(red: 0.06, green: 0.06, blue: 0.08))
            .padding(.horizontal, 12).frame(height: 26).background(Capsule().fill(.white))
            .position(x: min(max(rect.minX + 84, 90), fit.width - 90), y: rect.minY > 34 ? rect.minY - 17 : rect.maxY + 17)
        }
        .frame(width: fit.width, height: fit.height)
        .allowsHitTesting(false)
    }
}

/// The real preview at true size next to the plain enlargement, with a line to drag between them.
struct CompareStage: View {
    @EnvironmentObject var model: AppModel
    let preview: PreviewResult
    let area: CGSize

    var body: some View {
        let scale = model.backingScale
        let natural = CGSize(width: preview.result.size.width / scale, height: preview.result.size.height / scale)
        let aspect = natural.width / max(natural.height, 1)
        let room = CGSize(width: area.width, height: max(area.height - 90, 50))
        let fit = natural.width <= room.width && natural.height <= room.height ? natural : fitted(aspect, in: room)
        VStack(spacing: 12) {
            HStack {
                Text(verbatim: model.t("compare_hint")).font(.system(size: 12)).foregroundStyle(Theme.secondary).lineLimit(2)
                Spacer(minLength: 12)
                Button { model.backToPicking() } label: {
                    Label(model.t("back_to_pick"), systemImage: "chevron.left").font(.system(size: 13, weight: .medium))
                }
                .glassButton()
            }
            .frame(width: max(fit.width, 360))
            ZStack(alignment: .topLeading) {
                Image(nsImage: preview.plain).resizable().frame(width: fit.width, height: fit.height)
                Image(nsImage: preview.result).resizable().frame(width: fit.width, height: fit.height)
                    .mask(alignment: .leading) {
                        HStack(spacing: 0) {
                            Color.clear.frame(width: fit.width * model.split)
                            Color.black
                        }
                    }
                Rectangle().fill(.white).frame(width: 2, height: fit.height).offset(x: fit.width * model.split - 1)
                    .shadow(color: .black.opacity(0.3), radius: 3)
                Image(systemName: "arrow.left.and.right")
                    .font(.system(size: 14, weight: .bold)).foregroundStyle(Color(red: 0.1, green: 0.1, blue: 0.12))
                    .frame(width: 40, height: 40).background(Circle().fill(.white)).shadow(color: .black.opacity(0.35), radius: 8, y: 2)
                    .offset(x: fit.width * model.split - 20, y: fit.height / 2 - 20)
            }
            .overlay(alignment: .topLeading) {
                Tag(text: model.t("before"), fill: Color(red: 0.11, green: 0.11, blue: 0.12), ink: .white).padding(12)
            }
            .overlay(alignment: .topTrailing) {
                Tag(text: model.t("after"), fill: Theme.accent, ink: Theme.accentInk).padding(12)
            }
            .frame(width: fit.width, height: fit.height)
            .clipShape(RoundedRectangle(cornerRadius: 16, style: .continuous))
            .overlay(RoundedRectangle(cornerRadius: 16, style: .continuous).strokeBorder(Color.white.opacity(0.14), lineWidth: 1))
            .shadow(color: .black.opacity(0.5), radius: 40, y: 22)
            .contentShape(Rectangle())
            .gesture(DragGesture(minimumDistance: 0).onChanged { v in
                model.split = min(max(v.location.x / fit.width, 0), 1)
            })
        }
        .frame(width: area.width, height: area.height)
    }
}
