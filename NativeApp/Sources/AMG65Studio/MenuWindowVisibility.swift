import AppKit
import SwiftUI

/// Observes ordered-in visibility, never keyboard focus or the visible occlusion region.
/// A covered window, ColorPicker, or file panel must not release the menu's USB demand.
@MainActor final class MenuWindowVisibilityObservation {
    private let center:NotificationCenter
    private let readVisible:()->Bool
    private let changed:(Bool)->Void
    private var observers=[NSObjectProtocol]()
    private var timer:Timer?
    private var last:Bool?
    private var closing=false
    private var stopped=false

    init(object:NSObject,center:NotificationCenter = .default,startTimer:Bool = true,
         isVisible:@escaping()->Bool,onChange:@escaping(Bool)->Void) {
        self.center=center;readVisible=isVisible;changed=onChange
        for name in [NSWindow.didChangeOcclusionStateNotification,NSWindow.didBecomeKeyNotification,
                     NSWindow.didResignKeyNotification,NSWindow.didExposeNotification,
                     NSWindow.didDeminiaturizeNotification] {
            observers.append(center.addObserver(forName:name,object:object,queue:.main) { [weak self] note in
                MainActor.assumeIsolated {
                    if [NSWindow.didBecomeKeyNotification,NSWindow.didExposeNotification,
                        NSWindow.didDeminiaturizeNotification].contains(note.name) { self?.closing=false }
                    // AppKit can post before finishing the order change. Read next turn.
                    self?.scheduleSample()
                }
            })
        }
        observers.append(center.addObserver(forName:NSWindow.willCloseNotification,object:object,queue:.main) { [weak self] _ in
            MainActor.assumeIsolated { self?.closing=true;self?.scheduleSample() }
        })
        if startTimer {
            // Occlusion notifications can coalesce when already covered. A cheap
            // boolean sample guarantees orderOut is detected even in that case.
            let timer=Timer(timeInterval:0.5,repeats:true) { [weak self] _ in
                MainActor.assumeIsolated { self?.sample() }
            }
            timer.tolerance=0.25;self.timer=timer
            RunLoop.main.add(timer,forMode:.common)
        }
        scheduleSample()
    }
    private func scheduleSample() {
        DispatchQueue.main.async { [weak self] in self?.sample() }
    }
    func sample() {
        guard !stopped else { return }
        report(!closing && readVisible())
    }
    private func report(_ visible:Bool) {
        guard last != visible else { return }
        last=visible;changed(visible)
    }
    func stop() {
        guard !stopped else { return }
        stopped=true;timer?.invalidate();timer=nil
        observers.forEach(center.removeObserver);observers.removeAll()
        report(false)
    }
    deinit {
        timer?.invalidate()
        observers.forEach(center.removeObserver)
    }
}

struct MenuWindowVisibilityBridge:NSViewRepresentable {
    var onChange:(Bool)->Void
    func makeNSView(context:Context)->Marker {
        let view=Marker();view.onChange=onChange;return view
    }
    func updateNSView(_ view:Marker,context:Context) { view.onChange=onChange }
    static func dismantleNSView(_ view:Marker,coordinator:()) { view.detach() }

    final class Marker:NSView {
        var onChange:((Bool)->Void)?
        private weak var trackedWindow:NSWindow?
        private var observation:MenuWindowVisibilityObservation?
        override func viewDidMoveToWindow() {
            super.viewDidMoveToWindow()
            guard window !== trackedWindow else { return }
            detach();trackedWindow=window
            guard let window else { return }
            observation=MenuWindowVisibilityObservation(object:window,isVisible:{ [weak window] in window?.isVisible == true },
                                                        onChange:{ [weak self] visible in self?.onChange?(visible) })
        }
        func detach() {
            observation?.stop();observation=nil;trackedWindow=nil
        }
    }
}
