// DSHCockpitWidget — native macOS desktop widget for dsh-sentiment-cockpit.
//
// A borderless, always-on-desktop WKWebView window that renders the cockpit
// HTML snapshot and auto-reloads when the pipeline regenerates it.
//
// Two visual states:
//   - full:     420x560 card with header (DSI chip + actions) + dashboard
//   - mini:     small pill "📈 DSI 52.5" — click to expand, "—" to collapse
// Position and collapsed state persist in <cacheDir>/widget-state.json.
//
// Usage (spawned by the DSH host plugin):
//   DSHCockpitWidget <cacheDir> <mode:desktop|floating> <x> <y> <scale> <parentPid> <smoke:0|1>
//
// Build: swiftc -O -o DSHCockpitWidget main.swift

import Cocoa
import WebKit
import CoreGraphics
import Darwin

let args = Array(CommandLine.arguments.dropFirst())
let cacheDir = args.count > 0 ? args[0] : FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent(".dsh/storages/dsh-sentiment-cockpit").path
let mode = args.count > 1 ? args[1] : "desktop"
let smoke = args.count > 6 && args[6] == "1"
let parentPid = args.count > 5 ? Int32(args[5]) ?? 0 : 0
let scale = args.count > 4 ? Double(args[4]) ?? 1.0 : 1.0
let fullW = 420.0 * min(max(scale, 0.7), 1.6)
let fullH = 560.0 * min(max(scale, 0.7), 1.6)
let miniW = 92.0
let miniH = 44.0

let htmlPath = cacheDir + "/cockpit.html"
let snapPath = cacheDir + "/snapshot.json"
let statePath = cacheDir + "/widget-state.json"
let pidPath = cacheDir + "/.widget.pid"

// ---- single instance: replace a stale previous widget -------------------
if FileManager.default.fileExists(atPath: pidPath) {
    if let text = try? String(contentsOfFile: pidPath, encoding: .utf8),
       let old = Int32(text.trimmingCharacters(in: .whitespacesAndNewlines)), old > 1 {
        kill(old, SIGTERM)
    }
}
try? "\(getpid())".write(toFile: pidPath, atomically: true, encoding: .utf8)

final class MiniView: NSView {
    var onTap: (() -> Void)?
    override func mouseDown(with event: NSEvent) { onTap?() }
}

final class AppDelegate: NSObject, NSApplicationDelegate, NSWindowDelegate, WKNavigationDelegate {
    var window: NSWindow!
    var fullView: NSView!
    var miniView: MiniView!
    var webView: WKWebView!
    var dsiLabel: NSTextField!
    var miniLabel: NSTextField!
    var lastMtime: Date = .distantPast
    var timer: Timer?
    var watchdog: Timer?
    var collapsed = false
    var fullFrame: NSRect = .zero
    var miniFrame: NSRect = .zero

    // ---- persisted state ------------------------------------------------
    func loadState() {
        guard let data = FileManager.default.contents(atPath: statePath),
              let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else { return }
        collapsed = obj["collapsed"] as? Bool ?? false
        if let f = obj["full"] as? [String: Any],
           let x = f["x"] as? Double, let y = f["y"] as? Double,
           let w = f["w"] as? Double, let h = f["h"] as? Double {
            fullFrame = NSRect(x: x, y: y, width: w, height: h)
        }
        if let m = obj["mini"] as? [String: Any],
           let x = m["x"] as? Double, let y = m["y"] as? Double {
            miniFrame = NSRect(x: x, y: y, width: miniW, height: miniH)
        }
    }

    func saveState() {
        let obj: [String: Any] = [
            "collapsed": collapsed,
            "full": ["x": fullFrame.origin.x, "y": fullFrame.origin.y, "w": fullFrame.width, "h": fullFrame.height],
            "mini": ["x": miniFrame.origin.x, "y": miniFrame.origin.y],
        ]
        if let data = try? JSONSerialization.data(withJSONObject: obj) {
            try? data.write(to: URL(fileURLWithPath: statePath), options: .atomic)
        }
    }

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.accessory)
        loadState()

        let initial = NSRect(x: 0, y: 0, width: fullW, height: fullH)
        window = NSWindow(contentRect: initial,
                          styleMask: [.borderless],
                          backing: .buffered,
                          defer: false)
        window.isOpaque = false
        window.backgroundColor = .clear
        window.hasShadow = true
        window.isMovableByWindowBackground = true
        window.delegate = self
        if mode == "floating" {
            window.level = .floating
        } else {
            window.level = NSWindow.Level(rawValue: Int(CGWindowLevelForKey(.desktopWindow)))
        }
        window.collectionBehavior = [.canJoinAllSpaces, .stationary, .fullScreenAuxiliary]
        window.title = "社区情绪驾驶舱"

        // ---- full state view --------------------------------------------
        fullView = NSView(frame: NSRect(x: 0, y: 0, width: fullW, height: fullH))
        fullView.wantsLayer = true
        fullView.layer?.cornerRadius = 14
        fullView.layer?.masksToBounds = true
        fullView.layer?.backgroundColor = NSColor(calibratedRed: 0.047, green: 0.055, blue: 0.082, alpha: 0.98).cgColor

        let header = NSView(frame: NSRect(x: 0, y: fullH - 44, width: fullW, height: 44))
        header.wantsLayer = true
        header.layer?.backgroundColor = NSColor(calibratedRed: 0.075, green: 0.086, blue: 0.125, alpha: 1).cgColor

        let title = NSTextField(labelWithString: "社区情绪驾驶舱")
        title.font = NSFont.systemFont(ofSize: 12, weight: .semibold)
        title.textColor = NSColor(calibratedWhite: 0.92, alpha: 1)
        title.frame = NSRect(x: 14, y: 14, width: 140, height: 16)

        dsiLabel = NSTextField(labelWithString: "DSI —")
        dsiLabel.font = NSFont.monospacedDigitSystemFont(ofSize: 11, weight: .medium)
        dsiLabel.textColor = NSColor(calibratedRed: 0.302, green: 0.420, blue: 0.996, alpha: 1)
        dsiLabel.frame = NSRect(x: 158, y: 14.5, width: 160, height: 15)

        func button(_ glyph: String, _ tooltip: String, _ action: Selector) -> NSButton {
            let b = NSButton(title: glyph, target: self, action: action)
            b.isBordered = false
            b.font = NSFont.systemFont(ofSize: 13)
            b.contentTintColor = NSColor(calibratedWhite: 0.78, alpha: 1)
            b.toolTip = tooltip
            b.frame = NSRect(x: 0, y: 9, width: 30, height: 26)
            return b
        }
        let minBtn = button("—", "收起为迷你状态", #selector(minimize))
        let refreshBtn = button("⟳", "刷新快照", #selector(refreshNow))
        let openBtn = button("⧉", "在浏览器中打开快照", #selector(openSnapshot))
        let closeBtn = button("✕", "关闭小组件", #selector(closeWidget))
        minBtn.frame.origin.x = fullW - 118
        openBtn.frame.origin.x = fullW - 88
        refreshBtn.frame.origin.x = fullW - 58
        closeBtn.frame.origin.x = fullW - 30
        header.addSubview(title)
        header.addSubview(dsiLabel)
        header.addSubview(minBtn)
        header.addSubview(refreshBtn)
        header.addSubview(openBtn)
        header.addSubview(closeBtn)

        let config = WKWebViewConfiguration()
        config.websiteDataStore = .nonPersistent()
        webView = WKWebView(frame: NSRect(x: 0, y: 0, width: fullW, height: fullH - 44), configuration: config)
        webView.navigationDelegate = self
        webView.setValue(false, forKey: "drawsBackground")
        webView.loadFileURL(URL(fileURLWithPath: htmlPath), allowingReadAccessTo: URL(fileURLWithPath: cacheDir))

        fullView.addSubview(webView)
        fullView.addSubview(header)

        // ---- mini state view --------------------------------------------
        miniView = MiniView(frame: NSRect(x: 0, y: 0, width: miniW, height: miniH))
        miniView.wantsLayer = true
        miniView.layer?.cornerRadius = miniH / 2
        miniView.layer?.masksToBounds = true
        miniView.layer?.backgroundColor = NSColor(calibratedRed: 0.075, green: 0.086, blue: 0.125, alpha: 0.97).cgColor
        miniView.onTap = { [weak self] in self?.expand() }

        let emoji = NSTextField(labelWithString: "📈")
        emoji.font = NSFont.systemFont(ofSize: 19)
        emoji.frame = NSRect(x: 10, y: 8, width: 30, height: 28)
        miniLabel = NSTextField(labelWithString: "—")
        miniLabel.font = NSFont.monospacedDigitSystemFont(ofSize: 12, weight: .semibold)
        miniLabel.textColor = NSColor(calibratedRed: 0.302, green: 0.420, blue: 0.996, alpha: 1)
        miniLabel.frame = NSRect(x: 42, y: 13, width: 48, height: 16)
        miniView.addSubview(emoji)
        miniView.addSubview(miniLabel)

        window.contentView = NSView(frame: initial)
        window.contentView!.addSubview(fullView)
        window.contentView!.addSubview(miniView)

        // Always boot in the mini state: the 📈 pill sits on the desktop and
        // only expands when clicked. Saved positions (full + mini) are
        // restored; the saved collapsed flag is intentionally ignored.
        if fullFrame == .zero {
            positionWindow()
            fullFrame = window.frame
        }
        if miniFrame == .zero {
            if let vf = NSScreen.main?.visibleFrame {
                miniFrame = NSRect(x: vf.maxX - miniW - 24, y: vf.maxY - miniH - 24, width: miniW, height: miniH)
            } else {
                miniFrame = NSRect(x: fullFrame.maxX - miniW, y: fullFrame.maxY - miniH, width: miniW, height: miniH)
            }
        }
        applyCollapsed(true, animate: false)

        refreshChip()
        window.makeKeyAndOrderFront(nil)
        if mode == "floating" { NSApp.activate(ignoringOtherApps: true) }

        timer = Timer.scheduledTimer(withTimeInterval: 5, repeats: true) { [weak self] _ in
            self?.checkForUpdate()
        }
        if parentPid > 0 {
            watchdog = Timer.scheduledTimer(withTimeInterval: 10, repeats: true) { _ in
                if kill(parentPid, 0) != 0 { NSApp.terminate(nil) }
            }
        }
    }

    func applicationWillTerminate(_ notification: Notification) {
        saveState()
        timer?.invalidate()
        watchdog?.invalidate()
        try? FileManager.default.removeItem(atPath: pidPath)
    }

    // ---- state toggling -------------------------------------------------
    func clampToScreen(_ rect: NSRect) -> NSRect {
        guard let vf = NSScreen.main?.visibleFrame else { return rect }
        var r = rect
        if r.maxX > vf.maxX { r.origin.x = vf.maxX - r.width }
        if r.maxY > vf.maxY { r.origin.y = vf.maxY - r.height }
        if r.minX < vf.minX { r.origin.x = vf.minX }
        if r.minY < vf.minY { r.origin.y = vf.minY }
        return r
    }

    func applyCollapsed(_ shouldCollapse: Bool, animate: Bool) {
        collapsed = shouldCollapse
        if shouldCollapse {
            if fullFrame == .zero { fullFrame = window.frame }
            var target = miniFrame
            if target == .zero { target = NSRect(x: fullFrame.maxX - miniW, y: fullFrame.maxY - miniH, width: miniW, height: miniH) }
            target = clampToScreen(target)
            miniFrame = target
            let setFrame = { self.window.setFrame(target, display: true) }
            if animate {
                NSAnimationContext.runAnimationGroup({ ctx in
                    ctx.duration = 0.18
                    ctx.allowsImplicitAnimation = true
                    setFrame()
                })
            } else { setFrame() }
            fullView.isHidden = true
            miniView.isHidden = false
            miniView.frame = NSRect(x: 0, y: 0, width: miniW, height: miniH)
        } else {
            var target = fullFrame
            if target == .zero {
                positionWindow()
                target = window.frame
            }
            target = clampToScreen(target)
            fullFrame = target
            let setFrame = { self.window.setFrame(target, display: true) }
            if animate {
                NSAnimationContext.runAnimationGroup({ ctx in
                    ctx.duration = 0.18
                    ctx.allowsImplicitAnimation = true
                    setFrame()
                })
            } else { setFrame() }
            miniView.isHidden = true
            fullView.isHidden = false
            fullView.frame = NSRect(x: 0, y: 0, width: target.width, height: target.height)
        }
        saveState()
    }

    @objc func minimize() { applyCollapsed(true, animate: true) }
    @objc func expand() { applyCollapsed(false, animate: true) }

    func windowDidMove(_ notification: Notification) {
        if collapsed { miniFrame = window.frame } else { fullFrame = window.frame }
        saveState()
    }

    func positionWindow() {
        var x = args.count > 2 ? Double(args[2]) ?? -1 : -1
        var y = args.count > 3 ? Double(args[3]) ?? -1 : -1
        if let screen = NSScreen.main {
            let vf = screen.visibleFrame
            if x < 0 || y < 0 || x + fullW > vf.maxX || y + fullH > vf.maxY {
                x = vf.maxX - fullW - 24
                y = vf.maxY - fullH - 24
            }
            window.setFrameOrigin(NSPoint(x: x, y: y))
        }
    }

    // ---- data refresh ---------------------------------------------------
    func checkForUpdate() {
        let attrs = try? FileManager.default.attributesOfItem(atPath: htmlPath)
        let mtime = attrs?[.modificationDate] as? Date ?? .distantPast
        if mtime > lastMtime {
            lastMtime = mtime
            refreshChip()
            webView.reload()
        }
    }

    func refreshChip() {
        var dsi: Double?
        var zone = ""
        var updated: Date?
        if let data = FileManager.default.contents(atPath: snapPath),
           let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any] {
            dsi = (obj["dsi"] as? Double) ?? (obj["dsi"] as? NSNumber)?.doubleValue
            zone = obj["zone"] as? String ?? ""
            if let ts = obj["generatedAt"] as? NSNumber {
                updated = Date(timeIntervalSince1970: ts.doubleValue / 1000)
            }
        }
        if let dsi {
            miniLabel.stringValue = String(format: "%.1f", dsi)
            var text = String(format: "DSI %.1f", dsi)
            if !zone.isEmpty { text += " · \(zone)" }
            if let updated {
                let f = DateFormatter()
                f.dateFormat = "MM-dd HH:mm"
                text += "  更新 \(f.string(from: updated))"
            }
            dsiLabel.stringValue = text
        } else {
            miniLabel.stringValue = "—"
            dsiLabel.stringValue = "DSI —"
        }
    }

    @objc func refreshNow() {
        lastMtime = .distantPast
        checkForUpdate()
    }

    @objc func openSnapshot() {
        NSWorkspace.shared.open(URL(fileURLWithPath: htmlPath))
    }

    @objc func closeWidget() {
        NSApp.terminate(nil)
    }

    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
        if smoke {
            let bootFrame = window.frame
            let bootMiniVisible = !miniView.isHidden && fullView.isHidden
            applyCollapsed(false, animate: false)
            let expanded = window.frame
            applyCollapsed(true, animate: false)
            let miniAgain = window.frame
            let state = try? String(contentsOfFile: statePath, encoding: .utf8)
            let info = "\(mode) visible=\(window.isVisible) occlusion=\(window.occlusionState.rawValue) boot=\(NSStringFromRect(bootFrame)) bootMiniVisible=\(bootMiniVisible) expanded=\(NSStringFromRect(expanded)) miniAgain=\(NSStringFromRect(miniAgain)) state=\(state ?? "nil")"
            try? info.write(toFile: cacheDir + "/widget-ready", atomically: true, encoding: .utf8)
            DispatchQueue.main.asyncAfter(deadline: .now() + 1.0) { NSApp.terminate(nil) }
        }
    }

    func webView(_ webView: WKWebView, didFail navigation: WKNavigation!, withError error: Error) {
        if smoke {
            try? "fail:\(error.localizedDescription)".write(toFile: cacheDir + "/widget-ready", atomically: true, encoding: .utf8)
            DispatchQueue.main.asyncAfter(deadline: .now() + 1.0) { NSApp.terminate(nil) }
        }
    }
}

let app = NSApplication.shared
let delegate = AppDelegate()
app.delegate = delegate
app.run()
