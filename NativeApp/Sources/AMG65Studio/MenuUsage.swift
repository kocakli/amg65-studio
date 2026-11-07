import Foundation
import Combine

/// Only the normalized, identity-free local bridge response is consumed here.
struct MenuUsageWindow:Decodable,Identifiable {
    let id:String
    let label:String
    let remainingPercent:Double?
    let resetsAt:String?
    let updatedAt:String?
    let stale:Bool?
    enum CodingKeys:String,CodingKey {
        case id,label,stale
        case remainingPercent="remaining_percent",resetsAt="resets_at",updatedAt="updated_at"
    }
    var remaining:Double? { MenuUsageSnapshot.validPercent(remainingPercent) }
    var resetDate:Date? { MenuUsageSnapshot.date(resetsAt) }
    func isStale(at now:Date,offline:Bool)->Bool {
        offline || stale != false || MenuUsageSnapshot.old(updatedAt,now:now) || (resetDate.map{$0 <= now} ?? false)
    }
}

struct MenuUsageProvider:Decodable,Identifiable {
    let id:String
    let remainingPercent:Double?
    let remainingLabel:String?
    let windows:[MenuUsageWindow]?
    let updatedAt:String?
    let stale:Bool?
    enum CodingKeys:String,CodingKey {
        case id,windows,stale
        case remainingPercent="remaining_percent",remainingLabel="remaining_label",updatedAt="updated_at"
    }
    var name:String { ["claude":"Claude","cursor":"Cursor","codex":"Codex"][id] ?? id }
    var remaining:Double? { MenuUsageSnapshot.validPercent(remainingPercent) }
    var visibleWindows:[MenuUsageWindow] { Array((windows ?? []).prefix(4)) }
    var selectedWindow:MenuUsageWindow? {
        guard let remaining,let remainingLabel else { return nil }
        let matches=(windows ?? []).filter { $0.label == remainingLabel && $0.remaining == remaining }
        return matches.first { $0.stale == stale } ?? matches.first
    }
    func isStale(at now:Date,offline:Bool)->Bool {
        offline || stale != false || MenuUsageSnapshot.old(updatedAt,now:now) || (selectedWindow?.resetDate.map { $0 <= now } ?? false)
    }
    static func unknown(_ id:String)->MenuUsageProvider {
        MenuUsageProvider(id:id,remainingPercent:nil,remainingLabel:nil,windows:[],updatedAt:nil,stale:true)
    }
}

enum MenuBridgeState:Equatable {
    case offline,faultReconnect,nativeControl,displayDisabled,streaming,ready,noDevice,unknown
    var titleKey:String {
        switch self {
        case .offline:"Yerel köprü çevrimdışı"
        case .faultReconnect:"LED aktarımı durdu"
        case .nativeControl:"USB denetimi yerel sürücüde"
        case .displayDisabled:"Canlı LED kapalı"
        case .streaming:"LED aktarımı etkin"
        case .ready:"USB bağlı"
        case .noDevice:"USB bağlantısı bekleniyor"
        case .unknown:"USB durumu bilinmiyor"
        }
    }
}

struct MenuUsageSnapshot:Decodable {
    // Stable codes only. Arbitrary backend diagnostic messages are not displayed.
    struct Device:Decodable { let connected:Bool?; let code:String? }
    let providers:[MenuUsageProvider]
    let hardwareOwner:String?
    let device:Device?
    let settings:MenuDisplaySettings?
    let running:Bool?
    enum CodingKeys:String,CodingKey { case providers,device,settings,running; case hardwareOwner="hardware_owner" }
    var orderedProviders:[MenuUsageProvider] {
        ["claude","cursor","codex"].map { id in providers.first{$0.id == id} ?? .unknown(id) }
    }
    func bridgeState(offline:Bool)->MenuBridgeState {
        if offline { return .offline }
        if hardwareOwner=="native" || device?.code=="native_control" { return .nativeControl }
        if device?.code=="fault_reconnect" { return .faultReconnect }
        if running==false { return .displayDisabled }
        if let code=device?.code,!["ready","streaming","waiting","no_device"].contains(code) { return .unknown }
        if device?.code=="waiting" || device?.code=="no_device" || device?.connected==false { return .noDevice }
        guard device?.connected==true else { return .unknown }
        switch device?.code {
        case nil,"ready": return .ready
        case "streaming": return .streaming
        default: return .unknown
        }
    }
    var acceptsDeviceCommands:Bool {
        hardwareOwner=="dashboard" && device?.connected==true
            && (device?.code==nil || device?.code=="ready" || device?.code=="streaming")
    }
    static func validPercent(_ value:Double?)->Double? {
        guard let value,value.isFinite,(0...100).contains(value) else { return nil }
        return value
    }
    static func date(_ value:String?)->Date? {
        guard let value else { return nil }
        let formatter=ISO8601DateFormatter()
        formatter.formatOptions=[.withInternetDateTime,.withFractionalSeconds]
        if let result=formatter.date(from:value) { return result }
        formatter.formatOptions=[.withInternetDateTime]
        return formatter.date(from:value)
    }
    static func windowLabel(_ source:String,catalog:LocalizationCatalog,language:String)->String {
        if source.hasSuffix(" only"),source.count>5 {
            return catalog.format("Yalnızca {0}",arguments:[String(source.dropLast(5))],language:language)
        }
        let expression=try! NSRegularExpression(pattern:#"^([0-9]+(?:\.[0-9]+)?)([hmd])$"#)
        let raw=source as NSString
        guard let match=expression.firstMatch(in:source,range:NSRange(location:0,length:raw.length)),
              let value=Double(raw.substring(with:match.range(at:1))),value.isFinite else { return catalog.text(source,language:language) }
        let unit=raw.substring(with:match.range(at:2))
        let key=unit == "h" ? "{0} saat":unit == "d" ? "{0} gün":"{0} dk"
        let number=value.formatted(.number.precision(.fractionLength(0...2)).locale(Locale(identifier:language)))
        return catalog.format(key,arguments:[number],language:language)
    }
    static func old(_ value:String?,now:Date)->Bool {
        guard let measured=date(value) else { return true }
        let age=now.timeIntervalSince(measured)
        return age > 900 || age < -60
    }
}

/// Never follows redirects outside the fixed loopback service.
private final class LocalOnlySession:NSObject,URLSessionTaskDelegate {
    func urlSession(_ session:URLSession,task:URLSessionTask,willPerformHTTPRedirection response:HTTPURLResponse,
                    newRequest request:URLRequest,completionHandler:@escaping(URLRequest?)->Void) { completionHandler(nil) }
}

@MainActor final class MenuUsageMonitor:ObservableObject {
    @Published private(set) var snapshot:MenuUsageSnapshot?
    @Published private(set) var offline=true
    @Published private(set) var syncing=false
    @Published private(set) var refreshing=false
    private var readGeneration=0
    @Published private(set) var syncMessage:String?
    @Published private(set) var measuredNow=Date()
    private let base=URL(string:"http://127.0.0.1:47866")!
    private let redirectPolicy=LocalOnlySession()
    private lazy var client:URLSession = {
        let config=URLSessionConfiguration.ephemeral
        config.timeoutIntervalForRequest=5; config.timeoutIntervalForResource=8
        config.urlCache=nil; config.httpCookieStorage=nil
        return URLSession(configuration:config,delegate:redirectPolicy,delegateQueue:nil)
    }()
    init() {}
    #if STUDIO_UI_PREVIEW
    convenience init(preview:MenuUsageSnapshot) { self.init(); snapshot=preview; offline=false; measuredNow=Date() }
    #endif
    var providers:[MenuUsageProvider] { snapshot?.orderedProviders ?? ["claude","cursor","codex"].map(MenuUsageProvider.unknown) }
    var bridgeState:MenuBridgeState { snapshot?.bridgeState(offline:offline) ?? .offline }
    var canSync:Bool { !offline && !syncing && !refreshing && snapshot?.acceptsDeviceCommands==true }

    /// The popover's .task owns this loop; hiding it cancels polling and any request.
    func poll() async {
        #if STUDIO_UI_PREVIEW
        return
        #endif
        do {
            while !Task.isCancelled {
                await refresh()
                try await Task.sleep(nanoseconds:15_000_000_000)
            }
        } catch { /* Cancellation ends the local polling loop. */ }
    }
    func refresh() async {
        readGeneration += 1; let generation=readGeneration
        do {
            let request=URLRequest(url:base.appendingPathComponent("api/status"),cachePolicy:.reloadIgnoringLocalCacheData,timeoutInterval:5)
            let data=try await response(request)
            let value=try JSONDecoder().decode(MenuUsageSnapshot.self,from:data)
            try Task.checkCancellation()
            guard generation == readGeneration else { return }
            snapshot=value; offline=false; measuredNow=Date()
        } catch {
            if !Task.isCancelled && generation == readGeneration { offline=true; measuredNow=Date() }
        }
    }
    func requestRefresh() async {
        guard !refreshing,!syncing else { return }
        refreshing=true; syncMessage=nil
        defer { refreshing=false }
        do {
            _ = try await post("api/refresh")
            syncMessage="Kullanım yenileme isteği gönderildi."
            await refresh()
        } catch { if !Task.isCancelled { syncMessage="Kullanım yenileme isteği gönderilemedi." } }
    }
    func syncClock() async {
        guard canSync else { return }
        syncing=true; syncMessage=nil
        defer { syncing=false }
        do {
            _ = try await post("api/sync-time")
            syncMessage="Saat eşitleme isteği gönderildi."
        } catch { if !Task.isCancelled { syncMessage="Saat eşitleme isteği gönderilemedi." } }
    }
    private func post(_ path:String) async throws -> Data {
        var request=URLRequest(url:base.appendingPathComponent(path))
        request.httpMethod="POST"; request.httpBody=Data("{}".utf8)
        request.setValue("application/json",forHTTPHeaderField:"Content-Type")
        request.setValue(base.absoluteString,forHTTPHeaderField:"Origin")
        return try await response(request)
    }
    private func response(_ request:URLRequest) async throws -> Data {
        let (bytes,reply)=try await client.bytes(for:request)
        defer { bytes.task.cancel() }
        guard let http=reply as? HTTPURLResponse,(200...299).contains(http.statusCode),
              http.value(forHTTPHeaderField:"Content-Type")?.contains("application/json") == true else { throw URLError(.badServerResponse) }
        var data=Data()
        for try await byte in bytes {
            guard data.count < 256*1024 else { throw URLError(.dataLengthExceedsMaximum) }
            data.append(byte)
        }
        return data
    }
}
