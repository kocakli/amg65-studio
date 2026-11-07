import Foundation
import AppKit
import ImageIO
import UniformTypeIdentifiers
import Darwin

/// Exercises production encoding and decode guards only. Never constructs KeyboardHID,
/// opens USB, requests microphone access, changes keymaps, or contacts the backend.
@main @MainActor struct NativeChecks {
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
    static func main() async throws {
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
        let orange=RGB(r:254,g:92,b:24)
        check(RGB.parse(hex:"#fe5C18")==orange && RGB.parse(hex:" FE5C18 ")==orange,"HEX accepts six mixed-case digits with optional hash")
        check(orange.hex=="#FE5C18" && RGB.parse(hex:orange.hex)==orange,"RGB hex round trip")
        check(RGB.parse(hex:"000000")==RGB.off && RGB.parse(hex:"FFFFFF")==RGB(r:255,g:255,b:255),"RGB range endpoints")
        check(["#fff","#12345678","0x123456","GG1234","１２３４５６","","#12345","1234567"].allSatisfy{RGB.parse(hex:$0)==nil},"partial, alpha, non-ASCII and malformed HEX rejected")
        let colorSuite="amg65-color-checks-\(UUID().uuidString)"
        let colorDefaults=UserDefaults(suiteName:colorSuite)!
        defer { colorDefaults.removePersistentDomain(forName:colorSuite) }
        let lighting=LightingModel(defaults:colorDefaults)
        lighting.settings.colorful=true; lighting.settings.mode=7;lighting.settings.brightness=2
        lighting.selectColor(orange)
        check(lighting.selectedColor==orange && !lighting.settings.colorful,"single color selection clears multicolor flag")
        check(lighting.settings.mode==7 && lighting.settings.brightness==2,"color selection preserves chosen effect and brightness")
        check(lighting.applied==nil && lighting.lastResult==nil && !lighting.applying && lighting.hasUnappliedChanges,"color edits remain unapplied without hardware work")
        check(LightingModel(defaults:colorDefaults).settings==lighting.settings,"color draft persists independently of apply")
        let lightingPacket=AMG65Protocol.lighting(lighting.settings).first{$0.isData}!.bytes
        check(Array(lightingPacket[1...3])==[254,92,24] && lightingPacket[8]==0,"chosen RGB encodes with single color flag")
        lighting.settings.colorful=true
        check(AMG65Protocol.lighting(lighting.settings).first{$0.isData}!.bytes[8]==1,"explicit multicolor setting retained in protocol")
        lighting.useStaticColor()
        check(lighting.settings.mode==1 && !lighting.settings.colorful && lighting.selectedColor==orange && lighting.applied==nil,"explicit static shortcut changes only draft mode and color flag")
        let brush=CustomLightModel(preview:[:],defaults:colorDefaults)
        brush.erasing=true;brush.selectBrush(orange)
        check(brush.brush==orange && !brush.erasing && brush.colors.isEmpty && brush.appliedColors==nil,"brush selection exits eraser without painting or applying")
        let firstKey=KeyboardLayout.litKeys[0]
        brush.paint(firstKey.slot)
        check(brush.colors[firstKey.slot]==orange && brush.appliedColors==nil,"inline brush paints a draft key only")
        brush.fillAll()
        check(brush.colors.count==KeyboardLayout.litKeys.count && brush.colors.values.allSatisfy{$0==orange},"fill all uses selected inline brush")
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
        let key="customLightBrightness"
        colorDefaults.set(-100,forKey:key); check(CustomLightModel(preview:[:],defaults:colorDefaults).brightness==1,"negative stored brightness clamped")
        colorDefaults.set(Int.max,forKey:key); check(CustomLightModel(preview:[:],defaults:colorDefaults).brightness==5,"overflowing stored brightness clamped")
        let catalogs=LocalizationCatalog(directory:URL(fileURLWithPath:CommandLine.arguments[1],isDirectory:true))
        let catalogKeys=Set(catalogs.tables["tr"]!.keys)
        check(catalogKeys.count>=219 && LocalizationCatalog.codes.allSatisfy { Set(catalogs.tables[$0]!.keys)==catalogKeys },"five complete local catalogs")
        check(catalogs.text("Aydınlatma",language:"en")=="Lighting","English native label")
        check(catalogs.text("Aydınlatma",language:"es")=="Iluminación","Spanish native label")
        check(catalogs.text("Aydınlatma",language:"zh-Hans")=="灯光","Simplified Chinese native label")
        check(catalogs.text("Aydınlatma",language:"ja")=="ライティング","Japanese native label")
        check(catalogs.text("Aydınlatma",language:"tr")=="Aydınlatma","Turkish retained")
        check(catalogs.text("Onaylandı: colour data 2/8",language:"en")=="Confirmed: color data 2/8","existing nested diagnostic translated at display")
        check(catalogs.text("Blok 12 onaylanmadı; yükleme durdu.",language:"es")=="No se confirmó el bloque 12; se detuvo la carga.","dynamic diagnostic preserves block number")
        let filename="{1}-$1-\\.gif"
        check(catalogs.format("{0} · {1} kare",arguments:[filename,"2"],language:"en")==filename+" · 2 frames","format does not reinterpret user placeholders or escapes")
        check(catalogs.text(filename+" · 2 kare",language:"en")==filename+" · 2 frames","diagnostic substitution does not reinterpret captured placeholders")
        check(StudioLanguage.resolve(["fr-FR","ja-JP"])=="ja","System selects first supported language")
        check(StudioLanguage.resolve(["zh-TW"])=="zh-Hans","Chinese variants select supported Simplified Chinese")
        check(StudioLanguage.resolve(["de-DE"])=="en","unsupported System language falls back to English")
        let suite="AMG65LocalizationChecks-\(UUID().uuidString)"
        let isolated=UserDefaults(suiteName:suite)!
        defer { isolated.removePersistentDomain(forName:suite) }
        let language=StudioLanguage(defaults:isolated,catalog:catalogs)
        check(language.selection=="tr","upgrade preserves Turkish default")
        language.selection="ja"
        check(StudioLanguage(defaults:isolated,catalog:catalogs).selection=="ja","language preference persists")
        check(language.dashboardURL.fragment=="native&lang=ja","native language passes through dashboard fragment")
        language.selection="invalid"
        check(language.selection=="tr","invalid stored selection is bounded")
        let quotaJSON = #"{"providers":[{"id":"claude","remaining_percent":80,"remaining_label":"5h","stale":false,"updated_at":"2026-11-07T08:00:00Z","windows":[{"id":"primary","label":"5h","remaining_percent":80,"stale":false,"updated_at":"2026-11-07T08:00:00Z","resets_at":"2026-11-07T13:00:00Z"},{"id":"secondary","label":"7d","remaining_percent":10,"stale":false,"updated_at":"2026-11-07T08:00:00Z","resets_at":null}]}],"hardware_owner":"dashboard","device":{"connected":true}}"#
        let usage=try JSONDecoder().decode(MenuUsageSnapshot.self,from:Data(quotaJSON.utf8))
        let current=MenuUsageSnapshot.date("2026-11-07T08:01:00.000Z")!
        check(usage.orderedProviders.map(\.id)==["claude","cursor","codex"],"menu uses fixed three-provider order")
        check(usage.orderedProviders[1].remaining==nil && usage.orderedProviders[2].remaining==nil,"missing menu provider stays unknown, not zero")
        check(usage.providers[0].remaining==80 && usage.providers[0].visibleWindows[1].remaining==10,"menu keeps independent quotas, never aggregates")
        check(!usage.providers[0].isStale(at:current,offline:false),"fresh menu quota remains fresh")
        check(usage.providers[0].isStale(at:current,offline:true),"unreachable bridge marks retained quota stale")
        check(usage.providers[0].isStale(at:current.addingTimeInterval(901),offline:false),"menu ages quota from measurement time")
        check(usage.providers[0].visibleWindows[0].isStale(at:current.addingTimeInterval(18000),offline:false),"expired menu reset remains stale")
        check(MenuUsageSnapshot.validPercent(0)==0 && MenuUsageSnapshot.validPercent(100)==100,"menu preserves measured zero and full allowance")
        check(MenuUsageSnapshot.validPercent(nil)==nil && MenuUsageSnapshot.validPercent(-1)==nil && MenuUsageSnapshot.validPercent(101)==nil,"invalid menu percentage stays unknown")
        check(MenuUsageSnapshot.validPercent(.nan)==nil && MenuUsageSnapshot.validPercent(.infinity)==nil,"nonfinite menu percentage stays unknown")
        check(MenuUsageSnapshot.old(nil,now:current) && MenuUsageSnapshot.old("2026-11-08T00:00:00Z",now:current),"unknown and future measurements marked stale")
        var booleanRejected=false
        do { _ = try JSONDecoder().decode(MenuUsageSnapshot.self,from:Data(quotaJSON.replacingOccurrences(of:"\"remaining_percent\":80",with:"\"remaining_percent\":true").utf8)) }
        catch { booleanRejected=true }
        check(booleanRejected,"boolean menu quota is rejected")
        check(usage.providers[0].selectedWindow?.id=="primary","overview reset is tied to the selected quota window")
        let resetExpired=MenuUsageSnapshot.date("2026-11-07T13:00:01Z")!
        let updatedUsage=try JSONDecoder().decode(MenuUsageSnapshot.self,from:Data(quotaJSON.replacingOccurrences(of:"2026-11-07T08:00:00Z",with:"2026-11-07T12:59:59Z").utf8))
        check(updatedUsage.providers[0].isStale(at:resetExpired,offline:false),"headline cannot show fresh after selected reset expires")
        check(MenuUsageSnapshot.windowLabel("720h",catalog:catalogs,language:"ja")=="720 時間","arbitrary hour windows localize")
        check(MenuUsageSnapshot.windowLabel("60m",catalog:catalogs,language:"zh-Hans")=="60 分钟","minute windows localize")
        check(MenuUsageSnapshot.windowLabel("1.5h",catalog:catalogs,language:"es")=="1,5 h","fractional window labels use locale decimal separator")
        check(MenuUsageSnapshot.windowLabel("7d",catalog:catalogs,language:"tr")=="7 gün","day window labels localize")
        check(MenuUsageSnapshot.windowLabel("Custom plan",catalog:catalogs,language:"ja")=="Custom plan","unknown named window label remains unchanged")
        check(MenuUsageSnapshot.windowLabel("Fable only",catalog:catalogs,language:"tr")=="Yalnızca Fable","dynamic model-only window localizes")
        check(MenuUsageSnapshot.windowLabel("Team pool",catalog:catalogs,language:"ja")=="チーム共有枠","team pool is not mislabeled personal usage")
        var sentSettings:[String:Any]=[:]
        var settingsRequests=0
        let display=MenuDisplayModel(send:{ path,data in
            check(path=="api/settings","display uses settings endpoint for unchanged enable state")
            settingsRequests += 1
            sentSettings=(try JSONSerialization.jsonObject(with:data)) as! [String:Any]
        })
        func displaySnapshot(_ value:MenuDisplaySettings)->MenuUsageSnapshot {
            let settings=(try! JSONSerialization.jsonObject(with:JSONEncoder().encode(value))) as! [String:Any]
            let data=try! JSONSerialization.data(withJSONObject:["providers":[],"settings":settings,"running":true])
            return try! JSONDecoder().decode(MenuUsageSnapshot.self,from:data)
        }
        let initialSettings=MenuDisplaySettings()
        let legacySettings=try JSONDecoder().decode(MenuDisplaySettings.self,from:Data(##"{"display_mode":"text","brightness":0.4,"text":"DRAFT","text_color":"#ffffff","activity_enabled":true}"##.utf8))
        check(legacySettings.textEffect=="none" && legacySettings.text=="DRAFT" && legacySettings.valid,"legacy bridge settings default missing text effect to none")
        for effect in ["none","scan","breathe","matrix"] {
            var settings=initialSettings;settings.textEffect=effect
            let encoded=try JSONEncoder().encode(settings)
            let decoded=try JSONDecoder().decode(MenuDisplaySettings.self,from:encoded)
            check(decoded==settings && decoded.valid,"supported text effect round trip: \(effect)")
        }
        display.receive(displaySnapshot(initialSettings))
        display.draft.text="hello";display.draft.textColor="#ABCDEF";display.draft.textEffect="matrix"
        display.receive(displaySnapshot(initialSettings))
        check(display.draft.text=="hello" && display.draft.textEffect=="matrix" && display.dirty && settingsRequests==0,"effect choice and polling preserve text draft without sending")
        await display.save()
        check(sentSettings["text"] as? String=="HELLO" && sentSettings["text_color"] as? String=="#abcdef","display request matches backend canonicalization")
        check(sentSettings["text_effect"] as? String=="matrix","Apply submits selected text effect")
        var ack=initialSettings;ack.text="HELLO";ack.textColor="#abcdef"
        display.receive(displaySnapshot(ack))
        check(display.dirty && display.draft.textEffect=="matrix","older effect snapshot cannot acknowledge a pending change")
        display.draft.text="new draft";display.draft.textEffect="breathe"
        ack.textEffect="matrix"
        display.receive(displaySnapshot(ack))
        check(display.draft.text=="new draft" && display.draft.textEffect=="breathe" && display.dirty,"late settings acknowledgement preserves newer text and effect edit")
        display.discard()
        check(display.draft==ack && !display.dirty,"discard restores acknowledged canonical settings")
        display.draft.text="last"
        await display.save()
        ack.text="LAST";display.receive(displaySnapshot(ack))
        check(display.draft.text=="LAST" && !display.dirty,"unchanged sent draft canonicalizes on acknowledgement")
        var invalid=initialSettings;invalid.text="非ASCII"
        check(!invalid.valid,"unsupported LED text rejected before submission")
        invalid=initialSettings;invalid.brightness=Double.nan
        check(!invalid.valid,"nonfinite display brightness rejected")
        invalid=initialSettings;invalid.textEffect="rain"
        check(!invalid.valid,"unknown text effect rejected")
        let beforeInvalid=settingsRequests
        display.draft=invalid;await display.save()
        check(settingsRequests==beforeInvalid,"invalid effect never submits settings")
        check(MenuAccountsModel.authorizationURL("https://auth.openai.com/codex/device",provider:"codex") != nil,"Codex device sign-in URL accepted")
        check(MenuAccountsModel.authorizationURL("https://claude.ai/oauth/authorize?state=test",provider:"claude") != nil,"Claude provider authorization URL accepted")
        check(MenuAccountsModel.authorizationURL("https://claude.com/cai/oauth/authorize?code_challenge_method=S256",provider:"claude") != nil,"modern Claude direct-auth URL accepted")
        check(MenuAccountsModel.authorizationURL("https://claude.com/cai/oauth/authorize/redirect",provider:"claude")==nil,"modern Claude auth path prefix is not enough")
        check(MenuAccountsModel.authorizationURL("https://claude.com/cai/oauth/authorize.evil",provider:"claude")==nil,"modern Claude auth path suffix rejected")
        check(MenuAccountsModel.authorizationURL("https://auth.openai.com/cai/oauth/authorize",provider:"codex")==nil,"Claude-only auth path is not allowed for Codex")
        for invalidURL in ["http://auth.openai.com/codex/device","https://auth.openai.com.evil.test/codex/device","https://user:pass@auth.openai.com/codex/device","https://auth.openai.com/not-login","file:///tmp/login"] {
            check(MenuAccountsModel.authorizationURL(invalidURL,provider:"codex")==nil,"untrusted or unrelated sign-in URL rejected")
        }
        let account=try JSONDecoder().decode(MenuAccount.self,from:Data(#"{"provider":"claude","phase":"awaiting_code","expires_at":"2026-11-07T10:00:00Z","input_required":true}"#.utf8))
        check(account.pending && account.inputRequired==true && account.expiresAt != nil,"account contract decodes ISO timestamp and input phase")
        func accountFixture(phase:String="idle",percent:Double?=98,stale:Bool=false,error:String?=nil,
                            measured:Date?=current,provider:String="claude")->MenuAccount {
            var usage:[String:Any]=["stale":stale]
            if let percent { usage["remaining_percent"]=percent }
            if let error { usage["error"]=error }
            if let measured { usage["updated_at"]=ISO8601DateFormatter().string(from:measured) }
            let data=try! JSONSerialization.data(withJSONObject:["provider":provider,"phase":phase,"usage":usage])
            return try! JSONDecoder().decode(MenuAccount.self,from:data)
        }
        let connectedAccounts=MenuAccountsModel()
        let freshAccount=accountFixture()
        connectedAccounts.receive([freshAccount],at:current)
        check(connectedAccounts.connection(freshAccount,at:current) == .connected,"idle account with fresh API usage stays connected after app restart")
        let finishedAccount=accountFixture(phase:"complete")
        connectedAccounts.receive([finishedAccount],at:current)
        check(connectedAccounts.connection(finishedAccount,at:current) == .connected,"completed login with fresh usage is connected, not a pending refresh")
        let pendingAccount=accountFixture(phase:"awaiting_browser")
        check(pendingAccount.connection(at:current) == .pending,"active account switch remains pending despite old fresh usage")
        for failure in ["auth_required","relogin_required","invalid_credentials","auth_missing","auth_expired","unauthorized"] {
            let rejected=accountFixture(phase:"complete",error:failure)
            connectedAccounts.receive([rejected],at:current)
            check(connectedAccounts.connection(rejected,at:current) == .requiresSignIn,"explicit auth failure overrides completed login and a cached percentage")
        }
        let rejectedThenNetwork=accountFixture(phase:"complete",stale:true,error:"network_error")
        connectedAccounts.receive([rejectedThenNetwork],at:current)
        check(connectedAccounts.connection(rejectedThenNetwork,at:current) == .unknown,"old completed phase cannot resurrect rejected authentication after a network failure")
        connectedAccounts.receive([freshAccount],at:current)
        for failure in ["network_error","rate_limited","timeout"] {
            let temporary=accountFixture(stale:true,error:failure,measured:current.addingTimeInterval(-1800))
            connectedAccounts.receive([temporary],at:current)
            check(connectedAccounts.connection(temporary,at:current) == .connected,"transient error preserves known connection without forcing sign-in")
            let restarted=MenuAccountsModel();restarted.receive([temporary],at:current)
            check(restarted.connection(temporary,at:current) == .connected,"retained same-account measurement survives restart during a transient error")
        }
        let neverVerified=accountFixture(percent:nil,stale:true,error:"network_error",measured:nil)
        let unknownAccounts=MenuAccountsModel();unknownAccounts.receive([neverVerified],at:current)
        check(unknownAccounts.connection(neverVerified,at:current) == .unknown,"network error without authentication evidence is unknown, not a forced login")
        for failure in ["keychain_locked","credentials_unreadable","access_denied"] {
            let inaccessible=accountFixture(phase:"complete",error:failure)
            check(inaccessible.connection(at:current) == .unknown,"unreadable or denied credentials do not display a connected badge")
        }
        let noQuota=accountFixture(phase:"complete",percent:nil,stale:true,error:"no_usage",measured:nil)
        check(noQuota.connection(at:current) == .connected,"successful sign-in and unavailable quota are separate states")
        let cancelledSwitch=accountFixture(phase:"cancelled")
        check(cancelledSwitch.connection(at:current) == .connected,"cancelled switch preserves existing freshly measured account")
        let failedSwitch=accountFixture(phase:"error")
        check(failedSwitch.connection(at:current) == .connected,"failed switch does not erase a still valid existing account")
        let futureAccount=accountFixture(measured:current.addingTimeInterval(3600))
        check(futureAccount.connection(at:current) == .unknown,"future-dated usage cannot establish a connection")
        let zeroAccount=accountFixture(percent:0)
        check(zeroAccount.connection(at:current) == .connected,"exhausted quota is still an authenticated connection")
        let notifications=NotificationCenter(),menuObject=NSObject()
        var orderedIn=true,visibilityChanges=[Bool]()
        let visibility=MenuWindowVisibilityObservation(object:menuObject,center:notifications,startTimer:false,
            isVisible:{orderedIn},onChange:{visibilityChanges.append($0)})
        visibility.sample()
        check(visibilityChanges==[true],"ordered-in menu acquires its visible demand")
        notifications.post(name:NSWindow.didResignKeyNotification,object:menuObject)
        try await Task.sleep(nanoseconds:5_000_000)
        check(visibilityChanges==[true],"focus loss to color picker does not release a visible menu")
        notifications.post(name:NSWindow.didChangeOcclusionStateNotification,object:menuObject)
        try await Task.sleep(nanoseconds:5_000_000)
        check(visibilityChanges==[true],"occluded but ordered-in menu stays visible for ownership")
        orderedIn=false
        visibility.sample()
        check(visibilityChanges==[true,false],"fallback visibility sample catches orderOut without a notification")
        orderedIn=true
        notifications.post(name:NSWindow.didBecomeKeyNotification,object:menuObject)
        try await Task.sleep(nanoseconds:5_000_000)
        check(visibilityChanges==[true,false,true],"reopening retained menu reports visible again")
        notifications.post(name:NSWindow.willCloseNotification,object:menuObject)
        try await Task.sleep(nanoseconds:5_000_000)
        check(visibilityChanges.last==false,"willClose releases demand before final orderOut")
        notifications.post(name:NSWindow.didBecomeKeyNotification,object:menuObject)
        try await Task.sleep(nanoseconds:5_000_000)
        check(visibilityChanges.last==true,"reused closed window can become visible again")
        visibility.stop()
        let stoppedCount=visibilityChanges.count
        notifications.post(name:NSWindow.didBecomeKeyNotification,object:menuObject)
        visibility.sample()
        try await Task.sleep(nanoseconds:5_000_000)
        check(visibilityChanges.last==false && visibilityChanges.count==stoppedCount,"detaching observer releases once and removes stale callbacks")
        print("PASS: \(count) native offline checks; no hardware accessed.")
    }
}
