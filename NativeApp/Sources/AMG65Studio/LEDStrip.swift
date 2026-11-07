import AppKit
import ImageIO
import SwiftUI

// MARK: - Format (cmd 0x33 animation / 0x31 boot animation) — confirmed on the keyboard

enum StripFormat {
    static let width = 63, height = 5, leds = 315

    /// Row-major pixel → LED index (4 panels of 14 × 5, then one of 7 × 5). Same as the app's table at 0x59c7f0.
    static let position: [Int] = (0..<height).flatMap { r in
        (0..<width).map { c in c < 56 ? 70 * (c / 14) + 14 * r + c % 14 : 280 + 7 * r + (c - 56) }
    }
}

enum StripTarget: String, CaseIterable, Identifiable {
    case animation = "Animation", boot = "Boot animation"
    var id: String { rawValue }
    var command: UInt8 { self == .animation ? 0x33 : 0x31 }
    var maxFrames: Int { self == .animation ? 260 : 200 }
}

/// Frames of 63 × 5 RGB pixels (row-major).
struct StripAnimation {
    var frames: [[RGB]]
    var name: String

    func buffer(delay: UInt16, brightness: Double, target: StripTarget) -> (bytes: [UInt8], blocks: Int) {
        let frames = Array(self.frames.prefix(target.maxFrames))
        let end = 4 + frames.count * StripFormat.leds * 3
        let blocks = (end + 2 + 4095) / 4096
        var buf = [UInt8](repeating: 0, count: blocks * 4096)
        buf[0] = UInt8(frames.count & 0xFF); buf[1] = UInt8(frames.count >> 8)
        buf[2] = UInt8(delay & 0xFF); buf[3] = UInt8(delay >> 8)
        let k = max(0, min(1, brightness))
        for (f, frame) in frames.enumerated() {
            for (i, c) in frame.enumerated() where i < StripFormat.leds {
                let o = 4 + 3 * (f * StripFormat.leds + StripFormat.position[i])
                buf[o] = UInt8(Double(c.r) * k); buf[o + 1] = UInt8(Double(c.g) * k); buf[o + 2] = UInt8(Double(c.b) * k)
            }
        }
        buf[end] = 0xAA; buf[end + 1] = 0x55
        return (buf, blocks)
    }

    /// GIF / image → frames scaled to 63 × 5.
    static func load(_ url: URL) -> StripAnimation? {
        guard let src = MediaBudget.source(url,maxFrames:260) else { return nil }
        var frames: [[RGB]] = []
        for i in 0..<CGImageSourceGetCount(src) {
            if let img = MediaBudget.thumbnail(src,index:i,dimension:126) { frames.append(pixels(img)) }
        }
        return frames.isEmpty ? nil : StripAnimation(frames: frames, name: url.lastPathComponent)
    }

    static func pixels(_ img: CGImage) -> [RGB] {
        let w = StripFormat.width, h = StripFormat.height
        var px = [UInt8](repeating: 0, count: w * h * 4)
        let ctx = CGContext(data: &px, width: w, height: h, bitsPerComponent: 8, bytesPerRow: w * 4,
                            space: CGColorSpaceCreateDeviceRGB(), bitmapInfo: CGImageAlphaInfo.noneSkipLast.rawValue)!
        ctx.interpolationQuality = .medium
        ctx.draw(img, in: CGRect(x: 0, y: 0, width: w, height: h))
        return stride(from: 0, to: px.count, by: 4).map { RGB(r: px[$0], g: px[$0 + 1], b: px[$0 + 2]) }
    }

    /// Text scrolling right-to-left in a 3 × 5 pixel font.
    static func scrollingText(_ text: String, color: RGB) -> StripAnimation {
        let columns = TinyFont.columns(String(String(text.prefix(48)).uppercased().prefix(48)))
        let total = columns.count + StripFormat.width
        var frames: [[RGB]] = []
        for shift in 0..<total {
            var f = [RGB](repeating: .off, count: StripFormat.leds)
            for x in 0..<StripFormat.width {
                let col = x + shift - StripFormat.width
                guard col >= 0, col < columns.count else { continue }
                for y in 0..<5 where columns[col] & (1 << y) != 0 { f[y * StripFormat.width + x] = color }
            }
            frames.append(f)
        }
        return StripAnimation(frames: frames, name: "“\(String(text.prefix(48)))”")
    }
}

/// 3 × 5 pixel font. Each glyph = 3 columns; bit y (0 = top) set = lit.
enum TinyFont {
    private static let rows: [Character: [String]] = [
        "A": ["010", "101", "111", "101", "101"], "B": ["110", "101", "110", "101", "110"],
        "C": ["011", "100", "100", "100", "011"], "D": ["110", "101", "101", "101", "110"],
        "E": ["111", "100", "110", "100", "111"], "F": ["111", "100", "110", "100", "100"],
        "G": ["011", "100", "101", "101", "011"], "H": ["101", "101", "111", "101", "101"],
        "I": ["111", "010", "010", "010", "111"], "J": ["001", "001", "001", "101", "010"],
        "K": ["101", "101", "110", "101", "101"], "L": ["100", "100", "100", "100", "111"],
        "M": ["101", "111", "111", "101", "101"], "N": ["110", "101", "101", "101", "101"],
        "O": ["010", "101", "101", "101", "010"], "P": ["110", "101", "110", "100", "100"],
        "Q": ["010", "101", "101", "110", "011"], "R": ["110", "101", "110", "101", "101"],
        "S": ["011", "100", "010", "001", "110"], "T": ["111", "010", "010", "010", "010"],
        "U": ["101", "101", "101", "101", "111"], "V": ["101", "101", "101", "101", "010"],
        "W": ["101", "101", "111", "111", "101"], "X": ["101", "101", "010", "101", "101"],
        "Y": ["101", "101", "010", "010", "010"], "Z": ["111", "001", "010", "100", "111"],
        "0": ["111", "101", "101", "101", "111"], "1": ["010", "110", "010", "010", "111"],
        "2": ["110", "001", "010", "100", "111"], "3": ["110", "001", "010", "001", "110"],
        "4": ["101", "101", "111", "001", "001"], "5": ["111", "100", "110", "001", "110"],
        "6": ["011", "100", "111", "101", "111"], "7": ["111", "001", "010", "010", "010"],
        "8": ["111", "101", "111", "101", "111"], "9": ["111", "101", "111", "001", "110"],
        "!": ["010", "010", "010", "000", "010"], "?": ["110", "001", "010", "000", "010"],
        ".": ["000", "000", "000", "000", "010"], ",": ["000", "000", "000", "010", "100"],
        ":": ["000", "010", "000", "010", "000"], "-": ["000", "000", "111", "000", "000"],
        "+": ["000", "010", "111", "010", "000"], "'": ["010", "010", "000", "000", "000"],
        "/": ["001", "001", "010", "100", "100"], "#": ["101", "111", "101", "111", "101"],
        "<": ["001", "010", "100", "010", "001"], ">": ["100", "010", "001", "010", "100"],
        "%": ["101", "001", "010", "100", "101"], "=": ["000", "111", "000", "111", "000"],
        " ": ["000", "000", "000", "000", "000"],
    ]

    static func columns(_ text: String) -> [UInt8] {
        var out: [UInt8] = []
        for ch in text {
            let g = rows[ch] ?? rows["?"]!
            for c in 0..<3 {
                var bits: UInt8 = 0
                for y in 0..<5 where Array(g[y])[c] == "1" { bits |= 1 << y }
                out.append(bits)
            }
            out.append(0)   // 1-column gap
        }
        return out
    }
}

// MARK: - Model

final class StripModel: ObservableObject {
    enum Source: String, CaseIterable, Identifiable { case text = "Text", image = "GIF / image"; var id: String { rawValue } }

    @Published var source: Source = .text { didSet { rebuild() } }
    @Published var text = "HELLO FROM MAC" { didSet { rebuild() } }
    @Published var textColor = RGB(r: 0, g: 200, b: 255) { didSet { rebuild() } }
    @Published var delay: UInt8 = 10          // frame delay word; ≈ 75 ms + 2.2 ms × delay per frame (measured)

    /// Estimated time per frame on the keyboard, from user timings (delay 20 ≈ 118 ms, 80 ≈ 250 ms).
    static func frameMs(_ delay: UInt8) -> Double { 75 + 2.2 * Double(delay) }
    @Published var brightness: UInt8 = 5      // 1…5 → 20…100 %
    @Published var target: StripTarget = .animation
    @Published private(set) var animation: StripAnimation?
    @Published private(set) var uploading = false
    @Published private(set) var progress = 0.0
    @Published private(set) var lastResult: TransactionResult?
    private var imageAnimation: StripAnimation?
    private var generation = 0
    private var rebuildWork: DispatchWorkItem?
    @Published private(set) var loading = false

    init() { rebuild() }

    func rebuild() {
        if text.count > 48 { text = String(text.prefix(48)); return }
        rebuildWork?.cancel()
        let task = DispatchWorkItem { [weak self] in
            guard let self else { return }
            self.animation = self.source == .text ? StripAnimation.scrollingText(self.text,color:self.textColor) : self.imageAnimation
        }
        rebuildWork = task
        DispatchQueue.main.asyncAfter(deadline:.now()+0.12,execute:task)
    }

    func load(_ url: URL) {
        guard !uploading else { return }
        generation += 1; let token = generation
        loading = true; lastResult = nil
        DispatchQueue.global(qos:.userInitiated).async { [weak self] in
            let loaded = StripAnimation.load(url)
            DispatchQueue.main.async { [weak self] in
                guard let self, self.generation == token else { return }
                self.loading = false; self.imageAnimation = loaded; self.source = .image; self.rebuild()
                if loaded == nil { self.lastResult = TransactionResult(ok:false,lines:["Görsel açılamadı. En fazla 32 MB, 260 kare, 8192 px ve 32 MP desteklenir."]) }
            }
        }
    }

    func chooseFile() {
        let panel = NSOpenPanel()
        panel.allowedContentTypes = [.gif, .png, .jpeg, .image]
        if panel.runModal() == .OK, let url = panel.url { load(url) }
    }

    func upload(using hid: KeyboardHID) {
        guard let animation, !uploading else { return }
        uploading = true; progress = 0
        let (bytes, blocks) = animation.buffer(delay: UInt16(delay), brightness: Double(brightness) / 5, target: target)
        hid.uploadBulk(bytes, blocks: blocks,
                       header: AMG65Protocol.packet([0x04, target.command], [8: UInt8(blocks & 0xFF), 9: UInt8(blocks >> 8)]),
                       headerLabel: "strip header (04 \(String(format: "%02X", target.command)), \(blocks) blocks)",
                       applyAfter: true,
                       progress: { [weak self] p in self?.progress = p }) { [weak self] r in
            self?.uploading = false; self?.lastResult = r
        }
    }
}
