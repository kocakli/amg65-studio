// Adapted from CodexBar's MIT-licensed Codex OAuth provider; see NOTICE.md.
import Foundation

enum CodexProvider {
    struct Credentials {
        let token:String
        let account:String?
        let fingerprint:String
    }
    static func credentials(_ data:Data,now:Date)throws->Credentials {
        let root=try JSONValue.object(data)
        guard let tokens=root["tokens"] as? [String:Any],
              let token=JSONValue.text(tokens["access_token"] ?? tokens["accessToken"],maximum:32_768) else {
            throw UsageFailure(code:"auth_required")
        }
        let claims=JSONValue.jwt(token)
        if let expiry=JSONValue.number(claims?["exp"]),expiry<=now.timeIntervalSince1970+60 {
            throw UsageFailure(code:"relogin_required")
        }
        let identityClaims=JSONValue.jwt(tokens["id_token"] as? String ?? tokens["idToken"] as? String ?? "") ?? claims
        let namespace=identityClaims?["https://api.openai.com/auth"] as? [String:Any]
        let account=JSONValue.text(tokens["account_id"] ?? tokens["accountId"])
            ?? JSONValue.text(identityClaims?["chatgpt_account_id"])
            ?? JSONValue.text(namespace?["chatgpt_account_id"])
        return Credentials(token:token,account:account,fingerprint:AccountFingerprint.make(
            provider:"codex",identity:account ?? "credential:"+token))
    }
    static func fetch(context:FetchContext) async->ProviderResult {
        var fingerprint:String?
        do {
            let directory=try CredentialReader.directory(context.environment["CODEX_HOME"],fallback:context.home.appendingPathComponent(".codex"))
            guard let data=try CredentialReader.file(directory.appendingPathComponent("auth.json")) else {
                throw UsageFailure(code:"auth_required")
            }
            let credentials=try credentials(data,now:context.now)
            fingerprint=credentials.fingerprint
            var headers=["Authorization":"Bearer "+credentials.token]
            if let account=credentials.account { headers["ChatGPT-Account-Id"]=account }
            let response=try await context.http.get(url:URL(string:"https://chatgpt.com/backend-api/wham/usage")!,
                                                    headers:headers,deadline:context.deadline)
            return try parse(response,now:Date(),fingerprint:fingerprint)
        } catch { return .failed("codex",error:error,fingerprint:fingerprint) }
    }
    static func window(_ value:Any?)->UsageWindow? {
        guard let value=value as? [String:Any] else { return nil }
        let percent=JSONValue.percent(value["used_percent"])
        let seconds=JSONValue.number(value["limit_window_seconds"])
        let minutes=seconds.flatMap { (0...31_622_400).contains($0) && $0>0 ? $0/60:nil }
        let reset=JSONValue.number(value["reset_at"]).flatMap { (0...253_402_300_799).contains($0) ? UsageDates.iso(Date(timeIntervalSince1970:$0)):nil }
        return UsageWindow(usedPercent:percent,windowMinutes:minutes,resetsAt:reset)
    }
    static func parse(_ data:Data,now:Date,fingerprint:String?=nil)throws->ProviderResult {
        let root=try JSONValue.object(data)
        let limits=root["rate_limit"] as? [String:Any]
        let primary=window(limits?["primary_window"]), secondary=window(limits?["secondary_window"])
        var extras=[ExtraRateWindow]()
        for (index,raw) in ((root["additional_rate_limits"] as? [Any]) ?? []).prefix(24).enumerated() {
            guard let entry=raw as? [String:Any],let windows=entry["rate_limit"] as? [String:Any] else { continue }
            let title=JSONValue.text(entry["limit_name"],maximum:40) ?? "Model \(index+1)"
            for (slot,label) in [("primary_window",""),("secondary_window"," Weekly")] {
                if let item=window(windows[slot]) {
                    extras.append(ExtraRateWindow(id:"codex-extra-\(index)-\(slot)",title:title+label,
                                                 usageKnown:item.usedPercent != nil,window:item))
                }
            }
        }
        guard primary != nil || secondary != nil || !extras.isEmpty else { throw UsageFailure(code:"no_usage") }
        // Window duration comes from the response: some plans use a true30-day primary.
        var labels=[String:String]()
        for (key,item) in [("primary",primary),("secondary",secondary)] {
            if let minutes=item?.windowMinutes {
                if minutes==300 { labels[key]="5h" }
                else if minutes==10080 { labels[key]="7d" }
                else if minutes==43200 { labels[key]="Monthly" }
            }
        }
        return .success("codex",usage:UsageData(updatedAt:UsageDates.iso(now),primary:primary,
                        secondary:secondary,extraRateWindows:extras.isEmpty ? nil:extras),labels:labels,fingerprint:fingerprint)
    }
}
