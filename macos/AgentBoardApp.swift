import AppKit
import ServiceManagement
@preconcurrency import WebKit

private let boardPort = Int(ProcessInfo.processInfo.environment["AGENT_BOARD_PORT"] ?? "") ?? 8765
private let boardURL = URL(string: "http://127.0.0.1:\(boardPort)/")!
private let releasesURL = URL(string: "https://github.com/stellassx94/agent-board/releases")!

final class AppDelegate: NSObject, NSApplicationDelegate, WKNavigationDelegate {
    private var window: NSWindow?
    private var webView: WKWebView?
    private var statusItem: NSStatusItem!
    private var statusTimer: Timer?
    private var animationTimer: Timer?
    private var animationOn = true
    private var statusCounts: [String: Int] = [:]
    private var isFetching = false
    private var boardLoaded = false
    private var showingOffline = false
    private var backendTask: Process?
    private var backendLog: FileHandle?
    private var backendAttempts = 0
    private var serviceError: String?
    private var serviceVersion: String?
    private var lastStatusSuccess: Date?
    private var lastWorkstreams: [[String: Any]] = []
    private let appVersion = Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? "unknown"

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.regular)
        statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        statusItem.button?.font = NSFont.monospacedSystemFont(ofSize: 12, weight: .regular)
        statusItem.button?.title = "⚪"
        rebuildMenu()
        showBoard(nil)
        let timer = Timer(timeInterval: 5, repeats: true) { [weak self] _ in
            self?.refreshStatus()
        }
        RunLoop.main.add(timer, forMode: .common)
        statusTimer = timer
        let animation = Timer(timeInterval: 1.8, repeats: true) { [weak self] _ in
            guard let self else { return }
            self.animationOn.toggle()
            self.updateStatusTitle()
        }
        RunLoop.main.add(animation, forMode: .common)
        animationTimer = animation
        refreshStatus()
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool {
        false
    }

    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        showBoard(nil)
        return true
    }

    func applicationWillTerminate(_ notification: Notification) {
        statusTimer?.invalidate()
        animationTimer?.invalidate()
        if let task = backendTask, task.isRunning {
            task.terminate()
        }
        try? backendLog?.close()
    }

    @objc private func showBoard(_ sender: Any?) {
        if window == nil {
            let frame = NSRect(x: 0, y: 0, width: 1280, height: 820)
            let newWindow = NSWindow(contentRect: frame, styleMask: [.titled, .closable, .miniaturizable, .resizable],
                                     backing: .buffered, defer: false)
            newWindow.title = "Agent Board"
            newWindow.center()
            let newWebView = WKWebView(frame: frame)
            newWebView.navigationDelegate = self
            newWindow.contentView = newWebView
            window = newWindow
            webView = newWebView
            newWebView.load(URLRequest(url: boardURL))
        }
        window?.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
    }

    @objc private func openBrowser(_ sender: Any?) {
        NSWorkspace.shared.open(boardURL)
    }

    @objc private func viewReleases(_ sender: Any?) {
        let alert = NSAlert()
        alert.messageText = "Agent Board releases"
        alert.informativeText = "App v\(appVersion) · Service \(serviceVersion ?? "offline")\n\nPublished releases and ready-built Mac downloads are available on the public GitHub project. No corporate VPN is required."
        alert.addButton(withTitle: "Open published releases")
        alert.addButton(withTitle: "Close")
        if alert.runModal() == .alertFirstButtonReturn && !NSWorkspace.shared.open(releasesURL) {
            let error = NSAlert()
            error.messageText = "Could not open the release page"
            error.informativeText = releasesURL.absoluteString
            error.runModal()
        }
    }

    @objc private func retryService(_ sender: Any?) {
        backendAttempts = 0
        serviceError = nil
        if backendTask?.isRunning != true {
            startBackend()
        }
        refreshStatus()
    }

    @objc private func toggleLogin(_ sender: Any?) {
        do {
            if SMAppService.mainApp.status == .enabled {
                try SMAppService.mainApp.unregister()
            } else {
                try SMAppService.mainApp.register()
            }
            rebuildMenu()
        } catch {
            let alert = NSAlert()
            alert.messageText = "Could not change Launch at Login"
            alert.informativeText = error.localizedDescription
            alert.runModal()
        }
    }

    @objc private func openSession(_ sender: NSMenuItem) {
        guard let id = sender.representedObject as? String,
              let url = URL(string: "api/open?id=\(id)", relativeTo: boardURL) else { return }
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        URLSession.shared.dataTask(with: request).resume()
    }

    private func refreshStatus() {
        guard !isFetching else { return }
        isFetching = true
        var request = URLRequest(url: boardURL.appendingPathComponent("api/status"))
        request.timeoutInterval = 12
        URLSession.shared.dataTask(with: request) { [weak self] data, response, error in
            DispatchQueue.main.async {
                guard let self else { return }
                self.isFetching = false
                if let data,
                   let response = response as? HTTPURLResponse, response.statusCode == 200,
                   let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                   let workstreams = object["workstreams"] as? [[String: Any]] {
                    self.serviceError = nil
                    self.serviceVersion = object["version"] as? String
                    self.lastStatusSuccess = Date()
                    self.lastWorkstreams = workstreams
                    self.rebuildMenu()
                    if !self.boardLoaded {
                        self.showingOffline = false
                        self.webView?.load(URLRequest(url: boardURL))
                    }
                } else {
                    let nsError = error as NSError?
                    if nsError?.domain == NSURLErrorDomain && nsError?.code == NSURLErrorTimedOut,
                       let lastSuccess = self.lastStatusSuccess,
                       Date().timeIntervalSince(lastSuccess) < 30 {
                        self.statusItem.button?.toolTip = "Board is refreshing slowly; showing last known counts"
                        return
                    }
                    self.serviceError = "Board service is not responding. Use Retry service."
                    self.serviceVersion = nil
                    self.lastWorkstreams = []
                    self.rebuildMenu()
                    if nsError?.domain == NSURLErrorDomain &&
                        nsError?.code == NSURLErrorCannotConnectToHost {
                        self.startBackend()
                    }
                }
            }
        }.resume()
    }

    private func startBackend() {
        guard backendTask?.isRunning != true, backendAttempts < 2 else { return }
        guard let backend = Bundle.main.resourceURL?.appendingPathComponent("Backend/agent_board.py"),
              FileManager.default.fileExists(atPath: backend.path) else {
            serviceError = "Bundled board service is missing."
            rebuildMenu()
            return
        }
        backendAttempts += 1
        let task = Process()
        let bundled = Bundle.main.resourceURL?.appendingPathComponent("BackendExecutable/agent-board-service")
        if let bundled, FileManager.default.isExecutableFile(atPath: bundled.path) {
            task.executableURL = bundled
            task.arguments = ["--port", String(boardPort), "--no-open"]
        } else {
            let candidates = ["/usr/bin/python3", "/opt/homebrew/bin/python3", "/usr/local/bin/python3"]
            guard let python = candidates.first(where: { FileManager.default.isExecutableFile(atPath: $0) }) else {
                serviceError = "The bundled service is missing and Python 3 is unavailable."
                rebuildMenu()
                return
            }
            task.executableURL = URL(fileURLWithPath: python)
            task.arguments = ["-B", backend.path, "--port", String(boardPort), "--no-open"]
        }
        var environment = ProcessInfo.processInfo.environment
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        task.environment = environment
        let dataPath = (environment["AGENT_BOARD_DATA_DIR"] ?? "~/.agent-board") as NSString
        let logDirectory = URL(fileURLWithPath: dataPath.expandingTildeInPath)
        try? FileManager.default.createDirectory(at: logDirectory, withIntermediateDirectories: true)
        let logURL = logDirectory.appendingPathComponent("app-service.log")
        if !FileManager.default.fileExists(atPath: logURL.path) {
            FileManager.default.createFile(atPath: logURL.path, contents: nil)
        }
        if let handle = try? FileHandle(forWritingTo: logURL) {
            handle.seekToEndOfFile()
            task.standardOutput = handle
            task.standardError = handle
            backendLog = handle
        }
        task.terminationHandler = { [weak self] finished in
            DispatchQueue.main.async {
                guard let self, self.backendTask === finished else { return }
                self.backendTask = nil
                if finished.terminationStatus != 0 {
                    self.serviceError = "Board service stopped. Use Retry service."
                    self.rebuildMenu()
                }
            }
        }
        do {
            try task.run()
            backendTask = task
            serviceError = "Starting board service…"
            rebuildMenu()
        } catch {
            serviceError = "Could not start the board service: \(error.localizedDescription)"
            rebuildMenu()
        }
    }

    private func rebuildMenu() {
        let menu = NSMenu()
        let open = NSMenuItem(title: "Open Agent Board", action: #selector(showBoard(_:)), keyEquivalent: "")
        open.target = self
        menu.addItem(open)
        let browser = NSMenuItem(title: "Open in browser", action: #selector(openBrowser(_:)), keyEquivalent: "")
        browser.target = self
        menu.addItem(browser)
        menu.addItem(.separator())

        let sections: [(String, String)] = [
            ("asking", "? Asking you"),
            ("check", "! Check me"),
            ("yourturn", "↩ Your turn"),
            ("active", "✦ Working"),
            ("pending", "📌 Continue later"),
            ("suggested", "Suggestions to review")
        ]
        var counts: [String: Int] = [:]
        for (bucket, label) in sections {
            let rows = lastWorkstreams.filter { ($0["bucket"] as? String) == bucket }
            counts[bucket] = rows.count
            guard !rows.isEmpty else { continue }
            let header = NSMenuItem(title: "\(label) (\(rows.count))", action: nil, keyEquivalent: "")
            header.isEnabled = false
            menu.addItem(header)
            for row in rows.prefix(12) {
                let name = (row["title"] as? String ?? "Untitled").replacingOccurrences(of: "\n", with: " ")
                let display = name.count > 60 ? String(name.prefix(59)) + "…" : name
                let item = NSMenuItem(title: display, action: #selector(openSession(_:)), keyEquivalent: "")
                item.target = self
                item.representedObject = row["latest_id"] as? String ?? row["id"] as? String
                menu.addItem(item)
            }
            if rows.count > 12 {
                let more = NSMenuItem(title: "…and \(rows.count - 12) more", action: #selector(showBoard(_:)), keyEquivalent: "")
                more.target = self
                menu.addItem(more)
            }
            menu.addItem(.separator())
        }
        statusCounts = counts
        updateStatusTitle()
        if lastWorkstreams.isEmpty {
            let message = NSMenuItem(title: serviceError ?? "No workstreams yet.", action: nil, keyEquivalent: "")
            message.isEnabled = false
            menu.addItem(message)
        }
        let retry = NSMenuItem(title: "Retry service", action: #selector(retryService(_:)), keyEquivalent: "")
        retry.target = self
        menu.addItem(retry)
        let login = NSMenuItem(title: "Launch at Login", action: #selector(toggleLogin(_:)), keyEquivalent: "")
        login.target = self
        login.state = SMAppService.mainApp.status == .enabled ? .on : .off
        menu.addItem(login)
        menu.addItem(.separator())
        let serviceLabel = serviceVersion ?? "offline"
        let mismatch = serviceVersion != nil && serviceVersion != "v\(appVersion)"
        let version = NSMenuItem(title: "\(mismatch ? "⚠️ " : "")App v\(appVersion) · Service \(serviceLabel)",
                                 action: nil, keyEquivalent: "")
        version.isEnabled = false
        menu.addItem(version)
        let releases = NSMenuItem(title: "Check releases…", action: #selector(viewReleases(_:)), keyEquivalent: "")
        releases.target = self
        menu.addItem(releases)
        menu.addItem(.separator())
        let quit = NSMenuItem(title: "Quit Agent Board", action: #selector(quitApp(_:)), keyEquivalent: "")
        quit.target = self
        menu.addItem(quit)
        statusItem?.menu = menu
    }

    private func updateStatusTitle() {
        guard let button = statusItem?.button else { return }
        guard serviceVersion != nil else {
            button.title = serviceError == nil ? "⏳" : "⚠️"
            button.toolTip = serviceError ?? "Agent Board is starting"
            return
        }
        let indicators: [(String, String, String, NSColor)] = [
            ("asking", "?", "Asking you", .systemOrange),
            ("check", "!", "Check me", .systemRed),
            ("yourturn", "↩", "Your turn", .systemBlue),
            ("active", "✦", "Working", .systemGreen),
            ("pending", "📌", "Continue later", .systemPurple)
        ]
        let attentionBucket = ["asking", "check", "yourturn"].first { (statusCounts[$0] ?? 0) > 0 }
        let pulseBuckets = [attentionBucket, (statusCounts["active"] ?? 0) > 0 ? "active" : nil].compactMap { $0 }
        let styled = NSMutableAttributedString(string: "")
        var descriptions: [String] = []
        for (bucket, symbol, label, color) in indicators {
            let count = statusCounts[bucket] ?? 0
            guard count > 0 else { continue }
            if styled.length > 0 { styled.append(NSAttributedString(string: " ")) }
            let dimmed = pulseBuckets.contains(bucket) && !NSWorkspace.shared.accessibilityDisplayShouldReduceMotion && !animationOn
            let symbolFont = NSFont.systemFont(ofSize: bucket == "pending" ? 12 : 17, weight: .semibold)
            styled.append(NSAttributedString(string: symbol,
                attributes: [.font: symbolFont,
                             .foregroundColor: dimmed ? color.withAlphaComponent(0.45) : color]))
            styled.append(NSAttributedString(string: String(count)))
            descriptions.append("\(label): \(count)")
        }
        if styled.length == 0 { styled.append(NSAttributedString(string: "✓")) }
        button.attributedTitle = styled
        button.toolTip = descriptions.isEmpty ? "No active Agent Board workstreams" : descriptions.joined(separator: " · ")
    }

    @objc private func quitApp(_ sender: Any?) {
        NSApp.terminate(nil)
    }

    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
        boardLoaded = !showingOffline
    }

    func webView(_ webView: WKWebView, decidePolicyFor navigationAction: WKNavigationAction,
                 decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
        guard let url = navigationAction.request.url else {
            decisionHandler(.cancel)
            return
        }
        if url.scheme == "http" && ["127.0.0.1", "localhost"].contains(url.host ?? "") && url.port == boardPort {
            decisionHandler(.allow)
        } else if url.scheme == "about" {
            decisionHandler(.allow)
        } else {
            NSWorkspace.shared.open(url)
            decisionHandler(.cancel)
        }
    }

    func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) {
        boardLoaded = false
        showingOffline = true
        let html = """
        <html><meta name="viewport" content="width=device-width, initial-scale=1">
        <style>body{font:16px -apple-system,sans-serif;background:#f3f5f9;color:#141a26;display:grid;place-items:center;height:90vh}main{text-align:center}button{font:inherit;padding:10px 18px;border-radius:8px;border:1px solid #d8dce6;background:white;cursor:pointer}</style>
        <main><h1>Agent Board is starting</h1><p>The local service is loading. This window will refresh when it is ready.</p><button onclick="location.href='\(boardURL.absoluteString)'">Retry now</button></main>
        </html>
        """
        webView.loadHTMLString(html, baseURL: boardURL)
    }
}

let app = NSApplication.shared
let delegate = AppDelegate()
app.delegate = delegate
app.run()
