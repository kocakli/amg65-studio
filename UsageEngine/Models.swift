import Foundation
import CoreFoundation
import CryptoKit

/// Wire format deliberately contains quotas only: no credentials or account identity.
struct UsageWindow: Encodable, Sendable {
    let usedPercent: Double?
    let windowMinutes: Double?
    let resetsAt: String?
    init(usedPercent: Double?, windowMinutes: Double? = nil, resetsAt: String? = nil) {
        self.usedPercent=usedPercent; self.windowMinutes=windowMinutes; self.resetsAt=resetsAt
    }
}
struct ExtraRateWindow: Encodable, Sendable {
    let id: String
    let title: String
    let usageKnown: Bool
    let window: UsageWindow
    init(id:String,title:String,usageKnown:Bool=true,window:UsageWindow) {
        self.id=id; self.title=title; self.usageKnown=usageKnown; self.window=window
    }
}
struct UsageData: Encodable, Sendable {
    let updatedAt: String
    let primary: UsageWindow?
    let secondary: UsageWindow?
    let tertiary: UsageWindow?
    let extraRateWindows: [ExtraRateWindow]?
    init(updatedAt:String,primary:UsageWindow?=nil,secondary:UsageWindow?=nil,
         tertiary:UsageWindow?=nil,extraRateWindows:[ExtraRateWindow]?=nil) {
        self.updatedAt=updatedAt; self.primary=primary; self.secondary=secondary
        self.tertiary=tertiary; self.extraRateWindows=extraRateWindows
    }
}
struct UsageFailure: Error, Encodable, Sendable {
    let code:String
    init(code:String) { self.code=code }
}
struct ProviderResult: Encodable, Sendable {
    let provider:String
    let usage:UsageData?
    let rateWindowLabels:[String:String]?
    let error:UsageFailure?
    let accountFingerprint:String?
    init(provider:String,usage:UsageData?=nil,rateWindowLabels:[String:String]?=nil,error:UsageFailure?=nil,
         accountFingerprint:String?=nil) {
        self.provider=provider; self.usage=usage; self.rateWindowLabels=rateWindowLabels; self.error=error
        self.accountFingerprint=accountFingerprint
    }
    static func failure(_ provider:String,code:String,fingerprint:String?=nil)->Self {
        Self(provider:provider,error:UsageFailure(code:code),accountFingerprint:fingerprint)
    }
    static func success(_ provider:String,usage:UsageData,labels:[String:String]=[:],fingerprint:String?=nil)->Self {
        Self(provider:provider,usage:usage,rateWindowLabels:labels,accountFingerprint:fingerprint)
    }
    static func failed(_ provider:String,error:Error,fingerprint:String?=nil)->Self {
        if let error=error as? UsageFailure { return .failure(provider,code:error.code,fingerprint:fingerprint) }
        if error is CancellationError { return .failure(provider,code:"timeout",fingerprint:fingerprint) }
        return .failure(provider,code:"network_error",fingerprint:fingerprint)
    }
}
enum AccountFingerprint {
    static func make(provider:String,identity:String)->String {
        SHA256.hash(data:Data(("AMG65 usage account v1\0"+provider+"\0"+identity).utf8))
            .map { String(format:"%02x",$0) }.joined()
    }
}
struct FetchContext: Sendable {
    let http:UsageHTTPClient
    let home:URL
    let environment:[String:String]
    let now:Date
    let deadline:Date
}
enum UsageDates {
    static func iso(_ date:Date)->String { ISO8601DateFormatter().string(from:date) }
    static func date(_ value:String?)->Date? {
        guard let value, value.count<=80 else { return nil }
        let formatter=ISO8601DateFormatter()
        formatter.formatOptions=[.withInternetDateTime,.withFractionalSeconds]
        if let result=formatter.date(from:value) { return result }
        formatter.formatOptions=[.withInternetDateTime]
        return formatter.date(from:value)
    }
}
enum JSONValue {
    static func object(_ data:Data)throws->[String:Any] {
        guard data.count<=1_048_576,
              let value=try? JSONSerialization.jsonObject(with:data) as? [String:Any] else {
            throw UsageFailure(code:"invalid_response")
        }
        return value
    }
    static func number(_ value:Any?)->Double? {
        guard let number=value as? NSNumber, CFGetTypeID(number) != CFBooleanGetTypeID(),
              number.doubleValue.isFinite else { return nil }
        return number.doubleValue
    }
    /// Preserve over-limit usage; the presentation layer clamps remaining quota.
    static func percent(_ value:Any?)->Double? {
        guard let value=number(value),value>=0 else { return nil }; return value
    }
    static func text(_ value:Any?,maximum:Int=160)->String? {
        guard let value=value as? String,!value.isEmpty,value.count<=maximum,
              !value.unicodeScalars.contains(where:CharacterSet.controlCharacters.contains) else { return nil }
        return value
    }
    static func jwt(_ token:String)->[String:Any]? {
        let parts=token.split(separator:".",omittingEmptySubsequences:false)
        guard parts.count==3,parts[1].count<=32_768 else { return nil }
        var raw=String(parts[1]).replacingOccurrences(of:"-",with:"+").replacingOccurrences(of:"_",with:"/")
        raw += String(repeating:"=",count:(4-raw.count%4)%4)
        guard let data=Data(base64Encoded:raw) else { return nil }
        return try? object(data)
    }
}
