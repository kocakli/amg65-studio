import Foundation
import SwiftUI

// MARK: - AMG65 physical switch slots with independently drawn key geometry

struct PhysicalKey: Identifiable, Hashable {
    let slot: Int          // key_index = slot in the 0x11 key map
    let code: UInt8        // default HID usage
    let name: String
    let rect: CGRect       // studio layout coordinates
    var id: Int { slot }
    /// Fn and the volume knob aren't remappable here (Fn would lose its layer).
    var remappable: Bool { code != 0xAF && !isKnob }
    /// The volume knob is listed as two "keys" (vol +/−) with no light, drawn off the keyboard image.
    var isKnob: Bool { code == 0xE9 || code == 0xEA }
}

extension KeyboardLayout {
    /// Keys that have a backlight LED (everything except the knob).
    static var litKeys: [PhysicalKey] { keys.filter { !$0.isKnob } }
}

enum KeyboardLayout {
    static let keys: [PhysicalKey] = load()

    private static func load() -> [PhysicalKey] {
        var keys: [PhysicalKey] = []
        keys.append(PhysicalKey(slot: 0, code: 41, name: "Esc", rect: CGRect(x: 0, y: 0, width: 46, height: 46)))
        keys.append(PhysicalKey(slot: 17, code: 30, name: "1", rect: CGRect(x: 50, y: 0, width: 46, height: 46)))
        keys.append(PhysicalKey(slot: 18, code: 31, name: "2", rect: CGRect(x: 100, y: 0, width: 46, height: 46)))
        keys.append(PhysicalKey(slot: 19, code: 32, name: "3", rect: CGRect(x: 150, y: 0, width: 46, height: 46)))
        keys.append(PhysicalKey(slot: 20, code: 33, name: "4", rect: CGRect(x: 200, y: 0, width: 46, height: 46)))
        keys.append(PhysicalKey(slot: 21, code: 34, name: "5", rect: CGRect(x: 250, y: 0, width: 46, height: 46)))
        keys.append(PhysicalKey(slot: 22, code: 35, name: "6", rect: CGRect(x: 300, y: 0, width: 46, height: 46)))
        keys.append(PhysicalKey(slot: 23, code: 36, name: "7", rect: CGRect(x: 350, y: 0, width: 46, height: 46)))
        keys.append(PhysicalKey(slot: 24, code: 37, name: "8", rect: CGRect(x: 400, y: 0, width: 46, height: 46)))
        keys.append(PhysicalKey(slot: 25, code: 38, name: "9", rect: CGRect(x: 450, y: 0, width: 46, height: 46)))
        keys.append(PhysicalKey(slot: 26, code: 39, name: "0", rect: CGRect(x: 500, y: 0, width: 46, height: 46)))
        keys.append(PhysicalKey(slot: 27, code: 45, name: "-", rect: CGRect(x: 550, y: 0, width: 46, height: 46)))
        keys.append(PhysicalKey(slot: 28, code: 46, name: "=", rect: CGRect(x: 600, y: 0, width: 46, height: 46)))
        keys.append(PhysicalKey(slot: 92, code: 42, name: "Backspace", rect: CGRect(x: 650, y: 0, width: 96, height: 46)))
        keys.append(PhysicalKey(slot: 104, code: 74, name: "Home", rect: CGRect(x: 750, y: 0, width: 46, height: 46)))
        keys.append(PhysicalKey(slot: 32, code: 43, name: "Tab", rect: CGRect(x: 0, y: 52, width: 71, height: 46)))
        keys.append(PhysicalKey(slot: 33, code: 20, name: "Q", rect: CGRect(x: 75, y: 52, width: 46, height: 46)))
        keys.append(PhysicalKey(slot: 34, code: 26, name: "W", rect: CGRect(x: 125, y: 52, width: 46, height: 46)))
        keys.append(PhysicalKey(slot: 35, code: 8, name: "E", rect: CGRect(x: 175, y: 52, width: 46, height: 46)))
        keys.append(PhysicalKey(slot: 36, code: 21, name: "R", rect: CGRect(x: 225, y: 52, width: 46, height: 46)))
        keys.append(PhysicalKey(slot: 37, code: 23, name: "T", rect: CGRect(x: 275, y: 52, width: 46, height: 46)))
        keys.append(PhysicalKey(slot: 38, code: 28, name: "Y", rect: CGRect(x: 325, y: 52, width: 46, height: 46)))
        keys.append(PhysicalKey(slot: 39, code: 24, name: "U", rect: CGRect(x: 375, y: 52, width: 46, height: 46)))
        keys.append(PhysicalKey(slot: 40, code: 12, name: "I", rect: CGRect(x: 425, y: 52, width: 46, height: 46)))
        keys.append(PhysicalKey(slot: 41, code: 18, name: "O", rect: CGRect(x: 475, y: 52, width: 46, height: 46)))
        keys.append(PhysicalKey(slot: 42, code: 19, name: "P", rect: CGRect(x: 525, y: 52, width: 46, height: 46)))
        keys.append(PhysicalKey(slot: 43, code: 47, name: "[", rect: CGRect(x: 575, y: 52, width: 46, height: 46)))
        keys.append(PhysicalKey(slot: 44, code: 48, name: "]", rect: CGRect(x: 625, y: 52, width: 46, height: 46)))
        keys.append(PhysicalKey(slot: 60, code: 49, name: "\\", rect: CGRect(x: 675, y: 52, width: 71, height: 46)))
        keys.append(PhysicalKey(slot: 106, code: 76, name: "Del", rect: CGRect(x: 750, y: 52, width: 46, height: 46)))
        keys.append(PhysicalKey(slot: 48, code: 57, name: "Caps", rect: CGRect(x: 0, y: 104, width: 83.5, height: 46)))
        keys.append(PhysicalKey(slot: 49, code: 4, name: "A", rect: CGRect(x: 87.5, y: 104, width: 46, height: 46)))
        keys.append(PhysicalKey(slot: 50, code: 22, name: "S", rect: CGRect(x: 137.5, y: 104, width: 46, height: 46)))
        keys.append(PhysicalKey(slot: 51, code: 7, name: "D", rect: CGRect(x: 187.5, y: 104, width: 46, height: 46)))
        keys.append(PhysicalKey(slot: 52, code: 9, name: "F", rect: CGRect(x: 237.5, y: 104, width: 46, height: 46)))
        keys.append(PhysicalKey(slot: 53, code: 10, name: "G", rect: CGRect(x: 287.5, y: 104, width: 46, height: 46)))
        keys.append(PhysicalKey(slot: 54, code: 11, name: "H", rect: CGRect(x: 337.5, y: 104, width: 46, height: 46)))
        keys.append(PhysicalKey(slot: 55, code: 13, name: "J", rect: CGRect(x: 387.5, y: 104, width: 46, height: 46)))
        keys.append(PhysicalKey(slot: 56, code: 14, name: "K", rect: CGRect(x: 437.5, y: 104, width: 46, height: 46)))
        keys.append(PhysicalKey(slot: 57, code: 15, name: "L", rect: CGRect(x: 487.5, y: 104, width: 46, height: 46)))
        keys.append(PhysicalKey(slot: 58, code: 51, name: ";", rect: CGRect(x: 537.5, y: 104, width: 46, height: 46)))
        keys.append(PhysicalKey(slot: 59, code: 52, name: "'", rect: CGRect(x: 587.5, y: 104, width: 46, height: 46)))
        keys.append(PhysicalKey(slot: 76, code: 40, name: "Enter", rect: CGRect(x: 637.5, y: 104, width: 108.5, height: 46)))
        keys.append(PhysicalKey(slot: 105, code: 75, name: "PgUp", rect: CGRect(x: 750, y: 104, width: 46, height: 46)))
        keys.append(PhysicalKey(slot: 64, code: 225, name: "Shift", rect: CGRect(x: 0, y: 156, width: 108.5, height: 46)))
        keys.append(PhysicalKey(slot: 65, code: 29, name: "Z", rect: CGRect(x: 112.5, y: 156, width: 46, height: 46)))
        keys.append(PhysicalKey(slot: 66, code: 27, name: "X", rect: CGRect(x: 162.5, y: 156, width: 46, height: 46)))
        keys.append(PhysicalKey(slot: 67, code: 6, name: "C", rect: CGRect(x: 212.5, y: 156, width: 46, height: 46)))
        keys.append(PhysicalKey(slot: 68, code: 25, name: "V", rect: CGRect(x: 262.5, y: 156, width: 46, height: 46)))
        keys.append(PhysicalKey(slot: 69, code: 5, name: "B", rect: CGRect(x: 312.5, y: 156, width: 46, height: 46)))
        keys.append(PhysicalKey(slot: 70, code: 17, name: "N", rect: CGRect(x: 362.5, y: 156, width: 46, height: 46)))
        keys.append(PhysicalKey(slot: 71, code: 16, name: "M", rect: CGRect(x: 412.5, y: 156, width: 46, height: 46)))
        keys.append(PhysicalKey(slot: 72, code: 54, name: ",", rect: CGRect(x: 462.5, y: 156, width: 46, height: 46)))
        keys.append(PhysicalKey(slot: 73, code: 55, name: ".", rect: CGRect(x: 512.5, y: 156, width: 46, height: 46)))
        keys.append(PhysicalKey(slot: 74, code: 56, name: "/", rect: CGRect(x: 562.5, y: 156, width: 46, height: 46)))
        keys.append(PhysicalKey(slot: 75, code: 229, name: "Shift", rect: CGRect(x: 612.5, y: 156, width: 83.5, height: 46)))
        keys.append(PhysicalKey(slot: 90, code: 82, name: "↑", rect: CGRect(x: 700, y: 156, width: 46, height: 46)))
        keys.append(PhysicalKey(slot: 108, code: 78, name: "PgDn", rect: CGRect(x: 750, y: 156, width: 46, height: 46)))
        keys.append(PhysicalKey(slot: 80, code: 224, name: "Ctrl", rect: CGRect(x: 0, y: 208, width: 58.5, height: 46)))
        keys.append(PhysicalKey(slot: 81, code: 227, name: "⌘", rect: CGRect(x: 62.5, y: 208, width: 58.5, height: 46)))
        keys.append(PhysicalKey(slot: 82, code: 226, name: "⌥", rect: CGRect(x: 125, y: 208, width: 58.5, height: 46)))
        keys.append(PhysicalKey(slot: 83, code: 44, name: "Space", rect: CGRect(x: 187.5, y: 208, width: 308.5, height: 46)))
        keys.append(PhysicalKey(slot: 85, code: 175, name: "Fn", rect: CGRect(x: 500, y: 208, width: 46, height: 46)))
        keys.append(PhysicalKey(slot: 87, code: 228, name: "Ctrl", rect: CGRect(x: 550, y: 208, width: 46, height: 46)))
        keys.append(PhysicalKey(slot: 88, code: 80, name: "←", rect: CGRect(x: 600, y: 208, width: 46, height: 46)))
        keys.append(PhysicalKey(slot: 89, code: 81, name: "↓", rect: CGRect(x: 650, y: 208, width: 46, height: 46)))
        keys.append(PhysicalKey(slot: 91, code: 79, name: "→", rect: CGRect(x: 700, y: 208, width: 46, height: 46)))
        return keys
    }
}

// MARK: - What a key can be remapped to

enum KeyAction: Codable, Hashable {
    /// Type 02: modifier bits + HID keyboard usage (confirmed on the keyboard).
    case key(modifiers: UInt8, code: UInt8)
    /// Type 03: HID consumer usage (decoded from the app, untested).
    case media(UInt16)
    /// Type 01 01: mouse button mask (decoded, untested).
    case mouseButton(UInt8)
    /// Type 01 03: wheel +1 / -1 (decoded, untested).
    case wheel(up: Bool)

    var slot: [UInt8] {
        switch self {
        case let .key(mods, code):
            if (0xE0...0xE7).contains(code) { return [0x02, mods | (1 << (code - 0xE0)), 0x00, 0x00] }
            return [0x02, mods, code, 0x00]
        case let .media(u): return [0x03, UInt8(u & 0xFF), UInt8(u >> 8), 0x00]
        case let .mouseButton(mask): return [0x01, 0x01, mask, 0x00]
        case let .wheel(up): return [0x01, 0x03, up ? 0x01 : 0xFF, 0x00]
        }
    }

    var title: String {
        switch self {
        case let .key(mods, code):
            let name = HIDKeys.name(code)
            let m = Modifier.allCases.filter { mods & $0.bit != 0 }.map(\.symbol).joined()
            return m.isEmpty ? name : "\(m) \(name)"
        case let .media(u): return MediaKeys.all.first { $0.usage == u }?.name ?? String(format: "Media %04X", u)
        case let .mouseButton(m): return MouseActions.buttons.first { $0.mask == m }?.name ?? "Mouse \(m)"
        case let .wheel(up): return up ? "Scroll up" : "Scroll down"
        }
    }

    var tested: Bool { if case .key = self { true } else { false } }
}

enum Modifier: CaseIterable {
    case control, shift, option, command
    var bit: UInt8 {
        switch self { case .control: 0x01; case .shift: 0x02; case .option: 0x04; case .command: 0x08 }
    }
    var symbol: String {
        switch self { case .control: "⌃"; case .shift: "⇧"; case .option: "⌥"; case .command: "⌘" }
    }
    var name: String {
        switch self { case .control: "Control"; case .shift: "Shift"; case .option: "Option / Alt"; case .command: "Command / Win" }
    }
}

enum HIDKeys {
    struct Entry: Identifiable { let code: UInt8; let name: String; var id: UInt8 { code } }

    static let groups: [(String, [Entry])] = [
        ("Letters", (0..<26).map { Entry(code: 0x04 + UInt8($0), name: String(UnicodeScalar(65 + $0)!)) }),
        ("Numbers", (1...10).map { Entry(code: 0x1D + UInt8($0), name: $0 == 10 ? "0" : "\($0)") }),
        ("Function", (1...12).map { Entry(code: 0x39 + UInt8($0), name: "F\($0)") }
            + (13...24).map { Entry(code: 0x5B + UInt8($0), name: "F\($0)") }),
        ("Editing", [
            .init(code: 0x29, name: "Esc"), .init(code: 0x2B, name: "Tab"), .init(code: 0x39, name: "Caps Lock"),
            .init(code: 0x2C, name: "Space"), .init(code: 0x28, name: "Enter"), .init(code: 0x2A, name: "Backspace"),
            .init(code: 0x4C, name: "Delete"), .init(code: 0x49, name: "Insert"),
        ]),
        ("Navigation", [
            .init(code: 0x4A, name: "Home"), .init(code: 0x4D, name: "End"), .init(code: 0x4B, name: "Page Up"),
            .init(code: 0x4E, name: "Page Down"), .init(code: 0x50, name: "←"), .init(code: 0x4F, name: "→"),
            .init(code: 0x52, name: "↑"), .init(code: 0x51, name: "↓"),
        ]),
        ("Symbols", [
            .init(code: 0x35, name: "`"), .init(code: 0x2D, name: "-"), .init(code: 0x2E, name: "="),
            .init(code: 0x2F, name: "["), .init(code: 0x30, name: "]"), .init(code: 0x31, name: "\\"),
            .init(code: 0x33, name: ";"), .init(code: 0x34, name: "'"), .init(code: 0x36, name: ","),
            .init(code: 0x37, name: "."), .init(code: 0x38, name: "/"),
        ]),
        ("Modifiers", [
            .init(code: 0xE0, name: "Left Ctrl"), .init(code: 0xE1, name: "Left Shift"), .init(code: 0xE2, name: "Left Alt/⌥"),
            .init(code: 0xE3, name: "Left Win/⌘"), .init(code: 0xE4, name: "Right Ctrl"), .init(code: 0xE5, name: "Right Shift"),
            .init(code: 0xE6, name: "Right Alt/⌥"), .init(code: 0xE7, name: "Right Win/⌘"),
        ]),
        ("Other", [
            .init(code: 0x46, name: "Print Screen"), .init(code: 0x47, name: "Scroll Lock"), .init(code: 0x48, name: "Pause"),
        ]),
    ]

    static func name(_ code: UInt8) -> String {
        for (_, list) in groups { if let e = list.first(where: { $0.code == code }) { return e.name } }
        return String(format: "Key %02X", code)
    }
}

enum MediaKeys {
    struct Entry: Identifiable { let usage: UInt16; let name: String; var id: UInt16 { usage } }
    static let all: [Entry] = [
        .init(usage: 0xCD, name: "Play / Pause"), .init(usage: 0xB5, name: "Next track"),
        .init(usage: 0xB6, name: "Previous track"), .init(usage: 0xB7, name: "Stop"),
        .init(usage: 0xE9, name: "Volume up"), .init(usage: 0xEA, name: "Volume down"),
        .init(usage: 0xE2, name: "Mute"),
    ]
}

enum MouseActions {
    struct Button: Identifiable { let mask: UInt8; let name: String; var id: UInt8 { mask } }
    static let buttons: [Button] = [
        .init(mask: 0x01, name: "Left click"), .init(mask: 0x02, name: "Right click"),
        .init(mask: 0x04, name: "Middle click"), .init(mask: 0x08, name: "Back"), .init(mask: 0x10, name: "Forward"),
    ]
}

// MARK: - Model

/// The remaps the user has set. The keyboard can't be read back, so the
/// last-applied map is remembered locally.
final class KeymapModel: ObservableObject {
    @Published var assignments: [Int: KeyAction] { didSet { save(Self.key, assignments) } }
    @Published private(set) var applied: [Int: KeyAction]?
    @Published var selectedSlot: Int?
    @Published private(set) var applying = false
    @Published private(set) var lastResult: TransactionResult?

    private static let key = "keymapAssignments"
    private static let appliedKey = "appliedKeymap"

    init() {
        assignments = Self.load(Self.key) ?? [:]
        applied = Self.load(Self.appliedKey)
    }

    var hasUnappliedChanges: Bool { assignments != (applied ?? [:]) }
    var selectedKey: PhysicalKey? { KeyboardLayout.keys.first { $0.slot == selectedSlot } }

    func assign(_ action: KeyAction?) {
        guard let slot = selectedSlot else { return }
        if let action, action != .key(modifiers: 0, code: selectedKey?.code ?? 0) {
            assignments[slot] = action
        } else {
            assignments[slot] = nil   // same as default → no remap
        }
    }

    func apply(using hid: KeyboardHID) {
        guard !applying else { return }
        applying = true
        let sent = assignments
        let finish: (TransactionResult) -> Void = { [weak self] result in
            guard let self else { return }
            self.applying = false
            self.lastResult = result
            if result.ok {
                self.applied = sent
                self.save(Self.appliedKey, sent)
            }
        }
        if hid.connection == .dongle {
            hid.sendDongle(DongleProtocol.keymap(sent.mapValues(\.slot)), label: "key map", completion: finish)
        } else {
            hid.send(AMG65Protocol.keymap(sent.mapValues(\.slot)), completion: finish)
        }
    }

    private func save(_ key: String, _ value: [Int: KeyAction]) {
        if let data = try? JSONEncoder().encode(value) { UserDefaults.standard.set(data, forKey: key) }
    }

    private static func load(_ key: String) -> [Int: KeyAction]? {
        UserDefaults.standard.data(forKey: key).flatMap { try? JSONDecoder().decode([Int: KeyAction].self, from: $0) }
    }
}
