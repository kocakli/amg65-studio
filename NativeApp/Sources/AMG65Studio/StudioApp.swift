import SwiftUI
import WebKit
import AppKit

@MainActor
final class DriverSession: ObservableObject {
    let hid = KeyboardHID()
    @Published var active = false
    @Published var acquiring = false
    @Published var releasing = false
    private var releaseCompletions: [()->Void] = []
    @Published var message = "Kullanım paneli USB ekranını yönetiyor."
    private var heartbeat: Timer?
    private var task: Task<Void,Never>?
    private var generation = 0
    private let base = URL(string:"http://127.0.0.1:47866")!

    init() {
        let start=Process(); start.executableURL=URL(fileURLWithPath:"/bin/launchctl")
        start.arguments=["kickstart","gui/\(getuid())/io.github.kocakli.amg65studio"]
        start.standardOutput=FileHandle.nullDevice; start.standardError=FileHandle.nullDevice
        try? start.run()
    }

    private func call(_ path:String, owner:String? = nil) async throws -> [String:Any] {
        var request = URLRequest(url:base.appendingPathComponent(path))
        request.timeoutInterval = 5
        if let owner {
            request.httpMethod = "POST"
            request.setValue("application/json",forHTTPHeaderField:"Content-Type")
            request.setValue(base.absoluteString,forHTTPHeaderField:"Origin")
            var payload:[String:Any] = ["owner":owner]
            if owner == "dashboard", let failed = hid.failedRegistryID { payload["faulted_registry_id"] = NSNumber(value:failed) }
            request.httpBody = try JSONSerialization.data(withJSONObject:payload)
        }
        let (data,response) = try await URLSession.shared.data(for:request)
        guard let response = response as? HTTPURLResponse, (200...299).contains(response.statusCode) else {
            throw NSError(domain:"AMG65",code:1,userInfo:[NSLocalizedDescriptionKey:"Yerel köprüye erişilemiyor."])
        }
        return (try JSONSerialization.jsonObject(with:data)) as? [String:Any] ?? [:]
    }

    func enter() {
        guard !active, !acquiring, !releasing else { return }
        acquiring = true; generation += 1
        let token = generation
        message = "USB denetimi alınıyor…"
        task = Task { [self] in
            do {
                _ = try await call("api/control",owner:"native")
                for _ in 0..<40 {
                    try Task.checkCancellation()
                    let state = try await call("api/status")
                    if state["hardware_owner"] as? String == "native",
                       (state["device"] as? [String:Any])?["connected"] as? Bool == false {
                        guard token == generation else { return }
                        hid.resume { [weak self] success in
                            guard let self, token == self.generation else { return }
                            self.acquiring = false; self.active = success
                            self.message = success ? "Yerel sürücü USB denetimini aldı." : (self.hid.error ?? "USB açılamadı.")
                            if success { self.startHeartbeat() }
                            else { self.releaseLease() }
                        }
                        return
                    }
                    try await Task.sleep(nanoseconds:200_000_000)
                }
                throw NSError(domain:"AMG65",code:2,userInfo:[NSLocalizedDescriptionKey:"USB denetimi zamanında serbest kalmadı."])
            } catch {
                guard token == generation else { return }
                acquiring = false; message = error.localizedDescription; releaseLease()
            }
        }
    }

    private func startHeartbeat() {
        heartbeat?.invalidate()
        heartbeat = Timer.scheduledTimer(withTimeInterval:10,repeats:true) { [weak self] _ in
            Task { @MainActor in
                guard let self, self.active else { return }
                do { _ = try await self.call("api/control",owner:"native") }
                catch { self.message = "Yerel köprü bağlantısı kesildi; USB güvenli biçimde bırakılıyor."; self.leave() }
            }
        }
    }

    private func releaseLease() { leave(preserveMessage:true) }

    func leave(preserveMessage:Bool = false, completion: @escaping ()->Void = {}) {
        releaseCompletions.append(completion)
        guard !releasing else { return }
        releasing = true
        generation += 1; task?.cancel(); task = nil
        heartbeat?.invalidate(); heartbeat = nil
        acquiring = false; active = false
        hid.suspend { [weak self] in
            guard let self else { completion(); return }
            if !preserveMessage { self.message = "Kullanım paneli USB ekranını yönetiyor." }
            Task {
                _ = try? await self.call("api/control",owner:"dashboard")
                self.releasing = false
                let callbacks = self.releaseCompletions; self.releaseCompletions = []
                callbacks.forEach { $0() }
            }
        }
    }
}

@MainActor
final class StudioDelegate: NSObject, NSApplicationDelegate {
    var session: DriverSession?
    func applicationShouldTerminateAfterLastWindowClosed(_ sender:NSApplication) -> Bool { true }
    func applicationShouldTerminate(_ sender:NSApplication) -> NSApplication.TerminateReply {
        guard let session else { return .terminateNow }
        session.leave { sender.reply(toApplicationShouldTerminate:true) }
        return .terminateLater
    }
}

@main
struct StudioApp: App {
    @NSApplicationDelegateAdaptor(StudioDelegate.self) private var delegate
    @StateObject private var session = DriverSession()
    @StateObject private var lighting = LightingModel()
    @StateObject private var colors = CustomLightModel()
    @StateObject private var keymap = KeymapModel()
    @StateObject private var screen = ScreenModel()
    @StateObject private var strip = StripModel()
    @StateObject private var settings = SettingsModel()
    var body: some Scene {
        WindowGroup("AMG65 Studio") {
            StudioRoot()
                .environmentObject(session).environmentObject(session.hid)
                .environmentObject(lighting).environmentObject(colors).environmentObject(keymap)
                .environmentObject(screen).environmentObject(strip).environmentObject(settings)
                .frame(minWidth:1050,minHeight:720)
                .preferredColorScheme(.dark)
                .onAppear { delegate.session = session }
        }
        .defaultSize(width:1250,height:850)
        .commands { CommandGroup(replacing:.newItem) {} }
    }
}

enum StudioPage: String, CaseIterable, Identifiable {
    case dashboard = "Kullanım hakları", lighting = "Aydınlatma", colors = "Tuş renkleri", keys = "Tuş atamaları", lcd = "LCD ekran", strip = "LED animasyonu", settings = "Cihaz ayarları"
    var id: String { rawValue }
    var icon: String {
        switch self {
        case .dashboard:"chart.bar.fill"
        case .lighting:"lightbulb"
        case .colors:"paintpalette"
        case .keys:"keyboard"
        case .lcd:"rectangle.on.rectangle"
        case .strip:"rectangle.split.3x1"
        case .settings:"slider.horizontal.3"
        }
    }
}

struct StudioRoot: View {
    @EnvironmentObject var session:DriverSession
    @EnvironmentObject var hid:KeyboardHID
    @State private var page:StudioPage = .dashboard
    var body: some View {
        HStack(spacing:0) {
            VStack(alignment:.leading,spacing:26) {
                VStack(alignment:.leading,spacing:4) {
                    Text("AMG65").font(.system(size:25,weight:.black,design:.rounded))
                    Text("STUDIO / MAC").font(.system(size:10,weight:.semibold,design:.monospaced)).tracking(3).foregroundStyle(.mint)
                }.padding(.bottom,20)
                ForEach(StudioPage.allCases) { target in
                    Button {
                        page = target
                        if target == .dashboard { session.leave() } else { session.enter() }
                    } label: {
                        Label(target.rawValue,systemImage:target.icon)
                            .font(.system(size:13,weight:page == target ? .semibold:.regular))
                            .frame(maxWidth:.infinity,alignment:.leading).padding(11)
                            .background(page == target ? Color.mint.opacity(0.12):.clear,in:RoundedRectangle(cornerRadius:9))
                            .foregroundStyle(page == target ? Color.mint:Color.secondary)
                    }.buttonStyle(.plain).disabled(hid.busy || session.releasing)
                }
                Spacer()
                Text("Yerel bağlantı\nHesap verileri CodexBar’da kalır.")
                    .font(.system(size:11)).foregroundStyle(.secondary).lineSpacing(5)
            }.padding(24).frame(width:220).background(Color(red:0.065,green:0.08,blue:0.095))
            if page == .dashboard { DashboardHost() }
            else {
                VStack(alignment:.leading,spacing:20) {
                    HStack {
                        VStack(alignment:.leading,spacing:7) {
                            Text(page.rawValue).font(.system(size:30,weight:.semibold))
                            Text(session.message).font(.system(size:12)).foregroundStyle(.secondary)
                        }
                        Spacer()
                        if session.acquiring { ProgressView().controlSize(.small) }
                        else if !session.active { Button("Yeniden bağlan") { session.enter() } }
                        else { Label(hid.connection == .wired ? "USB bağlı":"Alıcı bağlı",systemImage:"circle.fill").font(.system(size:11)).foregroundStyle(.mint) }
                    }
                    if let error = hid.error { Text(error).font(.system(size:12)).foregroundStyle(.orange) }
                    ScrollView {
                        Group {
                            switch page {
                            case .lighting: LightingControls()
                            case .colors: PerKeyControls()
                            case .keys: KeyControls()
                            case .lcd: LCDControls()
                            case .strip: StripControls()
                            case .settings: DeviceControls()
                            case .dashboard: EmptyView()
                            }
                        }.disabled(!session.active || hid.busy)
                    }
                    Text("Gösterilen ayarlar yerel tercihlerdir; cihazdan geri okuma yapılmaz.").font(.system(size:11)).foregroundStyle(.secondary)
                }.padding(30).frame(maxWidth:.infinity,maxHeight:.infinity,alignment:.topLeading)
                    .background(Color(red:0.09,green:0.105,blue:0.125))
            }
        }
    }
}

struct DashboardHost:View {
    @State private var loading = true
    @State private var error:String?
    @State private var reload = UUID()
    var body:some View {
        ZStack {
            DashboardWebView(loading:$loading,error:$error).id(reload)
            if loading || error != nil {
                VStack(spacing:18) {
                    Image(systemName:error == nil ? "chart.bar.xaxis":"network.slash").font(.system(size:36)).foregroundStyle(.mint)
                    if let error {
                        Text(error).font(.headline)
                        Text("Önce AMG65 Studio yerel köprüsünü kurun veya başlatın.").foregroundStyle(.secondary)
                        Button("Yeniden yükle") { errorReset() }.buttonStyle(.borderedProminent).tint(.mint)
                    } else { ProgressView("Kullanım paneli yükleniyor…") }
                }.frame(maxWidth:.infinity,maxHeight:.infinity).background(Color(red:0.09,green:0.105,blue:0.125))
            }
        }
    }
    private func errorReset() { error = nil; loading = true; reload = UUID() }
}

struct DashboardWebView:NSViewRepresentable {
    @Binding var loading:Bool
    @Binding var error:String?
    func makeCoordinator()->Coordinator { Coordinator(loading:$loading,error:$error) }
    func makeNSView(context:Context)->WKWebView {
        let config=WKWebViewConfiguration(); config.websiteDataStore = .nonPersistent()
        let view=WKWebView(frame:.zero,configuration:config)
        view.navigationDelegate=context.coordinator
        view.setValue(false,forKey:"drawsBackground")
        view.load(URLRequest(url:URL(string:"http://127.0.0.1:47866/#native")!))
        return view
    }
    func updateNSView(_ view:WKWebView,context:Context) {}
    final class Coordinator:NSObject,WKNavigationDelegate {
        var loading:Binding<Bool>
        var error:Binding<String?>
        init(loading:Binding<Bool>,error:Binding<String?>) { self.loading=loading; self.error=error }
        func webView(_ view:WKWebView,didFinish navigation:WKNavigation!) { loading.wrappedValue=false; error.wrappedValue=nil }
        func webView(_ view:WKWebView,didFailProvisionalNavigation navigation:WKNavigation!,withError failure:Error) {
            loading.wrappedValue=false; error.wrappedValue="Yerel kullanım paneline erişilemiyor."
        }
        func webView(_ view:WKWebView,decidePolicyFor action:WKNavigationAction,decisionHandler:@escaping(WKNavigationActionPolicy)->Void) {
            guard let url=action.request.url else { decisionHandler(.cancel); return }
            if url.scheme == "http", url.host == "127.0.0.1", url.port == 47866 { decisionHandler(.allow) }
            else { decisionHandler(.cancel) }
        }
    }
}

struct Panel<Content:View>:View {
    var title:String
    @ViewBuilder var content:Content
    var body:some View {
        VStack(alignment:.leading,spacing:18) {
            Text(title).font(.system(size:15,weight:.semibold))
            content
        }.padding(22).frame(maxWidth:.infinity,alignment:.leading)
            .background(Color.white.opacity(0.045),in:RoundedRectangle(cornerRadius:16))
            .overlay(RoundedRectangle(cornerRadius:16).stroke(Color.white.opacity(0.06)))
    }
}

struct ResultView:View {
    let result:TransactionResult?
    var body:some View {
        if let result {
            VStack(alignment:.leading,spacing:6) {
                Label(result.ok ? "Cihaz işlemi onayladı":"İşlem tamamlanmadı",systemImage:result.ok ? "checkmark.circle":"exclamationmark.triangle")
                    .foregroundStyle(result.ok ? .mint:.orange)
                DisclosureGroup("İşlem ayrıntıları") {
                    Text(result.lines.joined(separator:"\n")).font(.system(size:10,design:.monospaced)).textSelection(.enabled)
                }.font(.system(size:11))
            }.padding(.top,10)
        }
    }
}

func colorValue(_ color:Color)->RGB {
    let value=NSColor(color).usingColorSpace(.deviceRGB) ?? .white
    return RGB(r:UInt8(max(0,min(255,Int(value.redComponent*255)))),g:UInt8(max(0,min(255,Int(value.greenComponent*255)))),b:UInt8(max(0,min(255,Int(value.blueComponent*255)))))
}

struct ByteSlider:View {
    let title:String
    @Binding var value:UInt8
    var range:ClosedRange<Double> = 1...5
    var body:some View {
        HStack {
            Text(title).frame(width:95,alignment:.leading)
            Slider(value:Binding(get:{Double(value)},set:{value=UInt8($0.rounded())}),in:range,step:1)
            Text("\(value)").monospacedDigit().frame(width:25)
        }.font(.system(size:12))
    }
}

struct LightingControls:View {
    @EnvironmentObject var model:LightingModel
    @EnvironmentObject var hid:KeyboardHID
    var body:some View {
        Panel(title:"Klavye aydınlatması") {
            Picker("Efekt",selection:$model.settings.mode) { ForEach(lightingModes) { Text($0.name).tag($0.id) } }
            ColorPicker("Tek renk",selection:Binding(get:{model.swiftUIColor},set:{let c=colorValue($0); model.settings.red=c.r;model.settings.green=c.g;model.settings.blue=c.b}),supportsOpacity:false)
            Toggle("Çok renkli",isOn:$model.settings.colorful)
            ByteSlider(title:"Parlaklık",value:$model.settings.brightness)
            ByteSlider(title:"Hız",value:$model.settings.speed)
            Button("Klavyeye uygula") { model.apply(using:hid) }.buttonStyle(.borderedProminent).tint(.mint).disabled(model.applying)
            ResultView(result:model.lastResult)
        }
    }
}

struct KeyGrid:View {
    var color:(PhysicalKey)->Color
    var selected:Int?
    var action:(PhysicalKey)->Void
    var body:some View {
        GeometryReader { proxy in
            let scale=min(1,proxy.size.width/800)
            ZStack(alignment:.topLeading) {
                ForEach(KeyboardLayout.litKeys) { key in
                    Button { action(key) } label: {
                        Text(key.name).font(.system(size:key.name.count>3 ? 8:11,weight:.medium))
                            .frame(width:key.rect.width*scale,height:key.rect.height*scale)
                            .background(color(key).opacity(0.22),in:RoundedRectangle(cornerRadius:5))
                            .overlay(RoundedRectangle(cornerRadius:5).stroke(selected==key.slot ? Color.white:color(key).opacity(0.5),lineWidth:1))
                    }.buttonStyle(.plain).offset(x:key.rect.minX*scale,y:key.rect.minY*scale)
                }
            }
        }.frame(height:260)
    }
}

struct PerKeyControls:View {
    @EnvironmentObject var model:CustomLightModel
    @EnvironmentObject var hid:KeyboardHID
    var body:some View {
        Panel(title:"Tuşları boya") {
            KeyGrid(color:{model.colors[$0.slot]?.color ?? .gray},action:{model.paint($0.slot)})
            ColorPicker("Fırça",selection:Binding(get:{model.brush.color},set:{model.brush=colorValue($0)}),supportsOpacity:false)
            HStack {
                Toggle("Silgi",isOn:$model.erasing)
                Button("Tümünü boya") { model.fillAll() }
                Button("Temizle") { model.colors=[:] }
            }
            ByteSlider(title:"Parlaklık",value:$model.brightness)
            Button("Renkleri uygula") { model.apply(using:hid) }.buttonStyle(.borderedProminent).tint(.mint).disabled(model.applying)
            ResultView(result:model.lastResult)
        }
    }
}

struct KeyControls:View {
    @EnvironmentObject var model:KeymapModel
    @EnvironmentObject var hid:KeyboardHID
    @State private var code:UInt8=0x04
    @State private var control=false
    @State private var shift=false
    @State private var option=false
    @State private var command=false
    var body:some View {
        Panel(title:"Bir tuş seç ve görevlendir") {
            KeyGrid(color:{model.assignments[$0.slot] == nil ? .gray:.mint},selected:model.selectedSlot,action:{if $0.remappable {model.selectedSlot=$0.slot}})
            if let key=model.selectedKey {
                Text("\(key.name) → \(model.assignments[key.slot]?.title ?? "Varsayılan")").font(.headline)
                Picker("Yeni tuş",selection:$code) { ForEach(HIDKeys.groups.flatMap{$0.1}) { Text($0.name).tag($0.code) } }
                HStack {
                    Toggle("⌃",isOn:$control); Toggle("⇧",isOn:$shift); Toggle("⌥",isOn:$option); Toggle("⌘",isOn:$command)
                }
                HStack {
                    Button("Atamayı hazırla") { model.assign(.key(modifiers:(control ? 1:0)|(shift ? 2:0)|(option ? 4:0)|(command ? 8:0),code:code)) }
                    Button("Bu tuşu varsayılana al") { model.assign(nil) }
                }
            } else { Text("Fn tuşu korunur. Klavye görselinden bir tuşa tıkla.").foregroundStyle(.secondary) }
            Text("Harita bütünüyle yazılır. Uygulama dışındaki mevcut atamalar geri okunamaz.").font(.caption).foregroundStyle(.orange)
            Button("Tuş haritasını uygula") { model.apply(using:hid) }.buttonStyle(.borderedProminent).tint(.mint).disabled(model.applying)
            ResultView(result:model.lastResult)
        }
    }
}

struct LCDControls:View {
    @EnvironmentObject var model:ScreenModel
    @EnvironmentObject var hid:KeyboardHID
    var body:some View {
        Panel(title:"240 × 135 LCD ekran") {
            if let image=model.animation?.frames.first {
                Image(decorative:image,scale:1).interpolation(.none).resizable().aspectRatio(240.0/135,contentMode:.fit).frame(maxWidth:480).clipShape(RoundedRectangle(cornerRadius:12))
            } else { RoundedRectangle(cornerRadius:12).fill(.black).frame(width:480,height:270).overlay(Text(model.loading ? "Görsel hazırlanıyor…":"GIF, PNG veya JPEG seç" ).foregroundStyle(.secondary)) }
            HStack {
                Button("Görsel seç…") { model.chooseFile() }.disabled(model.loading)
                Toggle("Ekranı doldur (kırp)",isOn:$model.fill)
            }
            if let animation=model.animation { Text("\(animation.name) · \(animation.frames.count) kare").font(.caption) }
            Text("32 MB / 130 kare sınırı. Yükleme mevcut ekran içeriğinin yerini alır.").font(.caption).foregroundStyle(.secondary)
            if model.uploading { ProgressView(value:model.progress) }
            HStack {
                Button("LCD’ye yükle") { model.upload(using:hid) }.buttonStyle(.borderedProminent).tint(.mint).disabled(model.animation == nil || model.loading || model.uploading || hid.connection != .wired)
                Button("Tarih ve saati eşitle") { model.syncTime(using:hid) }.disabled(hid.connection != .wired)
            }
            ResultView(result:model.lastResult)
            ResultView(result:model.lastTimeSync)
        }
    }
}

struct StripControls:View {
    @EnvironmentObject var model:StripModel
    @EnvironmentObject var hid:KeyboardHID
    var body:some View {
        Panel(title:"63 × 5 LED animasyonu") {
            if let pixels=model.animation?.frames.first {
                Canvas { context,size in
                    let cell=min(size.width/63,size.height/5)
                    for y in 0..<5 { for x in 0..<63 { context.fill(Path(ellipseIn:CGRect(x:Double(x)*cell,y:Double(y)*cell,width:cell*0.72,height:cell*0.72)),with:.color(pixels[y*63+x].color)) } }
                }.frame(height:70).padding().background(.black,in:RoundedRectangle(cornerRadius:12))
            }
            Picker("Kaynak",selection:$model.source) { ForEach(StripModel.Source.allCases) {Text($0.rawValue).tag($0)} }.pickerStyle(.segmented)
            if model.source == .text {
                TextField("Metin (en fazla 48 karakter)",text:$model.text).textFieldStyle(.roundedBorder)
                ColorPicker("Yazı rengi",selection:Binding(get:{model.textColor.color},set:{model.textColor=colorValue($0)}),supportsOpacity:false)
            } else { Button("GIF veya görsel seç…") { model.chooseFile() }.disabled(model.loading) }
            ByteSlider(title:"Parlaklık",value:$model.brightness)
            ByteSlider(title:"Gecikme",value:$model.delay,range:1...100)
            Picker("Hedef",selection:$model.target) { ForEach(StripTarget.allCases) { Text($0.rawValue).tag($0) } }
            Text("Yükleme seçili animasyonun yerini alır. Kullanım paneline döndüğünde canlı kullanım görünümü yeniden başlar.").font(.caption).foregroundStyle(.secondary)
            if model.uploading {ProgressView(value:model.progress)}
            Button("Animasyonu yükle") { model.upload(using:hid) }.buttonStyle(.borderedProminent).tint(.mint).disabled(model.animation == nil || model.loading || model.uploading || hid.connection != .wired)
            ResultView(result:model.lastResult)
        }
    }
}

struct DeviceControls:View {
    @EnvironmentObject var model:SettingsModel
    @EnvironmentObject var hid:KeyboardHID
    var body:some View {
        Panel(title:"Ekran ayarları") {
            ByteSlider(title:"Ekran ışığı",value:$model.settings.screenBrightness,range:1...7)
            Text("Ayar paketi ekran parlaklığıyla birlikte kayıtlı klavye ayarlarını da gönderir. Oyun modu ve Fn davranışı bu sürümde arayüze eklenmedi.").font(.caption).foregroundStyle(.secondary)
            Button("Parlaklığı uygula") { model.apply(using:hid) }.buttonStyle(.borderedProminent).tint(.mint).disabled(model.applying || hid.connection != .wired)
            ResultView(result:model.lastResult)
        }
    }
}
