import Foundation
import SwiftUI
import UserNotifications

@MainActor
final class ActivityStore: ObservableObject {
    @Published var payload: ActivityPayload?
    @Published var isLoading = false
    @Published var errorMessage: String?
    @Published var lastRefresh: Date?
    @Published var lastActionMessage: String?
    @Published var launchAgentStatus: LaunchAgentStatus?
    @Published var launchAgentError: String?
    @Published var isManagingLaunchAgent = false
    @Published var cliPath: String {
        didSet {
            UserDefaults.standard.set(cliPath, forKey: Defaults.cliPath)
        }
    }
    @Published var notifyOnWrites: Bool {
        didSet {
            UserDefaults.standard.set(notifyOnWrites, forKey: Defaults.notifyOnWrites)
            if notifyOnWrites {
                requestNotificationAuthorization()
            }
        }
    }

    private enum Defaults {
        static let cliPath = "AutopsyMenuBar.cliPath"
        static let notifyOnWrites = "AutopsyMenuBar.notifyOnWrites"
    }

    private var timer: Timer?
    private var newestWriteKey: String?
    private var hasLoadedActivity = false

    init() {
        cliPath = UserDefaults.standard.string(forKey: Defaults.cliPath) ?? Self.defaultCLIPath
        notifyOnWrites = UserDefaults.standard.bool(forKey: Defaults.notifyOnWrites)
        start()
    }

    deinit {
        timer?.invalidate()
    }

    var workspaceTitle: String {
        payload?.workspace?.title ?? payload?.workspace?.slug ?? "Local memory"
    }

    var workspacePath: String {
        payload?.workspace?.rootPath ?? ""
    }

    var recentWrites: [MemoryWrite] {
        payload?.activity?.recentWrites ?? []
    }

    var recentConsults: [ConsultEvent] {
        payload?.activity?.recentConsults ?? []
    }

    var attentionEvents: [AttentionEvent] {
        payload?.activity?.attention ?? []
    }

    var statusSummary: String {
        if let errorMessage, !errorMessage.isEmpty {
            return errorMessage
        }
        return payload?.status?.summary ?? payload?.activity?.summary ?? "Waiting for activity"
    }

    var menuBarSystemImage: String {
        if errorMessage != nil {
            return "exclamationmark.triangle"
        }
        if !attentionEvents.isEmpty {
            return "circle.lefthalf.filled"
        }
        if isLoading {
            return "arrow.triangle.2.circlepath"
        }
        return "brain.head.profile"
    }

    var notificationsAvailable: Bool {
        Self.notificationsAvailable
    }

    var detectedCLIPath: String {
        Self.defaultCLIPath
    }

    var launchAtLoginEnabled: Bool {
        launchAgentStatus?.installed == true
    }

    var launchAtLoginStatusText: String {
        if let launchAgentError, !launchAgentError.isEmpty {
            return launchAgentError
        }
        guard let launchAgentStatus else {
            return "Checking login startup"
        }
        if launchAgentStatus.installed == true && launchAgentStatus.loaded == true {
            return "Autopsy opens at login"
        }
        if launchAgentStatus.installed == true {
            return "Login startup installed, not loaded"
        }
        return "Login startup off"
    }

    private static var notificationsAvailable: Bool {
        guard let bundleIdentifier = Bundle.main.bundleIdentifier else { return false }
        return !bundleIdentifier.isEmpty
    }

    private static var defaultCLIPath: String {
        if let configured = Bundle.main.object(forInfoDictionaryKey: "AutopsyDefaultCLIPath") as? String,
           !configured.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            return configured
        }
        return "autopsy"
    }

    func start() {
        guard timer == nil else { return }
        refresh()
        timer = Timer.scheduledTimer(withTimeInterval: 30, repeats: true) { [weak self] _ in
            Task { @MainActor in
                self?.refresh(includeLaunchAgent: false)
            }
        }
    }

    func refresh(includeLaunchAgent: Bool = true) {
        Task {
            await loadActivity()
        }
        if includeLaunchAgent {
            Task {
                await loadLaunchAgentStatus()
            }
        }
    }

    func runHealth() {
        Task {
            await runUtilityCommand(["health"], successMessage: "Health check passed")
        }
    }

    func runBackup() {
        Task {
            await runUtilityCommand(["backup"], successMessage: "Backup written")
        }
    }

    func resetCLIPath() {
        cliPath = Self.defaultCLIPath
        refresh()
    }

    func setLaunchAtLogin(_ enabled: Bool) {
        Task {
            await updateLaunchAgent(enabled: enabled)
        }
    }

    private func loadActivity() async {
        isLoading = true
        errorMessage = nil
        defer {
            isLoading = false
            lastRefresh = Date()
        }

        do {
            let output = try await AutopsyCLI(executable: cliPath, timeoutSeconds: 20).run(["activity", "--limit", "6"])
            let decoded = try JSONDecoder().decode(ActivityPayload.self, from: Data(output.utf8))
            payload = decoded
            maybeNotifyAboutWrite(decoded.activity?.recentWrites?.first)
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    private func runUtilityCommand(_ arguments: [String], successMessage: String) async {
        isLoading = true
        errorMessage = nil
        lastActionMessage = nil
        defer {
            isLoading = false
            lastRefresh = Date()
        }

        do {
            _ = try await AutopsyCLI(executable: cliPath, timeoutSeconds: 90).run(arguments)
            lastActionMessage = successMessage
            await loadActivity()
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    private func loadLaunchAgentStatus() async {
        launchAgentError = nil
        do {
            let output = try await AutopsyCLI(executable: cliPath, timeoutSeconds: 10).run(["menubar", "--launch-agent-status"])
            launchAgentStatus = try JSONDecoder().decode(LaunchAgentStatus.self, from: Data(output.utf8))
        } catch {
            launchAgentError = error.localizedDescription
        }
    }

    private func updateLaunchAgent(enabled: Bool) async {
        isManagingLaunchAgent = true
        launchAgentError = nil
        lastActionMessage = nil
        defer {
            isManagingLaunchAgent = false
        }

        do {
            let arguments = enabled ? ["menubar", "--install-launch-agent"] : ["menubar", "--uninstall-launch-agent"]
            let output = try await AutopsyCLI(executable: cliPath, timeoutSeconds: 120).run(arguments)
            launchAgentStatus = try JSONDecoder().decode(LaunchAgentStatus.self, from: Data(output.utf8))
            lastActionMessage = enabled ? "Opens at login" : "Login startup disabled"
        } catch {
            launchAgentError = error.localizedDescription
        }
    }

    private func maybeNotifyAboutWrite(_ write: MemoryWrite?) {
        guard let write, let key = write.stableKey, !key.isEmpty else { return }
        defer {
            newestWriteKey = key
            hasLoadedActivity = true
        }

        guard hasLoadedActivity, newestWriteKey != key, notifyOnWrites, notificationsAvailable else { return }
        let content = UNMutableNotificationContent()
        content.title = "Autopsy memory written"
        content.body = write.title ?? "New memory captured"
        content.sound = nil
        let request = UNNotificationRequest(identifier: key, content: content, trigger: nil)
        UNUserNotificationCenter.current().add(request)
    }

    private func requestNotificationAuthorization() {
        guard notificationsAvailable else { return }
        UNUserNotificationCenter.current().requestAuthorization(options: [.alert]) { _, _ in }
    }
}
