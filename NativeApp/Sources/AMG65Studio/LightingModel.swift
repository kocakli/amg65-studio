import Foundation
import SwiftUI

/// Lighting settings shown in the UI. The keyboard can't be read back yet, so the
/// last values the user applied are remembered locally.
final class LightingModel: ObservableObject {
    @Published var settings: LightingSettings { didSet { save() } }
    @Published private(set) var applied: LightingSettings?
    @Published private(set) var applying = false
    @Published private(set) var lastResult: TransactionResult?

    private static let key = "lightingSettings"
    private static let appliedKey = "appliedLightingSettings"
    private let defaults: UserDefaults

    init(defaults: UserDefaults = .standard) {
        self.defaults = defaults
        let d = defaults
        settings = (d.data(forKey: Self.key)).flatMap { try? JSONDecoder().decode(LightingSettings.self, from: $0) }
            ?? LightingSettings()
        applied = (d.data(forKey: Self.appliedKey)).flatMap { try? JSONDecoder().decode(LightingSettings.self, from: $0) }
    }

    var hasUnappliedChanges: Bool { settings != applied }
    var mode: LightingMode { lightingModes.first { $0.id == settings.mode } ?? lightingModes[0] }

    var color: Binding<(r: UInt8, g: UInt8, b: UInt8)> {
        Binding(
            get: { (self.settings.red, self.settings.green, self.settings.blue) },
            set: { self.selectColor(RGB(r: $0.r, g: $0.g, b: $0.b)) }
        )
    }

    var swiftUIColor: Color {
        Color(red: Double(settings.red) / 255, green: Double(settings.green) / 255, blue: Double(settings.blue) / 255)
    }

    var selectedColor: RGB { RGB(r: settings.red, g: settings.green, b: settings.blue) }

    /// Draft only. Choosing a single RGB color must not leave the rainbow flag set.
    func selectColor(_ color: RGB) {
        var draft = settings
        draft.red = color.r; draft.green = color.g; draft.blue = color.b
        draft.colorful = false
        settings = draft
    }

    func useStaticColor() {
        var draft = settings
        draft.mode = 1
        draft.colorful = false
        settings = draft
    }

    func apply(using hid: KeyboardHID) {
        guard !applying else { return }
        applying = true
        let sent = settings
        let finish: (TransactionResult) -> Void = { [weak self] result in
            guard let self else { return }
            self.applying = false
            self.lastResult = result
            if result.ok {
                self.applied = sent
                if let data = try? JSONEncoder().encode(sent) {
                    self.defaults.set(data, forKey: Self.appliedKey)
                }
            }
        }
        if hid.connection == .dongle {
            hid.sendDongle(DongleProtocol.lighting(sent), label: "lighting", completion: finish)
        } else {
            hid.send(AMG65Protocol.lighting(sent), completion: finish)
        }
    }

    private func save() {
        if let data = try? JSONEncoder().encode(settings) {
            defaults.set(data, forKey: Self.key)
        }
    }
}
