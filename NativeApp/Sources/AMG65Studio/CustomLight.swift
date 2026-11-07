import SwiftUI

struct RGB: Codable, Hashable {
    var r: UInt8, g: UInt8, b: UInt8
    static let off = RGB(r: 0, g: 0, b: 0)
    var color: Color { Color(red: Double(r) / 255, green: Double(g) / 255, blue: Double(b) / 255) }
    var isOff: Bool { r == 0 && g == 0 && b == 0 }
    var hex: String { String(format: "#%02X%02X%02X", r, g, b) }

    /// Six RGB digits only; alpha and partial edits must never change a draft.
    static func parse(hex: String) -> RGB? {
        let text = hex.trimmingCharacters(in: .whitespacesAndNewlines)
        let digits = text.hasPrefix("#") ? String(text.dropFirst()) : text
        guard digits.utf8.count == 6,
              digits.utf8.allSatisfy({ (48...57).contains($0) || (65...70).contains($0) || (97...102).contains($0) }),
              let number = UInt32(digits, radix: 16) else { return nil }
        return RGB(r: UInt8((number >> 16) & 255), g: UInt8((number >> 8) & 255), b: UInt8(number & 255))
    }

    struct Swatch: Identifiable {
        let name: String
        let value: RGB
        var id: String { name }
    }
    static let swatches: [Swatch] = [
        .init(name: "Kırmızı", value: RGB(r: 255, g: 48, b: 48)),
        .init(name: "Turuncu", value: RGB(r: 254, g: 92, b: 24)),
        .init(name: "Sarı", value: RGB(r: 255, g: 210, b: 24)),
        .init(name: "Yeşil", value: RGB(r: 48, g: 230, b: 128)),
        .init(name: "Camgöbeği", value: RGB(r: 32, g: 210, b: 240)),
        .init(name: "Mavi", value: RGB(r: 64, g: 112, b: 255)),
        .init(name: "Mor", value: RGB(r: 184, g: 92, b: 255)),
        .init(name: "Beyaz", value: RGB(r: 255, g: 255, b: 255)),
    ]
}

/// Per-key colours (Custom Light tab). Keys without a colour are off.
final class CustomLightModel: ObservableObject {
    @Published var colors: [Int: RGB] { didSet { save() } }
    @Published var brush = RGB(r: 255, g: 0, b: 0)
    @Published var erasing = false
    @Published var brightness: UInt8 = 5 { didSet { defaults.set(Int(brightness), forKey: "customLightBrightness") } }
    @Published private(set) var appliedColors: [Int: RGB]?
    @Published private(set) var appliedBrightness: UInt8?
    @Published private(set) var applying = false
    @Published private(set) var lastResult: TransactionResult?
    private let defaults: UserDefaults

    /// `preview` (for snapshots) is shown without being saved.
    init(preview: [Int: RGB]? = nil, defaults: UserDefaults = .standard) {
        self.defaults = defaults
        let d = defaults
        colors = preview ?? d.data(forKey: "customLightColors").flatMap { try? JSONDecoder().decode([Int: RGB].self, from: $0) } ?? [:]
        if d.object(forKey: "customLightBrightness") != nil { brightness = UInt8(max(1, min(5, d.integer(forKey: "customLightBrightness")))) }
    }

    var hasUnappliedChanges: Bool { colors != appliedColors || brightness != appliedBrightness }

    func selectBrush(_ color: RGB) {
        brush = color
        erasing = false
    }

    func paint(_ slot: Int) {
        if erasing { colors[slot] = nil } else { colors[slot] = brush }
    }

    func fillAll() {
        var all: [Int: RGB] = [:]
        for k in KeyboardLayout.litKeys { all[k.slot] = brush }
        colors = all
    }

    func apply(using hid: KeyboardHID) {
        guard !applying else { return }
        applying = true
        let sentColors = colors, sentBrightness = brightness
        if hid.connection == .dongle {
            // Dongle: custom-mode packet first, then the table in 0x14 chunks (0x435f40).
            hid.sendDongle(DongleProtocol.customLight(sentColors, brightness: sentBrightness), label: "custom colours") { [weak self] r in
                self?.finish(r, r.ok ? (sentColors, sentBrightness) : nil)
            }
            return
        }
        // 1) upload the colour table, 2) switch lighting to the custom mode — like the Windows app.
        hid.send(AMG65Protocol.customColorTable(sentColors)) { [weak self] first in
            guard let self else { return }
            guard first.ok else { self.finish(first, nil) ; return }
            hid.send(AMG65Protocol.customLightMode(brightness: sentBrightness)) { second in
                let merged = TransactionResult(ok: second.ok, lines: first.lines + ["— custom mode —"] + second.lines)
                self.finish(merged, second.ok ? (sentColors, sentBrightness) : nil)
            }
        }
    }

    private func finish(_ result: TransactionResult, _ applied: ([Int: RGB], UInt8)?) {
        applying = false
        lastResult = result
        if let applied { appliedColors = applied.0; appliedBrightness = applied.1 }
    }

    private func save() {
        if let data = try? JSONEncoder().encode(colors) { defaults.set(data, forKey: "customLightColors") }
    }
}
