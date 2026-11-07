import Foundation

private final class NoRedirects:NSObject,URLSessionTaskDelegate,Sendable {
    func urlSession(_ session:URLSession,task:URLSessionTask,willPerformHTTPRedirection response:HTTPURLResponse,
                    newRequest request:URLRequest,completionHandler:@escaping(URLRequest?)->Void) {
        completionHandler(nil)
    }
}

final class UsageHTTPClient: @unchecked Sendable {
    static let maximumBytes=1_048_576
    private let session:URLSession
    private let redirects=NoRedirects()
    init(configuration:URLSessionConfiguration = .ephemeral) {
        configuration.timeoutIntervalForRequest=10
        configuration.timeoutIntervalForResource=18
        configuration.urlCache=nil; configuration.httpCookieStorage=nil
        configuration.httpShouldSetCookies=false
        configuration.requestCachePolicy = .reloadIgnoringLocalCacheData
        session=URLSession(configuration:configuration,delegate:redirects,delegateQueue:nil)
    }
    static func allowed(_ url:URL)->Bool {
        url.scheme=="https" && ["chatgpt.com","api.anthropic.com","cursor.com"].contains(url.host ?? "")
            && (url.port==nil || url.port==443) && url.user==nil && url.password==nil && url.fragment==nil
    }
    func get(url:URL,headers:[String:String],deadline:Date) async throws->Data {
        try await request(url:url,method:"GET",headers:headers,body:nil,deadline:deadline)
    }
    func post(url:URL,headers:[String:String],body:Data,deadline:Date) async throws->Data {
        try await request(url:url,method:"POST",headers:headers,body:body,deadline:deadline)
    }
    private func request(url:URL,method:String,headers:[String:String],body:Data?,deadline:Date) async throws->Data {
        guard Self.allowed(url) else { throw UsageFailure(code:"invalid_endpoint") }
        let remaining=deadline.timeIntervalSinceNow
        guard remaining>0 else { throw UsageFailure(code:"timeout") }
        var request=URLRequest(url:url,cachePolicy:.reloadIgnoringLocalCacheData,timeoutInterval:min(10,remaining))
        request.httpMethod=method; request.httpBody=body
        request.setValue("application/json",forHTTPHeaderField:"Accept")
        request.setValue("AMG65Studio/0.3",forHTTPHeaderField:"User-Agent")
        for (name,value) in headers {
            guard !value.contains("\r"),!value.contains("\n"),name.lowercased() != "host" else {
                throw UsageFailure(code:"invalid_credentials")
            }
            request.setValue(value,forHTTPHeaderField:name)
        }
        do {
            let (bytes,response)=try await session.bytes(for:request)
            defer { bytes.task.cancel() }
            guard let response=response as? HTTPURLResponse else { throw UsageFailure(code:"invalid_response") }
            switch response.statusCode {
            case 200...299:break
            case 401:throw UsageFailure(code:"auth_required")
            case 403:throw UsageFailure(code:"access_denied")
            case 429:throw UsageFailure(code:"rate_limited")
            default:throw UsageFailure(code:"network_error")
            }
            if response.expectedContentLength>Int64(Self.maximumBytes) { throw UsageFailure(code:"invalid_response") }
            var data=Data()
            for try await byte in bytes {
                if data.count % 4096 == 0 {
                    try Task.checkCancellation()
                    guard Date()<deadline else { throw UsageFailure(code:"timeout") }
                }
                guard data.count<Self.maximumBytes else { throw UsageFailure(code:"invalid_response") }
                data.append(byte)
            }
            return data
        } catch let failure as UsageFailure { throw failure }
        catch let error as URLError where error.code == .timedOut || error.code == .cancelled { throw UsageFailure(code:"timeout") }
        catch is CancellationError { throw UsageFailure(code:"timeout") }
        catch { throw UsageFailure(code:"network_error") }
    }
}
