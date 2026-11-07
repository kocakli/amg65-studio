import Foundation
import CommonCrypto
import SQLite3

// Every credential and database below is synthetic. No home-directory, Keychain,
// browser, or HTTP access is needed to exercise the production Cursor decoder.
func cursorChecks() throws {
    let now = Date(timeIntervalSince1970: 1_800_000_000)
    let token = try cursorToken(subject: "auth0|synthetic_user-1", expiration: now.timeIntervalSince1970 + 3600)
    let session = try CursorProvider.parseToken(token, now: now)
    try check(session.userID == "synthetic_user-1", "Cursor JWT cookie identity")
    try check(session.cookieHeader == "WorkosCursorSessionToken=synthetic_user-1%3A%3A" + token,
              "Cursor cookie encoding")
    try cursorFailure("relogin_required") {
        _ = try CursorProvider.parseToken(cursorToken(subject: "user", expiration: now.timeIntervalSince1970 + 60), now: now)
    }
    try cursorFailure("auth_required") {
        _ = try CursorProvider.parseToken(cursorToken(subject: "bad\r\nCookie", expiration: now.timeIntervalSince1970 + 3600), now: now)
    }
    try cursorFailure("auth_required") {
        _ = try CursorProvider.parseToken(cursorToken(subject: "auth0|", expiration: now.timeIntervalSince1970 + 3600), now: now)
    }
    try cursorFailure("auth_required") {
        _ = try CursorProvider.parseToken(cursorToken(subject: "user", expiration: true), now: now)
    }
    try cursorFailure("auth_required") { _ = try CursorProvider.parseToken(token + ".extra", now: now) }
    try cursorFailure("auth_required") {
        _ = try CursorProvider.parseToken(String(repeating: "A", count: 65_537), now: now)
    }
    try cursorCredentialChecks(token: token, now: now)
    try cursorQuotaChecks(now: now)
}

private func cursorToken(subject: String, expiration: Any) throws -> String {
    func segment(_ data: Data) -> String {
        data.base64EncodedString().replacingOccurrences(of: "+", with: "-")
            .replacingOccurrences(of: "/", with: "_").replacingOccurrences(of: "=", with: "")
    }
    return "eyJhbGciOiJIUzI1NiJ9." + segment(try JSONSerialization.data(withJSONObject: [
        "sub": subject, "exp": expiration, "email": "synthetic@example.invalid",
    ])) + ".c3ludGhldGljLXNpZ25hdHVyZQ"
}

private func cursorFailure(_ code: String, _ body: () throws -> Void) throws {
    do { try body() }
    catch let failure as UsageFailure { try check(failure.code == code, "Cursor failure code: " + code); return }
    try check(false, "Cursor expected failure: " + code)
}

private func cursorCredentialChecks(token: String, now: Date) throws {
    let directory = FileManager.default.temporaryDirectory.appendingPathComponent("AMG65-Cursor-checks-" + UUID().uuidString)
    try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: false)
    defer { try? FileManager.default.removeItem(at: directory) }
    let database = directory.appendingPathComponent("state.vscdb")
    var writer: OpaquePointer?
    try check(sqlite3_open(database.path, &writer) == SQLITE_OK, "Cursor fixture database")
    defer { sqlite3_close(writer) }
    func execute(_ statement: String) throws {
        try check(sqlite3_exec(writer, statement, nil, nil, nil) == SQLITE_OK, "Cursor fixture SQL")
    }
    func write(_ data: Data, blob: Bool = false) throws {
        var statement: OpaquePointer?
        try check(sqlite3_prepare_v2(writer,
            "INSERT OR REPLACE INTO ItemTable(key,value) VALUES('cursorAuth/accessToken',?)", -1, &statement, nil) == SQLITE_OK,
            "Cursor bound fixture statement")
        defer { sqlite3_finalize(statement) }
        let transient = unsafeBitCast(-1, to: sqlite3_destructor_type.self)
        let bound = data.withUnsafeBytes { bytes in
            if blob { return sqlite3_bind_blob(statement, 1, bytes.baseAddress, Int32(data.count), transient) }
            return sqlite3_bind_text(statement, 1, bytes.baseAddress?.assumingMemoryBound(to: CChar.self), Int32(data.count), transient)
        }
        try check(bound == SQLITE_OK && sqlite3_step(statement) == SQLITE_DONE, "Cursor bound fixture write")
    }
    try execute("PRAGMA journal_mode=WAL")
    try execute("PRAGMA wal_autocheckpoint=0")
    try execute("CREATE TABLE ItemTable(key TEXT PRIMARY KEY,value)")
    try write(Data("old.invalid.value".utf8))
    try execute("PRAGMA wal_checkpoint(TRUNCATE)")
    try write(Data(token.utf8))
    let wal = URL(fileURLWithPath: database.path + "-wal")
    let mainBefore = try Data(contentsOf: database)
    let walBefore = try Data(contentsOf: wal)
    try check(!walBefore.isEmpty, "Cursor active WAL fixture")
    var keychainCalls = 0
    let plain = try CursorProvider.loadSession(database: database, now: now) { _, _ in
        keychainCalls += 1; return nil
    }
    try check(plain.token == token, "Cursor reads latest uncheckpointed WAL token")
    try check(keychainCalls == 0, "Cursor plaintext bypasses Keychain")
    try check(try Data(contentsOf: database) == mainBefore, "Cursor main database not modified")
    try check(try Data(contentsOf: wal) == walBefore, "Cursor WAL not modified")

    try write(Data(token.utf16.flatMap { [UInt8($0 & 255), UInt8($0 >> 8)] }), blob: true)
    try check(try CursorProvider.readToken(database: database) == token, "Cursor UTF16LE BLOB token")
    try write(Data(token.utf8), blob: true)
    try check(try CursorProvider.readToken(database: database) == token, "Cursor UTF8 BLOB token")
    try write(Data(repeating: 65, count: 65_537))
    try cursorFailure("auth_required") { _ = try CursorProvider.readToken(database: database) }

    let password = "synthetic-safe-storage-password"
    let envelope = try cursorEncryptedToken(token, password: password)
    try write(Data(envelope.utf8))
    var accounts = [String]()
    let current = try CursorProvider.loadSession(database: database, now: now) { service, account in
        try check(service == "Cursor Safe Storage", "Cursor keychain service")
        accounts.append(account); return Data(password.utf8)
    }
    try check(current.token == token && accounts == ["Cursor Key"], "Cursor current encrypted key")
    accounts = []
    let legacy = try CursorProvider.loadSession(database: database, now: now) { _, account in
        accounts.append(account)
        return Data((account == "Cursor" ? password : "wrong-key").utf8)
    }
    try check(legacy.token == token && accounts == ["Cursor Key", "Cursor"], "Cursor legacy key fallback")
    try cursorFailure("auth_required") {
        _ = try CursorProvider.loadSession(database: database, now: now) { _, _ in Data("wrong-key".utf8) }
    }
    try cursorFailure("keychain_locked") {
        _ = try CursorProvider.loadSession(database: database, now: now) { _, _ in throw UsageFailure(code: "keychain_locked") }
    }
    for malformed in ["cursor-safe-storage:v2:AAAA", "cursor-safe-storage:v1:not-base64",
                      "cursor-safe-storage:v1:" + Data("v10short".utf8).base64EncodedString()] {
        try write(Data(malformed.utf8)); keychainCalls = 0
        try cursorFailure("auth_required") {
            _ = try CursorProvider.loadSession(database: database, now: now) { _, _ in keychainCalls += 1; return nil }
        }
        try check(keychainCalls == 0, "Cursor malformed envelope bypasses Keychain")
    }
    let expired = try cursorToken(subject: "user", expiration: now.timeIntervalSince1970 - 1)
    try write(Data(try cursorEncryptedToken(expired, password: password).utf8))
    try cursorFailure("relogin_required") {
        _ = try CursorProvider.loadSession(database: database, now: now) { _, _ in Data(password.utf8) }
    }
    try execute("DELETE FROM ItemTable")
    try cursorFailure("auth_required") {
        _ = try CursorProvider.loadSession(database: database, now: now) { _, _ in nil }
    }
}

private func cursorEncryptedToken(_ token: String, password: String) throws -> String {
    guard let key = CursorProvider.deriveKey(password: password) else { throw UsageFailure(code: "test_encrypt") }
    let input = Data(token.utf8), iv = Data(repeating: 0x20, count: kCCBlockSizeAES128)
    var output = Data(count: input.count + kCCBlockSizeAES128), count = 0
    let capacity = output.count
    let result = output.withUnsafeMutableBytes { destination in
        input.withUnsafeBytes { source in key.withUnsafeBytes { keyBytes in iv.withUnsafeBytes { ivBytes in
            CCCrypt(CCOperation(kCCEncrypt), CCAlgorithm(kCCAlgorithmAES), CCOptions(kCCOptionPKCS7Padding),
                    keyBytes.baseAddress, key.count, ivBytes.baseAddress, source.baseAddress, input.count,
                    destination.baseAddress, capacity, &count)
        } } }
    }
    try check(result == kCCSuccess, "Cursor fixture encryption")
    output.count = count
    return CursorProvider.encryptedPrefix + (Data("v10".utf8) + output).base64EncodedString()
}

private func cursorQuotaChecks(now: Date) throws {
    let start = UsageDates.iso(now.addingTimeInterval(-86400 * 10))
    let end = UsageDates.iso(now.addingTimeInterval(86400 * 20))
    func summary(_ plan: [String: Any]) -> [String: Any] {
        ["billingCycleStart": start, "billingCycleEnd": end, "individualUsage": ["plan": plan]]
    }
    let fingerprint = AccountFingerprint.make(provider: "cursor", identity: "synthetic_user-1")
    let result = try CursorProvider.parse(summary: summary([
        "totalPercentUsed": 0.36, "autoPercentUsed": 12.5, "apiPercentUsed": 35,
    ]), sand: nil, now: now, fingerprint: fingerprint)
    try check(result.usage?.primary?.usedPercent == 0.36, "Cursor percent units are not fractions")
    try check(result.usage?.secondary?.usedPercent == 12.5 && result.usage?.tertiary?.usedPercent == 35,
              "Cursor independent Auto and API windows")
    try check(result.usage?.primary?.windowMinutes == 43200 && result.usage?.primary?.resetsAt == end,
              "Cursor billing cadence and reset")
    try check(result.accountFingerprint == fingerprint, "Cursor account isolation fingerprint")
    let encoded = String(decoding: try JSONEncoder().encode(result), as: UTF8.self)
    try check(!encoded.contains("synthetic_user-1") && !encoded.contains("example.invalid") && !encoded.contains("Workos"),
              "Cursor normalized output excludes identity and credentials")
    let ratio = try CursorProvider.parse(summary: summary(["used": 250, "limit": 500]), sand: nil, now: now)
    try check(ratio.usage?.primary?.usedPercent == 50, "Cursor valid plan cap fallback")
    let overall = try CursorProvider.parse(summary: ["individualUsage": ["overall": ["used": 10, "limit": 40]]], sand: nil, now: now)
    try check(overall.usage?.primary?.usedPercent == 25, "Cursor individual overall fallback")
    let pooled = try CursorProvider.parse(summary: ["individualUsage": ["plan": ["enabled": true]],
        "teamUsage": ["pooled": ["used": 75, "limit": 100]]], sand: nil, now: now)
    try check(pooled.usage?.primary?.usedPercent == 75 && pooled.rateWindowLabels?["primary"] == "Team pool",
              "Cursor team fallback explicitly labeled")
    let lanes = try CursorProvider.parse(summary: summary(["autoPercentUsed": 20, "apiPercentUsed": 60]), sand: nil, now: now)
    try check(lanes.usage?.primary == nil, "Cursor does not average independent lane quotas")
    for invalid in [[:], ["used": 50], ["limit": 100], ["used": 1, "limit": 0],
                    ["totalPercentUsed": true], ["totalPercentUsed": -1], ["totalPercentUsed": Double.infinity]] as [[String: Any]] {
        try cursorFailure("no_usage") { _ = try CursorProvider.parse(summary: summary(invalid), sand: nil, now: now) }
    }
    let exhausted = try CursorProvider.parse(summary: summary(["totalPercentUsed": 112]), sand: nil, now: now)
    try check(exhausted.usage?.primary?.usedPercent == 112, "Cursor over-limit usage preserved")
    let weeklyEnd = UsageDates.iso(now.addingTimeInterval(86400 * 3))
    let weekly: [String: Any] = ["usagePercent": 72.2, "hasNonZeroIncludedLimit": true, "isUnified": true,
                                "currentPeriodStart": start, "nextResetTimestampUtc": weeklyEnd]
    let unified = try CursorProvider.parse(summary: summary(["totalPercentUsed": 0, "autoPercentUsed": 0]), sand: weekly, now: now)
    try check(unified.usage?.primary?.usedPercent == 72.2 && unified.usage?.primary?.windowMinutes == 10080,
              "Cursor unified weekly quota takes precedence")
    try check(unified.rateWindowLabels?["primary"] == "Weekly" && unified.usage?.secondary == nil && unified.usage?.extraRateWindows == nil,
              "Cursor unified pool not duplicated")
    for change in [["nextResetTimestampUtc": "invalid"], ["nextResetTimestampUtc": start],
                   ["currentPeriodStart": weeklyEnd], ["includedLimitZero": true], ["usagePercent": true]] as [[String: Any]] {
        let invalid = weekly.merging(change) { _, new in new }
        let fallback = try CursorProvider.parse(summary: summary(["totalPercentUsed": 31]), sand: invalid, now: now)
        try check(fallback.usage?.primary?.usedPercent == 31 && fallback.rateWindowLabels?["primary"] == "Monthly",
                  "Cursor invalid Sand retains valid monthly quota")
    }
    let numericFlag = weekly.merging(["isUnified": 1]) { _, new in new }
    try check(CursorProvider.sandWindow(numericFlag, now: now)?.unified == false, "Cursor boolean flags reject numeric lookalikes")
    let noAvailability = weekly.merging(["hasAvailableUsage": false, "usagePercent": 100]) { _, new in new }
    try check(CursorProvider.sandWindow(noAvailability, now: now)?.window.usedPercent == 100,
              "Cursor exhausted allowance remains visible")
    let trial: [String: Any] = ["includedLimitZero": true, "hasNonZeroIncludedLimit": true, "usagePercent": 50,
                               "sandTrialExpiresAt": weeklyEnd, "nextResetTimestampUtc": start]
    let trialWindow = CursorProvider.sandWindow(trial, now: now)
    try check(trialWindow?.window.usedPercent == 50 && trialWindow?.window.resetsAt == nil && trialWindow?.window.windowMinutes == nil,
              "Cursor trial expiry is not a recurring reset")
    let extra = try CursorProvider.parse(summary: summary(["totalPercentUsed": 25]), sand: trial, now: now)
    try check(extra.usage?.extraRateWindows?.first?.id == "cursor-grok-bot", "Cursor separate Grok Bot window")
    var staleReset = summary(["totalPercentUsed": 25]); staleReset["billingCycleEnd"] = start
    let stale = try CursorProvider.parse(summary: staleReset, sand: nil, now: now)
    try check(stale.usage?.primary?.resetsAt == nil, "Cursor expired billing reset stays unknown")
}
