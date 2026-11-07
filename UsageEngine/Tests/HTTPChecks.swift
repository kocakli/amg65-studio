import Foundation

/// Intercepts every request inside URLSession; it never opens a socket.
private final class FixtureURLProtocol:URLProtocol,@unchecked Sendable {
    override class func canInit(with request:URLRequest)->Bool { true }
    override class func canonicalRequest(for request:URLRequest)->URLRequest { request }
    override func startLoading() {
        let path=request.url!.lastPathComponent
        let status=Int(path) ?? 200
        let body=path=="overflow" ? Data(repeating:65,count:UsageHTTPClient.maximumBytes+1):Data("{\"ok\":true}".utf8)
        let headers=path=="oversized" ? ["Content-Length":String(UsageHTTPClient.maximumBytes+1)]:[:]
        let response=HTTPURLResponse(url:request.url!,statusCode:status,httpVersion:"HTTP/1.1",headerFields:headers)!
        client?.urlProtocol(self,didReceive:response,cacheStoragePolicy:.notAllowed)
        client?.urlProtocol(self,didLoad:body)
        client?.urlProtocolDidFinishLoading(self)
    }
    override func stopLoading() {}
}

func httpChecks() async throws {
    let configuration=URLSessionConfiguration.ephemeral
    configuration.protocolClasses=[FixtureURLProtocol.self]
    let client=UsageHTTPClient(configuration:configuration)
    let deadline=Date().addingTimeInterval(18)
    let body=try await client.get(url:URL(string:"https://cursor.com/fixture/ok")!,headers:[:],deadline:deadline)
    try check((try JSONValue.object(body))["ok"] as? Bool==true,"Actual HTTP client accepts bounded JSON fixture")
    for (path,code) in [("401","auth_required"),("403","access_denied"),("429","rate_limited"),
                        ("302","network_error"),("oversized","invalid_response"),("overflow","invalid_response")] {
        do {
            _=try await client.get(url:URL(string:"https://cursor.com/fixture/"+path)!,headers:[:],deadline:deadline)
            throw CheckFailure(name:"HTTP fixture unexpectedly accepted "+path)
        } catch let error as UsageFailure { try check(error.code==code,"HTTP response bound/status "+path) }
    }
    do {
        _=try await client.get(url:URL(string:"https://cursor.com/fixture/ok")!,headers:[:],deadline:Date.distantPast)
        throw CheckFailure(name:"Expired HTTP deadline accepted")
    } catch let error as UsageFailure { try check(error.code=="timeout","HTTP deadline checked before request") }
}
