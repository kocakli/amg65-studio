import Foundation
import Combine

/// Local, framework-independent catalogs. Stored diagnostic strings are translated
/// when rendered, so changing language also updates previously reported results.
final class LocalizationCatalog {
    static let codes = ["tr","en","es","zh-Hans","ja"]
    private(set) var tables:[String:[String:String]] = [:]
    private var templates:[(key:String,regex:NSRegularExpression,indices:[Int])] = []

    init(directory:URL?) {
        if let directory {
            for code in Self.codes {
                if let data=try? Data(contentsOf:directory.appendingPathComponent(code+".json")),
                   let table=try? JSONDecoder().decode([String:String].self,from:data) { tables[code]=table }
            }
        }
        let placeholder=try! NSRegularExpression(pattern:#"\{(\d+)\}"#)
        for key in (tables["tr"] ?? [:]).keys.sorted(by:{$0.count > $1.count}) {
            let string=key as NSString
            let matches=placeholder.matches(in:key,range:NSRange(location:0,length:string.length))
            guard !matches.isEmpty else { continue }
            var pattern="^",cursor=0,indices=[Int]()
            for match in matches {
                pattern += NSRegularExpression.escapedPattern(for:string.substring(with:NSRange(location:cursor,length:match.range.location-cursor)))
                pattern += "(.+?)"; cursor=NSMaxRange(match.range)
                indices.append(Int(string.substring(with:match.range(at:1)))!)
            }
            pattern += NSRegularExpression.escapedPattern(for:string.substring(from:cursor))+"$"
            if let regex=try? NSRegularExpression(pattern:pattern,options:.dotMatchesLineSeparators) { templates.append((key,regex,indices)) }
        }
    }

    static func bundled()->LocalizationCatalog {
        if let root=Bundle.main.resourceURL?.appendingPathComponent("localizations"),
           FileManager.default.fileExists(atPath:root.appendingPathComponent("tr.json").path) { return LocalizationCatalog(directory:root) }
        #if SWIFT_PACKAGE
        return LocalizationCatalog(directory:Bundle.module.resourceURL?.appendingPathComponent("localizations"))
        #else
        return LocalizationCatalog(directory:nil)
        #endif
    }

    func text(_ source:String,language:String,depth:Int=0)->String {
        let table=tables[language] ?? tables["en"] ?? [:]
        if let translated=table[source] { return translated }
        guard depth < 3 else { return source }
        let raw=source as NSString,range=NSRange(location:0,length:(source as NSString).length)
        for item in templates {
            guard let match=item.regex.firstMatch(in:source,range:range) else { continue }
            var arguments=[Int:String]()
            for (position,index) in item.indices.enumerated() {
                let argument=raw.substring(with:match.range(at:position+1))
                arguments[index]=text(argument,language:language,depth:depth+1)
            }
            return substitute(table[item.key] ?? item.key,arguments:arguments)
        }
        return source
    }

    func format(_ source:String,arguments:[String],language:String)->String {
        substitute(text(source,language:language),arguments:Dictionary(uniqueKeysWithValues:arguments.enumerated().map { ($0.offset,$0.element) }))
    }

    private func substitute(_ template:String,arguments:[Int:String])->String {
        let expression=try! NSRegularExpression(pattern:#"\{(\d+)\}"#)
        let value=NSMutableString(string:template)
        let matches=expression.matches(in:template,range:NSRange(location:0,length:value.length))
        for match in matches.reversed() {
            let index=Int((template as NSString).substring(with:match.range(at:1)))!
            if let argument=arguments[index] { value.replaceCharacters(in:match.range,with:argument) }
        }
        return value as String
    }
}

final class StudioLanguage:ObservableObject {
    static let shared=StudioLanguage()
    static let choices=["system","tr","en","es","zh-Hans","ja"]
    static let names=["tr":"Türkçe","en":"English","es":"Español","zh-Hans":"简体中文","ja":"日本語"]
    private let defaults:UserDefaults
    let catalog:LocalizationCatalog
    @Published var selection:String { didSet {
        guard Self.choices.contains(selection) else { selection="tr"; return }
        defaults.set(selection,forKey:"studioLanguage")
    } }
    private var localeObserver:NSObjectProtocol?
    var resolved:String { selection == "system" ? Self.resolve(Locale.preferredLanguages) : selection }
    var locale:Locale { Locale(identifier:resolved) }
    var dashboardURL:URL { URL(string:"http://127.0.0.1:47866/#native&lang=\(resolved)")! }

    init(defaults:UserDefaults = .standard,catalog:LocalizationCatalog = .bundled()) {
        self.defaults=defaults; self.catalog=catalog
        let stored=defaults.string(forKey:"studioLanguage") ?? "tr"
        selection=Self.choices.contains(stored) ? stored:"tr"
        localeObserver=NotificationCenter.default.addObserver(forName:NSLocale.currentLocaleDidChangeNotification,object:nil,queue:.main) { [weak self] _ in
            self?.objectWillChange.send()
        }
    }
    deinit { if let localeObserver { NotificationCenter.default.removeObserver(localeObserver) } }
    static func resolve(_ preferred:[String])->String {
        for identifier in preferred {
            let base=identifier.lowercased().replacingOccurrences(of:"_",with:"-").split(separator:"-").first.map(String.init) ?? ""
            if base == "zh" { return "zh-Hans" }
            if ["tr","en","es","ja"].contains(base) { return base }
        }
        return "en"
    }
}

func L(_ source:String,_ arguments:String...)->String {
    let language=StudioLanguage.shared
    return arguments.isEmpty ? language.catalog.text(source,language:language.resolved)
        : language.catalog.format(source,arguments:arguments,language:language.resolved)
}
