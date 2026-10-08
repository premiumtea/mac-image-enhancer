import SwiftUI
import UniformTypeIdentifiers

struct ContentView: View {
    @EnvironmentObject var model: AppModel

    var body: some View {
        ZStack {
            AmbientBackground(image: model.source?.thumbnail)
            HStack(alignment: .top, spacing: 24) {
                VStack(spacing: 14) {
                    TopPill().frame(height: 34)
                    StageView()
                    BottomBar()
                }
                .padding(.leading, 28).padding(.top, 14).padding(.bottom, 24)
                InspectorView().padding(.top, 16).padding(.trailing, 16).padding(.bottom, 16)
            }
            if model.dropTargeted { DropOverlay() }
        }
        .frame(minWidth: 1000, minHeight: 680)
        .preferredColorScheme(.dark)
        .sheet(isPresented: $model.showAdvanced) { AdvancedSheet().environmentObject(model) }
        .alert(model.t("weights_title"), isPresented: Binding(get: { model.pendingDownload != nil }, set: { _ in }), presenting: model.pendingDownload) { _ in
            Button(model.t("download_btn")) { model.answerDownload(true) }
            Button(model.t("later_btn"), role: .cancel) { model.answerDownload(false) }
        } message: { p in
            Text(verbatim: model.t("weights_msg", ["mb": Double(p.bytes) / 1_048_576] ) + (p.includesFaces ? model.t("faces_license") : ""))
        }
        .onDrop(of: [UTType.fileURL], isTargeted: $model.dropTargeted) { providers in
            let lock = NSLock()
            var urls: [URL] = []
            let group = DispatchGroup()
            for p in providers {
                group.enter()
                p.loadItem(forTypeIdentifier: UTType.fileURL.identifier, options: nil) { item, _ in
                    if let d = item as? Data, let u = URL(dataRepresentation: d, relativeTo: nil) {
                        lock.lock(); urls.append(u); lock.unlock()
                    }
                    group.leave()
                }
            }
            group.notify(queue: .main) { model.load(urls.sorted { $0.path < $1.path }) }
            return true
        }
    }
}

/// The name of the open picture above the stage, with a way to change it.
struct TopPill: View {
    @EnvironmentObject var model: AppModel

    var body: some View {
        if let s = model.source {
            HStack(spacing: 10) {
                Text(verbatim: s.name).font(.system(size: 13, weight: .semibold)).lineLimit(1).truncationMode(.middle)
                Text(verbatim: "\(s.pixelWidth) × \(s.pixelHeight)").font(.system(size: 13)).foregroundStyle(Theme.secondary).monospacedDigit()
                if model.images.count > 1 {
                    Text(verbatim: model.t("files_more", ["n": model.images.count - 1])).font(.system(size: 12)).foregroundStyle(Theme.secondary)
                }
                Button { model.chooseImages() } label: {
                    Text(verbatim: model.t("change_pic").replacingOccurrences(of: "…", with: ""))
                        .font(.system(size: 12, weight: .medium)).padding(.horizontal, 11).frame(height: 24)
                        .background(Capsule().fill(Color.white.opacity(0.14)))
                }
                .buttonStyle(.plain)
            }
            .padding(.leading, 16).padding(.trailing, 5).frame(height: 34)
            .liquidGlass(Capsule())
        } else {
            Color.clear
        }
    }
}

struct DropOverlay: View {
    @EnvironmentObject var model: AppModel

    var body: some View {
        ZStack {
            Color.black.opacity(0.35)
            Text(verbatim: model.t("drop_hint")).font(.system(size: 22, weight: .semibold)).foregroundStyle(.white)
                .padding(.horizontal, 36).frame(height: 84).liquidGlass(RoundedRectangle(cornerRadius: 28, style: .continuous))
        }
        .ignoresSafeArea().allowsHitTesting(false)
    }
}
