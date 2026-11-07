import AppKit

/// SwiftUI owns the app commands; AppKit owns their standard menu titles. Update
/// the app-owned standard actions by selector without restarting the application.
@MainActor enum StudioMenuLocalization {
    private static var observers=[NSObjectProtocol]()
    private static var pending:DispatchWorkItem?
    private static var applying=false

    static func start() {
        guard observers.isEmpty else { refresh(); return }
        let center=NotificationCenter.default
        for name in [NSApplication.didBecomeActiveNotification,NSWindow.didBecomeKeyNotification,
                     NSMenu.didAddItemNotification,NSMenu.didChangeItemNotification] {
            observers.append(center.addObserver(forName:name,object:nil,queue:.main) { _ in
                MainActor.assumeIsolated { if !applying { refresh() } }
            })
        }
        observers.append(center.addObserver(forName:NSMenu.didBeginTrackingNotification,object:nil,queue:.main) { _ in
            MainActor.assumeIsolated { apply() }
        })
        refresh()
    }

    static func refresh() {
        apply()
        pending?.cancel()
        let work=DispatchWorkItem { MainActor.assumeIsolated { apply() } }
        pending=work
        DispatchQueue.main.asyncAfter(deadline:.now()+0.2,execute:work)
    }

    private static func apply() {
        guard !applying,let main=NSApp.mainMenu else { return }
        applying=true; defer { applying=false }
        func setTitle(_ item:NSMenuItem,_ title:String) { if item.title != title { item.title=title } }
        func translatedKey(_ title:String,keys:[String])->String? {
            keys.first { key in
                title == key || StudioLanguage.shared.catalog.tables.values.contains { $0[key] == title }
            }
        }
        let actions:[String:String] = [
            "orderFrontStandardAboutPanel:":"About AMG65 Studio", "hide:":"Hide AMG65 Studio",
            "hideOtherApplications:":"Hide Others", "unhideAllApplications:":"Show All",
            "terminate:":"Quit AMG65 Studio", "performClose:":"Close Window",
            "undo:":"Undo", "redo:":"Redo", "cut:":"Cut", "copy:":"Copy",
            "paste:":"Paste", "pasteAsPlainText:":"Paste and Match Style", "selectAll:":"Select All",
            "delete:":"Delete", "performMiniaturize:":"Minimize", "performZoom:":"Zoom",
            "arrangeInFront:":"Bring All to Front"
        ]
        func selectors(_ menu:NSMenu)->Set<String> {
            Set(menu.items.compactMap{$0.action.map(NSStringFromSelector)}).union(menu.items.compactMap(\.submenu).reduce(into:Set<String>()){$0.formUnion(selectors($1))})
        }
        func walk(_ menu:NSMenu) {
            for item in menu.items {
                if let action=item.action {
                    let name=NSStringFromSelector(action)
                    if let key=actions[name] { setTitle(item,L(key)) }
                    if name == "toggleFullScreen:" {
                        setTitle(item,L(NSApp.keyWindow?.styleMask.contains(.fullScreen) == true ? "Exit Full Screen":"Enter Full Screen"))
                    }
                }
                if let key=translatedKey(item.title,keys:Array(actions.values)+["Enter Full Screen","Exit Full Screen"]) { setTitle(item,L(key)) }
                if let submenu=item.submenu {
                    if submenu === NSApp.servicesMenu { setTitle(item,L("Services")); if submenu.title != item.title { submenu.title=item.title } }
                    else { walk(submenu) }
                }
            }
        }
        for (index,item) in main.items.enumerated() {
            guard let menu=item.submenu else { continue }
            let names=selectors(menu)
            if index > 0 {
                let key:String?
                if names.contains("performMiniaturize:") { key="Window" }
                else if names.contains("copy:") || names.contains("paste:") { key="Edit" }
                else if names.contains("performClose:") { key="File" }
                else if names.contains("toggleFullScreen:") { key="View" }
                else if names.contains("showHelp:") { key="Help" }
                else { key=translatedKey(item.title,keys:["File","Edit","View","Window","Help"]) }
                if let key { setTitle(item,L(key)); if menu.title != item.title { menu.title=item.title } }
            }
            walk(menu)
        }
    }
}
