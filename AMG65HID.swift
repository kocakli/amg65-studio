import Foundation
import IOKit.hid
import Darwin

// Protocol reference: aumbro/leobog_amg65_rgb, MIT, commit 2bd9ed8.
// This bridge only addresses the AMG65 vendor interface; never the key input interface.
struct BridgeError: Error, CustomStringConvertible {
    let description: String
    init(_ text: String) { description = text }
}

final class Keyboard {
    let manager: IOHIDManager
    let device: IOHIDDevice
    let buffer = UnsafeMutablePointer<UInt8>.allocate(capacity: 64)
    var replies = [[UInt8]]()
    var packets = 0
    var streamActive = false
    var healthy = true
    var lastFrame = Date.distantPast
    var registryID: UInt64 {
        var value: UInt64 = 0
        IORegistryEntryGetRegistryEntryID(IOHIDDeviceGetService(device), &value)
        return value
    }

    init() throws {
        manager = IOHIDManagerCreate(kCFAllocatorDefault, IOOptionBits(kIOHIDOptionsTypeNone))
        IOHIDManagerSetDeviceMatching(manager, [
            kIOHIDVendorIDKey: 0x0c45, kIOHIDProductIDKey: 0x800a,
            kIOHIDPrimaryUsagePageKey: 0xff68, kIOHIDPrimaryUsageKey: 0x61
        ] as CFDictionary)
        guard let devices = IOHIDManagerCopyDevices(manager) as? Set<IOHIDDevice>,
              devices.count == 1, let target = devices.first else {
            throw BridgeError("AMG65 vendor USB interface not found (wired mode required).")
        }
        device = target
        let code = IOHIDDeviceOpen(device, IOOptionBits(kIOHIDOptionsTypeNone))
        guard code == kIOReturnSuccess else {
            throw BridgeError(String(format: "Cannot open AMG65: 0x%08x", code))
        }
        buffer.initialize(repeating: 0, count: 64)
        IOHIDDeviceRegisterInputReportCallback(device, buffer, 64, { context, result, _, _, _, report, length in
            guard result == kIOReturnSuccess, let context else { return }
            let keyboard = Unmanaged<Keyboard>.fromOpaque(context).takeUnretainedValue()
            if keyboard.replies.count < 64 { keyboard.replies.append(Array(UnsafeBufferPointer(start: report, count: length))) }
        }, Unmanaged.passUnretained(self).toOpaque())
        IOHIDDeviceScheduleWithRunLoop(device, CFRunLoopGetCurrent(), CFRunLoopMode.defaultMode.rawValue)
        pump(0.03)
        replies.removeAll()
    }

    deinit {
        IOHIDDeviceUnscheduleFromRunLoop(device, CFRunLoopGetCurrent(), CFRunLoopMode.defaultMode.rawValue)
        IOHIDDeviceClose(device, 0)
        IOHIDManagerClose(manager, 0)
        buffer.deallocate()
    }

    func pump(_ seconds: Double) {
        CFRunLoopRunInMode(CFRunLoopMode.defaultMode, seconds, false)
    }

    func send(_ bytes: [UInt8], expected: UInt8, flush: Bool = false, checksum: UInt16? = nil) throws {
        guard healthy else { throw BridgeError("USB session stopped after missing ACK. Reconnect the keyboard.") }
        guard bytes.count <= 64 else { throw BridgeError("Invalid report length") }
        var report = bytes + [UInt8](repeating: 0, count: 64 - bytes.count)
        replies.removeAll()
        let result = IOHIDDeviceSetReport(device, kIOHIDReportTypeOutput, 0, &report, report.count)
        guard result == kIOReturnSuccess else {
            healthy = false
            throw BridgeError(String(format: "USB write failed: 0x%08x", result))
        }
        let deadline = Date().addingTimeInterval(0.5)
        var observed = [String]()
        while Date() < deadline {
            pump(0.005)
            while !replies.isEmpty {
                let reply = replies.removeFirst()
                observed.append(reply.prefix(8).map { String(format: "%02x", $0) }.joined(separator: " "))
                // On this AMG65, zero-flush returns 00 00 00 FF instead of 04 41 00 01.
                // Verified on the connected device; permit this only for the zero flush.
                let matchingEnvelope = reply.count >= 4 && reply[0] == 4 && reply[1] == expected && reply[2] == 0
                if matchingEnvelope && reply[3] != 1 {
                    // A negative status is a response, not a timeout. Its exact
                    // meaning and retry safety are not guaranteed by firmware.
                    healthy = false
                    throw BridgeError(String(format: "USB rejected opcode 0x%02X with status 0x%02X after %d accepted packets; sending stopped. Reconnect the keyboard.", expected, reply[3], packets))
                }
                let normalAck = matchingEnvelope && reply[3] == 1
                let flushAck = flush && reply.starts(with: [0, 0, 0, 0xff])
                if normalAck || flushAck {
                    if let checksum {
                        guard reply.count >= 6,
                              UInt16(reply[4]) | (UInt16(reply[5]) << 8) == checksum else {
                            healthy = false
                            throw BridgeError("Missing or mismatched USB checksum; sending stopped. Reconnect the keyboard.")
                        }
                    }
                    packets += 1
                    Thread.sleep(forTimeInterval: 0.010)
                    return
                }
            }
        }
        healthy = false
        throw BridgeError(String(format: "No ACK for 0x%02x after %d accepted packets; replies=%@; sending stopped.", expected, packets, observed.joined(separator: ";")))
    }

    func command(_ opcode: UInt8, count: UInt8 = 0, checksum: UInt16? = nil) throws {
        var report = [UInt8](repeating: 0, count: 64)
        report[0] = 4; report[1] = opcode; report[8] = count
        try send(report, expected: opcode, checksum: checksum)
    }

    func syncTime() throws -> String {
        if streamActive { try stopStream() }
        let now = Date()
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = TimeZone.autoupdatingCurrent
        let c = calendar.dateComponents([.year,.month,.day,.hour,.minute,.second,.weekday], from: now)
        var report = [UInt8](repeating: 0, count: 64)
        report[2] = 0x5a
        report[3] = UInt8(c.year! % 100); report[4] = UInt8(c.month!); report[5] = UInt8(c.day!)
        report[6] = UInt8(c.hour!); report[7] = UInt8(c.minute!); report[8] = UInt8(c.second!)
        report[10] = UInt8((c.weekday! + 5) % 7 + 1)
        try command(0x18)
        try command(0x28, count: 1)
        try send(report, expected: 0x41)
        try command(0x02)
        let formatter = ISO8601DateFormatter()
        formatter.timeZone = TimeZone.autoupdatingCurrent
        return formatter.string(from: now)
    }

    func frame(_ pixels: [[Int]]) throws {
        guard pixels.count == 315, pixels.allSatisfy({$0.count == 3 && $0.allSatisfy({0...254 ~= $0})}) else {
            throw BridgeError("Expected 315 RGB pixels with channels 0...254")
        }
        let delay = 0.25 - Date().timeIntervalSince(lastFrame)
        if delay > 0 { Thread.sleep(forTimeInterval: delay) }
        var raw = [UInt8]()
        for block in 0..<4 { for y in 0..<5 { for x in (block*14)..<(block*14+14) {
            raw += pixels[y*63+x].map(UInt8.init)
        } } }
        for y in 0..<5 { for x in 56..<63 { raw += pixels[y*63+x].map(UInt8.init) } }
        raw += [0xaa,0x55] + [UInt8](repeating: 0, count: 13)
        try command(0x18)
        try command(0x35, count: 15)
        streamActive = true
        for offset in stride(from: 0, to: 960, by: 64) {
            try send(Array(raw[offset..<offset+64]), expected: 0x41)
        }
        try send([UInt8](repeating: 0, count: 64), expected: 0x41, flush: true)
        try command(0x02)
        lastFrame = Date()
    }

    func stopStream() throws {
        guard streamActive else { return }
        try command(0x02)
        try command(0xf0)
        streamActive = false
    }

    func lighting(_ request: [String:Any]) throws {
        func integer(_ key:String, _ range:ClosedRange<Int>) throws -> Int {
            guard let number=request[key] as? NSNumber,
                  CFGetTypeID(number) != CFBooleanGetTypeID(),
                  number.doubleValue == Double(number.intValue),range.contains(number.intValue) else {
                throw BridgeError("Invalid lighting \(key)")
            }
            return number.intValue
        }
        let mode=try integer("mode",0...19)
        let brightness=try integer("brightness",1...5)
        let speed=try integer("speed",1...5)
        guard let color=request["color"] as? String,color.count==7,color.first=="#",
              let packed=UInt32(color.dropFirst(),radix:16),let colorful=request["colorful"] as? Bool else {
            throw BridgeError("Invalid lighting color")
        }
        if streamActive { try stopStream() }
        var data=[UInt8](repeating:0,count:64)
        data[0]=UInt8(mode)
        if mode != 0 {
            data[1]=UInt8((packed>>16)&255);data[2]=UInt8((packed>>8)&255);data[3]=UInt8(packed&255)
            data[8]=colorful ? 1:0;data[9]=UInt8(brightness);data[10]=UInt8(speed)
        }
        data[14]=0xaa;data[15]=0x55
        try command(0x18)
        try command(0x13,count:1)
        try send(data,expected:0x41)
        try command(0x02,checksum:data.reduce(UInt16(0)) { $0 &+ UInt16($1) })
        try command(0xf0)
    }
}

func emit(_ value: [String: Any]) {
    if let data = try? JSONSerialization.data(withJSONObject: value, options: [.sortedKeys]),
       let text = String(data: data, encoding: .utf8) {
        print(text); fflush(stdout)
    }
}

// A per-user lock protects every invocation, including direct CLI calls and
// companions with different state directories. macOS releases it on process exit.
let hardwareLock = open("/private/tmp/amg65-hid-\(getuid()).lock", O_RDWR | O_CREAT | O_NOFOLLOW, S_IRUSR | S_IWUSR)
do {
    guard hardwareLock >= 0, flock(hardwareLock, LOCK_EX | LOCK_NB) == 0 else {
        throw BridgeError("Another AMG65 bridge is using the vendor USB interface.")
    }
    let keyboard = try Keyboard()
    let arg = CommandLine.arguments.dropFirst().first ?? "--probe"
    if arg == "--sync-time" {
        emit(["ok": true, "synced_at": try keyboard.syncTime(), "timezone": TimeZone.autoupdatingCurrent.identifier, "acknowledged_packets": keyboard.packets])
    } else if arg == "--session" {
        emit(["ok": true, "device": "LEOBOG AMG65", "vendor": "0C45:800A", "registry_id": keyboard.registryID])
        while let line = readLine() {
            do {
                guard let bytes = line.data(using: .utf8),
                      let request = try JSONSerialization.jsonObject(with: bytes) as? [String: Any],
                      let op = request["op"] as? String else { throw BridgeError("Invalid request") }
                switch op {
                case "time": emit(["ok": true, "synced_at": try keyboard.syncTime(), "timezone": TimeZone.autoupdatingCurrent.identifier])
                case "frame":
                    guard let pixels = request["pixels"] as? [[Int]] else { throw BridgeError("Missing pixels") }
                    try keyboard.frame(pixels)
                    emit(["ok": true, "acknowledged_packets": keyboard.packets])
                case "stop": try keyboard.stopStream(); emit(["ok":true])
                case "lighting": try keyboard.lighting(request); emit(["ok":true,"acknowledged_packets":keyboard.packets])
                case "close": try keyboard.stopStream(); emit(["ok":true]); exit(0)
                default: throw BridgeError("Unknown operation")
                }
            } catch { emit(["ok": false,"error": String(describing:error)]) }
        }
        try keyboard.stopStream()
    } else if arg == "--probe" {
        emit(["ok":true,"device":"LEOBOG AMG65","vendor":"0C45:800A","usage_page":"FF68","timezone":TimeZone.autoupdatingCurrent.identifier,"registry_id":keyboard.registryID])
    } else { throw BridgeError("Usage: amg65-hid --probe | --sync-time | --session") }
} catch { emit(["ok": false,"error": String(describing:error)]); exit(1) }
