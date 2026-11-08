import SwiftUI
import WebKit
import AppKit
import Combine
import Darwin

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
    private var nativeConsumers=Set<String>()
    private var faultObserver:AnyCancellable?
    private let base = URL(string:"http://127.0.0.1:47866")!

    init() {
        #if STUDIO_UI_PREVIEW
        return
        #endif
        // A fault must also end the lease and free the USB handle, not only be displayed.
        faultObserver=hid.$failedRegistryID.compactMap{$0}.sink { [weak self] _ in
            Task { @MainActor in if self?.active==true { self?.leave(preserveMessage:true) } }
        }
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

    func setNativeRequested(_ requested:Bool,by consumer:String) {
        #if STUDIO_UI_PREVIEW
        return
        #endif
        if requested {
            nativeConsumers.insert(consumer)
            if !releasing { enter() }
        } else {
            nativeConsumers.remove(consumer)
            if nativeConsumers.isEmpty { leave(releaseAll:false) }
        }
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
                guard let self, self.active || self.releasing else { return }
                do { _ = try await self.call("api/control",owner:"native") }
                catch { self.message = "Yerel köprü bağlantısı kesildi; USB güvenli biçimde bırakılıyor."; self.leave() }
            }
        }
    }

    private func releaseLease() { leave(preserveMessage:true) }

    func leave(preserveMessage:Bool = false, releaseAll:Bool = true, completion: @escaping ()->Void = {}) {
        if releaseAll { nativeConsumers.removeAll() }
        releaseCompletions.append(completion)
        guard !releasing else { return }
        releasing = true
        generation += 1; task?.cancel(); task = nil
        acquiring = false; active = false
        hid.suspend { [weak self] in
            guard let self else { completion(); return }
            self.heartbeat?.invalidate(); self.heartbeat=nil
            if !preserveMessage { self.message = "Kullanım paneli USB ekranını yönetiyor." }
            Task {
                _ = try? await self.call("api/control",owner:"dashboard")
                self.releasing = false
                let callbacks = self.releaseCompletions; self.releaseCompletions = []
                callbacks.forEach { $0() }
                if !self.nativeConsumers.isEmpty { self.enter() }
            }
        }
    }
}

@MainActor
final class StudioDelegate: NSObject, NSApplicationDelegate {
    var session: DriverSession?
    private var windowObserver:NSObjectProtocol?
    private var terminationSignal:DispatchSourceSignal?
    private var terminationRequested=false
    func applicationWillFinishLaunching(_ notification:Notification) {
        if StudioLaunch.menuBarOnly { NSApp.setActivationPolicy(.accessory) }
    }
    func applicationDidFinishLaunching(_ notification:Notification) {
        StudioMenuLocalization.start()
        windowObserver=NotificationCenter.default.addObserver(forName:NSWindow.willCloseNotification,object:nil,queue:.main) { [weak self] note in
            guard let window=note.object as? NSWindow,window.identifier?.rawValue == "studio-main" else { return }
            Task { @MainActor [weak self] in
                self?.session?.setNativeRequested(false,by:"window")
                NSApp.setActivationPolicy(.accessory)
            }
        }
        Darwin.signal(SIGTERM,SIG_IGN)
        let source=DispatchSource.makeSignalSource(signal:SIGTERM,queue:.main)
        source.setEventHandler { [weak self] in
            guard let self,!self.terminationRequested else { return }
            self.terminationRequested=true
            // terminateLater enters an AppKit run loop. Leave the dispatch-main
            // block first so HID/lease completion can still reach that queue.
            RunLoop.main.perform(inModes:[.default,.common]) { NSApp.terminate(nil) }
        }
        source.resume(); terminationSignal=source
        if StudioLaunch.menuBarOnly {
            DispatchQueue.main.async {
                NSApp.windows.filter{$0.identifier?.rawValue == "studio-main"}.forEach{$0.orderOut(nil); $0.alphaValue=1}
            }
        }
    }
    func applicationShouldTerminateAfterLastWindowClosed(_ sender:NSApplication) -> Bool { false }
    func applicationShouldHandleReopen(_ sender:NSApplication,hasVisibleWindows flag:Bool)->Bool {
        if !flag,let window=sender.windows.first(where:{$0.identifier?.rawValue == "studio-main"}) {
            StudioLaunch.activateWindow(); window.makeKeyAndOrderFront(nil)
        }
        return true
    }
    func applicationShouldTerminate(_ sender:NSApplication) -> NSApplication.TerminateReply {
        guard let session else { return .terminateNow }
        session.leave { sender.reply(toApplicationShouldTerminate:true) }
        return .terminateLater
    }
}

#if !STUDIO_UI_PREVIEW
@main
struct StudioApp: App {
    @ObservedObject private var language = StudioLanguage.shared
    @NSApplicationDelegateAdaptor(StudioDelegate.self) private var delegate
    @StateObject private var session = DriverSession()
    @StateObject private var lighting = LightingModel()
    @StateObject private var colors = CustomLightModel()
    @StateObject private var keymap = KeymapModel()
    @StateObject private var screen = ScreenModel()
    @StateObject private var strip = StripModel()
    @StateObject private var settings = SettingsModel()
    var body: some Scene {
        Window("AMG65 Studio",id:"studio") {
            StudioRoot()
                .environmentObject(session).environmentObject(session.hid)
                .environmentObject(lighting).environmentObject(colors).environmentObject(keymap)
                .environmentObject(screen).environmentObject(strip).environmentObject(settings)
                .frame(minWidth:1050,minHeight:720)
                .background(StudioWindowBridge())
                .preferredColorScheme(.dark)
                .environment(\.locale,language.locale)
                .onAppear { delegate.session = session; StudioMenuLocalization.refresh() }
                .onChange(of:language.selection) { _,_ in StudioMenuLocalization.refresh() }
        }
        .defaultSize(width:1250,height:850)
        .commands {
            CommandGroup(replacing:.newItem) {}
            CommandMenu(L("Dil")) {
                ForEach(StudioLanguage.choices,id:\.self) { code in
                    Button(code == "system" ? L("Sistem dili") : StudioLanguage.names[code]!) { language.selection=code }
                }
            }
        }
        MenuBarExtra {
            StudioMenuPopover()
                .environmentObject(session).environmentObject(session.hid)
                .environmentObject(lighting).environmentObject(colors).environmentObject(keymap)
                .environmentObject(screen).environmentObject(strip).environmentObject(settings)
                .onAppear { delegate.session=session }
        } label: {
            Image(nsImage:StudioLaunch.statusIcon).accessibilityLabel("AMG65 Studio").accessibilityIdentifier("studio-status-item")
        }.menuBarExtraStyle(.window)
    }
}

#endif

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
    @ObservedObject private var language = StudioLanguage.shared
    @EnvironmentObject var session:DriverSession
    @EnvironmentObject var hid:KeyboardHID
    @State private var page:StudioPage = .dashboard
    var body: some View {
        HStack(spacing:0) {
            VStack(alignment:.leading,spacing:26) {
                VStack(alignment:.leading,spacing:4) {
                    HStack(spacing:10) {
                        if let url=Bundle.main.url(forResource:"AppIcon",withExtension:"png"),let icon=NSImage(contentsOf:url) {
                            Image(nsImage:icon).resizable().frame(width:36,height:36).accessibilityHidden(true)
                        }
                        Text("AMG65").font(.system(size:25,weight:.black,design:.rounded))
                    }
                    Text("STUDIO / MAC").font(.system(size:10,weight:.semibold,design:.monospaced)).tracking(3).foregroundStyle(.mint)
                }.padding(.bottom,20)
                ForEach(StudioPage.allCases) { target in
                    Button {
                        page = target
                        session.setNativeRequested(target != .dashboard,by:"window")
                    } label: {
                        Label(L(target.rawValue),systemImage:target.icon)
                            .font(.system(size:13,weight:page == target ? .semibold:.regular))
                            .frame(maxWidth:.infinity,alignment:.leading).padding(11)
                            .background(page == target ? Color.mint.opacity(0.12):.clear,in:RoundedRectangle(cornerRadius:9))
                            .foregroundStyle(page == target ? Color.mint:Color.secondary)
                    }.buttonStyle(.plain).disabled(hid.busy || session.releasing)
                }
                Spacer()
                Picker(L("Dil"),selection:$language.selection) {
                    Text(L("Sistem dili")).tag("system")
                    ForEach(LocalizationCatalog.codes,id:\.self) { code in Text(StudioLanguage.names[code]!).tag(code) }
                }.pickerStyle(.menu).font(.system(size:11)).accessibilityIdentifier("studio-language")
                Text(L("Yerel bağlantı\nOturumlar sağlayıcı uygulamalarında kalır."))
                    .font(.system(size:11)).foregroundStyle(.secondary).lineSpacing(5)
            }.padding(24).frame(width:220).background(Color(red:0.065,green:0.08,blue:0.095))
            if page == .dashboard { DashboardHost() }
            else {
                VStack(alignment:.leading,spacing:20) {
                    HStack {
                        VStack(alignment:.leading,spacing:7) {
                            Text(L(page.rawValue)).font(.system(size:30,weight:.semibold))
                            Text(L(session.message)).font(.system(size:12)).foregroundStyle(.secondary)
                        }
                        Spacer()
                        if session.acquiring { ProgressView().controlSize(.small) }
                        else if hid.failedRegistryID != nil {
                            Label {
                                Text(L("LED aktarımı durdu")).foregroundStyle(.primary)
                            } icon: {
                                Image(systemName:"exclamationmark.triangle.fill").foregroundStyle(.orange)
                            }.font(.system(size:11)).help(L("USB kablosunu çıkarıp yeniden takın."))
                        }
                        else if !session.active { Button(L("Yeniden bağlan")) { session.setNativeRequested(true,by:"window") } }
                        else if hid.connection != .none { Label(L(hid.connection == .wired ? "USB bağlı":"Alıcı bağlı"),systemImage:"circle.fill").font(.system(size:11)).foregroundStyle(.mint) }
                        else { Label(L("USB durumu bilinmiyor"),systemImage:"questionmark.circle").font(.system(size:11)).foregroundStyle(.secondary) }
                    }
                    if let error = hid.error { Text(L(error)).font(.system(size:12)).foregroundStyle(.orange) }
                    Form {
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
                    }.studioForm().id(page)
                    Text(L("Gösterilen ayarlar yerel tercihlerdir; cihazdan geri okuma yapılmaz.")).font(.system(size:11)).foregroundStyle(.secondary)
                }.padding(30).frame(maxWidth:.infinity,maxHeight:.infinity,alignment:.topLeading)
                    .background(Color(red:0.09,green:0.105,blue:0.125))
            }
        }
    }
}

struct DashboardHost:View {
    @ObservedObject private var language = StudioLanguage.shared
    @State private var loading = true
    @State private var error:String?
    @State private var reload = UUID()
    var body:some View {
        ZStack {
            DashboardWebView(loading:$loading,error:$error,url:language.dashboardURL).id(reload)
            if loading || error != nil {
                VStack(spacing:18) {
                    Image(systemName:error == nil ? "chart.bar.xaxis":"network.slash").font(.system(size:36)).foregroundStyle(.mint)
                    if let error {
                        Text(L(error)).font(.headline)
                        Text(L("Önce AMG65 Studio yerel köprüsünü kurun veya başlatın.")).foregroundStyle(.secondary)
                        Button(L("Yeniden yükle")) { errorReset() }.buttonStyle(.borderedProminent).tint(.mint)
                    } else { ProgressView(L("Kullanım paneli yükleniyor…")) }
                }.frame(maxWidth:.infinity,maxHeight:.infinity).background(Color(red:0.09,green:0.105,blue:0.125))
            }
        }
    }
    private func errorReset() { error = nil; loading = true; reload = UUID() }
}

struct DashboardWebView:NSViewRepresentable {
    @Binding var loading:Bool
    @Binding var error:String?
    var url:URL
    func makeCoordinator()->Coordinator { Coordinator(loading:$loading,error:$error) }
    func makeNSView(context:Context)->WKWebView {
        let config=WKWebViewConfiguration(); config.websiteDataStore = .nonPersistent()
        let view=WKWebView(frame:.zero,configuration:config)
        view.navigationDelegate=context.coordinator
        view.setValue(false,forKey:"drawsBackground")
        context.coordinator.lastURL=url
        view.load(URLRequest(url:url))
        return view
    }
    func updateNSView(_ view:WKWebView,context:Context) {
        guard context.coordinator.lastURL != url else { return }
        context.coordinator.lastURL=url
        // Change only the fragment. Preserve web drafts and the current USB owner.
        view.callAsyncJavaScript("window.location.hash = fragment",arguments:["fragment":url.fragment ?? "native"],in:nil,in:.page) { _ in }

    }
    final class Coordinator:NSObject,WKNavigationDelegate {
        var lastURL:URL?
        var loading:Binding<Bool>
        var error:Binding<String?>
        init(loading:Binding<Bool>,error:Binding<String?>) { self.loading=loading; self.error=error }
        func webView(_ view:WKWebView,didFinish navigation:WKNavigation!) {
            loading.wrappedValue=false; error.wrappedValue=nil
            if let fragment=lastURL?.fragment,view.url?.fragment != fragment {
                view.callAsyncJavaScript("window.location.hash = fragment",arguments:["fragment":fragment],in:nil,in:.page) { _ in }
            }
        }
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

extension View {
    /// The grouped System Settings look, transparent over the panel or window behind it.
    func studioForm()->some View {
        formStyle(.grouped).scrollContentBackground(.hidden)
            // Grouped forms reserve about 20pt above the first section; keep it level with the content inset.
            .contentMargins(.top,-10,for:.scrollContent).contentMargins(.bottom,4,for:.scrollContent)
    }
}

/// One section of a grouped form. `title` is a catalog key; `footer` is already localized.
struct Panel<Content:View>:View {
    @ObservedObject private var language = StudioLanguage.shared
    var title:String
    var footer:String?=nil
    @ViewBuilder var content:Content
    var body:some View {
        Section {
            content
        } header: {
            Text(L(title))
        } footer: {
            if let footer { Text(footer).font(.footnote).foregroundStyle(.secondary).fixedSize(horizontal:false,vertical:true) }
        }
    }
}

struct ResultView:View {
    @ObservedObject private var language = StudioLanguage.shared
    let result:TransactionResult?
    var body:some View {
        if let result {
            VStack(alignment:.leading,spacing:6) {
                Label(L(result.ok ? "Cihaz işlemi onayladı":"İşlem tamamlanmadı"),systemImage:result.ok ? "checkmark.circle":"exclamationmark.triangle")
                    .foregroundStyle(result.ok ? .mint:.orange)
                DisclosureGroup(L("İşlem ayrıntıları")) {
                    Text(result.lines.map { L($0) }.joined(separator:"\n")).font(.system(size:10,design:.monospaced)).textSelection(.enabled)
                }.font(.system(size:11))
            }.padding(.top,10)
        }
    }
}

struct ByteSlider:View {
    @ObservedObject private var language = StudioLanguage.shared
    let title:String
    @Binding var value:UInt8
    var range:ClosedRange<Double> = 1...5
    var body:some View {
        LabeledContent(L(title)) {
            HStack {
                Slider(value:Binding(get:{Double(value)},set:{value=UInt8($0.rounded())}),in:range,step:1).labelsHidden()
                Text("\(value)").monospacedDigit().frame(width:25,alignment:.trailing)
            }
        }
    }
}

/// The last row of a device section: its one action, on the trailing edge.
struct ApplyRow:View {
    let title:String
    var disabled=false
    let action:()->Void
    var body:some View {
        HStack {
            Spacer()
            Button(title,action:action).buttonStyle(.borderedProminent).disabled(disabled)
        }
    }
}

struct LightingControls:View {
    @ObservedObject private var language = StudioLanguage.shared
    @EnvironmentObject var model:LightingModel
    @EnvironmentObject var hid:KeyboardHID
    var body:some View {
        Panel(title:"Klavye aydınlatması",footer:L(model.settings.colorful ? "Çok renkli açık. Bir renk seçmek tek renge geçer.":"Seçtiğiniz renk taslaktır; yalnızca Uygula ile klavyeye gönderilir.")) {
            Picker(L("Efekt"),selection:$model.settings.mode) { ForEach(lightingModes) { Text(L($0.name)).tag($0.id) } }
            Toggle(L("Çok renkli"),isOn:$model.settings.colorful)
            ByteSlider(title:"Parlaklık",value:$model.settings.brightness)
            ByteSlider(title:"Hız",value:$model.settings.speed)
            InlineColorControls(title:"Tek renk",value:model.selectedColor,onSelect:model.selectColor)
            if model.settings.mode != 1 {
                HStack {
                    Text(L("Düz bir arka plan için Sabit efekti kullanın. Animasyonlarda renk davranışı değişebilir."))
                        .font(.caption).foregroundStyle(.secondary).fixedSize(horizontal:false,vertical:true)
                    Spacer(minLength:8)
                    Button(L("Sabit renge geç")) { model.useStaticColor() }
                }
            }
            ApplyRow(title:L("Klavyeye uygula"),disabled:model.applying) { model.apply(using:hid) }
            ResultView(result:model.lastResult)
        }
    }
}

/// Inline controls stay inside the menu/window; no floating NSColorPanel is required.
struct InlineColorControls:View {
    @ObservedObject private var language = StudioLanguage.shared
    let title:String
    let value:RGB
    let onSelect:(RGB)->Void
    @State private var hexText=""
    private var invalidHex:Bool { !hexText.isEmpty && RGB.parse(hex:hexText)==nil }

    var body:some View {
        VStack(alignment:.leading,spacing:12) {
            HStack(spacing:10) {
                RoundedRectangle(cornerRadius:6).fill(value.color)
                    .overlay(RoundedRectangle(cornerRadius:6).strokeBorder(Color.primary.opacity(0.16)))
                    .frame(width:30,height:30)
                Text(L(title)).font(.system(size:12,weight:.semibold))
                Spacer(minLength:8)
                Text(L("HEX")).font(.system(size:10,weight:.medium)).foregroundStyle(.secondary)
                TextField(L("HEX"),text:$hexText)
                    .font(.system(size:12,design:.monospaced)).textFieldStyle(.roundedBorder)
                    .frame(width:88).labelsHidden().accessibilityLabel(L("HEX renk kodu"))
                    .onChange(of:hexText) { _,new in
                        if let color=RGB.parse(hex:new),color != value { onSelect(color) }
                    }
                    .onSubmit { if let color=RGB.parse(hex:hexText) { onSelect(color);hexText=color.hex } }
            }
            HStack(spacing:8) {
                ForEach(RGB.swatches) { swatch in
                    Button { onSelect(swatch.value);hexText=swatch.value.hex } label: {
                        RoundedRectangle(cornerRadius:6).fill(swatch.value.color)
                            .overlay(RoundedRectangle(cornerRadius:6).strokeBorder(Color.primary.opacity(0.15)))
                            .overlay {
                                if value == swatch.value {
                                    Image(systemName:"checkmark").font(.system(size:11,weight:.bold))
                                        .foregroundStyle(swatch.value.g > 180 ? Color.black:Color.white)
                                }
                            }.frame(width:28,height:28)
                    }.buttonStyle(.plain).help(L(swatch.name)).accessibilityLabel(L(swatch.name))
                        .accessibilityAddTraits(value == swatch.value ? .isSelected:[])
                }
            }
            VStack(spacing:5) {
                channel("Kırmızı",keyPath:\.r,tint:.red)
                channel("Yeşil",keyPath:\.g,tint:.green)
                channel("Mavi",keyPath:\.b,tint:.blue)
            }
            if invalidHex {
                Text(L("HEX kodu 6 haneli olmalıdır; geçersiz giriş rengi değiştirmez."))
                    .font(.caption).foregroundStyle(.orange)
            }
        }
        .onAppear { hexText=value.hex }
        .onChange(of:value) { _,new in hexText=new.hex }
    }

    private func channel(_ name:String,keyPath:WritableKeyPath<RGB,UInt8>,tint:Color)->some View {
        HStack(spacing:8) {
            Text(L(name)).font(.system(size:10)).foregroundStyle(.secondary).frame(width:52,alignment:.leading)
            Slider(value:Binding(get:{Double(value[keyPath:keyPath])},set:{ number in
                var color=value;color[keyPath:keyPath]=UInt8(max(0,min(255,number.rounded())))
                onSelect(color)
            }),in:0...255,step:1).tint(tint).accessibilityLabel(L(name))
            Text("\(value[keyPath:keyPath])").font(.system(size:10,design:.monospaced)).monospacedDigit().frame(width:25,alignment:.trailing)
        }
    }
}

struct KeyGrid:View {
    var color:(PhysicalKey)->Color
    var selected:Int?
    var action:(PhysicalKey)->Void
    private static let extent=KeyboardLayout.litKeys.map(\.rect).reduce(CGRect.null) { $0.union($1) }.size
    var body:some View {
        GeometryReader { proxy in
            let scale=min(1,proxy.size.width/Self.extent.width)
            ZStack(alignment:.topLeading) {
                ForEach(KeyboardLayout.litKeys) { key in
                    Button { action(key) } label: {
                        Text(key.name).font(.system(size:key.name.count>3 ? 8:11,weight:.medium)).lineLimit(1).minimumScaleFactor(0.7)
                            .frame(width:key.rect.width*scale,height:key.rect.height*scale)
                            .background(color(key).opacity(0.22),in:RoundedRectangle(cornerRadius:5))
                            .overlay(RoundedRectangle(cornerRadius:5).stroke(selected==key.slot ? Color.accentColor:color(key).opacity(0.5),lineWidth:selected==key.slot ? 2:1))
                    }.buttonStyle(.plain).offset(x:key.rect.minX*scale,y:key.rect.minY*scale)
                }
            }
        }.aspectRatio(Self.extent.width/Self.extent.height,contentMode:.fit).frame(maxWidth:Self.extent.width)
    }
}

struct PerKeyControls:View {
    @ObservedObject private var language = StudioLanguage.shared
    @EnvironmentObject var model:CustomLightModel
    @EnvironmentObject var hid:KeyboardHID
    var body:some View {
        Panel(title:"Tuşları boya",footer:L("Rengi seçin, tuşlara tıklayın veya tümünü boyayın. Renkleri uygula ile kaydedin.")) {
            KeyGrid(color:{model.colors[$0.slot]?.color ?? .gray},action:{model.paint($0.slot)})
            InlineColorControls(title:"Fırça",value:model.brush,onSelect:model.selectBrush)
            HStack {
                Toggle(L("Silgi"),isOn:$model.erasing).toggleStyle(.checkbox)
                Spacer()
                Button(L("Tümünü boya")) { model.fillAll() }
                Button(L("Temizle")) { model.colors=[:] }
            }
            ByteSlider(title:"Parlaklık",value:$model.brightness)
            ApplyRow(title:L("Renkleri uygula"),disabled:model.applying) { model.apply(using:hid) }
            ResultView(result:model.lastResult)
        }
    }
}

struct KeyControls:View {
    @ObservedObject private var language = StudioLanguage.shared
    @EnvironmentObject var model:KeymapModel
    @EnvironmentObject var hid:KeyboardHID
    @State private var code:UInt8=0x04
    @State private var control=false
    @State private var shift=false
    @State private var option=false
    @State private var command=false
    var body:some View {
        Panel(title:"Bir tuş seç ve görevlendir") {
            KeyGrid(color:{model.assignments[$0.slot] == nil ? .gray:.accentColor},selected:model.selectedSlot,action:{if $0.remappable {model.selectedSlot=$0.slot}})
            if let key=model.selectedKey {
                Text("\(key.name) → \(model.assignments[key.slot]?.localizedTitle ?? L("Varsayılan"))").font(.headline)
                Picker(L("Yeni tuş"),selection:$code) { ForEach(HIDKeys.groups.flatMap{$0.1}) { Text(L($0.name)).tag($0.code) } }
                HStack {
                    Toggle("⌃",isOn:$control); Toggle("⇧",isOn:$shift); Toggle("⌥",isOn:$option); Toggle("⌘",isOn:$command)
                    Spacer()
                    Button(L("Atamayı hazırla")) { model.assign(.key(modifiers:(control ? 1:0)|(shift ? 2:0)|(option ? 4:0)|(command ? 8:0),code:code)) }
                    Button(L("Bu tuşu varsayılana al")) { model.assign(nil) }
                }.toggleStyle(.button)
            } else { Text(L("Fn tuşu korunur. Klavye görselinden bir tuşa tıkla.")).foregroundStyle(.secondary) }
            Label(L("Harita bütünüyle yazılır. Uygulama dışındaki mevcut atamalar geri okunamaz."),systemImage:"exclamationmark.triangle")
                .font(.caption).foregroundStyle(.orange)
            ApplyRow(title:L("Tuş haritasını uygula"),disabled:model.applying) { model.apply(using:hid) }
            ResultView(result:model.lastResult)
        }
    }
}

struct LCDControls:View {
    @ObservedObject private var language = StudioLanguage.shared
    @EnvironmentObject var model:ScreenModel
    @EnvironmentObject var hid:KeyboardHID
    var body:some View {
        Panel(title:"240 × 135 LCD ekran",footer:L("32 MB / 130 kare sınırı. Yükleme mevcut ekran içeriğinin yerini alır.")) {
            HStack {
                Spacer()
                if let image=model.animation?.frames.first {
                    Image(decorative:image,scale:1).interpolation(.none).resizable().aspectRatio(240.0/135,contentMode:.fit).frame(maxWidth:320).clipShape(RoundedRectangle(cornerRadius:12))
                } else { RoundedRectangle(cornerRadius:12).fill(.black).aspectRatio(240.0/135,contentMode:.fit).frame(maxWidth:320).overlay(Text(L(model.loading ? "Görsel hazırlanıyor…":"GIF, PNG veya JPEG seç")).foregroundStyle(.secondary)) }
                Spacer()
            }
            HStack {
                Button(L("Görsel seç…")) { model.chooseFile() }.disabled(model.loading)
                Spacer()
                Toggle(L("Ekranı doldur (kırp)"),isOn:$model.fill).toggleStyle(.checkbox)
            }
            if let animation=model.animation { Text(L("{0} · {1} kare",animation.name,String(animation.frames.count))).font(.caption) }
            if model.uploading { ProgressView(value:model.progress) }
            HStack {
                Button(L("Tarih ve saati eşitle")) { model.syncTime(using:hid) }.disabled(hid.connection != .wired)
                Spacer()
                Button(L("LCD’ye yükle")) { model.upload(using:hid) }.buttonStyle(.borderedProminent).disabled(model.animation == nil || model.loading || model.uploading || hid.connection != .wired)
            }
            ResultView(result:model.lastResult)
            ResultView(result:model.lastTimeSync)
        }
    }
}

struct StripControls:View {
    @ObservedObject private var language = StudioLanguage.shared
    @EnvironmentObject var model:StripModel
    @EnvironmentObject var hid:KeyboardHID
    var body:some View {
        Panel(title:"63 × 5 LED animasyonu",footer:L("Yükleme seçili animasyonun yerini alır. Kullanım paneline döndüğünde canlı kullanım görünümü yeniden başlar.")) {
            if let pixels=model.animation?.frames.first {
                Canvas { context,size in
                    let cell=min(size.width/63,size.height/5)
                    for y in 0..<5 { for x in 0..<63 { context.fill(Path(ellipseIn:CGRect(x:Double(x)*cell,y:Double(y)*cell,width:cell*0.72,height:cell*0.72)),with:.color(pixels[y*63+x].color)) } }
                }.frame(height:44).padding(10).background(.black,in:RoundedRectangle(cornerRadius:8))
            }
            Picker(L("Kaynak"),selection:$model.source) { ForEach(StripModel.Source.allCases) {Text(L($0.rawValue)).tag($0)} }.pickerStyle(.segmented)
            if model.source == .text {
                TextField(L("Metin (en fazla 48 karakter)"),text:$model.text)
                Text(L("LED yazı tipi A–Z, 0–9 ve temel noktalama işaretlerini destekler. Diğer karakterler ? olarak gösterilir.")).font(.caption).foregroundStyle(.secondary)
                InlineColorControls(title:"Yazı rengi",value:model.textColor) { model.textColor=$0 }
            } else { Button(L("GIF veya görsel seç…")) { model.chooseFile() }.disabled(model.loading) }
            ByteSlider(title:"Parlaklık",value:$model.brightness)
            ByteSlider(title:"Gecikme",value:$model.delay,range:1...100)
            Picker(L("Hedef"),selection:$model.target) { ForEach(StripTarget.allCases) { Text(L($0.rawValue)).tag($0) } }
            if model.uploading {ProgressView(value:model.progress)}
            ApplyRow(title:L("Animasyonu yükle"),disabled:model.animation == nil || model.loading || model.uploading || hid.connection != .wired) { model.upload(using:hid) }
            ResultView(result:model.lastResult)
        }
    }
}

struct DeviceControls:View {
    @ObservedObject private var language = StudioLanguage.shared
    @EnvironmentObject var model:SettingsModel
    @EnvironmentObject var hid:KeyboardHID
    var body:some View {
        Panel(title:"Ekran ayarları",footer:L("Ayar paketi ekran parlaklığıyla birlikte kayıtlı klavye ayarlarını da gönderir. Oyun modu ve Fn davranışı bu sürümde arayüze eklenmedi.")) {
            ByteSlider(title:"Ekran ışığı",value:$model.settings.screenBrightness,range:1...7)
            ApplyRow(title:L("Parlaklığı uygula"),disabled:model.applying || hid.connection != .wired) { model.apply(using:hid) }
            ResultView(result:model.lastResult)
        }
    }
}
