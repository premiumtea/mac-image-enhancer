import AppKit
import ImageIO
import UniformTypeIdentifiers

/// A picture opened for printing: its real size and a screen-sized copy (colour-managed, turned upright).
struct SourceImage {
    let url: URL
    let pixelWidth: Int
    let pixelHeight: Int
    let thumbnail: CGImage
    var name: String { url.lastPathComponent }
}

enum ImageTools {
    static let thumbnailPixels = 2000

    /// Reads the size (with the EXIF orientation applied) and makes a screen-sized copy. Nil if it is not a picture.
    static func load(url: URL) -> SourceImage? {
        guard let src = CGImageSourceCreateWithURL(url as CFURL, nil),
              let props = CGImageSourceCopyPropertiesAtIndex(src, 0, nil) as? [CFString: Any],
              let w = (props[kCGImagePropertyPixelWidth] as? NSNumber)?.intValue,
              let h = (props[kCGImagePropertyPixelHeight] as? NSNumber)?.intValue, w > 0, h > 0 else { return nil }
        let orientation = (props[kCGImagePropertyOrientation] as? NSNumber)?.intValue ?? 1
        let opts: [CFString: Any] = [kCGImageSourceCreateThumbnailFromImageAlways: true,
                                     kCGImageSourceCreateThumbnailWithTransform: true,
                                     kCGImageSourceThumbnailMaxPixelSize: thumbnailPixels]
        guard let thumb = CGImageSourceCreateThumbnailAtIndex(src, 0, opts as CFDictionary) else { return nil }
        let turned = (5...8).contains(orientation)
        return SourceImage(url: url, pixelWidth: turned ? h : w, pixelHeight: turned ? w : h, thumbnail: thumb)
    }

    /// The part of the thumbnail the print shows: the plan's crop box, scaled from picture pixels to thumbnail pixels.
    static func cropped(_ thumb: CGImage, source: (w: Int, h: Int), plan: PrintPlan) -> CGImage {
        let fx = Double(thumb.width) / Double(source.w), fy = Double(thumb.height) / Double(source.h)
        let rect = CGRect(x: (Double(plan.crop.x0) * fx).rounded(), y: (Double(plan.crop.y0) * fy).rounded(),
                          width: (Double(plan.cropSize.w) * fx).rounded(), height: (Double(plan.cropSize.h) * fy).rounded())
        let bounded = rect.intersection(CGRect(x: 0, y: 0, width: thumb.width, height: thumb.height))
        return thumb.cropping(to: bounded) ?? thumb
    }

    static func nsImage(_ cg: CGImage) -> NSImage { NSImage(cgImage: cg, size: NSSize(width: cg.width, height: cg.height)) }

    /// Loads a PNG written by the engine, at its true pixel size.
    /// The file is read and decoded right away, so it can be deleted afterwards (a lazily decoded image would turn black).
    static func loadPixels(_ url: URL) -> NSImage? {
        guard let data = try? Data(contentsOf: url),
              let src = CGImageSourceCreateWithData(data as CFData, nil),
              let cg = CGImageSourceCreateImageAtIndex(src, 0, [kCGImageSourceShouldCacheImmediately: true] as CFDictionary) else { return nil }
        return nsImage(cg)
    }

    static func isImage(_ url: URL) -> Bool {
        guard let t = UTType(filenameExtension: url.pathExtension) else { return false }
        return t.conforms(to: .image)
    }
}
