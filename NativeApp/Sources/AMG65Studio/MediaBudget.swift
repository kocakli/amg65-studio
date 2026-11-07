import Foundation
import ImageIO

/// Limits are checked before any image decompression. Only thumbnail decoding is used.
enum MediaBudget {
    static let maxBytes = 32 * 1024 * 1024
    static let maxDimension = 8192
    static let maxPixels = 32 * 1024 * 1024

    static func source(_ url: URL, maxFrames: Int) -> CGImageSource? {
        guard url.isFileURL,
              let attrs = try? url.resourceValues(forKeys:[.isRegularFileKey,.fileSizeKey]),
              attrs.isRegularFile == true, let size = attrs.fileSize, size > 0, size <= maxBytes,
              let source = CGImageSourceCreateWithURL(url as CFURL,[kCGImageSourceShouldCache:false] as CFDictionary),
              (1...maxFrames).contains(CGImageSourceGetCount(source)) else { return nil }
        for i in 0..<CGImageSourceGetCount(source) {
            guard let props = CGImageSourceCopyPropertiesAtIndex(source,i,nil) as? [CFString:Any],
                  let w = props[kCGImagePropertyPixelWidth] as? Int,
                  let h = props[kCGImagePropertyPixelHeight] as? Int,
                  w > 0, h > 0, w <= maxDimension, h <= maxDimension, w*h <= maxPixels else { return nil }
        }
        return source
    }

    static func thumbnail(_ source:CGImageSource, index:Int, dimension:Int) -> CGImage? {
        CGImageSourceCreateThumbnailAtIndex(source,index,[
            kCGImageSourceCreateThumbnailFromImageAlways:true,
            kCGImageSourceCreateThumbnailWithTransform:true,
            kCGImageSourceThumbnailMaxPixelSize:dimension,
            kCGImageSourceShouldCacheImmediately:false
        ] as CFDictionary)
    }
}
