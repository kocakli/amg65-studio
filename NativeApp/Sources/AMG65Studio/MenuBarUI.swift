import SwiftUI
import AppKit

@MainActor enum StudioLaunch {
    static let menuBarOnly=CommandLine.arguments.contains("--menu-bar")
    static var initialWindowHandled=false
    static func activateWindow() { NSApp.setActivationPolicy(.regular); NSApp.activate(ignoringOtherApps:true) }
    static var statusIcon:NSImage {
        let symbol=NSImage(systemSymbolName:"keyboard.badge.ellipsis",accessibilityDescription:"AMG65 Studio")
            ?? NSImage(systemSymbolName:"keyboard",accessibilityDescription:"AMG65 Studio")!
        symbol.isTemplate=true
        return symbol
    }
}

/// Marks the Studio window independently of the transient menu-bar popover.
struct StudioWindowBridge:NSViewRepresentable {
    func makeNSView(context:Context)->NSView { Marker() }
    func updateNSView(_ view:NSView,context:Context) {}
    final class Marker:NSView {
        override func viewDidMoveToWindow() {
            super.viewDidMoveToWindow()
            guard let window else { return }
            window.identifier=NSUserInterfaceItemIdentifier("studio-main")
            guard !StudioLaunch.initialWindowHandled else { return }
            StudioLaunch.initialWindowHandled=true
            if StudioLaunch.menuBarOnly {
                window.alphaValue=0
                DispatchQueue.main.async { window.orderOut(nil); window.alphaValue=1 }
            }
        }
    }
}

private enum UsageTab:String,CaseIterable,Identifiable {
    case overview,codex,claude,cursor
    var id:String { rawValue }
    var title:String {
        switch self { case .overview:return L("Genel bakış"); case .codex:return "Codex"; case .claude:return "Claude"; case .cursor:return "Cursor" }
    }
    var glyph:String {
        switch self { case .overview:return "square.grid.2x2"; case .codex:return "terminal"; case .claude:return "asterisk"; case .cursor:return "cursorarrow.rays" }
    }
    var tint:Color {
        switch self { case .overview:return .primary
        case .codex:return Color(red:0.39,green:0.57,blue:0.45)
        case .claude:return Color(red:254.0/255,green:90.0/255,blue:0)
        case .cursor:return Color(red:0.49,green:0.51,blue:0.70) }
    }
}

/// A quiet native toolbar, flat usage rows and one small action strip.
struct MenuUsagePopover:View {
    @ObservedObject private var language=StudioLanguage.shared
    @ObservedObject private var monitor:MenuUsageMonitor
    private var embedded=false
    @Environment(\.openWindow) private var openWindow
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var selected:UsageTab = .overview
    @State private var action:Task<Void,Never>?
    init(monitor:MenuUsageMonitor,embedded:Bool=false,tab:String="overview") {
        _monitor=ObservedObject(wrappedValue:monitor); self.embedded=embedded
        _selected=State(initialValue:UsageTab(rawValue:tab) ?? .overview)
    }
    #if STUDIO_UI_PREVIEW
    init(preview:MenuUsageSnapshot,tab:String="overview") {
        _monitor=ObservedObject(wrappedValue:MenuUsageMonitor(preview:preview))
        _selected=State(initialValue:UsageTab(rawValue:tab) ?? .overview)
    }
    #endif

    var body:some View {
        VStack(spacing:0) {
            tabs
            Divider().padding(.horizontal,14)
            VStack(alignment:.leading,spacing:0) {
                if monitor.offline {
                    Label(L("Yerel köprü çevrimdışı"),systemImage:"wifi.slash")
                        .font(.system(size:11)).foregroundStyle(.orange)
                        .padding(.top,12).padding(.bottom,4)
                        .help(L("Yerel köprüye erişilemiyor. Son değerler güncel olmayabilir."))
                }
                if selected == .overview { overview }
                else { detail(provider(selected)) }
                if let message=monitor.syncMessage {
                    Text(L(message)).font(.system(size:10)).foregroundStyle(.secondary)
                        .fixedSize(horizontal:false,vertical:true).padding(.bottom,10)
                }
            }.padding(.horizontal,18)
            if !embedded { Divider().padding(.horizontal,14); footer }
        }
        .frame(width:embedded ? nil:380,alignment:.topLeading)
        .frame(maxWidth:.infinity,alignment:.topLeading)
        .background(.regularMaterial)
        .environment(\.locale,language.locale)
        .task { if !embedded { await monitor.poll() } }
        .onDisappear { action?.cancel(); action=nil }
        .onChange(of:language.selection) { _,_ in StudioMenuLocalization.refresh() }
    }

    private var tabs:some View {
        HStack(spacing:3) {
            ForEach(UsageTab.allCases) { tab in
                let value=provider(tab)
                Button {
                    withAnimation(reduceMotion ? nil:.easeOut(duration:0.12)) { selected=tab }
                } label: {
                    VStack(spacing:5) {
                        HStack(spacing:5) {
                            Image(systemName:tab.glyph).font(.system(size:13,weight:.medium))
                            Text(tab.title).font(.system(size:11,weight:selected == tab ? .semibold:.medium)).lineLimit(1)
                        }.frame(height:18)
                        if tab != .overview {
                            QuotaMeter(value:value.remaining,tint:tab.tint,stale:value.isStale(at:monitor.measuredNow,offline:monitor.offline),height:3)
                                .frame(width:48)
                        } else { Color.clear.frame(width:48,height:3) }
                    }.frame(maxWidth:.infinity).padding(.vertical,9)
                        .foregroundStyle(selected == tab ? Color.primary:Color.secondary)
                        .background(selected == tab ? Color.primary.opacity(0.065):.clear,in:RoundedRectangle(cornerRadius:7))
                        .contentShape(RoundedRectangle(cornerRadius:7))
                }.buttonStyle(.plain).accessibilityLabel(tab.title)
                    .accessibilityAddTraits(selected == tab ? .isSelected:[])
                    .accessibilityIdentifier("quota-tab-"+tab.rawValue)
            }
        }.padding(.horizontal,8).padding(.vertical,8)
    }

    private var overview:some View {
        VStack(spacing:0) {
            ForEach([UsageTab.codex,.claude,.cursor]) { tab in
                let row=provider(tab)
                let stale=row.isStale(at:monitor.measuredNow,offline:monitor.offline)
                Button { selected=tab } label: {
                    VStack(alignment:.leading,spacing:7) {
                        HStack(alignment:.firstTextBaseline,spacing:8) {
                            Image(systemName:tab.glyph).font(.system(size:12,weight:.medium)).foregroundStyle(tab.tint).frame(width:15)
                            Text(row.name).font(.system(size:13,weight:.semibold))
                            Text(windowLabel(row.remainingLabel ?? "Bilinmiyor")).font(.system(size:10)).foregroundStyle(.secondary).lineLimit(1)
                            Spacer(minLength:4)
                            Text(percent(row.remaining)).font(.system(size:16,weight:.semibold)).monospacedDigit()
                        }
                        QuotaMeter(value:row.remaining,tint:tab.tint,stale:stale,height:4)
                        HStack(spacing:5) {
                            if let reset=row.selectedWindow?.resetDate {
                                Text(L("Yenilenme: {0}",resetText(reset)))
                            } else { Text(L(row.remaining == nil ? "Henüz kullanım verisi yok.":"Kalan kullanım hakları")) }
                            Spacer(minLength:5)
                            freshness(known:row.remaining != nil,stale:stale)
                        }.font(.system(size:10)).foregroundStyle(.secondary).lineLimit(1)
                    }.padding(.vertical,13).contentShape(Rectangle())
                }.buttonStyle(.plain).accessibilityLabel(row.name+", "+percent(row.remaining))
                    .help(L("Sağlayıcı ayrıntılarını göster"))
                if tab != .cursor { Divider() }
            }
        }
    }

    private func detail(_ row:MenuUsageProvider)->some View {
        VStack(alignment:.leading,spacing:0) {
            HStack(alignment:.center,spacing:9) {
                Image(systemName:selected.glyph).font(.system(size:19,weight:.medium)).foregroundStyle(selected.tint)
                Text(row.name).font(.system(size:17,weight:.semibold))
                Spacer()
                if let measured=MenuUsageSnapshot.date(row.updatedAt) {
                    Text(L("Ölçüm: {0}",measured.formatted(.dateTime.hour().minute().locale(language.locale))))
                        .font(.system(size:10)).foregroundStyle(.secondary)
                        .help(measured.formatted(.dateTime.month().day().hour().minute().locale(language.locale)))
                }
            }.padding(.top,16).padding(.bottom,13)
            if row.visibleWindows.isEmpty {
                VStack(alignment:.leading,spacing:6) {
                    Text("—").font(.system(size:27,weight:.medium)).foregroundStyle(.tertiary)
                    Text(L("Henüz kullanım verisi yok.")).font(.system(size:12)).foregroundStyle(.secondary)
                    Text(L("Kullanımı yenileyebilir veya Studio’da ayrıntıları açabilirsiniz."))
                        .font(.system(size:11)).foregroundStyle(.secondary).fixedSize(horizontal:false,vertical:true)
                }.padding(.bottom,20)
            } else {
                VStack(spacing:0) {
                        ForEach(Array(row.visibleWindows.enumerated()),id:\.offset) { index,window in
                            let stale=window.isStale(at:monitor.measuredNow,offline:monitor.offline)
                            VStack(alignment:.leading,spacing:8) {
                                HStack(alignment:.firstTextBaseline) {
                                    Text(windowLabel(window.label)).font(.system(size:12,weight:.medium))
                                    Spacer()
                                    Text(percent(window.remaining)).font(.system(size:20,weight:.semibold)).monospacedDigit()
                                }
                                QuotaMeter(value:window.remaining,tint:selected.tint,stale:stale,height:5)
                                HStack {
                                    if let reset=window.resetDate { Text(L("Yenilenme: {0}",resetText(reset))) }
                                    else { Text(L("Yenilenme zamanı bilinmiyor")) }
                                    Spacer(minLength:5)
                                    freshness(known:window.remaining != nil,stale:stale)
                                }.font(.system(size:10)).foregroundStyle(.secondary).lineLimit(1)
                            }.padding(.vertical,12)
                            if index < row.visibleWindows.count-1 { Divider() }
                        }
                }
                if (row.windows?.count ?? 0)>row.visibleWindows.count {
                    Text(L("Diğer pencereler Studio’da gösterilir.")).font(.system(size:10)).foregroundStyle(.secondary).padding(.bottom,10)
                }
            }
        }
    }

    private var footer:some View {
        HStack(spacing:7) {
            Button { StudioLaunch.activateWindow(); openWindow(id:"studio") } label: {
                HStack(spacing:6) {
                    Image(systemName:"macwindow").font(.system(size:11))
                    Text(L("Studio’yu aç")).font(.system(size:11,weight:.medium))
                }.padding(.vertical,6)
            }.buttonStyle(.plain)
            Spacer()
            Button { perform { await monitor.requestRefresh() } } label: {
                Image(systemName:"arrow.clockwise").font(.system(size:12)).frame(width:25,height:25)
            }.buttonStyle(.plain).disabled(monitor.refreshing || monitor.syncing)
                .help(L("Kullanımı yenile")).accessibilityLabel(L("Kullanımı yenile"))
            Button { perform { await monitor.syncClock() } } label: {
                Image(systemName:"clock.arrow.circlepath").font(.system(size:12)).frame(width:25,height:25)
            }.buttonStyle(.plain).disabled(!monitor.canSync)
                .help(L("Tarih ve saati eşitle")).accessibilityLabel(L("Tarih ve saati eşitle"))
            #if STUDIO_UI_PREVIEW
            Image(systemName:"gearshape").font(.system(size:12)).frame(width:25,height:25)
            #else
            Menu {
                Picker(L("Dil"),selection:$language.selection) {
                    Text(L("Sistem dili")).tag("system")
                    ForEach(LocalizationCatalog.codes,id:\.self) { Text(StudioLanguage.names[$0]!).tag($0) }
                }
                Divider()
                Button(L("Quit AMG65 Studio")) { NSApp.terminate(nil) }
            } label: {
                Image(systemName:"gearshape").font(.system(size:12)).frame(width:25,height:25)
            }.menuStyle(.borderlessButton).menuIndicator(.hidden).fixedSize()
                .help(L("Ayarlar ve dil")).accessibilityLabel(L("Ayarlar ve dil"))
            #endif
        }.foregroundStyle(.secondary).padding(.horizontal,18).padding(.vertical,7)
    }

    @ViewBuilder private func freshness(known:Bool,stale:Bool)->some View {
        if !known { Text(L("Bilinmiyor")).foregroundStyle(.secondary) }
        else if stale {
            HStack(spacing:3) { Image(systemName:"clock"); Text(L("Eski veri")) }.foregroundStyle(.orange)
        } else { Text(L("Kalan")).foregroundStyle(.secondary) }
    }
    private func provider(_ tab:UsageTab)->MenuUsageProvider { monitor.providers.first{$0.id == tab.rawValue} ?? .unknown(tab.rawValue) }
    private func percent(_ value:Double?)->String {
        guard let value else { return "—" }
        return (value/100).formatted(.percent.precision(.fractionLength(0)).locale(language.locale))
    }
    private func windowLabel(_ value:String)->String { MenuUsageSnapshot.windowLabel(value,catalog:language.catalog,language:language.resolved) }
    private func resetText(_ date:Date)->String { date.formatted(.dateTime.month(.abbreviated).day().hour().minute().locale(language.locale)) }
    private func perform(_ work:@escaping @MainActor () async -> Void) { action?.cancel(); action=Task { await work() } }
}

/// A measured value fills the rail; an unknown value is a dotted rail, never zero.
private struct QuotaMeter:View {
    let value:Double?
    let tint:Color
    let stale:Bool
    let height:CGFloat
    var body:some View {
        GeometryReader { proxy in
            ZStack(alignment:.leading) {
                Capsule().fill(Color.primary.opacity(0.09))
                if let value {
                    Capsule().fill(tint.opacity(stale ? 0.4:0.85)).frame(width:proxy.size.width*CGFloat(value/100))
                } else {
                    Capsule().strokeBorder(Color.secondary.opacity(0.3),style:StrokeStyle(lineWidth:1,dash:[2,3]))
                }
            }
        }.frame(height:height).accessibilityHidden(true)
    }
}

private enum MenuSection:String,CaseIterable,Identifiable {
    case usage,display,lighting,keys,lcd,led,device,accounts
    var id:String { rawValue }
    var title:String {
        switch self {
        case .usage:L("Kullanım hakları")
        case .display:L("Gösterim")
        case .lighting:L("Aydınlatma")
        case .keys:L("Tuş atamaları")
        case .lcd:L("LCD ekran")
        case .led:L("LED animasyonu")
        case .device:L("Cihaz ayarları")
        case .accounts:L("Hesaplar")
        }
    }
    var icon:String {
        switch self {
        case .usage:"chart.bar.xaxis"
        case .display:"text.rectangle"
        case .lighting:"lightbulb"
        case .keys:"keyboard"
        case .lcd:"photo.on.rectangle"
        case .led:"rectangle.split.3x1"
        case .device:"slider.horizontal.3"
        case .accounts:"person.crop.circle"
        }
    }
    var native:Bool { ![Self.usage,.display,.accounts].contains(self) }
}

/// All settings stay in the status-item panel. Only the two keyboard canvases widen.
struct StudioMenuPopover:View {
    @ObservedObject private var language=StudioLanguage.shared
    @EnvironmentObject private var session:DriverSession
    @EnvironmentObject private var hid:KeyboardHID
    @Environment(\.openWindow) private var openWindow
    @StateObject private var monitor=MenuUsageMonitor()
    @StateObject private var display=MenuDisplayModel()
    @StateObject private var accounts=MenuAccountsModel()
    @State private var section:MenuSection = .usage
    @State private var menuVisible=false
    @State private var perKey=false
    @State private var action:Task<Void,Never>?
    private var initialUsageTab="overview"
    init() {}
    #if STUDIO_UI_PREVIEW
    init(preview:MenuUsageSnapshot,section:String="usage",tab:String="overview",previewAccounts:[MenuAccount]=[]) {
        _monitor=StateObject(wrappedValue:MenuUsageMonitor(preview:preview))
        _section=State(initialValue:MenuSection(rawValue:section) ?? .usage)
        let model=MenuDisplayModel();model.receive(preview)
        _display=StateObject(wrappedValue:model)
        if !previewAccounts.isEmpty { _accounts=StateObject(wrappedValue:MenuAccountsModel(preview:previewAccounts)) }
        initialUsageTab=tab
    }
    #endif
    private var wide:Bool { section == .keys || (section == .lighting && perKey) }
    var body:some View {
        HStack(alignment:.top,spacing:0) {
            navigation
            Divider()
            VStack(spacing:0) {
                header
                Divider()
                #if STUDIO_UI_PREVIEW && !STUDIO_HOST_PREVIEW
                // ImageRenderer cannot render AppKit's NSScrollView. Keep the
                // production content and exact top anchor, clipped to its viewport.
                VStack(alignment:.leading,spacing:0) {
                    content.padding(section == .usage ? 0:16)
                    Spacer(minLength:0)
                }.frame(maxWidth:.infinity,maxHeight:.infinity,alignment:.topLeading).clipped()
                #else
                ScrollViewReader { scroll in
                    ScrollView {
                        VStack(alignment:.leading,spacing:0) {
                            content.padding(section == .usage ? 0:16)
                        }.frame(maxWidth:.infinity,alignment:.topLeading).id("menu-content-top")
                    }.defaultScrollAnchor(.top)
                        .onChange(of:section) { _,_ in scroll.scrollTo("menu-content-top",anchor:.top) }
                }.frame(maxWidth:.infinity,maxHeight:.infinity,alignment:.topLeading)
                #endif
                Divider()
                footer
            }
        }.frame(width:wide ? 760:460,height:section == .usage ? 410:600)
            .background(.regularMaterial)
            .background(MenuWindowVisibilityBridge { visible in
                Task { @MainActor in
                    guard menuVisible != visible else { return }
                    menuVisible=visible
                    if !visible { accounts.clearInput() }
                    session.setNativeRequested(visible && section.native,by:"menu")
                }
            })
            .environment(\.locale,language.locale)
            .environment(\.studioCompact,true)
            .task(id:menuVisible) { if menuVisible { await monitor.poll() } }
            .task(id:section.rawValue+String(menuVisible)) {
                if menuVisible && section == .accounts { await accounts.poll() }
            }
            .onAppear {
                accounts.openAuthorization={ url in NSWorkspace.shared.open(url) }
                display.receive(monitor.snapshot)
            }
            .onChange(of:monitor.measuredNow) { _,_ in display.receive(monitor.snapshot) }
            .onChange(of:language.selection) { _,_ in StudioMenuLocalization.refresh() }
            .onDisappear {
                action?.cancel();action=nil;accounts.clearInput()
            }
    }
    private var navigation:some View {
        VStack(spacing:5) {
            Image(systemName:"keyboard.badge.ellipsis").font(.system(size:18)).padding(.top,17).padding(.bottom,14).accessibilityHidden(true)
            ForEach(MenuSection.allCases) { target in
                Button {
                    section=target
                    session.setNativeRequested(menuVisible && target.native,by:"menu")
                } label: {
                    Image(systemName:target.icon).font(.system(size:16,weight:section == target ? .semibold:.regular))
                        .frame(width:36,height:37)
                        .foregroundStyle(section == target ? Color.accentColor:Color.secondary)
                        .background(section == target ? Color.accentColor.opacity(0.12):.clear,in:RoundedRectangle(cornerRadius:8))
                }.buttonStyle(.plain).help(target.title).accessibilityLabel(target.title)
                    .accessibilityAddTraits(section == target ? .isSelected:[])
                    .accessibilityIdentifier("menu-section-"+target.rawValue)
                    .disabled(hid.busy || session.acquiring || session.releasing)
            }
            Spacer(minLength:8)
        }.frame(width:50)
    }
    private var header:some View {
        let reconnect=monitor.bridgeState == .faultReconnect || (section.native && hid.failedRegistryID != nil)
        return VStack(alignment:.leading,spacing:3) {
            HStack(spacing:10) {
                Text(section.title).font(.system(size:15,weight:.semibold)).lineLimit(1)
                Spacer(minLength:4)
                if reconnect {
                    Label {
                        Text(L("LED aktarımı durdu")).foregroundStyle(.primary)
                    } icon: {
                        Image(systemName:"exclamationmark.triangle.fill").foregroundStyle(.orange)
                    }.font(.system(size:10,weight:.medium)).lineLimit(1)
                } else if section.native {
                    if session.acquiring || session.releasing || hid.busy { ProgressView().controlSize(.small) }
                    else if session.active && hid.connection != .none && hid.failedRegistryID==nil {
                        Image(systemName:"cable.connector").foregroundStyle(.mint).help(L("USB bağlı"))
                    } else if session.active {
                        Image(systemName:"questionmark.circle").foregroundStyle(.secondary).help(L("USB durumu bilinmiyor"))
                    } else {
                        Button(L("Yeniden bağlan")) { session.setNativeRequested(menuVisible,by:"menu") }.font(.system(size:11))
                    }
                } else {
                    bridgeIndicator
                }
            }
            if reconnect {
                Text(L("USB kablosunu çıkarıp yeniden takın."))
                    .font(.system(size:10)).foregroundStyle(.primary).lineLimit(1).minimumScaleFactor(0.85)
            }
        // Reuse the existing header: warnings do not shift tabs or enlarge the 410pt usage panel.
        }.padding(.horizontal,18).frame(height:53)
    }
    private var bridgeIndicator:some View {
        let state=monitor.bridgeState
        let symbol:String = switch state {
        case .offline:"wifi.slash"
        case .faultReconnect:"exclamationmark.triangle.fill"
        case .nativeControl:"hand.raised"
        case .displayDisabled:"pause.circle"
        case .streaming:"dot.radiowaves.left.and.right"
        case .ready:"cable.connector"
        case .noDevice:"cable.connector"
        case .unknown:"questionmark.circle"
        }
        let tint:Color = switch state {
        case .ready,.streaming:.mint
        case .offline,.faultReconnect,.noDevice:.orange
        default:.secondary
        }
        return Image(systemName:symbol).foregroundStyle(tint)
            .help(L(state.titleKey)).accessibilityLabel(L(state.titleKey))
    }
    @ViewBuilder private var content:some View {
        switch section {
        case .usage: MenuUsagePopover(monitor:monitor,embedded:true,tab:initialUsageTab)
        case .display: MenuDisplayControls(model:display,offline:monitor.offline) { perform { await display.save(); await monitor.refresh();display.receive(monitor.snapshot) } }
        case .accounts: accountControls
        default:
            VStack(alignment:.leading,spacing:12) {
                Text(L(session.message)).font(.system(size:11)).foregroundStyle(.secondary).fixedSize(horizontal:false,vertical:true)
                if let error=hid.error { Text(L(error)).font(.system(size:11)).foregroundStyle(.orange).fixedSize(horizontal:false,vertical:true) }
                if section == .lighting {
                    Picker(L("Aydınlatma"),selection:$perKey) {
                        Text(L("Efekt")).tag(false)
                        Text(L("Tuş renkleri")).tag(true)
                    }.pickerStyle(.segmented).disabled(hid.busy)
                }
                Group {
                    switch section {
                    case .lighting: if perKey { PerKeyControls() } else { LightingControls() }
                    case .keys: KeyControls()
                    case .lcd: LCDControls()
                    case .led: StripControls()
                    case .device: DeviceControls()
                    default: EmptyView()
                    }
                }.disabled(!session.active || hid.busy || session.releasing)
                Text(L("Gösterilen ayarlar yerel tercihlerdir; cihazdan geri okuma yapılmaz."))
                    .font(.system(size:10)).foregroundStyle(.secondary).fixedSize(horizontal:false,vertical:true)
            }
        }
    }
    private var footer:some View {
        HStack(spacing:5) {
            Button { StudioLaunch.activateWindow();openWindow(id:"studio") } label: {
                Image(systemName:"macwindow").font(.system(size:12)).frame(width:26,height:28)
            }.buttonStyle(.plain).help(L("Studio’yu aç")).accessibilityLabel(L("Studio’yu aç"))
            Spacer()
            Button { perform { await monitor.requestRefresh();if section == .accounts { await accounts.refresh() } } } label: {
                Image(systemName:"arrow.clockwise").frame(width:26,height:28)
            }.buttonStyle(.plain).disabled(monitor.refreshing || monitor.syncing)
                .help(L("Kullanımı yenile")).accessibilityLabel(L("Kullanımı yenile"))
            Button { perform { await monitor.syncClock() } } label: {
                Image(systemName:"clock.arrow.circlepath").frame(width:26,height:28)
            }.buttonStyle(.plain).disabled(!monitor.canSync)
                .help(L("Tarih ve saati eşitle")).accessibilityLabel(L("Tarih ve saati eşitle"))
            #if STUDIO_UI_PREVIEW
            Image(systemName:"gearshape").frame(width:26,height:28)
            #else
            Menu {
                Picker(L("Dil"),selection:$language.selection) {
                    Text(L("Sistem dili")).tag("system")
                    ForEach(LocalizationCatalog.codes,id:\.self) { Text(StudioLanguage.names[$0]!).tag($0) }
                }
                Divider()
                Button(L("Quit AMG65 Studio")) { NSApp.terminate(nil) }
            } label: { Image(systemName:"gearshape").frame(width:26,height:28) }
                .menuStyle(.borderlessButton).menuIndicator(.hidden).fixedSize()
                .help(L("Ayarlar ve dil")).accessibilityLabel(L("Ayarlar ve dil"))
            #endif
        }.font(.system(size:12)).foregroundStyle(.secondary).padding(.horizontal,14).padding(.vertical,5)
    }
    private var accountControls:some View {
        VStack(alignment:.leading,spacing:0) {
            Text(L("Hesap bağlantılarınızı buradan yönetin."))
                .font(.system(size:12)).foregroundStyle(.secondary).fixedSize(horizontal:false,vertical:true).padding(.bottom,10)
            ForEach([UsageTab.codex,.claude,.cursor]) { provider in
                let row=accounts.row(provider.rawValue)
                let connection=accounts.connection(row)
                VStack(alignment:.leading,spacing:10) {
                    HStack(spacing:8) {
                        Image(systemName:provider.glyph).foregroundStyle(provider.tint)
                        Text(provider.title).font(.system(size:14,weight:.semibold))
                        Spacer()
                        if row.pending { ProgressView().controlSize(.small) }
                        else if connection == .connected {
                            Label(L("Bağlı"),systemImage:"checkmark.circle.fill")
                                .font(.system(size:10,weight:.medium)).foregroundStyle(.green)
                                .padding(.horizontal,7).padding(.vertical,4)
                                .background(Color.green.opacity(0.1),in:Capsule())
                        }
                    }
                    Text(accountMessage(row)).font(.system(size:11)).foregroundStyle(connection != .connected && row.phase == "error" ? Color.orange:Color.secondary)
                        .fixedSize(horizontal:false,vertical:true)
                    if let code=row.userCode,!code.isEmpty {
                        HStack {
                            Text(code).font(.system(size:16,weight:.semibold,design:.monospaced)).textSelection(.enabled)
                            Spacer()
                            Button(L("Kodu kopyala")) { NSPasteboard.general.clearContents();NSPasteboard.general.setString(code,forType:.string) }.font(.system(size:11))
                        }
                    }
                    if row.inputRequired == true {
                        SecureField(L("Yetkilendirme kodu"),text:Binding(get:{accounts.inputCodes[row.provider] ?? ""},set:{accounts.inputCodes[row.provider]=String($0.prefix(2048))}))
                            .textFieldStyle(.roundedBorder)
                        Button(L("Kodu gönder")) { perform { await accounts.submit(row.provider) } }
                            .disabled(accounts.inputCodes[row.provider]?.isEmpty != false || accounts.busy)
                    }
                    if row.phase == "awaiting_confirmation",row.interaction == "workspace_trust",
                       row.actions?.contains("trust_login_workspace")==true {
                        Text(L("Claude, Studio’nun özel giriş klasörüne güvenmenizi istiyor."))
                            .font(.system(size:11)).foregroundStyle(.secondary).fixedSize(horizontal:false,vertical:true)
                        Button(L("Giriş klasörüne güven ve devam et")) { perform { await accounts.confirmWorkspace(row.provider) } }
                            .disabled(accounts.busy)
                    }
                    HStack {
                        if !row.pending {
                            if connection == .connected {
                                Button(L("Hesap değiştir")) { connect(provider.rawValue) }
                                    .buttonStyle(.bordered).disabled(accounts.busy || accounts.offline)
                            } else if connection == .requiresSignIn {
                                Button(L("Yeniden giriş yap")) { connect(provider.rawValue) }
                                    .buttonStyle(.borderedProminent).disabled(accounts.busy || accounts.offline)
                            } else {
                                Button(L("Kullanımı yenile")) { perform { await monitor.requestRefresh();await accounts.refresh() } }
                                    .buttonStyle(.bordered).disabled(accounts.busy || monitor.refreshing)
                                Button(L(provider == .cursor ? "Cursor’da giriş yap":"Giriş yap")) { connect(provider.rawValue) }
                                    .buttonStyle(.plain).disabled(accounts.busy || accounts.offline)
                            }
                        }
                        if let url=MenuAccountsModel.authorizationURL(row.authURL,provider:row.provider),row.pending {
                            Button(L("Tarayıcıyı aç")) { NSWorkspace.shared.open(url) }.disabled(accounts.busy)
                        }
                        if row.pending {
                            Button(L("İptal")) { perform { await accounts.cancel(row.provider) } }.disabled(accounts.busy)
                        }
                    }.font(.system(size:11))
                }.padding(.vertical,15)
                if provider != .cursor { Divider() }
            }
            if accounts.offline { Text(L("Yerel köprü çevrimdışı")).font(.system(size:11)).foregroundStyle(.orange).padding(.top,8) }
            if let message=accounts.message { Text(L(message)).font(.system(size:11)).foregroundStyle(.orange).padding(.top,8) }
        }
    }
    private func accountMessage(_ row:MenuAccount)->String {
        let connection=accounts.connection(row)
        if connection == .connected {
            if accounts.offline { return L("Yerel köprü çevrimdışı") }
            if row.usage?.fresh(at:Date())==true { return L("Kullanım bilgisi güncel.") }
            if row.usage?.transient==true { return L("Kullanım geçici olarak yenilenemiyor. Hesabınızın yeniden bağlanması gerekmiyor.") }
            if row.usage?.hasMeasurement(at:Date())==true { return L("Son kullanım bilgisi güncel değil. Yenileyebilirsiniz.") }
            return L("Hesap bağlı. Kullanım bilgisi henüz alınamadı.")
        }
        if connection == .requiresSignIn {
            return L(row.provider == "cursor" ? "Cursor uygulamasında giriş yaptıktan sonra kullanımı yenileyin.":"Hesabınıza yeniden giriş yapmanız gerekiyor.")
        }
        if row.provider == "cursor",row.pending { return L("Cursor uygulamasında giriş yaptıktan sonra kullanımı yenileyin.") }
        switch row.phase {
        case "starting":return L("Giriş başlatılıyor…")
        case "awaiting_browser":return L("Tarayıcıda giriş işlemini tamamlayın.")
        case "awaiting_code":return L("Tarayıcının verdiği yetkilendirme kodunu girin.")
        case "awaiting_confirmation":return L("Claude giriş izni bekliyor.")
        case "cancelled":return L("Giriş iptal edildi.")
        case "error":
            switch row.error {
            case "cli_unavailable":return L("Sağlayıcının komut satırı uygulaması bulunamadı.")
            case "login_timeout":return L("Giriş süresi doldu. Yeniden deneyin.")
            case "code_rejected":return L("Kod kabul edilmedi. Yeni bir giriş başlatın.")
            case "login_interaction_required":return L("Girişi sağlayıcının uygulamasında tamamlayın.")
            default:return L("Giriş tamamlanamadı. Yeniden deneyin.")
            }
        default:
            if row.usage?.inaccessible==true { return L("Hesap bilgilerine erişilemiyor. Erişim izinlerini kontrol edin.") }
            return L("Bağlantı henüz doğrulanamadı. Kullanımı yenileyin.")
        }
    }
    private func connect(_ provider:String) {
        perform {
            await accounts.start(provider)
            if provider == "cursor",let url=NSWorkspace.shared.urlForApplication(withBundleIdentifier:"com.todesktop.230313mzl4w4u92") {
                NSWorkspace.shared.openApplication(at:url,configuration:NSWorkspace.OpenConfiguration()) { _,_ in }
            }
        }
    }
    private func perform(_ work:@escaping @MainActor () async -> Void) { action?.cancel();action=Task { await work() } }
}

private struct MenuDisplayControls:View {
    @ObservedObject var model:MenuDisplayModel
    let offline:Bool
    let apply:()->Void
    var body:some View {
        VStack(alignment:.leading,spacing:19) {
            Toggle(L("Canlı LED görünümü"),isOn:$model.enabled)
            VStack(alignment:.leading,spacing:7) {
                Picker(L("Gösterilecek araç"),selection:$model.draft.trackedProvider) {
                    Text(L("Otomatik")).tag("all")
                    Text("Claude").tag("claude")
                    Text("Codex").tag("codex")
                    Text("Cursor").tag("cursor")
                }.pickerStyle(.menu)
                Text(L("Seçilen aracın durumları ve çalışma adımları gösterilir."))
                    .font(.system(size:11)).foregroundStyle(.secondary).fixedSize(horizontal:false,vertical:true)
            }
            if model.draft.trackedProvider == "all" {
                Picker(L("Görünüm"),selection:$model.draft.displayMode) {
                    Text(L("Toplu görünüm")).tag("overview")
                    Text(L("Sırayla göster")).tag("rotate")
                    Text(L("Özel metin")).tag("text")
                }.pickerStyle(.menu)
            }
            VStack(alignment:.leading,spacing:7) {
                Picker(L("Yazı efekti"),selection:$model.draft.textEffect) {
                    Text(L("Sade")).tag("none")
                    Text(L("Tarama")).tag("scan")
                    Text(L("Nefes")).tag("breathe")
                    Text(L("Matrix")).tag("matrix")
                    Text(L("Kayan yazı")).tag("scroll")
                }.pickerStyle(.menu)
                Text(L("Efektler metin ve kota görünümlerinde kullanılır; onay, bilgi ve hata uyarıları sabit kalır."))
                    .font(.system(size:10)).foregroundStyle(.secondary).fixedSize(horizontal:false,vertical:true)
            }
            if model.draft.trackedProvider == "all" && model.draft.displayMode == "text" {
                VStack(alignment:.leading,spacing:7) {
                    TextField(L("Özel metin"),text:$model.draft.text).textFieldStyle(.roundedBorder)
                    Text(L("En fazla 64 ASCII karakter. LED metni büyük harfle gösterilir."))
                        .font(.system(size:10)).foregroundStyle(.secondary).fixedSize(horizontal:false,vertical:true)
                    InlineColorControls(title:"Yazı rengi",value:RGB.parse(hex:model.draft.textColor) ?? RGB(r:123,g:220,b:176)) { value in
                        model.draft.textColor=value.hex.lowercased()
                    }
                }
            }
            VStack(alignment:.leading,spacing:7) {
                HStack { Text(L("Parlaklık"));Spacer();Text(model.draft.brightness.formatted(.percent.precision(.fractionLength(0)))).monospacedDigit() }
                Slider(value:$model.draft.brightness,in:0...1,step:0.05)
            }
            Divider()
            Toggle(L("Çalışma ve bekleme durumlarını göster"),isOn:$model.draft.activityEnabled)
            Text(L("Desteklenen olaylarda çalışma, onay ve bilgi bekleme durumları kullanımın yanında gösterilir."))
                .font(.system(size:11)).foregroundStyle(.secondary).fixedSize(horizontal:false,vertical:true)
            VStack(alignment:.leading,spacing:7) {
                Toggle(L("Araç maskotları"),isOn:$model.draft.mascotEnabled)
                Text(L("Claude yengeci, Codex robotu ve Cursor imleci; seçilen araçta veya Otomatik'te gözlenen duruma göre hareket eder."))
                    .font(.system(size:11)).foregroundStyle(.secondary).fixedSize(horizontal:false,vertical:true)
            }
            HStack {
                Button(L("Uygula"),action:apply).buttonStyle(.borderedProminent)
                    .disabled(!model.loaded || !model.dirty || !model.draft.valid || model.saving || offline)
                Button(L("Değişiklikleri geri al")) { model.discard() }.disabled(!model.dirty || model.saving)
                Spacer()
                if model.saving { ProgressView().controlSize(.small) }
            }
            if !model.draft.valid { Text(L("Metni ve rengi kontrol edin.")).font(.system(size:11)).foregroundStyle(.orange) }
            if let message=model.message { Text(L(message)).font(.system(size:11)).foregroundStyle(.secondary).fixedSize(horizontal:false,vertical:true) }
            if !model.loaded { Text(L("Ekran ayarları bekleniyor…")).font(.system(size:11)).foregroundStyle(.secondary) }
        }.font(.system(size:12)).disabled(model.saving)
    }
}
