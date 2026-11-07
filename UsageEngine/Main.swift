import Foundation

@main struct UsageMain {
    static func main() async {
        let arguments=Array(CommandLine.arguments.dropFirst())
        let selected:String
        if arguments.isEmpty { selected="all" }
        else if arguments.count==2,arguments[0]=="--provider" { selected=arguments[1] }
        else { emit([.failure("unknown",code:"invalid_arguments")]); return }
        guard ["all","claude","cursor","codex"].contains(selected) else {
            emit([.failure("unknown",code:"invalid_arguments")]); return
        }
        let providers=selected=="all" ? ["claude","cursor","codex"]:[selected]
        let now=Date()
        let context=FetchContext(http:UsageHTTPClient(),home:FileManager.default.homeDirectoryForCurrentUser,
            environment:ProcessInfo.processInfo.environment,now:now,deadline:now.addingTimeInterval(18))
        enum Event:Sendable { case result(ProviderResult), deadline }
        let results=await withTaskGroup(of:Event.self,returning:[ProviderResult].self) { group in
            for provider in providers {
                group.addTask {
                    switch provider {
                    case "codex":return .result(await CodexProvider.fetch(context:context))
                    case "claude":return .result(await ClaudeProvider.fetch(context:context))
                    default:return .result(await CursorProvider.fetch(context:context))
                    }
                }
            }
            group.addTask {
                try? await Task.sleep(nanoseconds:18_000_000_000)
                return .deadline
            }
            var results=[String:ProviderResult]()
            while let event=await group.next() {
                if case let .result(result)=event { results[result.provider]=result }
                else { break }
                if results.count==providers.count { break }
            }
            group.cancelAll()
            return providers.map { results[$0] ?? .failure($0,code:"timeout") }
        }
        emit(results)
    }
    static func emit(_ results:[ProviderResult]) {
        let encoder=JSONEncoder(); encoder.outputFormatting=[.sortedKeys,.withoutEscapingSlashes]
        guard let data=try? encoder.encode(results) else { print("[]"); return }
        FileHandle.standardOutput.write(data); FileHandle.standardOutput.write(Data([10]))
    }
}
