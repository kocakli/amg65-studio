// Cursor session and quota protocol adapted from CodexBar (MIT), commit
// 53f9e1e24d28b0d7f451449b4a25d0e076ea5bc9. See UsageEngine/NOTICE.md.
// Credentials stay in memory; only normalized usage leaves this provider.
import Foundation
import CoreFoundation
import CommonCrypto
import SQLite3

enum CursorProvider {
    static let maximumTokenBytes = 65_536
    static let encryptedPrefix = "cursor-safe-storage:v1:"

    struct Session {
        let token: String
        let userID: String
        let expiresAt: Date

        var cookieHeader: String {
            "WorkosCursorSessionToken=\(userID)%3A%3A\(token)"
        }
    }

    static func fetch(context: FetchContext) async -> ProviderResult {
        var fingerprint: String?
        do {
            let database = context.home.appendingPathComponent(
                "Library/Application Support/Cursor/User/globalStorage/state.vscdb")
            let session = try loadSession(database: database, now: context.now) { service, account in
                try CredentialReader.keychain(service: service, account: account)
            }
            fingerprint = AccountFingerprint.make(provider: "cursor", identity: session.userID)
            let headers = ["Accept": "application/json", "Cookie": session.cookieHeader]
            async let summaryData = context.http.get(
                url: URL(string: "https://cursor.com/api/usage-summary")!,
                headers: headers, deadline: context.deadline)
            async let sandData = optionalSand(context: context, headers: headers)
            let summary = try JSONValue.object(await summaryData)
            let optionalSandData = await sandData
            let sand = optionalSandData.flatMap { try? JSONValue.object($0) }
            return try parse(summary: summary, sand: sand, now: context.now, fingerprint: fingerprint)
        } catch let error as UsageFailure {
            return .failure("cursor", code: error.code, fingerprint: fingerprint)
        } catch is CancellationError {
            return .failure("cursor", code: "timeout", fingerprint: fingerprint)
        } catch {
            return .failure("cursor", code: "invalid_response", fingerprint: fingerprint)
        }
    }

    private static func optionalSand(context: FetchContext, headers: [String: String]) async -> Data? {
        var headers = headers
        headers["Content-Type"] = "application/json"
        headers["Origin"] = "https://cursor.com"
        return try? await context.http.post(
            url: URL(string: "https://cursor.com/api/dashboard/get-sand-usage-status")!,
            headers: headers, body: Data("{}".utf8),
            deadline: min(context.deadline, Date().addingTimeInterval(5)))
    }

    // MARK: Local credentials

    static func loadSession(
        database: URL, now: Date,
        keychain: (_ service: String, _ account: String) throws -> Data?) throws -> Session
    {
        guard FileManager.default.fileExists(atPath: database.path),
              let stored = try readToken(database: database), !stored.isEmpty
        else { throw UsageFailure(code: "auth_required") }

        if !stored.hasPrefix("cursor-safe-storage:") {
            return try parseToken(stored, now: now)
        }
        guard stored.hasPrefix(encryptedPrefix),
              let encrypted = Data(base64Encoded: String(stored.dropFirst(encryptedPrefix.count))),
              encrypted.starts(with: Data("v10".utf8)), encrypted.count > 3,
              (encrypted.count - 3).isMultiple(of: kCCBlockSizeAES128)
        else { throw UsageFailure(code: "auth_required") }

        // CredentialReader is strictly noninteractive. A locked/denied item
        // never creates a background authorization prompt or a shell command.
        for account in ["Cursor Key", "Cursor"] {
            guard let secret = try keychain("Cursor Safe Storage", account),
                  secret.count <= maximumTokenBytes,
                  let password = String(data: secret, encoding: .utf8),
                  let decoded = decrypt(encrypted, password: password),
                  let token = String(data: decoded, encoding: .utf8)
            else { continue }
            do {
                return try parseToken(token, now: now)
            } catch let error as UsageFailure where error.code == "relogin_required" {
                throw error
            } catch {
                // A mismatched current key must not hide a usable legacy key.
                continue
            }
        }
        throw UsageFailure(code: "auth_required")
    }

    static func parseToken(_ token: String, now: Date) throws -> Session {
        guard !token.isEmpty, token.utf8.count <= maximumTokenBytes else {
            throw UsageFailure(code: "auth_required")
        }
        let segments = token.split(separator: ".", omittingEmptySubsequences: false)
        guard segments.count == 3, segments.allSatisfy({ !$0.isEmpty }),
              segments.allSatisfy({ $0.utf8.allSatisfy(isBase64URL) })
        else { throw UsageFailure(code: "auth_required") }
        var encoded = String(segments[1]).replacingOccurrences(of: "-", with: "+")
            .replacingOccurrences(of: "_", with: "/")
        encoded += String(repeating: "=", count: (4 - encoded.count % 4) % 4)
        guard let payload = Data(base64Encoded: encoded), payload.count <= maximumTokenBytes,
              let claims = try? JSONSerialization.jsonObject(with: payload) as? [String: Any],
              let subject = claims["sub"] as? String,
              let userID = subject.split(separator: "|", omittingEmptySubsequences: false).last,
              !userID.isEmpty, userID.utf8.count <= 512,
              userID.utf8.allSatisfy({ isBase64URL($0) || $0 == 46 }),
              let expiration = JSONValue.number(claims["exp"])
        else { throw UsageFailure(code: "auth_required") }
        let expiresAt = Date(timeIntervalSince1970: expiration)
        guard expiresAt.timeIntervalSince(now) > 60 else {
            throw UsageFailure(code: "relogin_required")
        }
        // JWT claims select the cookie identity; the HTTPS service validates
        // the token. Local decoding does not assert signature authenticity.
        return Session(token: token, userID: String(userID), expiresAt: expiresAt)
    }

    private static func isBase64URL(_ byte: UInt8) -> Bool {
        (65...90).contains(byte) || (97...122).contains(byte) || (48...57).contains(byte)
            || byte == 45 || byte == 95
    }

    struct SQLiteFailure: Error { let code: Int32 }

    static func readToken(database: URL) throws -> String? {
        do {
            return try readToken(database: database, immutable: false)
        } catch let failure as SQLiteFailure {
            let missingSidecars = !FileManager.default.fileExists(atPath: database.path + "-wal")
                && !FileManager.default.fileExists(atPath: database.path + "-shm")
            guard failure.code == SQLITE_CANTOPEN, missingSidecars else {
                // Cursor holding a write lock says nothing about the sign-in; keep the last quota.
                throw UsageFailure(code: [SQLITE_BUSY, SQLITE_LOCKED, SQLITE_IOERR].contains(failure.code & 0xff) ? "timeout" : "auth_required")
            }
            // Immutable mode would ignore uncheckpointed state in an active WAL.
            // It is used only for an idle main file with no sidecars.
            do { return try readToken(database: database, immutable: true) }
            catch { throw UsageFailure(code: "auth_required") }
        }
    }

    private static func readToken(database: URL, immutable: Bool) throws -> String? {
        var db: OpaquePointer?
        let name = immutable ? database.absoluteURL.absoluteString + "?immutable=1" : database.path
        let flags = SQLITE_OPEN_READONLY | (immutable ? SQLITE_OPEN_URI : 0)
        let result = sqlite3_open_v2(name, &db, flags, nil)
        defer { sqlite3_close(db) }
        guard result == SQLITE_OK else { throw SQLiteFailure(code: result) }
        sqlite3_busy_timeout(db, 250)
        var statement: OpaquePointer?
        let query = "SELECT value FROM ItemTable WHERE key = 'cursorAuth/accessToken' LIMIT 1"
        let prepared = sqlite3_prepare_v2(db, query, -1, &statement, nil)
        defer { sqlite3_finalize(statement) }
        guard prepared == SQLITE_OK else { throw SQLiteFailure(code: prepared) }
        let step = sqlite3_step(statement)
        if step == SQLITE_DONE { return nil }
        guard step == SQLITE_ROW else { throw SQLiteFailure(code: step) }
        let kind = sqlite3_column_type(statement, 0)
        guard kind == SQLITE_TEXT || kind == SQLITE_BLOB else { return nil }
        let count = Int(sqlite3_column_bytes(statement, 0))
        guard count <= maximumTokenBytes else { throw UsageFailure(code: "auth_required") }
        if count == 0 { return "" }
        guard let bytes = sqlite3_column_blob(statement, 0) else { return nil }
        return decodeSQLiteToken(Data(bytes: bytes, count: count), isBlob: kind == SQLITE_BLOB)
    }

    static func decodeSQLiteToken(_ data: Data, isBlob: Bool) -> String? {
        if isBlob, data.count.isMultiple(of: 2), !data.isEmpty,
           stride(from: 0, to: data.count, by: 2).allSatisfy({
               (1..<128).contains(data[$0]) && data[$0 + 1] == 0
           })
        {
            return String(data: data, encoding: .utf16LittleEndian)
        }
        return String(data: data, encoding: .utf8)
            ?? (isBlob ? String(data: data, encoding: .utf16LittleEndian) : nil)
    }

    static func deriveKey(password: String) -> Data? {
        let password = Data(password.utf8), salt = Data("saltysalt".utf8)
        var key = Data(count: kCCKeySizeAES128)
        let status = key.withUnsafeMutableBytes { keyBytes in
            password.withUnsafeBytes { passwordBytes in
                salt.withUnsafeBytes { saltBytes in
                    CCKeyDerivationPBKDF(CCPBKDFAlgorithm(kCCPBKDF2),
                        passwordBytes.bindMemory(to: Int8.self).baseAddress, password.count,
                        saltBytes.bindMemory(to: UInt8.self).baseAddress, salt.count,
                        CCPseudoRandomAlgorithm(kCCPRFHmacAlgSHA1), 1003,
                        keyBytes.bindMemory(to: UInt8.self).baseAddress, kCCKeySizeAES128)
                }
            }
        }
        return status == kCCSuccess ? key : nil
    }

    static func decrypt(_ encrypted: Data, password: String) -> Data? {
        guard encrypted.count > 3, encrypted.count <= maximumTokenBytes,
              encrypted.starts(with: Data("v10".utf8)),
              (encrypted.count - 3).isMultiple(of: kCCBlockSizeAES128),
              let key = deriveKey(password: password)
        else { return nil }
        let payload = Data(encrypted.dropFirst(3))
        let iv = Data(repeating: 0x20, count: kCCBlockSizeAES128)
        var output = Data(count: payload.count + kCCBlockSizeAES128), count = 0
        let capacity = output.count
        let result = output.withUnsafeMutableBytes { outputBytes in
            payload.withUnsafeBytes { inputBytes in
                key.withUnsafeBytes { keyBytes in
                    iv.withUnsafeBytes { ivBytes in
                        CCCrypt(CCOperation(kCCDecrypt), CCAlgorithm(kCCAlgorithmAES),
                            CCOptions(kCCOptionPKCS7Padding), keyBytes.baseAddress, key.count,
                            ivBytes.baseAddress, inputBytes.baseAddress, payload.count,
                            outputBytes.baseAddress, capacity, &count)
                    }
                }
            }
        }
        guard result == kCCSuccess else { return nil }
        output.count = count
        return output
    }

    // MARK: Quota decoding

    static func parse(summary: [String: Any], sand: [String: Any]?, now: Date,
                      fingerprint: String? = nil) throws -> ProviderResult {
        let individual = summary["individualUsage"] as? [String: Any] ?? [:]
        let plan = individual["plan"] as? [String: Any] ?? [:]
        let overall = individual["overall"] as? [String: Any] ?? [:]
        let team = summary["teamUsage"] as? [String: Any] ?? [:]
        let pooled = team["pooled"] as? [String: Any] ?? [:]
        let start = UsageDates.date(summary["billingCycleStart"] as? String)
        let end = UsageDates.date(summary["billingCycleEnd"] as? String)
        let windowMinutes: Double? = if let start, let end, end > start {
            end.timeIntervalSince(start) / 60
        } else { nil }
        let reset = end.flatMap { $0 > now ? UsageDates.iso($0) : nil }
        var labels: [String: String] = [:]
        var primary: UsageWindow?
        let personalTotal = nonnegative(plan["totalPercentUsed"]) ?? ratio(plan) ?? ratio(overall)
        let total = personalTotal ?? ratio(pooled)
        if let total {
            primary = UsageWindow(usedPercent: total, windowMinutes: windowMinutes, resetsAt: reset)
            labels["primary"] = personalTotal == nil ? "Team pool" : "Monthly"
        }
        let auto = nonnegative(plan["autoPercentUsed"]).map {
            UsageWindow(usedPercent: $0, windowMinutes: windowMinutes, resetsAt: reset)
        }
        let api = nonnegative(plan["apiPercentUsed"]).map {
            UsageWindow(usedPercent: $0, windowMinutes: windowMinutes, resetsAt: reset)
        }
        if auto != nil { labels["secondary"] = "Auto" }
        if api != nil { labels["tertiary"] = "API" }
        let sandResult = sand.flatMap { sandWindow($0, now: now) }
        if let sandResult, sandResult.unified {
            return .success("cursor", usage: UsageData(updatedAt: UsageDates.iso(now),
                primary: sandResult.window), labels: ["primary": "Weekly"], fingerprint: fingerprint)
        }
        guard primary != nil || auto != nil || api != nil || sandResult != nil else {
            throw UsageFailure(code: "no_usage")
        }
        let extras = sandResult.map { [ExtraRateWindow(id: "cursor-grok-bot", title: "Grok Bot",
            usageKnown: true, window: $0.window)] }
        return .success("cursor", usage: UsageData(updatedAt: UsageDates.iso(now), primary: primary,
            secondary: auto, tertiary: api, extraRateWindows: extras), labels: labels, fingerprint: fingerprint)
    }

    private static func nonnegative(_ value: Any?) -> Double? {
        guard let number = JSONValue.number(value), number >= 0 else { return nil }
        return number
    }

    private static func ratio(_ object: [String: Any]) -> Double? {
        guard let used = nonnegative(object["used"]), let limit = nonnegative(object["limit"]), limit > 0 else {
            return nil
        }
        let result = used / limit * 100
        return result.isFinite ? result : nil
    }

    private static func boolean(_ value: Any?) -> Bool? {
        guard let value = value as? NSNumber, CFGetTypeID(value) == CFBooleanGetTypeID() else { return nil }
        return value.boolValue
    }

    static func sandWindow(_ value: [String: Any], now: Date) -> (window: UsageWindow, unified: Bool)? {
        guard let used = nonnegative(value["usagePercent"]) else { return nil }
        let hasLimit = boolean(value["includedLimitZero"]).map { !$0 }
            ?? boolean(value["hasNonZeroIncludedLimit"]) ?? false
        let trialEnd = UsageDates.date(value["sandTrialExpiresAt"] as? String)
        let trial = !hasLimit && trialEnd.map { $0 > now } == true
        guard hasLimit || trial else { return nil }
        let unified = boolean(value["isUnified"]) == true
        let reset = UsageDates.date(value["nextResetTimestampUtc"] as? String)
        if !trial, let rawStart = value["currentPeriodStart"] as? String {
            guard let start = UsageDates.date(rawStart), start <= now,
                  reset.map({ $0 > start }) ?? true else { return nil }
        }
        if !trial, let reset, reset <= now { return nil }
        if unified {
            guard hasLimit, !trial, let reset, reset > now else { return nil }
            return (UsageWindow(usedPercent: used, windowMinutes: 10080,
                resetsAt: UsageDates.iso(reset)), true)
        }
        // Trial expiration is not a recurring reset. Missing reset stays unknown.
        return (UsageWindow(usedPercent: used, windowMinutes: !trial && reset != nil ? 10080 : nil,
            resetsAt: trial ? nil : reset.map(UsageDates.iso)), false)
    }
}
