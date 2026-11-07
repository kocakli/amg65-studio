import Foundation
import Darwin

/// A fault survives either writer crashing. Both the bridge and native app use this
/// same attachment identity; a different registry ID requires physical reattachment.
enum SharedUSBFault {
    private struct Marker:Codable { let registry_id:UInt64 }
    static var directory:URL {
        FileManager.default.urls(for:.applicationSupportDirectory,in:.userDomainMask)[0]
            .appendingPathComponent("AMG65 Studio",isDirectory:true).appendingPathComponent("state",isDirectory:true)
    }

    private static func failure(_ message:String)->Error {
        NSError(domain:"AMG65.USBFault",code:1,userInfo:[NSLocalizedDescriptionKey:message])
    }

    private static func secureDirectory(_ url:URL) throws {
        var status=stat()
        if lstat(url.path,&status) != 0 {
            guard errno == ENOENT, mkdir(url.path,0o700) == 0, lstat(url.path,&status) == 0 else {
                throw failure("USB durum klasörü oluşturulamadı.")
            }
        }
        guard (status.st_mode & S_IFMT) == S_IFDIR, status.st_uid == getuid(), chmod(url.path,0o700) == 0 else {
            throw failure("USB durum klasörü güvenli değil.")
        }
    }

    static func prepare(at directory:URL = directory) throws {
        try secureDirectory(directory.deletingLastPathComponent())
        try secureDirectory(directory)
    }

    static func read(at directory:URL = directory) throws -> UInt64? {
        try prepare(at:directory)
        let file=directory.appendingPathComponent("usb-blocked.json")
        var status=stat()
        if lstat(file.path,&status) != 0 {
            if errno == ENOENT { return nil }
            throw failure("USB hata kaydı okunamadı.")
        }
        guard (status.st_mode & S_IFMT) == S_IFREG, status.st_uid == getuid(),
              status.st_size > 0, status.st_size <= 4096, chmod(file.path,0o600) == 0 else { throw failure("USB hata kaydı geçersiz.") }
        let marker=try JSONDecoder().decode(Marker.self,from:Data(contentsOf:file))
        guard marker.registry_id > 0 else { throw failure("USB aygıt kimliği geçersiz.") }
        return marker.registry_id
    }

    static func write(_ identity:UInt64, at directory:URL = directory) throws {
        guard identity > 0 else { throw failure("USB aygıt kimliği alınamadı.") }
        try prepare(at:directory)
        let payload=try JSONEncoder().encode(Marker(registry_id:identity))
        let temporary=directory.appendingPathComponent(".usb-blocked-\(UUID().uuidString).tmp")
        let target=directory.appendingPathComponent("usb-blocked.json")
        let fd=Darwin.open(temporary.path,O_WRONLY|O_CREAT|O_EXCL|O_NOFOLLOW,0o600)
        guard fd >= 0 else { throw failure("USB hata kaydı yazılamadı.") }
        defer { Darwin.close(fd); unlink(temporary.path) }
        try payload.withUnsafeBytes { raw in
            guard let bytes=raw.baseAddress else { throw failure("USB hata kaydı boş.") }
            var written=0
            while written < raw.count {
                let amount=Darwin.write(fd,bytes.advanced(by:written),raw.count-written)
                if amount < 0 && errno == EINTR { continue }
                guard amount > 0 else { throw failure("USB hata kaydı tamamlanamadı.") }
                written += amount
            }
        }
        guard fsync(fd) == 0, rename(temporary.path,target.path) == 0 else {
            throw failure("USB hata kaydı atomik olarak kaydedilemedi.")
        }
        let directoryFD=Darwin.open(directory.path,O_RDONLY|O_DIRECTORY|O_NOFOLLOW)
        if directoryFD >= 0 { _ = fsync(directoryFD); Darwin.close(directoryFD) }
    }

    static func clearStale(afterOpening identity:UInt64, at directory:URL = directory) throws {
        guard let previous=try read(at:directory) else { return }
        guard previous != identity else { throw failure("USB hata kilidi aynı bağlantıda kaldı.") }
        guard unlink(directory.appendingPathComponent("usb-blocked.json").path) == 0 || errno == ENOENT else {
            throw failure("Eski USB hata kaydı kaldırılamadı.")
        }
    }
}
