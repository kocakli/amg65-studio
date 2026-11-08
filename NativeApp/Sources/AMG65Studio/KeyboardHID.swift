import Foundation
import Combine
import IOKit
import IOKit.hid
import Darwin

enum Connection: Equatable { case none, dongle, wired }
struct TransactionResult { var ok: Bool; var lines: [String] }

/// One selected physical device, one process-wide writer, and serialized transactions.
final class KeyboardHID: ObservableObject {
    @Published private(set) var connection: Connection = .none
    @Published private(set) var error: String?
    @Published private(set) var busy = false
    @Published private(set) var failedRegistryID: UInt64?
    private let io = DispatchQueue(label: "studio.hid.transactions")
    private let replyLock = NSLock()
    private var replies = [[UInt8]]()
    private let signal = DispatchSemaphore(value: 0)
    private var device: IOHIDDevice?
    private var manager: IOHIDManager?
    private var selectedConnection: Connection = .none
    private var faulted = false
    private var activeSender: UnsafeMutableRawPointer?
    private var hardwareLock: Int32 = -1
    private var hidLoop: CFRunLoop!
    private var thread: Thread?
    private let buffer = UnsafeMutablePointer<UInt8>.allocate(capacity: 64)

    init() {
        let ready = DispatchSemaphore(value: 0)
        let t = Thread { [weak self] in
            guard let self else { return }
            self.hidLoop = CFRunLoopGetCurrent()
            let timer = Timer(timeInterval: 3600, repeats: true) { _ in }
            RunLoop.current.add(timer, forMode: .default)
            ready.signal()
            RunLoop.current.run()
        }
        t.name = "AMG65 Studio HID callbacks"; t.start(); thread = t; ready.wait()
    }

    private func onHID(_ body: @escaping () -> Void) {
        CFRunLoopPerformBlock(hidLoop, CFRunLoopMode.defaultMode.rawValue, body)
        CFRunLoopWakeUp(hidLoop)
    }

    func resume(completion: @escaping (Bool) -> Void) {
        io.async {
            if self.device != nil {
                DispatchQueue.main.async { completion(!self.faulted) }; return
            }
            let fd = Darwin.open("/private/tmp/amg65-hid-\(getuid()).lock", O_CREAT | O_RDWR | O_NOFOLLOW, S_IRUSR | S_IWUSR)
            guard fd >= 0, flock(fd, LOCK_EX | LOCK_NB) == 0 else {
                if fd >= 0 { Darwin.close(fd) }
                DispatchQueue.main.async { self.error = "USB başka bir uygulamada. Kullanım panelinden denetimi devralmayı yeniden deneyin."; completion(false) }
                return
            }
            self.hardwareLock = fd
            let finished = DispatchSemaphore(value: 0)
            var result = false
            self.onHID {
                result = self.openDevice()
                finished.signal()
            }
            finished.wait()
            if !result { Darwin.close(self.hardwareLock); self.hardwareLock = -1 }
            DispatchQueue.main.async { completion(result) }
        }
    }

    private func openDevice() -> Bool {
        let manager = IOHIDManagerCreate(kCFAllocatorDefault, 0)
        let matches: [[String:Any]] = [
            [kIOHIDVendorIDKey:0x0c45,kIOHIDProductIDKey:0x800a,kIOHIDPrimaryUsagePageKey:0xff68],
            [kIOHIDVendorIDKey:0x05ac,kIOHIDProductIDKey:0x024f,kIOHIDPrimaryUsagePageKey:0xff60]
        ]
        IOHIDManagerSetDeviceMatchingMultiple(manager, matches as CFArray)
        let candidates = (IOHIDManagerCopyDevices(manager) as? Set<IOHIDDevice>) ?? []
        let wired = candidates.filter { property($0,kIOHIDVendorIDKey) == 0x0c45 }
        let target: IOHIDDevice?
        if wired.count > 1 || (wired.isEmpty && candidates.count > 1) {
            DispatchQueue.main.async { self.error = "Birden fazla AMG65 bulundu. Yalnızca ayarlanacak cihazı bağlayın." }; return false
        }
        target = wired.first ?? candidates.first
        guard let target else {
            DispatchQueue.main.async { self.error = "AMG65 bulunamadı. USB kablosunu ve kablolu modu kontrol edin." }; return false
        }
        let identity = registryID(target)
        guard identity > 0 else {
            DispatchQueue.main.async { self.error = "USB fiziksel aygıt kimliği alınamadı." }
            return false
        }
        let sharedBlock:UInt64?
        do { sharedBlock = try SharedUSBFault.read() }
        catch {
            DispatchQueue.main.async { self.error = "USB güvenlik kaydı okunamadı: \(error.localizedDescription)" }
            return false
        }
        if sharedBlock == identity || (UserDefaults.standard.object(forKey:"blockedUSBRegistryID") as? NSNumber)?.uint64Value == identity {
            DispatchQueue.main.async { self.failedRegistryID = identity; self.error = "Önceki USB işlemi kesildi. Kabloyu çıkarıp yeniden takın." }
            return false
        }
        let result = IOHIDDeviceOpen(target, 0)
        guard result == kIOReturnSuccess else {
            DispatchQueue.main.async { self.error = String(format:"USB açılamadı: 0x%08x",result) }; return false
        }
        do { try SharedUSBFault.clearStale(afterOpening:identity) }
        catch {
            IOHIDDeviceClose(target,0)
            DispatchQueue.main.async { self.error = "USB güvenlik kaydı güncellenemedi: \(error.localizedDescription)" }
            return false
        }
        self.manager = manager; device = target
        selectedConnection = wired.isEmpty ? .dongle : .wired
        activeSender = Unmanaged.passUnretained(target).toOpaque()
        let context = Unmanaged.passUnretained(self).toOpaque()
        IOHIDDeviceRegisterInputReportCallback(target, buffer, 64, { context,result,sender,_,_,report,count in
            guard result == kIOReturnSuccess, count > 0, count <= 64, let context else { return }
            let selfRef = Unmanaged<KeyboardHID>.fromOpaque(context).takeUnretainedValue()
            guard sender == selfRef.activeSender else { return }
            selfRef.replyLock.lock()
            if selfRef.replies.count < 64 {
                selfRef.replies.append(Array(UnsafeBufferPointer(start:report,count:count)))
                selfRef.signal.signal()
            }
            selfRef.replyLock.unlock()
        }, context)
        IOHIDDeviceScheduleWithRunLoop(target, hidLoop, CFRunLoopMode.defaultMode.rawValue)
        faulted = false
        UserDefaults.standard.removeObject(forKey:"blockedUSBRegistryID")
        DispatchQueue.main.async { self.failedRegistryID = nil; self.connection = self.selectedConnection; self.error = nil }
        return true
    }

    func suspend(completion: @escaping () -> Void = {}) {
        io.async {
            let done = DispatchSemaphore(value: 0)
            self.onHID {
                if let device = self.device {
                    IOHIDDeviceUnscheduleFromRunLoop(device,self.hidLoop,CFRunLoopMode.defaultMode.rawValue)
                    IOHIDDeviceClose(device,0)
                }
                self.device = nil; self.activeSender = nil; self.manager = nil
                done.signal()
            }
            done.wait()
            if self.hardwareLock >= 0 { Darwin.close(self.hardwareLock); self.hardwareLock = -1 }
            self.selectedConnection = .none
            DispatchQueue.main.async { self.connection = .none; completion() }
        }
    }

    private func property(_ device: IOHIDDevice, _ key: String) -> Int {
        (IOHIDDeviceGetProperty(device,key as CFString) as? NSNumber)?.intValue ?? -1
    }

    private func registryID(_ device: IOHIDDevice) -> UInt64 {
        var value: UInt64 = 0
        IORegistryEntryGetRegistryEntryID(IOHIDDeviceGetService(device),&value)
        return value
    }

    private func drain() {
        replyLock.lock(); defer { replyLock.unlock() }
        replies.removeAll()
        for _ in 0..<64 { if signal.wait(timeout:.now()) != .success { break } }
    }

    private func nextReply(timeout: Double = 1) -> [UInt8]? {
        guard signal.wait(timeout:.now()+timeout) == .success else { return nil }
        replyLock.lock(); defer { replyLock.unlock() }
        return replies.isEmpty ? nil : replies.removeFirst()
    }

    private func exchange(_ packet: [UInt8], on selected: IOHIDDevice) -> [UInt8]? {
        guard !faulted, [32,64].contains(packet.count), self.device.map({CFEqual($0,selected)}) == true else { return nil }
        drain()
        var data = packet
        guard IOHIDDeviceSetReport(selected,kIOHIDReportTypeOutput,0,&data,data.count) == kIOReturnSuccess else { return nil }
        return nextReply()
    }

    static func validACK(_ reply: [UInt8], opcode: UInt8, checksum: UInt16? = nil) -> Bool {
        guard reply.count >= 4, reply[0] == 4, reply[1] == opcode, reply[2] == 0, reply[3] == 1 else { return false }
        if let checksum { return reply.count >= 6 && UInt16(reply[4]) | UInt16(reply[5]) << 8 == checksum }
        return true
    }

    private func finish(_ ok: Bool, _ lines: [String], _ completion: @escaping (TransactionResult)->Void) {
        let failedIdentity = !ok ? device.map(registryID) : nil
        var details = lines
        if !ok {
            faulted = true
            if let failedIdentity {
                do { try SharedUSBFault.write(failedIdentity) }
                catch { details.append("Kalıcı USB kilidi yazılamadı: \(error.localizedDescription). Kabloyu çıkarın.") }
                UserDefaults.standard.set(NSNumber(value:failedIdentity),forKey:"blockedUSBRegistryID")
            }
        }
        let finalDetails = details
        DispatchQueue.main.async {
            self.busy = false
            if !ok { self.failedRegistryID = failedIdentity; self.error = "USB işlemi durduruldu. Durumu kontrol edip cihazı yeniden bağlayın." }
            completion(TransactionResult(ok:ok,lines:finalDetails))
        }
    }

    /// Refuses before any packet left the Mac. The device is untouched, so it must not be marked faulted.
    private func reject(_ lines: [String], _ completion: @escaping (TransactionResult)->Void) {
        DispatchQueue.main.async { self.busy = false; completion(TransactionResult(ok:false,lines:lines)) }
    }

    func send(_ steps:[AMG65Protocol.Step], completion:@escaping(TransactionResult)->Void) {
        DispatchQueue.main.async { self.busy = true }
        io.async {
            guard !self.faulted, let selected = self.device, self.selectedConnection == .wired else {
                return self.reject(["Kablolu AMG65 bağlantısı gerekli."],completion)
            }
            let checksum = AMG65Protocol.checksum(steps)
            let hasData = steps.contains { $0.isData }
            var lines = [String]()
            for step in steps {
                let expected: UInt8 = step.isData || step.label == "time data" ? 0x41 : step.bytes[1]
                guard let reply = self.exchange(step.bytes,on:selected), Self.validACK(reply,opcode:expected) else {
                    return self.finish(false,lines+["Yanıt doğrulanamadı: \(step.label)"],completion)
                }
                if hasData && step.bytes == AMG65Protocol.end {
                    guard Self.validACK(reply,opcode:0x02,checksum:checksum) else {
                        return self.finish(false,lines+["Veri sağlama toplamı doğrulanamadı."],completion)
                    }
                }
                lines.append("Onaylandı: \(step.label)")
                Thread.sleep(forTimeInterval:0.010)
            }
            self.finish(true,lines,completion)
        }
    }

    func sendDongle(_ packets:[[UInt8]], label:String, completion:@escaping(TransactionResult)->Void) {
        DispatchQueue.main.async { self.busy = true }
        io.async {
            guard !self.faulted, let selected = self.device, self.selectedConnection == .dongle else {
                return self.reject(["Alıcı bağlantısı gerekli."],completion)
            }
            for packet in packets {
                guard packet.count == 32, let reply = self.exchange(packet,on:selected), reply.count >= 3,
                      reply.prefix(3) == packet.prefix(3) else {
                    return self.finish(false,["Alıcı yanıtı doğrulanamadı: \(label)"],completion)
                }
                Thread.sleep(forTimeInterval:0.010)
            }
            self.finish(true,["\(packets.count) alıcı paketi onaylandı."],completion)
        }
    }

    func uploadLCD(_ bytes:[UInt8], blocks:Int, slot:UInt8, progress:@escaping(Double)->Void,
                   completion:@escaping(TransactionResult)->Void) {
        uploadBulk(bytes,blocks:blocks,header:AMG65Protocol.packet([4,0x72,slot],[8:UInt8(blocks & 255),9:UInt8((blocks >> 8)&255)]),
                   headerLabel:"LCD",applyAfter:false,progress:progress,completion:completion)
    }

    func uploadBulk(_ bytes:[UInt8], blocks:Int, header:[UInt8], headerLabel:String, applyAfter:Bool,
                    progress:@escaping(Double)->Void, completion:@escaping(TransactionResult)->Void) {
        DispatchQueue.main.async { self.busy = true }
        io.async {
            guard !self.faulted, let selected = self.device, self.selectedConnection == .wired,
                  blocks > 0, blocks <= 4096, bytes.count == blocks * 4096, header.count == 64 else {
                return self.reject(["Geçersiz yükleme veya USB bağlantısı."],completion)
            }
            func command(_ packet:[UInt8]) -> Bool {
                guard let reply = self.exchange(packet,on:selected) else { return false }
                return Self.validACK(reply,opcode:packet[1])
            }
            // Match the bulk interface to the pinned HID's USB location.
            let bulk: LCDBulkChannel
            do { bulk = try LCDBulkChannel(locationID: UInt32(truncatingIfNeeded:self.property(selected,kIOHIDLocationIDKey))) }
            catch { return self.reject([String(describing:error)],completion) }
            do {
                guard command(AMG65Protocol.begin),command(header) else {
                    return self.finish(false,["Yükleme başlığı onaylanmadı."],completion)
                }
                for index in 0..<blocks {
                    self.drain()
                    try bulk.write(Array(bytes[index*4096..<(index+1)*4096]))
                    guard let reply = self.nextReply(timeout:3), Self.validACK(reply,opcode:0x41) else {
                        return self.finish(false,["Blok \(index+1) onaylanmadı; yükleme durdu."],completion)
                    }
                    if index == 0 { Thread.sleep(forTimeInterval:0.5) }
                    DispatchQueue.main.async { progress(Double(index+1)/Double(blocks)) }
                    Thread.sleep(forTimeInterval:0.010)
                }
                guard command(AMG65Protocol.end), !applyAfter || command(AMG65Protocol.apply) else {
                    return self.finish(false,["Yükleme bitişi onaylanmadı."],completion)
                }
                self.finish(true,["\(headerLabel): \(blocks) blok onaylandı."],completion)
            } catch { self.finish(false,[String(describing:error)],completion) }
        }
    }
}

extension Array { subscript(safe i:Int) -> Element? { indices.contains(i) ? self[i] : nil } }
