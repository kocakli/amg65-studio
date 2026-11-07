import AppKit
import CLibUSB
import ImageIO
import SwiftUI
import UniformTypeIdentifiers

// MARK: - Format (cmd 0x72) — confirmed on the keyboard

enum LCDFormat {
    static let width = 240, height = 135
    static let header = 256          // [0] frame count, [1+i] delay of frame i in 2 ms units
    static let maxFrames = 130
    static let block = 4096
    static let slot: UInt8 = 1       // the only slot tested so far
}

/// Frames ready for the LCD (already scaled to 240×135).
struct LCDAnimation {
    var frames: [CGImage]
    var delaysMs: [Int]
    var name: String

    var truncated: Bool { frames.count > LCDFormat.maxFrames }
    var uploadFrames: [CGImage] { Array(frames.prefix(LCDFormat.maxFrames)) }

    /// Whole upload buffer: FF-filled, header, RGB565 little-endian frames, padded to 4 KB blocks.
    func buffer() -> (bytes: [UInt8], blocks: Int) {
        let frames = uploadFrames
        let frameBytes = LCDFormat.width * LCDFormat.height * 2
        let size = LCDFormat.header + frames.count * frameBytes
        let blocks = (size + LCDFormat.block - 1) / LCDFormat.block
        var buf = [UInt8](repeating: 0xFF, count: blocks * LCDFormat.block)
        buf[0] = UInt8(frames.count)
        for (i, d) in delaysMs.prefix(frames.count).enumerated() { buf[1 + i] = UInt8(max(1, min(255, d / 2))) }
        for (i, frame) in frames.enumerated() {
            let px = LCDAnimation.rgba(frame)
            var o = LCDFormat.header + i * frameBytes
            for p in stride(from: 0, to: px.count, by: 4) {
                let v = (UInt16(px[p] & 0xF8) << 8) | (UInt16(px[p + 1] & 0xFC) << 3) | UInt16(px[p + 2] >> 3)
                buf[o] = UInt8(v & 0xFF); buf[o + 1] = UInt8(v >> 8)
                o += 2
            }
        }
        return (buf, blocks)
    }

    static func rgba(_ image: CGImage) -> [UInt8] {
        var px = [UInt8](repeating: 0, count: LCDFormat.width * LCDFormat.height * 4)
        let ctx = CGContext(data: &px, width: LCDFormat.width, height: LCDFormat.height, bitsPerComponent: 8,
                            bytesPerRow: LCDFormat.width * 4, space: CGColorSpaceCreateDeviceRGB(),
                            bitmapInfo: CGImageAlphaInfo.noneSkipLast.rawValue)!
        ctx.draw(image, in: CGRect(x: 0, y: 0, width: LCDFormat.width, height: LCDFormat.height))
        return px
    }

    /// Loads a GIF / PNG / JPEG and scales every frame to 240×135 (fill = crop to cover, else fit with black bars).
    static func load(_ url: URL, fill: Bool) -> LCDAnimation? {
        guard let src = MediaBudget.source(url, maxFrames: LCDFormat.maxFrames) else { return nil }
        let count = CGImageSourceGetCount(src)
        var frames: [CGImage] = [], delays: [Int] = []
        for i in 0..<count {
            guard let img = MediaBudget.thumbnail(src,index:i,dimension:480) else { continue }
            frames.append(scaled(img, fill: fill))
            let props = CGImageSourceCopyPropertiesAtIndex(src, i, nil) as? [CFString: Any]
            let gif = props?[kCGImagePropertyGIFDictionary] as? [CFString: Any]
            let d = (gif?[kCGImagePropertyGIFUnclampedDelayTime] as? Double) ?? (gif?[kCGImagePropertyGIFDelayTime] as? Double) ?? 0.1
            delays.append(d.isFinite ? Int(max(20,min(510,d*1000))) : 100)
        }
        return frames.isEmpty ? nil : LCDAnimation(frames: frames, delaysMs: delays, name: url.lastPathComponent)
    }

    static func scaled(_ img: CGImage, fill: Bool) -> CGImage {
        let w = CGFloat(LCDFormat.width), h = CGFloat(LCDFormat.height)
        let ctx = CGContext(data: nil, width: LCDFormat.width, height: LCDFormat.height, bitsPerComponent: 8,
                            bytesPerRow: 0, space: CGColorSpaceCreateDeviceRGB(),
                            bitmapInfo: CGImageAlphaInfo.noneSkipLast.rawValue)!
        ctx.setFillColor(CGColor(gray: 0, alpha: 1))
        ctx.fill(CGRect(x: 0, y: 0, width: w, height: h))
        ctx.interpolationQuality = .high
        let iw = CGFloat(img.width), ih = CGFloat(img.height)
        let s = fill ? max(w / iw, h / ih) : min(w / iw, h / ih)
        let dw = iw * s, dh = ih * s
        ctx.draw(img, in: CGRect(x: (w - dw) / 2, y: (h - dh) / 2, width: dw, height: dh))
        return ctx.makeImage()!
    }
}

// MARK: - Bulk channel (interface 3, endpoint 0x06) via libusb

final class LCDBulkChannel {
    private var ctx: OpaquePointer?
    private var handle: OpaquePointer?
    private var claimed = false

    init(locationID: UInt32) throws {
        var ready = false
        defer { if !ready { close() } }
        guard libusb_init(&ctx) == 0 else { throw LCDError.usb("libusb init failed") }
        var devices: UnsafeMutablePointer<OpaquePointer?>?
        let count = libusb_get_device_list(ctx, &devices)
        guard count >= 0, let devices else { throw LCDError.usb("USB list unavailable") }
        defer { libusb_free_device_list(devices, 1) }
        for index in 0..<Int(count) {
            guard let device = devices[index] else { continue }
            var descriptor = libusb_device_descriptor()
            guard libusb_get_device_descriptor(device, &descriptor) == 0,
                  descriptor.idVendor == 0x0c45, descriptor.idProduct == 0x800a else { continue }
            var ports = [UInt8](repeating:0,count:7)
            let depth = libusb_get_port_numbers(device,&ports,7)
            guard depth > 0, depth <= 6 else { continue }
            var location = UInt32(libusb_get_bus_number(device)) << 24
            for i in 0..<Int(depth) { location |= UInt32(ports[i]) << UInt32(20-4*i) }
            guard location == locationID else { continue }
            guard libusb_open(device,&handle) == 0 else { throw LCDError.usb("USB bulk interface cannot open") }
            break
        }
        guard handle != nil else { throw LCDError.usb("The matching physical AMG65 bulk interface was not found") }
        let result = libusb_claim_interface(handle,3)
        guard result == 0 else { throw LCDError.usb("Cannot claim bulk interface (\(result))") }
        claimed = true; ready = true
    }

    func write(_ data: [UInt8]) throws {
        var bytes = data
        var sent: Int32 = 0
        let r = libusb_interrupt_transfer(handle, 0x06, &bytes, Int32(bytes.count), &sent, 2000)
        guard r == 0, sent == Int32(bytes.count) else { throw LCDError.usb("block write failed (\(r))") }
    }

    private func close() {
        if let handle { if claimed { libusb_release_interface(handle,3) }; libusb_close(handle) }
        if let ctx { libusb_exit(ctx) }
        handle = nil; ctx = nil; claimed = false
    }

    deinit { close() }
}

enum LCDError: Error, CustomStringConvertible {
    case usb(String)
    var description: String { if case let .usb(s) = self { return s }; return "error" }
}

// MARK: - Model

final class ScreenModel: ObservableObject {
    @Published var animation: LCDAnimation?
    @Published var fill = true { didSet { reload() } }
    @Published private(set) var uploading = false
    @Published private(set) var progress = 0.0
    @Published private(set) var lastResult: TransactionResult?
    @Published private(set) var lastTimeSync: TransactionResult?
    private var sourceURL: URL?
    private var generation = 0
    @Published private(set) var loading = false

    init(preload: URL? = nil) {
        if let preload { load(preload) }
    }

    func load(_ url: URL) {
        guard !uploading else { return }
        sourceURL = url; generation += 1
        let token = generation, fit = fill
        loading = true; animation = nil; lastResult = nil
        DispatchQueue.global(qos:.userInitiated).async { [weak self] in
            let loaded = LCDAnimation.load(url,fill:fit)
            DispatchQueue.main.async { [weak self] in
                guard let self, self.generation == token else { return }
                self.loading = false; self.animation = loaded
                if loaded == nil { self.lastResult = TransactionResult(ok:false,lines:["Görsel açılamadı. En fazla 32 MB, 130 kare, 8192 px ve 32 MP desteklenir."]) }
            }
        }
    }

    private func reload() { if let sourceURL { load(sourceURL) } }

    func chooseFile() {
        let panel = NSOpenPanel()
        panel.title = L("Görsel seç…"); panel.prompt = L("Seç")
        panel.allowedContentTypes = [.gif, .png, .jpeg, .image]
        panel.allowsMultipleSelection = false
        if panel.runModal() == .OK, let url = panel.url { load(url) }
    }

    func upload(using hid: KeyboardHID) {
        guard let animation, !uploading else { return }
        uploading = true
        progress = 0
        let (bytes, blocks) = animation.buffer()
        hid.uploadLCD(bytes, blocks: blocks, slot: LCDFormat.slot,
                      progress: { [weak self] p in self?.progress = p }) { [weak self] result in
            self?.uploading = false
            self?.lastResult = result
        }
    }

    func syncTime(using hid: KeyboardHID) {
        hid.send(AMG65Protocol.timeSync(Date(), view: LCDFormat.slot)) { [weak self] r in self?.lastTimeSync = r }
    }
}
