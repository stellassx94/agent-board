import AppKit
import CryptoKit
import ServiceManagement
@preconcurrency import WebKit

private let boardPort = Int(ProcessInfo.processInfo.environment["AGENT_BOARD_PORT"] ?? "") ?? 8765
private let boardURL = URL(string: "http://127.0.0.1:\(boardPort)/")!
private let releasesURL = URL(string: "https://github.com/stellassx94/agent-board/releases")!
private let latestReleaseURL = URL(string: "https://api.github.com/repos/stellassx94/agent-board/releases/latest")!
private let bundleIdentifier = "com.stella.agentboard.trial"

private struct Release: Decodable {
    struct Asset: Decodable {
        let name: String
        let size: Int
        let digest: String?
        let browser_download_url: URL
    }
    let tag_name: String
    let html_url: URL
    let draft: Bool
    let prerelease: Bool
    let assets: [Asset]
}

private enum UpdateError: LocalizedError {
    case invalidRelease, missingAsset, invalidDownload, invalidBundle, unsupportedLocation

    var errorDescription: String? {
        switch self {
        case .invalidRelease: "GitHub returned an invalid release or version."
        case .missingAsset: "This release has no verified Apple Silicon app download."
        case .invalidDownload: "The download did not match the release digest."
        case .invalidBundle: "The downloaded app failed bundle or signature validation."
        case .unsupportedLocation: "This app location cannot be replaced. Install the update manually from the release page."
        }
    }
}

private func versionParts(_ text: String) -> [Int]? {
    let value = text.hasPrefix("v") ? String(text.dropFirst()) : text
    let parts = value.split(separator: ".", omittingEmptySubsequences: false)
    guard parts.count == 3, parts.allSatisfy({ !$0.isEmpty && $0.allSatisfy(\.isNumber) }) else { return nil }
    let numbers = parts.compactMap { Int($0) }
    guard numbers.count == 3, numbers.allSatisfy({ $0 < 1_000_000 }) else { return nil }
    return numbers
}

private func isNewer(_ remote: String, than local: String) -> Bool {
    guard let remoteParts = versionParts(remote), let localParts = versionParts(local) else { return false }
    return localParts.lexicographicallyPrecedes(remoteParts)
}

private func runTool(_ executable: String, _ arguments: [String]) throws {
    let process = Process()
    process.executableURL = URL(fileURLWithPath: executable)
    process.arguments = arguments
    process.standardOutput = FileHandle.nullDevice
    process.standardError = FileHandle.nullDevice
    try process.run()
    process.waitUntilExit()
    guard process.terminationStatus == 0 else { throw UpdateError.invalidBundle }
}

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
    private var isUpdating = false
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
        guard !isUpdating else { return }
        isUpdating = true
        rebuildMenu()
        var request = URLRequest(url: latestReleaseURL)
        request.timeoutInterval = 20
        request.setValue("application/vnd.github+json", forHTTPHeaderField: "Accept")
        URLSession.shared.dataTask(with: request) { [weak self] data, response, error in
            DispatchQueue.main.async {
                guard let self else { return }
                self.isUpdating = false
                self.rebuildMenu()
                guard error == nil, let data, data.count < 1_000_000,
                      let response = response as? HTTPURLResponse, response.statusCode == 200,
                      response.url?.host == "api.github.com",
                      let release = try? JSONDecoder().decode(Release.self, from: data),
                      !release.draft, !release.prerelease,
                      release.tag_name.hasPrefix("v"),
                      versionParts(release.tag_name) != nil,
                      release.html_url.host == "github.com",
                      release.html_url.path == "/stellassx94/agent-board/releases/tag/\(release.tag_name)"
                else {
                    self.showUpdateError(error?.localizedDescription ?? "Could not check the official GitHub release.")
                    return
                }
                self.showRelease(release)
            }
        }.resume()
    }

    private func showRelease(_ release: Release) {
        let newer = isNewer(release.tag_name, than: appVersion)
        let assetName = "Agent-Board-\(release.tag_name)-macos-arm64.zip"
        let asset = release.assets.first { $0.name == assetName }
        let digest = asset?.digest ?? ""
        let validAsset = asset != nil && asset!.size > 0 && asset!.size < 200_000_000 &&
            digest.hasPrefix("sha256:") && digest.count == 71 &&
            digest.dropFirst(7).allSatisfy { $0.isHexDigit } &&
            asset!.browser_download_url.host == "github.com" &&
            asset!.browser_download_url.path ==
                "/stellassx94/agent-board/releases/download/\(release.tag_name)/\(assetName)"
        let alert = NSAlert()
        alert.messageText = newer ? "\(release.tag_name) is available" : "Agent Board is up to date"
        alert.informativeText = "Installed app: v\(appVersion)\nRunning service: \(serviceVersion ?? "offline")\nPublished release: \(release.tag_name)" +
            (newer && !validAsset ? "\n\nNo verifiable Mac download is available. Open the release page to install manually." : "")
        if newer && validAsset { alert.addButton(withTitle: "Download and install") }
        alert.addButton(withTitle: "View release")
        alert.addButton(withTitle: "Cancel")
        let choice = alert.runModal()
        if newer && validAsset && choice == .alertFirstButtonReturn {
            install(release: release, asset: asset!)
        } else if choice == (newer && validAsset ? .alertSecondButtonReturn : .alertFirstButtonReturn) {
            NSWorkspace.shared.open(release.html_url)
        }
    }

    private func showUpdateError(_ message: String) {
        let alert = NSAlert()
        alert.messageText = "Agent Board update"
        alert.informativeText = message
        alert.addButton(withTitle: "OK")
        alert.runModal()
    }

    private func install(release: Release, asset: Release.Asset) {
        guard !isUpdating else { return }
        isUpdating = true
        rebuildMenu()
        var request = URLRequest(url: asset.browser_download_url)
        request.timeoutInterval = 120
        URLSession.shared.downloadTask(with: request) { [weak self] temporaryURL, response, error in
            do {
                guard error == nil, let temporaryURL,
                      let response = response as? HTTPURLResponse, response.statusCode == 200,
                      response.expectedContentLength <= 0 || response.expectedContentLength == Int64(asset.size)
                else { throw error ?? UpdateError.invalidDownload }
                let data = try Data(contentsOf: temporaryURL)
                let actualDigest = "sha256:" + SHA256.hash(data: data).map {
                    String(format: "%02x", $0)
                }.joined()
                guard data.count == asset.size,
                      actualDigest == asset.digest?.lowercased()
                else { throw UpdateError.invalidDownload }
                let staged = try self?.stageUpdate(archive: temporaryURL, version: release.tag_name)
                DispatchQueue.main.async {
                    guard let self, let staged else { return }
                    self.isUpdating = false
                    self.rebuildMenu()
                    self.confirmReplacement(staged: staged, version: release.tag_name)
                }
            } catch {
                DispatchQueue.main.async {
                    self?.isUpdating = false
                    self?.rebuildMenu()
                    self?.showUpdateError("Update stopped; the installed app was not changed.\n\n\(error.localizedDescription)")
                }
            }
        }.resume()
    }

    private func stageUpdate(archive: URL, version: String) throws -> URL {
        let fm = FileManager.default
        let current = Bundle.main.bundleURL.standardizedFileURL
        let parent = current.deletingLastPathComponent()
        guard current.pathExtension == "app", current.lastPathComponent == "Agent Board.app",
              (try? fm.destinationOfSymbolicLink(atPath: current.path)) == nil,
              fm.isWritableFile(atPath: parent.path) else { throw UpdateError.unsupportedLocation }
        let unpack = fm.temporaryDirectory.appendingPathComponent("agent-board-\(UUID().uuidString)")
        try fm.createDirectory(at: unpack, withIntermediateDirectories: false)
        defer { try? fm.removeItem(at: unpack) }
        let listing = Process()
        listing.executableURL = URL(fileURLWithPath: "/usr/bin/unzip")
        listing.arguments = ["-Z", "-1", archive.path]
        let output = Pipe()
        listing.standardOutput = output
        listing.standardError = FileHandle.nullDevice
        try listing.run()
        let names = output.fileHandleForReading.readDataToEndOfFile()
        listing.waitUntilExit()
        guard listing.terminationStatus == 0,
              let listingText = String(data: names, encoding: .utf8),
              !listingText.isEmpty,
              listingText.split(separator: "\n").allSatisfy({
                  let path = String($0)
                  let expectedRoot = path == "Agent Board.app/" || path == "__MACOSX/" ||
                      path.hasPrefix("Agent Board.app/") || path.hasPrefix("__MACOSX/Agent Board.app/")
                  return expectedRoot &&
                      !path.split(separator: "/").contains(where: { $0 == "." || $0 == ".." || $0.contains("\\") })
              }) else { throw UpdateError.invalidBundle }
        try runTool("/usr/bin/ditto", ["-x", "-k", archive.path, unpack.path])
        let app = unpack.appendingPathComponent("Agent Board.app")
        let entries = try fm.contentsOfDirectory(atPath: unpack.path)
        guard Set(entries) == Set(["Agent Board.app"]) ||
                Set(entries) == Set(["Agent Board.app", "__MACOSX"]),
              (try? fm.destinationOfSymbolicLink(atPath: app.path)) == nil,
              let info = Bundle(url: app),
              info.bundleIdentifier == bundleIdentifier,
              info.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ==
                String(version.dropFirst()),
              let embedded = try? String(contentsOf: app.appendingPathComponent("Contents/Resources/Backend/VERSION"),
                                         encoding: .utf8),
              embedded.trimmingCharacters(in: .whitespacesAndNewlines) == version
        else { throw UpdateError.invalidBundle }
        try runTool("/usr/bin/codesign", ["--verify", "--deep", "--strict", app.path])
        let staged = parent.appendingPathComponent(".Agent Board-update-\(UUID().uuidString).app")
        do {
            try fm.copyItem(at: app, to: staged)
        } catch {
            try? fm.removeItem(at: staged)
            throw error
        }
        return staged
    }

    private func confirmReplacement(staged: URL, version: String) {
        let alert = NSAlert()
        alert.messageText = "Install \(version) and relaunch?"
        alert.informativeText = "Agent Board will quit, stop its service, replace this app, and reopen. Your settings in ~/.agent-board will not be changed."
        alert.addButton(withTitle: "Install and relaunch")
        alert.addButton(withTitle: "Cancel")
        guard alert.runModal() == .alertFirstButtonReturn else {
            try? FileManager.default.removeItem(at: staged)
            return
        }
        let current = Bundle.main.bundleURL.standardizedFileURL
        let backup = current.deletingLastPathComponent()
            .appendingPathComponent(".Agent Board-backup-\(UUID().uuidString).app")
        let script = """
        pid="$1"; current="$2"; staged="$3"; backup="$4"; port="$5"; data_dir="$6"
        n=0
        while kill -0 "$pid" 2>/dev/null; do
          n=$((n + 1))
          if [ "$n" -ge 120 ]; then exit 1; fi
          sleep 1
        done
        if ! mv "$current" "$backup"; then exit 1; fi
        if ! mv "$staged" "$current"; then
          mv "$backup" "$current"
          exit 1
        fi
        set --
        if [ -n "$port" ]; then set -- "$@" --env "AGENT_BOARD_PORT=$port"; fi
        if [ -n "$data_dir" ]; then set -- "$@" --env "AGENT_BOARD_DATA_DIR=$data_dir"; fi
        if ! /usr/bin/open -n "$@" "$current"; then
          mv "$current" "$staged"
          mv "$backup" "$current"
          /usr/bin/open -n "$@" "$current"
          exit 1
        fi
        """
        let helper = Process()
        helper.executableURL = URL(fileURLWithPath: "/bin/sh")
        helper.arguments = ["-c", script, "agent-board-updater", String(ProcessInfo.processInfo.processIdentifier),
                            current.path, staged.path, backup.path,
                            ProcessInfo.processInfo.environment["AGENT_BOARD_PORT"] ?? "",
                            ProcessInfo.processInfo.environment["AGENT_BOARD_DATA_DIR"] ?? ""]
        helper.standardOutput = FileHandle.nullDevice
        helper.standardError = FileHandle.nullDevice
        do {
            try helper.run()
            NSApp.terminate(nil)
        } catch {
            try? FileManager.default.removeItem(at: staged)
            showUpdateError("Could not start the installer: \(error.localizedDescription)")
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
        let releases = NSMenuItem(title: isUpdating ? "Checking or downloading update…" : "Check for updates…",
                                  action: #selector(viewReleases(_:)), keyEquivalent: "")
        releases.target = self
        releases.isEnabled = !isUpdating
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
