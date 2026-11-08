import Foundation
import Security
import LocalAuthentication

struct CheckFailure:Error { let name:String }
enum OfflineCheckCount { nonisolated(unsafe) static var value=0 }
func check(_ condition:Bool,_ name:String)throws {
    OfflineCheckCount.value += 1
    if !condition { throw CheckFailure(name:name) }
}
func expectFailure(_ code:String,_ body:()throws->Void)throws {
    do { try body(); throw CheckFailure(name:"Expected "+code) }
    catch let error as UsageFailure { try check(error.code==code,"Wrong failure code") }
}
func fixtureJWT(_ payload:[String:Any])throws->String {
    let data=try JSONSerialization.data(withJSONObject:payload)
    let raw=data.base64EncodedString().replacingOccurrences(of:"+",with:"-").replacingOccurrences(of:"/",with:"_").replacingOccurrences(of:"=",with:"")
    return "fixture."+raw+".signature"
}

@main struct EngineChecks {
    static func main() async throws {
        let now=Date(timeIntervalSince1970:1_800_000_000)
        try check(JSONValue.number(true)==nil && JSONValue.number(Double.nan)==nil,"Reject Boolean and NaN quota")
        try check(JSONValue.percent(-1)==nil && JSONValue.percent(125)==125,"Preserve over-limit usage")
        for raw in ["http://chatgpt.com/","https://chatgpt.com.evil.test/","https://user:secret@chatgpt.com/",
                    "https://chatgpt.com:444/","https://evil.test/"] {
            try check(!UsageHTTPClient.allowed(URL(string:raw)!),"Reject untrusted credential destination")
        }
        try check(UsageHTTPClient.allowed(URL(string:"https://cursor.com/api/usage-summary")!),"Allow exact provider origin")
        let query=CredentialReader.keychainQuery(service:"offline-fixture",account:"fixture")
        try check((query[kSecUseAuthenticationContext as String] as? LAContext)?.interactionNotAllowed==true,"Keychain context forbids UI")
        try check((query[kSecUseAuthenticationUI as String] as? String)==(kSecUseAuthenticationUIFail as String),"Legacy Keychain query forbids UI")
        let access=CredentialReader.keychainAccessQuery(service:"offline-fixture")
        try check(access[kSecReturnData as String] as? Bool==true,"Access request reads data so the Keychain ACL is evaluated")
        try check(access[kSecUseAuthenticationUI as String]==nil && access[kSecUseAuthenticationContext as String]==nil,"Access request may show the system dialog")
        let token=try fixtureJWT(["exp":now.timeIntervalSince1970+3600,"https://api.openai.com/auth":["chatgpt_account_id":"fixture-account"]])
        let credential=try JSONSerialization.data(withJSONObject:["tokens":["access_token":token]])
        let codex=try CodexProvider.credentials(credential,now:now)
        try check(codex.account=="fixture-account" && codex.fingerprint.count==64,"Codex JWT account fallback and opaque hash")
        let expired=try fixtureJWT(["exp":now.timeIntervalSince1970-1])
        try expectFailure("relogin_required") { _=try CodexProvider.credentials(JSONSerialization.data(withJSONObject:["tokens":["access_token":expired]]),now:now) }
        try expectFailure("auth_required") { _=try CodexProvider.credentials(Data(#"{"OPENAI_API_KEY":"fake"}"#.utf8),now:now) }
        let codexData=Data(#"{"account_id":"private-account","rate_limit":{"primary_window":{"used_percent":0,"reset_at":1800003600,"limit_window_seconds":18000},"secondary_window":{"used_percent":true,"reset_at":1800604800,"limit_window_seconds":604800}},"additional_rate_limits":[null,{"limit_name":"Spark","rate_limit":{"primary_window":{"used_percent":38,"limit_window_seconds":18000}}}]}"#.utf8)
        let snapshot=try CodexProvider.parse(codexData,now:now,fingerprint:codex.fingerprint)
        try check(snapshot.usage?.primary?.usedPercent==0 && snapshot.usage?.secondary?.usedPercent==nil,"Real zero distinct from malformed quota")
        try check(snapshot.usage?.primary?.windowMinutes==300 && snapshot.usage?.extraRateWindows?.count==1,"Codex duration and lossy extras")
        let encoded=String(data:try JSONEncoder().encode(snapshot),encoding:.utf8)!
        try check(!encoded.contains("private-account") && !encoded.contains("fixture-account") && !encoded.contains(token),"Wire output omits identifiers and token")
        let claudeCredentials=Data(#"{"claudeAiOauth":{"accessToken":"fake-secret","expiresAt":1800003600000,"scopes":["user:profile"]}}"#.utf8)
        let claude=try ClaudeProvider.credentials(claudeCredentials,now:now)
        try check(claude.fingerprint.count==64 && claude.fingerprint != codex.fingerprint,"Provider-specific credential fingerprint")
        let expiredClaude=Data(#"{"claudeAiOauth":{"accessToken":"expired-fixture","expiresAt":1799999999000,"scopes":["user:profile"]}}"#.utf8)
        let recovered=try ClaudeProvider.loadCredentials(now:now,file:{expiredClaude},keychain:{claudeCredentials})
        try check(recovered.fingerprint==claude.fingerprint,"Expired Claude file cannot hide fresh default Keychain session")
        let recoveredMalformed=try ClaudeProvider.loadCredentials(now:now,file:{Data("{}".utf8)},keychain:{claudeCredentials})
        try check(recoveredMalformed.fingerprint==claude.fingerprint,"Invalid Claude file permits valid default Keychain fallback")
        var keychainRead=false
        _=try ClaudeProvider.loadCredentials(now:now,file:{claudeCredentials},keychain:{keychainRead=true; return nil})
        try check(!keychainRead,"Valid Claude profile file keeps precedence without unnecessary Keychain access")
        try expectFailure("relogin_required") { _=try ClaudeProvider.loadCredentials(now:now,file:{expiredClaude}) }
        try expectFailure("relogin_required") { _=try ClaudeProvider.loadCredentials(now:now,file:{expiredClaude},keychain:{nil}) }
        try expectFailure("keychain_locked") {
            _=try ClaudeProvider.loadCredentials(now:now,file:{expiredClaude},keychain:{throw UsageFailure(code:"keychain_locked")})
        }
        try expectFailure("invalid_credentials") {
            _=try CredentialReader.directory("relative-profile",fallback:URL(fileURLWithPath:"/fixture/default"))
        }
        try expectFailure("auth_required") { _=try ClaudeProvider.credentials(Data(#"{"mcpOAuth":{"token":"fake"}}"#.utf8),now:now) }
        let claudeData=Data(#"{"five_hour":{"utilization":0.36,"resets_at":"2027-01-15T09:00:00Z"},"seven_day":{"utilization":null},"seven_day_sonnet":{"utilization":105},"email":"private@example.invalid"}"#.utf8)
        let usage=try ClaudeProvider.parse(claudeData,now:now,fingerprint:claude.fingerprint)
        try check(usage.usage?.primary?.usedPercent==0.36 && usage.usage?.secondary?.usedPercent==nil,"Claude fractional percent and unknown window")
        try check(usage.usage?.extraRateWindows?.first?.window.usedPercent==105,"Claude over-limit extra")
        let scoped=Data(#"{"seven_day":{"utilization":2},"limits":[{"kind":"weekly_scoped","group":"weekly","percent":0,"scope":{"model":{"id":"fable","display_name":"Fable"}}},{"kind":"weekly_scoped","group":"weekly","percent":0,"scope":{"model":{"id":"fable","display_name":"Fable"}}},{"kind":"weekly_scoped","group":"weekly","percent":2,"scope":{"model":{"id":"all-models","display_name":"All models"}}},{"kind":"daily_scoped","group":"daily","percent":99,"scope":{"model":{"id":"ignored","display_name":"Ignored"}}}]}"#.utf8)
        let scopedResult=try ClaudeProvider.parse(scoped,now:now)
        try check(scopedResult.usage?.secondary?.usedPercent==2,"Model allowance does not replace general quota")
        try check(scopedResult.usage?.extraRateWindows?.count==1 && scopedResult.usage?.extraRateWindows?.first?.id=="claude-weekly-scoped-fable","Scoped weekly model identity, duplicates and general-limit exclusions")
        try check(scopedResult.usage?.extraRateWindows?.first?.title=="Fable only" && scopedResult.usage?.extraRateWindows?.first?.window.windowMinutes==10080,"Fable window label and documented cadence")
        try expectFailure("no_usage") { _=try ClaudeProvider.parse(Data(#"{"email":"hidden"}"#.utf8),now:now) }
        let error=ProviderResult.failed("claude",error:UsageFailure(code:"network_error"),fingerprint:claude.fingerprint)
        try check(error.usage==nil && error.accountFingerprint==claude.fingerprint,"Failure retains same-account evidence without fresh measurement")
        let directory=FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at:directory,withIntermediateDirectories:true)
        defer { try? FileManager.default.removeItem(at:directory) }
        let file=directory.appendingPathComponent("fixture.json")
        try Data("fixture".utf8).write(to:file)
        try check(try CredentialReader.file(file)==Data("fixture".utf8),"Owned regular fixture reads")
        let link=directory.appendingPathComponent("link")
        try FileManager.default.createSymbolicLink(at:link,withDestinationURL:file)
        try expectFailure("credentials_unreadable") { _=try CredentialReader.file(link) }
        try check(try CredentialReader.file(directory.appendingPathComponent("missing"))==nil,"Missing credentials do not become zero")
        try cursorChecks()
        try await httpChecks()
        print("PASS: \(OfflineCheckCount.value) independent usage engine offline checks; no real credentials, network or USB accessed.")
    }
}
