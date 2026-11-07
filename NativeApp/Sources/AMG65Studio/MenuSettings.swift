import Foundation
import Combine

struct MenuDisplaySettings:Codable,Equatable {
    var displayMode="overview"
    var brightness=0.4
    var text="AMG65 STUDIO"
    var textColor="#7bdcb0"
    var textEffect="none"
    var activityEnabled=true
    var mascotEnabled=false
    var trackedProvider="all"
    var claudeGreenGain=1.0
    enum CodingKeys:String,CodingKey {
        case brightness,text
        case displayMode="display_mode",textColor="text_color",textEffect="text_effect",activityEnabled="activity_enabled"
        case mascotEnabled="mascot_enabled"
        case trackedProvider="tracked_provider"
        case claudeGreenGain="claude_green_gain"
    }
    private enum LegacyCodingKeys:String,CodingKey { case claudeMascot="claude_mascot" }
    init() {}
    init(from decoder:Decoder) throws {
        let values=try decoder.container(keyedBy:CodingKeys.self)
        displayMode=try values.decode(String.self,forKey:.displayMode)
        brightness=try values.decode(Double.self,forKey:.brightness)
        text=try values.decode(String.self,forKey:.text)
        textColor=try values.decode(String.self,forKey:.textColor)
        activityEnabled=try values.decode(Bool.self,forKey:.activityEnabled)
        // Older local bridges did not expose text effects.
        textEffect=try values.decodeIfPresent(String.self,forKey:.textEffect) ?? "none"
        if values.contains(.mascotEnabled) {
            mascotEnabled=try values.decode(Bool.self,forKey:.mascotEnabled)
        } else {
            let legacy=try decoder.container(keyedBy:LegacyCodingKeys.self)
            if legacy.contains(.claudeMascot) { mascotEnabled=try legacy.decode(Bool.self,forKey:.claudeMascot) }
        }
        if values.contains(.trackedProvider) { trackedProvider=try values.decode(String.self,forKey:.trackedProvider) }
        if values.contains(.claudeGreenGain) { claudeGreenGain=try values.decode(Double.self,forKey:.claudeGreenGain) }
    }
    var valid:Bool {
        ["overview","rotate","text"].contains(displayMode) && brightness.isFinite && (0...1).contains(brightness)
        && ["none","scan","breathe","matrix","scroll"].contains(textEffect)
        && ["all","claude","codex","cursor"].contains(trackedProvider)
        && claudeGreenGain.isFinite && (0...1).contains(claudeGreenGain)
        && text.utf8.count<=64 && text.unicodeScalars.allSatisfy{(32...126).contains($0.value)}
        && textColor.range(of:#"^#[0-9a-fA-F]{6}$"#,options:.regularExpression) != nil
    }
}

private final class MenuSettingsRedirectPolicy:NSObject,URLSessionTaskDelegate {
    func urlSession(_ session:URLSession,task:URLSessionTask,willPerformHTTPRedirection response:HTTPURLResponse,
                    newRequest request:URLRequest,completionHandler:@escaping(URLRequest?)->Void) { completionHandler(nil) }
}

/// Fixed loopback origin, bounded replies, no cookies, no redirect or remote auth requests.
@MainActor final class MenuLocalClient {
    private let base=URL(string:"http://127.0.0.1:47866")!
    private let policy=MenuSettingsRedirectPolicy()
    private lazy var session:URLSession = {
        let config=URLSessionConfiguration.ephemeral
        config.timeoutIntervalForRequest=5; config.timeoutIntervalForResource=8
        config.httpCookieStorage=nil; config.urlCache=nil
        return URLSession(configuration:config,delegate:policy,delegateQueue:nil)
    }()
    func request(_ path:String,body:Data?=nil) async throws -> Data {
        let allowed=["api/settings","api/display","api/accounts","api/accounts/start","api/accounts/submit","api/accounts/cancel"]
        guard allowed.contains(path) else { throw URLError(.unsupportedURL) }
        var request=URLRequest(url:base.appendingPathComponent(path))
        if let body {
            guard body.count<=4096 else { throw URLError(.dataLengthExceedsMaximum) }
            request.httpMethod="POST"; request.httpBody=body
            request.setValue("application/json",forHTTPHeaderField:"Content-Type")
            request.setValue(base.absoluteString,forHTTPHeaderField:"Origin")
        }
        let (bytes,response)=try await session.bytes(for:request)
        defer { bytes.task.cancel() }
        guard let http=response as? HTTPURLResponse,(200...299).contains(http.statusCode),
              http.value(forHTTPHeaderField:"Content-Type")?.contains("application/json") == true else { throw URLError(.badServerResponse) }
        var data=Data()
        for try await byte in bytes {
            guard data.count<256*1024 else { throw URLError(.dataLengthExceedsMaximum) }
            data.append(byte)
        }
        return data
    }
}

@MainActor final class MenuDisplayModel:ObservableObject {
    @Published var draft=MenuDisplaySettings()
    @Published var enabled=true
    @Published private(set) var loaded=false
    @Published private(set) var saving=false
    @Published private(set) var message:String?
    private var baseline=MenuDisplaySettings()
    private var baselineEnabled=true
    private var pending:MenuDisplaySettings?
    private var pendingEnabled:Bool?
    private var pendingOriginal:MenuDisplaySettings?
    private let client=MenuLocalClient()
    private let sendOverride:((String,Data) async throws -> Void)?
    init(send:((String,Data) async throws -> Void)?=nil) { sendOverride=send }
    private func send(_ path:String,_ body:Data) async throws {
        if let sendOverride { try await sendOverride(path,body) }
        else { _ = try await client.request(path,body:body) }
    }
    var dirty:Bool { loaded && (draft != baseline || enabled != baselineEnabled) }
    func receive(_ snapshot:MenuUsageSnapshot?) {
        guard !saving,let value=snapshot?.settings,value.valid,let enabled=snapshot?.running else { return }
        if let pending,value==pending,enabled==pendingEnabled {
            if draft==pendingOriginal { draft=value }
            baseline=value; baselineEnabled=enabled; self.pending=nil;pendingEnabled=nil;pendingOriginal=nil
            message="Ayarlar uygulandı."
        }
        guard !dirty else { return }
        draft=value; baseline=value; self.enabled=enabled; baselineEnabled=enabled; loaded=true
    }
    func discard() { draft=baseline; enabled=baselineEnabled; pending=nil;pendingEnabled=nil;pendingOriginal=nil;message=nil }
    func save() async {
        guard loaded,draft.valid,!saving else { return }
        saving=true; message=nil
        let original=draft
        var sent=draft
        sent.text=sent.text.uppercased();sent.textColor=sent.textColor.lowercased()
        let sentEnabled=enabled
        defer { saving=false }
        do {
            try await send("api/settings",JSONEncoder().encode(sent))
            if sentEnabled != baselineEnabled {
                try await send("api/display",JSONSerialization.data(withJSONObject:["enabled":sentEnabled]))
            }
            pending=sent;pendingEnabled=sentEnabled;pendingOriginal=original
            message="Ayar isteği gönderildi."
        } catch { if !Task.isCancelled { message="Ayarlar gönderilemedi. Yerel bağlantıyı kontrol edin." } }
    }
}

struct MenuAccountUsage:Decodable {
    let remainingPercent:Double?
    let remainingLabel:String?
    let stale:Bool?
    let error:String?
    let updatedAt:String?
    enum CodingKeys:String,CodingKey {
        case stale,error
        case remainingPercent="remaining_percent",remainingLabel="remaining_label",updatedAt="updated_at"
    }
    var requiresSignIn:Bool {
        ["auth_required","relogin_required","invalid_credentials","auth_missing","auth_expired","unauthorized","credentials_expired"].contains(error ?? "")
    }
    var transient:Bool { ["network_error","rate_limited","timeout"].contains(error ?? "") }
    var inaccessible:Bool { ["keychain_locked","credentials_unreadable","access_denied"].contains(error ?? "") }
    func hasMeasurement(at now:Date)->Bool {
        guard MenuUsageSnapshot.validPercent(remainingPercent) != nil,let measured=MenuUsageSnapshot.date(updatedAt) else { return false }
        return measured.timeIntervalSince(now)<=60
    }
    func fresh(at now:Date)->Bool {
        error==nil && stale==false && hasMeasurement(at:now) && !MenuUsageSnapshot.old(updatedAt,now:now)
    }
}

enum MenuAccountConnection:Equatable { case pending,connected,requiresSignIn,unknown }

struct MenuAccount:Decodable,Identifiable {
    let provider:String
    let phase:String
    let authURL:String?
    let userCode:String?
    let inputRequired:Bool?
    let error:String?
    let expiresAt:String?
    let method:String?
    let interaction:String?
    let actions:[String]?
    let usage:MenuAccountUsage?
    var id:String { provider }
    enum CodingKeys:String,CodingKey {
        case provider,phase,error,method,interaction,actions,usage
        case authURL="auth_url",userCode="user_code",inputRequired="input_required",expiresAt="expires_at"
    }
    var pending:Bool { ["starting","awaiting_browser","awaiting_code","awaiting_confirmation"].contains(phase) }
    func connection(at now:Date,knownConnected:Bool=false,allowCompletedPhase:Bool=true)->MenuAccountConnection {
        if pending { return .pending }
        if usage?.requiresSignIn==true { return .requiresSignIn }
        if usage?.inaccessible==true { return .unknown }
        if usage?.fresh(at:now)==true { return .connected }
        // A completed provider login is evidence of authentication, not of a fresh
        // quota. An explicit later auth rejection invalidates that completion.
        if phase=="complete",allowCompletedPhase { return .connected }
        if usage?.transient==true,allowCompletedPhase,
           knownConnected || usage?.hasMeasurement(at:now)==true { return .connected }
        if knownConnected,usage?.error==nil || usage?.error=="no_usage" { return .connected }
        return .unknown
    }
    static func idle(_ provider:String)->MenuAccount {
        MenuAccount(provider:provider,phase:"idle",authURL:nil,userCode:nil,inputRequired:false,error:nil,expiresAt:nil,method:nil,interaction:nil,actions:nil,usage:nil)
    }
}

@MainActor final class MenuAccountsModel:ObservableObject {
    @Published private(set) var accounts=[MenuAccount]()
    @Published private(set) var offline=true
    @Published private(set) var busy=false
    @Published private(set) var message:String?
    @Published var inputCodes=[String:String]()
    private let client=MenuLocalClient()
    private var generation=0
    private var pendingBrowserOpen=Set<String>()
    private var verifiedConnections=Set<String>()
    private var rejectedCompletions=Set<String>()
    var openAuthorization:((URL)->Void)?
    init() {}
    #if STUDIO_UI_PREVIEW
    convenience init(preview:[MenuAccount]) { self.init();receive(preview) }
    #endif
    func row(_ provider:String)->MenuAccount { accounts.first{$0.provider == provider} ?? .idle(provider) }
    func connection(_ row:MenuAccount,at now:Date=Date())->MenuAccountConnection {
        row.connection(at:now,knownConnected:verifiedConnections.contains(row.provider),
                       allowCompletedPhase:!rejectedCompletions.contains(row.provider))
    }
    func receive(_ rows:[MenuAccount],at now:Date=Date()) {
        accounts=Array(rows.filter{["claude","codex","cursor"].contains($0.provider)}.prefix(3));offline=false
        for row in accounts {
            if row.pending { rejectedCompletions.remove(row.provider) }
            if row.usage?.requiresSignIn==true {
                verifiedConnections.remove(row.provider);rejectedCompletions.insert(row.provider)
            } else if row.usage?.inaccessible==true {
                verifiedConnections.remove(row.provider)
            } else if row.usage?.fresh(at:now)==true {
                verifiedConnections.insert(row.provider);rejectedCompletions.remove(row.provider)
            } else if connection(row,at:now) == .connected { verifiedConnections.insert(row.provider) }
        }
    }
    static func authorizationURL(_ value:String?,provider:String)->URL? {
        guard let value,value.count<=4096,let url=URL(string:value),url.scheme=="https",
              url.user==nil,url.password==nil,url.port==nil || url.port==443 else { return nil }
        let hosts:[String:Set<String>]=["codex":["auth.openai.com","chatgpt.com"],"claude":["claude.ai","claude.com","console.anthropic.com","platform.claude.com"]]
        guard let host=url.host?.lowercased(),hosts[provider]?.contains(host)==true else { return nil }
        let paths=provider=="codex" ? ["/codex/device","/device","/activate","/oauth/authorize"]:["/oauth/authorize","/cai/oauth/authorize","/login"]
        guard paths.contains(url.path) else { return nil }
        return url
    }
    func poll() async {
        #if STUDIO_UI_PREVIEW
        return
        #endif
        do {
            while !Task.isCancelled {
                await refresh()
                try await Task.sleep(nanoseconds:2_000_000_000)
            }
        } catch {}
    }
    func refresh() async {
        generation += 1; let token=generation
        do {
            let data=try await client.request("api/accounts")
            struct Reply:Decodable { let accounts:[MenuAccount] }
            let reply=try JSONDecoder().decode(Reply.self,from:data)
            try Task.checkCancellation()
            guard token==generation else { return }
            receive(reply.accounts)
            for row in accounts where pendingBrowserOpen.contains(row.provider) {
                if row.pending,let url=Self.authorizationURL(row.authURL,provider:row.provider) {
                    pendingBrowserOpen.remove(row.provider); openAuthorization?(url)
                } else if ["complete","error","cancelled"].contains(row.phase) { pendingBrowserOpen.remove(row.provider) }
            }
        } catch { if !Task.isCancelled && token==generation { offline=true } }
    }
    func start(_ provider:String) async {
        guard !busy,["codex","claude","cursor"].contains(provider) else { return }
        pendingBrowserOpen.insert(provider); inputCodes[provider]=nil
        await action("start",provider:provider)
    }
    func submit(_ provider:String) async {
        guard let code=inputCodes[provider],!code.isEmpty,code.utf8.count<=2048 else { return }
        inputCodes[provider]=nil
        await action("submit",provider:provider,code:code)
    }
    func cancel(_ provider:String) async {
        pendingBrowserOpen.remove(provider); inputCodes[provider]=nil
        await action("cancel",provider:provider)
    }
    func confirmWorkspace(_ provider:String) async {
        let account=row(provider)
        guard provider=="claude",account.phase=="awaiting_confirmation",account.interaction=="workspace_trust",
              account.actions?.contains("trust_login_workspace")==true else { return }
        await action("submit",provider:provider,code:"trust_login_workspace")
    }
    private func action(_ action:String,provider:String,code:String?=nil) async {
        guard !busy,["codex","claude","cursor"].contains(provider) else { return }
        busy=true;message=nil;defer { busy=false }
        do {
            var payload=["provider":provider]
            if let code { payload["code"]=code }
            _ = try await client.request("api/accounts/"+action,body:JSONSerialization.data(withJSONObject:payload))
            await refresh()
        } catch { if !Task.isCancelled { message="Hesap işlemi tamamlanamadı. Yeniden deneyin." } }
    }
    func clearInput() { inputCodes.removeAll() }
}
