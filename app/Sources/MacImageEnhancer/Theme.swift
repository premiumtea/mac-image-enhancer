import SwiftUI

/// The look: dark, with the picture's own colours glowing behind panels of Liquid Glass (macOS 26), or of
/// frosted material on older systems.
enum Theme {
    static let accent = Color(red: 1.0, green: 0.54, blue: 0.30)          // the dusk orange of the design
    static let accentInk = Color(red: 0.10, green: 0.055, blue: 0.02)    // text on the accent
    static let ok = Color(red: 0.36, green: 0.89, blue: 0.66)
    static let care = Color(red: 1.0, green: 0.76, blue: 0.35)
    static let bad = Color(red: 1.0, green: 0.48, blue: 0.42)
    static let secondary = Color.white.opacity(0.62)
    static let chipFill = Color.white.opacity(0.10)
    static let chipStroke = Color.white.opacity(0.14)

    static func level(_ l: PrintMath.Level) -> Color { l == .ok ? ok : l == .care ? care : bad }
}

extension View {
    /// A pane of Liquid Glass in `shape` (frosted material before macOS 26).
    @ViewBuilder
    func liquidGlass<S: InsettableShape>(_ shape: S, interactive: Bool = false) -> some View {
        if #available(macOS 26.0, *) {
            self.glassEffect(interactive ? Glass.regular.interactive() : Glass.regular, in: shape)
        } else {
            self.background(.ultraThinMaterial, in: shape)
                .overlay(shape.strokeBorder(Color.white.opacity(0.18), lineWidth: 1))
                .shadow(color: .black.opacity(0.25), radius: 18, y: 8)
        }
    }

    /// The system's glass button style (bordered before macOS 26).
    @ViewBuilder
    func glassButton(prominent: Bool = false) -> some View {
        if #available(macOS 26.0, *) {
            if prominent { self.buttonStyle(.glassProminent) } else { self.buttonStyle(.glass) }
        } else {
            if prominent { self.buttonStyle(.borderedProminent) } else { self.buttonStyle(.bordered) }
        }
    }

    /// Cuts the shape of `hole` out of this view.
    func reverseMask<M: View>(@ViewBuilder _ hole: () -> M) -> some View {
        self.mask {
            Rectangle().overlay { hole().blendMode(.destinationOut) }.compositingGroup()
        }
    }
}

/// The window's background: the picture, blurred into a glow, or a dusk gradient before one is open.
struct AmbientBackground: View {
    let image: CGImage?

    var body: some View {
        ZStack {
            Color(red: 0.043, green: 0.043, blue: 0.07)
            if let image {
                Image(decorative: image, scale: 1)
                    .resizable().scaledToFill()
                    .blur(radius: 80)
                    .saturation(1.6)
                    .brightness(-0.22)
                    .scaleEffect(1.4)
                    .transition(.opacity)
            } else {
                LinearGradient(colors: [Color(red: 0.11, green: 0.09, blue: 0.27), Color(red: 0.30, green: 0.16, blue: 0.40),
                                        Color(red: 0.55, green: 0.24, blue: 0.40)], startPoint: .top, endPoint: .bottom)
                    .opacity(0.65)
                RadialGradient(colors: [Theme.accent.opacity(0.45), .clear], center: .init(x: 0.45, y: 1.0), startRadius: 0, endRadius: 520)
            }
            Color.black.opacity(0.32)
        }
        .animation(.easeInOut(duration: 0.5), value: image == nil)
        .ignoresSafeArea()
    }
}

/// Lays children out left to right and wraps to a new row, like words.
struct FlowLayout: Layout {
    var spacing: CGFloat = 7

    func sizeThatFits(proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) -> CGSize {
        let width = proposal.width ?? .infinity
        var x: CGFloat = 0, y: CGFloat = 0, rowHeight: CGFloat = 0, widest: CGFloat = 0
        for s in subviews {
            let size = s.sizeThatFits(.unspecified)
            if x > 0, x + size.width > width { x = 0; y += rowHeight + spacing; rowHeight = 0 }
            x += size.width + spacing
            rowHeight = max(rowHeight, size.height)
            widest = max(widest, x - spacing)
        }
        return CGSize(width: widest, height: y + rowHeight)
    }

    func placeSubviews(in bounds: CGRect, proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) {
        var x = bounds.minX, y = bounds.minY, rowHeight: CGFloat = 0
        for s in subviews {
            let size = s.sizeThatFits(.unspecified)
            if x > bounds.minX, x + size.width > bounds.maxX { x = bounds.minX; y += rowHeight + spacing; rowHeight = 0 }
            s.place(at: CGPoint(x: x, y: y), proposal: ProposedViewSize(size))
            x += size.width + spacing
            rowHeight = max(rowHeight, size.height)
        }
    }
}

/// A small pill label (Experimental, Before, After...).
struct Tag: View {
    let text: String
    var fill: Color = .white
    var ink: Color = Color(red: 0.06, green: 0.06, blue: 0.08)

    var body: some View {
        Text(verbatim: text)
            .font(.system(size: 12, weight: .semibold))
            .foregroundStyle(ink)
            .padding(.horizontal, 12).frame(height: 26)
            .background(Capsule().fill(fill))
    }
}
