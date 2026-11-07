import Foundation
import AppKit
import ImageIO
import UniformTypeIdentifiers
import Darwin

/// Exercises production encoding and decode guards only. Never constructs KeyboardHID,
/// opens USB, requests microphone access, changes keymaps, or contacts the backend.
@main struct NativeChecks {
    static var count = 0
    static func check(_ value:@autoclosure()->Bool,_ name:String) {
        guard value() else { fatalError("FAILED: \(name)") }
        count += 1
    }
    static func image(_ width:Int,_ height:Int)->CGImage {
        let context=CGContext(data:nil,width:width,height:height,bitsPerComponent:8,bytesPerRow:width*4,
                              space:CGColorSpaceCreateDeviceRGB(),bitmapInfo:CGImageAlphaInfo.noneSkipLast.rawValue)!
        context.setFillColor(CGColor(red:1,green:0,blue:0,alpha:1)); context.fill(CGRect(x:0,y:0,width:width,height:height))
        return context.makeImage()!
    }
    static func write(_ image:CGImage,to url:URL,count:Int=1,type:UTType = .png) {
        let destination=CGImageDestinationCreateWithURL(url as CFURL,type.identifier as CFString,count,nil)!
        for _ in 0..<count { CGImageDestinationAddImage(destination,image,nil) }
        check(CGImageDestinationFinalize(destination),"fixture encoding")
    }
    static func main() throws {
        check(KeyboardHID.validACK([4,0x18,0,1],opcode:0x18),"valid begin acknowledgement")
        check(!KeyboardHID.validACK([4,0x41,0,1],opcode:0x18),"wrong opcode rejected")
        check(!KeyboardHID.validACK([4,0x18,0],opcode:0x18),"short acknowledgement rejected")
        check(!KeyboardHID.validACK([4,0x02,0,1],opcode:0x02,checksum:0x1234),"missing checksum rejected")
        check(!KeyboardHID.validACK([4,0x02,0,1,0x35,0x12],opcode:0x02,checksum:0x1234),"wrong checksum rejected")
        check(KeyboardHID.validACK([4,0x02,0,1,0x34,0x12],opcode:0x02,checksum:0x1234),"valid checksum accepted")
        check(!KeyboardHID.validACK([5,0x18,0,1],opcode:0x18),"wrong report prefix rejected")
        check(!KeyboardHID.validACK([4,0x18,1,1],opcode:0x18),"invalid acknowledgement flags rejected")
        var calendar=Calendar(identifier:.gregorian); calendar.timeZone = .current
        let date=calendar.date(from:DateComponents(year:2026,month:11,day:7,hour:12,minute:34,second:56))!
        let clock=AMG65Protocol.timeSync(date,view:1)
        check(clock.count==4 && clock.allSatisfy{$0.bytes.count==64},"RTC packet sequence")
        check(Array(clock[2].bytes.prefix(11))==[0,1,0x5A,26,11,7,12,34,56,0,6],"Gregorian RTC and Saturday mapping")
        check(!clock.contains{$0.isData},"RTC does not request unsupported checksum")
        check(AMG65Protocol.packet([UInt8](repeating:1,count:100),[-1:7,64:7]).count==64,"packet input bounds")
        let map=AMG65Protocol.keymap([-1:[1],127:[2],49:KeyAction.key(modifiers:8,code:4).slot])
        let table=map.filter{$0.isData}.flatMap{$0.bytes}
        check(table.count==512 && table[510]==0xAA && table[511]==0x55,"keymap table trailer")
        check(Array(table[196..<200])==[2,8,4,0],"command-A encoding in A slot")
        let keys=KeyboardLayout.litKeys
        check(Set(keys.map{$0.slot}).count==keys.count,"unique physical key slots")
        check(keys.filter{$0.name=="Fn"}.count==1 && keys.filter{$0.name=="Fn"}.allSatisfy{!$0.remappable},"Fn key preserved")
        check(keys.allSatisfy{(0..<127).contains($0.slot)},"physical slot bounds")
        check(Set(StripFormat.position)==Set(0..<315),"LED mapping is complete permutation")
        let strip=StripAnimation.scrollingText(String(repeating:"ß",count:10000),color:RGB(r:255,g:0,b:0))
        check(strip.frames.count<=255 && strip.frames.allSatisfy{$0.count==315},"Unicode expansion and long text bounded")
        let bytes=strip.buffer(delay:10,brightness:1,target:.boot)
        check(bytes.bytes.count==bytes.blocks*4096 && bytes.bytes[0]==200 && bytes.bytes[1]==0,"boot upload frame budget and block alignment")
        let directory=FileManager.default.temporaryDirectory.appendingPathComponent("amg65-native-checks-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at:directory,withIntermediateDirectories:true)
        defer { try? FileManager.default.removeItem(at:directory) }
        let valid=directory.appendingPathComponent("valid.png")
        write(image(64,64),to:valid)
        let lcd=LCDAnimation.load(valid,fill:true)
        check(lcd?.frames.first?.width==240 && lcd?.frames.first?.height==135,"LCD thumbnail decode and target dimensions")
        let encoded=lcd!.buffer()
        check(encoded.bytes.count==encoded.blocks*4096 && encoded.bytes[0]==1,"LCD block alignment and header")
        check(StripAnimation.load(valid)?.frames.first?.count==315,"LED bounded image decode")
        let wide=directory.appendingPathComponent("wide.png")
        write(image(8193,1),to:wide)
        check(MediaBudget.source(wide,maxFrames:130)==nil,"oversize pixel dimension rejected")
        let animation=directory.appendingPathComponent("many.gif")
        write(image(1,1),to:animation,count:131,type:.gif)
        check(MediaBudget.source(animation,maxFrames:130)==nil,"GIF frame count rejected before decoding")
        let oversized=directory.appendingPathComponent("oversized.png")
        check(FileManager.default.createFile(atPath:oversized.path,contents:nil),"sparse fixture created")
        let file=try FileHandle(forWritingTo:oversized); try file.truncate(atOffset:UInt64(MediaBudget.maxBytes+1)); try file.close()
        check(MediaBudget.source(oversized,maxFrames:130)==nil,"oversized file rejected")
        check(MediaBudget.source(URL(string:"https://example.invalid/image.png")!,maxFrames:130)==nil,"remote image URL rejected")
        let shared=directory.appendingPathComponent("private/state",isDirectory:true)
        try SharedUSBFault.write(UInt64.max-1,at:shared)
        let marker=shared.appendingPathComponent("usb-blocked.json")
        let first=try SharedUSBFault.read(at:shared)
        check(first == UInt64.max-1,"shared marker preserves full UInt64 identity")
        var markerStat=stat(),directoryStat=stat()
        check(lstat(marker.path,&markerStat)==0 && (markerStat.st_mode & 0o777)==0o600 && markerStat.st_uid==getuid(),"marker is owner-only")
        check(lstat(shared.path,&directoryStat)==0 && (directoryStat.st_mode & 0o777)==0o700,"state directory is owner-only")
        try SharedUSBFault.write(123,at:shared)
        let second=try SharedUSBFault.read(at:shared)
        check(second==123,"atomic fault replacement")
        let children=try FileManager.default.contentsOfDirectory(atPath:shared.path)
        check(children == ["usb-blocked.json"],"atomic write leaves no temporary records")
        var rejected=false
        do { try SharedUSBFault.clearStale(afterOpening:123,at:shared) } catch { rejected=true }
        check(rejected && FileManager.default.fileExists(atPath:marker.path),"same attachment cannot clear fault")
        try SharedUSBFault.clearStale(afterOpening:456,at:shared)
        let cleared=try SharedUSBFault.read(at:shared)
        check(cleared==nil,"new attachment clears stale fault")
        try Data("{\"registry_id\":-1}".utf8).write(to:marker)
        rejected=false
        do { _ = try SharedUSBFault.read(at:shared) } catch { rejected=true }
        check(rejected,"malformed shared identity fails closed")
        try FileManager.default.removeItem(at:marker)
        try FileManager.default.createSymbolicLink(at:marker,withDestinationURL:valid)
        rejected=false
        do { _ = try SharedUSBFault.read(at:shared) } catch { rejected=true }
        check(rejected,"shared marker symlink fails closed")
        let defaults=UserDefaults.standard,key="customLightBrightness",old=defaults.object(forKey:key)
        defer { if let old {defaults.set(old,forKey:key)} else {defaults.removeObject(forKey:key)} }
        defaults.set(-100,forKey:key); check(CustomLightModel(preview:[:]).brightness==1,"negative stored brightness clamped")
        defaults.set(Int.max,forKey:key); check(CustomLightModel(preview:[:]).brightness==5,"overflowing stored brightness clamped")
        print("PASS: \(count) native offline checks; no hardware accessed.")
    }
}
