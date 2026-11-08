import Foundation
import Security
import LocalAuthentication
import Darwin

enum KeychainAccess:String { case granted,denied,missing,failed }

enum CredentialReader {
    static func file(_ url:URL)throws->Data? {
        let descriptor=open(url.path,O_RDONLY|O_NOFOLLOW|O_NONBLOCK)
        guard descriptor>=0 else {
            if errno==ENOENT { return nil }
            throw UsageFailure(code:"credentials_unreadable")
        }
        defer { close(descriptor) }
        var info=stat()
        guard fstat(descriptor,&info)==0,info.st_uid==getuid(),
              (info.st_mode & S_IFMT)==S_IFREG,info.st_size<=1_048_576 else {
            throw UsageFailure(code:"credentials_unreadable")
        }
        var data=Data(),buffer=[UInt8](repeating:0,count:8192)
        while true {
            let count=read(descriptor,&buffer,buffer.count)
            if count==0 { break }
            if count<0 {
                if errno==EINTR { continue }
                throw UsageFailure(code:"credentials_unreadable")
            }
            guard data.count+count<=1_048_576 else { throw UsageFailure(code:"credentials_unreadable") }
            data.append(contentsOf:buffer.prefix(count))
        }
        return data
    }
    /// Never launches `security` or an authentication prompt in the background.
    static func keychain(service:String,account:String?)throws->Data? {
        // The query's LAContext and UI flags only govern data-protection items. These
        // records live in the file-based login keychain, whose ACL dialog ignores both,
        // so this process-wide switch is what actually forbids the password prompt.
        guard SecKeychainSetUserInteractionAllowed(false)==errSecSuccess else { throw UsageFailure(code:"keychain_locked") }
        let query=keychainQuery(service:service,account:account)
        var item:CFTypeRef?
        let status=SecItemCopyMatching(query as CFDictionary,&item)
        if status==errSecItemNotFound { return nil }
        guard status==errSecSuccess else { throw UsageFailure(code:"keychain_locked") }
        guard let data=item as? Data,data.count<=1_048_576 else { throw UsageFailure(code:"credentials_unreadable") }
        return data
    }
    static func keychainQuery(service:String,account:String?)->[String:Any] {
        let context=LAContext(); context.interactionNotAllowed=true
        var query:[String:Any]=[
            kSecClass as String:kSecClassGenericPassword,
            kSecAttrService as String:service,
            kSecMatchLimit as String:kSecMatchLimitOne,
            kSecReturnData as String:true,
            kSecUseAuthenticationContext as String:context,
            kSecUseAuthenticationUI as String:kSecUseAuthenticationUIFail,
        ]
        if let account { query[kSecAttrAccount as String]=account }
        return query
    }
    /// The only path allowed to show macOS's dialog. Only an explicit user action in the
    /// native app starts it. The secret is read to satisfy the ACL, then discarded unseen.
    static func requestKeychainAccess(provider:String)->KeychainAccess {
        guard let target=keychainAccessTarget(provider:provider),
              SecKeychainSetUserInteractionAllowed(true)==errSecSuccess else { return .failed }
        for account in target.accounts {
            var item:CFTypeRef?
            switch SecItemCopyMatching(keychainAccessQuery(service:target.service,account:account) as CFDictionary,&item) {
            case errSecSuccess:return .granted
            case errSecItemNotFound:continue
            case errSecUserCanceled,errSecAuthFailed:return .denied
            default:return .failed
            }
        }
        return .missing
    }
    /// The records each provider's reader opens, in the order it opens them.
    static func keychainAccessTarget(provider:String)->(service:String,accounts:[String?])? {
        switch provider {
        case "claude":return ("Claude Code-credentials",[nil])
        case "cursor":return ("Cursor Safe Storage",["Cursor Key","Cursor"])
        default:return nil
        }
    }
    static func keychainAccessQuery(service:String,account:String?)->[String:Any] {
        // Asking for the data, not just its attributes, is what triggers the ACL check.
        var query:[String:Any]=[kSecClass as String:kSecClassGenericPassword,
                                kSecAttrService as String:service,
                                kSecMatchLimit as String:kSecMatchLimitOne,
                                kSecReturnData as String:true]
        if let account { query[kSecAttrAccount as String]=account }
        return query
    }
    static func directory(_ value:String?,fallback:URL)throws->URL {
        guard let value,!value.isEmpty else { return fallback }
        // Never silently borrow the default account for an unsupported profile path.
        guard value.hasPrefix("/") else { throw UsageFailure(code:"invalid_credentials") }
        return URL(fileURLWithPath:value,isDirectory:true)
    }
}
