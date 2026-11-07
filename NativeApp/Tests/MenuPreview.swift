import SwiftUI
import AppKit

/// Fixture-only render; not a representation of the user's current quota.
@main struct MenuPreview {
    @MainActor static func main() throws {
        let now=Date(),formatter=ISO8601DateFormatter()
        func provider(_ id:String,_ first:Double,_ second:Double)->[String:Any] {
            ["id":id,"remaining_percent":first,"remaining_label":"5h","stale":false,"updated_at":formatter.string(from:now),
             "windows":[["id":"primary","label":"5h","remaining_percent":first,"stale":false,"updated_at":formatter.string(from:now),"resets_at":formatter.string(from:now.addingTimeInterval(8100))],
                        ["id":"secondary","label":"7d","remaining_percent":second,"stale":false,"updated_at":formatter.string(from:now),"resets_at":formatter.string(from:now.addingTimeInterval(286000))]]]
        }
        let data=try JSONSerialization.data(withJSONObject:["providers":[provider("codex",62,84),provider("claude",94,48),provider("cursor",37,71)],"hardware_owner":"dashboard","device":["connected":true],"running":true,"settings":["display_mode":"text","brightness":0.4,"text":"AMG65 STUDIO","text_color":"#7bdcb0","activity_enabled":true]])
        let snapshot=try JSONDecoder().decode(MenuUsageSnapshot.self,from:data)
        var faultObject=(try JSONSerialization.jsonObject(with:data)) as! [String:Any]
        faultObject["device"]=["connected":false,"code":"fault_reconnect"]
        let faultSnapshot=try JSONDecoder().decode(MenuUsageSnapshot.self,from:JSONSerialization.data(withJSONObject:faultObject))
        let fixtureAccounts=try JSONDecoder().decode([MenuAccount].self,from:JSONSerialization.data(withJSONObject:
            ["codex","claude","cursor"].map { id in ["provider":id,"phase":id=="claude" ? "complete":"idle",
                "usage":["remaining_percent":62,"stale":false,"updated_at":formatter.string(from:now)]] as [String:Any] }))
        let session=DriverSession();session.active=true
        let lighting=LightingModel(),colors=CustomLightModel(),keys=KeymapModel(),lcd=ScreenModel(),strip=StripModel(),settings=SettingsModel()
        let cases=[("usage","overview","overview"),("usage","codex","codex"),("usage","claude","claude"),("usage","cursor","cursor"),("display","overview","display"),("lighting","overview","lighting"),("keys","overview","keys"),("lcd","overview","lcd"),("led","overview","led"),("device","overview","device"),("accounts","overview","accounts"),("usage","overview","fault-overview"),("usage","codex","fault-codex"),("usage","claude","fault-claude"),("usage","cursor","fault-cursor"),("display","overview","fault-display")]
        for (section,tab,name) in cases {
            let view=StudioMenuPopover(preview:name.hasPrefix("fault-") ? faultSnapshot:snapshot,section:section,tab:tab,previewAccounts:fixtureAccounts)
                .environmentObject(session).environmentObject(session.hid)
                .environmentObject(lighting).environmentObject(colors).environmentObject(keys)
                .environmentObject(lcd).environmentObject(strip).environmentObject(settings)
                .environment(\.colorScheme,.light)
            let host=NSHostingView(rootView:view)
            host.frame=CGRect(x:0,y:0,width:section=="keys" ? 760:460,height:section=="usage" ? 410:600)
            host.layoutSubtreeIfNeeded()
            guard let bitmap=host.bitmapImageRepForCachingDisplay(in:host.bounds) else { fatalError("Could not allocate preview") }
            host.cacheDisplay(in:host.bounds,to:bitmap)
            guard let png=bitmap.representation(using:.png,properties:[:]) else { fatalError("Could not render popup") }
            try png.write(to:URL(fileURLWithPath:CommandLine.arguments[1],isDirectory:true).appendingPathComponent(name+".png"))
        }
    }
}
