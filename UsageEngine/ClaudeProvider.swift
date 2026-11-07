// Adapted from CodexBar's MIT-licensed Claude OAuth provider; see NOTICE.md.
import Foundation

enum ClaudeProvider {
    struct Credentials { let token:String; let fingerprint:String }
    static func credentials(_ data:Data,now:Date)throws->Credentials {
        let root=try JSONValue.object(data)
        guard let oauth=root["claudeAiOauth"] as? [String:Any],
              let token=JSONValue.text(oauth["accessToken"],maximum:32_768) else {
            throw UsageFailure(code:"auth_required") // MCP-only credentials are unrelated to subscription quotas.
        }
        if let expiration=JSONValue.number(oauth["expiresAt"]),expiration/1000<=now.timeIntervalSince1970+60 {
            throw UsageFailure(code:"relogin_required")
        }
        if let scopes=oauth["scopes"] as? [String],!scopes.contains("user:profile") {
            throw UsageFailure(code:"auth_required")
        }
        // Claude Code's credential schema does not guarantee a stable organization ID.
        // Rotated tokens therefore invalidate the retained quota rather than mix accounts.
        return Credentials(token:token,fingerprint:AccountFingerprint.make(provider:"claude",identity:"credential:"+token))
    }
    /// Like upstream, an expired file does not hide a usable Claude Code Keychain
    /// record. A valid file keeps precedence. No shared token is renewed or saved.
    static func loadCredentials(now:Date,file:()throws->Data?,keychain:(()throws->Data?)?=nil)throws->Credentials {
        var errors=[String]()
        do { if let data=try file() { return try credentials(data,now:now) } }
        catch let failure as UsageFailure { errors.append(failure.code) }
        catch { errors.append("credentials_unreadable") }
        if let keychain {
            do { if let data=try keychain() { return try credentials(data,now:now) } }
            catch let failure as UsageFailure { errors.append(failure.code) }
            catch { errors.append("credentials_unreadable") }
        }
        // A blocked fresh store calls for access, not a misleading sign-out request.
        for code in ["keychain_locked","relogin_required","credentials_unreadable","invalid_response"] {
            if errors.contains(code) { throw UsageFailure(code:code) }
        }
        throw UsageFailure(code:"auth_required")
    }
    static func fetch(context:FetchContext) async->ProviderResult {
        var fingerprint:String?
        do {
            let standard=context.home.appendingPathComponent(".claude")
            let config=try CredentialReader.directory(context.environment["CLAUDE_CONFIG_DIR"],fallback:standard)
            let storage=context.environment["CLAUDE_SECURESTORAGE_CONFIG_DIR"]
            let secure=try CredentialReader.directory(storage,fallback:storage == "" ? standard:config)
            // A custom profile must not silently borrow another profile's default login.
            let defaultProfile=config.standardizedFileURL==standard.standardizedFileURL
                && secure.standardizedFileURL==standard.standardizedFileURL
            let keychain:(()throws->Data?)?=defaultProfile
                ? { try CredentialReader.keychain(service:"Claude Code-credentials",account:nil) }:nil
            let credentials=try loadCredentials(now:context.now,file:{
                try CredentialReader.file(secure.appendingPathComponent(".credentials.json"))
            },keychain:keychain)
            fingerprint=credentials.fingerprint
            let response=try await context.http.get(url:URL(string:"https://api.anthropic.com/api/oauth/usage")!,headers:[
                "Authorization":"Bearer "+credentials.token,
                "anthropic-beta":"oauth-2025-04-20",
                "Content-Type":"application/json",
                "User-Agent":"claude-code/2.1.0",
            ],deadline:context.deadline)
            return try parse(response,now:Date(),fingerprint:fingerprint)
        } catch { return .failed("claude",error:error,fingerprint:fingerprint) }
    }
    static func window(_ value:Any?,minutes:Double)->UsageWindow? {
        guard let raw=value as? [String:Any] else { return nil }
        return UsageWindow(usedPercent:JSONValue.percent(raw["utilization"]),windowMinutes:minutes,
                           resetsAt:UsageDates.date(raw["resets_at"] as? String).map(UsageDates.iso))
    }
    static func parse(_ data:Data,now:Date,fingerprint:String?=nil)throws->ProviderResult {
        let root=try JSONValue.object(data)
        let primary=window(root["five_hour"],minutes:300), secondary=window(root["seven_day"],minutes:10080)
        var extras=[ExtraRateWindow]()
        for (key,title) in [("seven_day_opus","Opus Weekly"),("seven_day_sonnet","Sonnet Weekly"),
                            ("seven_day_oauth_apps","OAuth Apps Weekly"),("seven_day_routines","Daily Routines")] {
            if let item=window(root[key],minutes:10080) {
                extras.append(ExtraRateWindow(id:key,title:title,usageKnown:item.usedPercent != nil,window:item))
            }
        }
        // Match CodexBar's documented weekly-scoped model lanes; general limits
        // remain five_hour/seven_day and are never replaced by a model allowance.
        var seen=Set<String>()
        for value in ((root["limits"] as? [Any]) ?? []).prefix(24) {
            guard let entry=value as? [String:Any],entry["group"] as? String == "weekly",
                  entry["kind"] as? String == "weekly_scoped",let used=JSONValue.percent(entry["percent"]),
                  let scope=entry["scope"] as? [String:Any],let model=scope["model"] as? [String:Any],
                  let title=JSONValue.text(model["display_name"],maximum:40) else { continue }
            let identity=JSONValue.text(model["id"],maximum:80) ?? title
            let slug=identity.lowercased().components(separatedBy:CharacterSet.alphanumerics.inverted)
                .filter { !$0.isEmpty }.joined(separator:"-")
            let nameSlug=title.lowercased().components(separatedBy:CharacterSet.alphanumerics.inverted)
                .filter { !$0.isEmpty }.joined(separator:"-")
            guard !slug.isEmpty,slug != "all-models",!slug.hasSuffix("-all-models"),nameSlug != "all-models",
                  seen.insert(slug).inserted else { continue }
            extras.append(ExtraRateWindow(id:"claude-weekly-scoped-"+slug,title:title+" only",
                window:UsageWindow(usedPercent:used,windowMinutes:10080,
                                   resetsAt:UsageDates.date(entry["resets_at"] as? String).map(UsageDates.iso))))
        }
        guard primary != nil || secondary != nil || !extras.isEmpty else { throw UsageFailure(code:"no_usage") }
        return .success("claude",usage:UsageData(updatedAt:UsageDates.iso(now),primary:primary,
                        secondary:secondary,extraRateWindows:extras.isEmpty ? nil:extras),
                        labels:["primary":"5h","secondary":"7d"],fingerprint:fingerprint)
    }
}
