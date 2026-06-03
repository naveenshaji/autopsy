import AppKit
import Foundation
import SwiftUI

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
    @Published var instructionStatus: InstructionStatusPayload?
    @Published var instructionStatusError: String?
    @Published var isManagingInstructions = false
    @Published var isCopyingInstructions = false
    @Published var setupStatus: SetupStatusPayload?
    @Published var setupStatusError: String?
    @Published var isRepairingSetup = false
    @Published var softwareUpdateStatus: SoftwareUpdateStatus?
    @Published var softwareUpdateError: String?
    @Published var isCheckingForSoftwareUpdates = false
    @Published var isUpdatingAutopsy = false
    @Published var cliPath: String {
        didSet {
            UserDefaults.standard.set(cliPath, forKey: Defaults.cliPath)
        }
    }

    private enum Defaults {
        static let cliPath = "AutopsyMenuBar.cliPath"
        static let cachedActivityPayload = "AutopsyMenuBar.cachedActivityPayload"
        static let cachedActivityDate = "AutopsyMenuBar.cachedActivityDate"
        static let cachedLaunchAgentStatus = "AutopsyMenuBar.cachedLaunchAgentStatus"
        static let cachedInstructionStatus = "AutopsyMenuBar.cachedInstructionStatus"
        static let cachedSetupStatus = "AutopsyMenuBar.cachedSetupStatus"
    }

    private let activitySnapshotURL = ActivityStore.defaultActivitySnapshotURL
    private var activityWatcher: ActivitySnapshotWatcher?
    private var hasBootstrappedActivitySnapshot = false

    init() {
        let storedCLIPath = UserDefaults.standard.string(forKey: Defaults.cliPath)
        cliPath = Self.normalizedCLIPath(storedCLIPath ?? Self.defaultCLIPath)
        if storedCLIPath != nil && storedCLIPath != cliPath {
            UserDefaults.standard.set(cliPath, forKey: Defaults.cliPath)
        }
        loadCachedState()
        start()
    }

    deinit {
        activityWatcher?.stop()
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
        return "brain.head.profile"
    }

    var detectedCLIPath: String {
        Self.defaultCLIPath
    }

    var launchAtLoginEnabled: Bool {
        launchAgentStatus?.installed == true
    }

    var launchAtLoginLoaded: Bool {
        launchAgentStatus?.loaded == true
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

    var instructionTargets: [InstructionTarget] {
        let knownAgents = ["codex", "claude", "gemini", "opencode", "cursor", "copilot", "windsurf"]
        let targets = instructionStatus?.targets ?? []
        let knownTargets = targets.filter { target in
            guard let agent = target.agent else { return false }
            return knownAgents.contains(agent)
        }
        let missingAgents = knownAgents.filter { agent in
            !knownTargets.contains { $0.agent == agent }
        }
        return knownTargets + missingAgents.map { agent in
            InstructionTarget(
                agent: agent,
                scope: "global",
                path: nil,
                description: instructionDescription(agent),
                state: "missing",
                action: "install",
                changed: true,
                dryRun: true
            )
        }
    }

    var hasPriorMemory: Bool {
        !recentWrites.isEmpty || !recentConsults.isEmpty
    }

    var hasInstalledInstructions: Bool {
        instructionTargets.contains { target in
            target.state == "managed"
        }
    }

    var shouldShowOnboardingPrompt: Bool {
        instructionStatus != nil && !hasPriorMemory && !hasInstalledInstructions
    }

    var setupHealthIssues: [SetupHealthIssue] {
        var issues: [SetupHealthIssue] = []

        if let setupStatusError, !setupStatusError.isEmpty {
            issues.append(SetupHealthIssue(
                id: "setup-status-error",
                title: "Setup status unavailable",
                detail: setupStatusError.clippedForMenuBar(limit: 80),
                systemImage: "exclamationmark.triangle"
            ))
        }

        if let pathRepair = setupStatus?.pathRepair,
           pathRepair.skipped != true,
           pathRepair.ok != true {
            let detail = pathRepair.error
                ?? pathRepair.checkBefore?.error
                ?? "The autopsy command on PATH needs repair."
            issues.append(SetupHealthIssue(
                id: "path-repair",
                title: "Command needs repair",
                detail: detail.clippedForMenuBar(limit: 90),
                systemImage: "terminal"
            ))
        }

        if let menubar = setupStatus?.menubar, menubar.supported == true {
            if let error = menubar.error, !error.isEmpty {
                issues.append(SetupHealthIssue(
                    id: "menubar-error",
                    title: "Menu bar startup failed",
                    detail: error.clippedForMenuBar(limit: 90),
                    systemImage: "menubar.rectangle"
                ))
            } else {
                if menubar.installed != true {
                    issues.append(SetupHealthIssue(
                        id: "menubar-missing",
                        title: "Menu bar startup missing",
                        detail: "Autopsy is not installed as a login item.",
                        systemImage: "menubar.rectangle"
                    ))
                } else if menubar.loaded != true {
                    issues.append(SetupHealthIssue(
                        id: "menubar-unloaded",
                        title: "Menu bar app is not running",
                        detail: "The LaunchAgent exists but is not loaded.",
                        systemImage: "menubar.rectangle"
                    ))
                }

                if menubar.appBundleCurrent == false {
                    issues.append(SetupHealthIssue(
                        id: "menubar-app-stale",
                        title: "Menu bar app is stale",
                        detail: "The installed app bundle needs to be rebuilt.",
                        systemImage: "arrow.triangle.2.circlepath"
                    ))
                }

                if menubar.launchAgentCurrent == false {
                    issues.append(SetupHealthIssue(
                        id: "menubar-agent-stale",
                        title: "Login item points at old app",
                        detail: "The LaunchAgent needs to be reinstalled.",
                        systemImage: "arrow.triangle.2.circlepath"
                    ))
                }
            }
        }

        if !shouldShowOnboardingPrompt,
           instructionStatus != nil,
           !hasInstalledInstructions {
            issues.append(SetupHealthIssue(
                id: "instructions-missing",
                title: "Agent instructions missing",
                detail: "No managed Autopsy agent instructions are installed.",
                systemImage: "text.book.closed"
            ))
        }

        if setupStatus?.instructions?.workflow?.complete == false {
            let detail = setupStatus?.instructions?.workflow?.nextSteps?.first
                ?? "Instruction setup needs attention."
            issues.append(SetupHealthIssue(
                id: "instructions-workflow",
                title: "Instruction setup incomplete",
                detail: detail.clippedForMenuBar(limit: 90),
                systemImage: "text.book.closed"
            ))
        }

        var seen: Set<String> = []
        return issues.filter { issue in
            if seen.contains(issue.id) {
                return false
            }
            seen.insert(issue.id)
            return true
        }
    }

    var setupHealthStatusText: String {
        if isRepairingSetup {
            return "Repairing"
        }
        let issues = setupHealthIssues
        guard let first = issues.first else {
            return "Ready"
        }
        if issues.count == 1 {
            return first.title
        }
        return "\(issues.count) issues"
    }

    var softwareUpdateTitle: String {
        if isUpdatingAutopsy {
            return "Updating Autopsy"
        }
        if softwareUpdateStatus?.updateAvailable == true {
            return "Update Autopsy"
        }
        return "Check for Updates"
    }

    var softwareUpdateStatusText: String {
        if isUpdatingAutopsy {
            return "Updating"
        }
        if isCheckingForSoftwareUpdates {
            return "Checking"
        }
        if let softwareUpdateError, !softwareUpdateError.isEmpty {
            return softwareUpdateError.clippedForMenuBar(limit: 24)
        }
        return softwareUpdateStatus?.message ?? "Not checked"
    }

    var softwareUpdateSystemImage: String {
        if isUpdatingAutopsy || isCheckingForSoftwareUpdates {
            return "arrow.triangle.2.circlepath"
        }
        if softwareUpdateStatus?.updateAvailable == true {
            return "arrow.down.circle"
        }
        return "arrow.clockwise.circle"
    }

    private static var defaultCLIPath: String {
        if let configured = Bundle.main.object(forInfoDictionaryKey: "AutopsyDefaultCLIPath") as? String,
           !configured.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            return normalizedCLIPath(configured)
        }
        return "autopsy"
    }

    private static var defaultActivitySnapshotURL: URL {
        if let configured = ProcessInfo.processInfo.environment["AUTOPSY_ACTIVITY_SNAPSHOT_PATH"]?
            .trimmingCharacters(in: .whitespacesAndNewlines),
           !configured.isEmpty {
            return URL(fileURLWithPath: NSString(string: configured).expandingTildeInPath)
        }
        return FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Library", isDirectory: true)
            .appendingPathComponent("Application Support", isDirectory: true)
            .appendingPathComponent("Autopsy", isDirectory: true)
            .appendingPathComponent("Activity", isDirectory: true)
            .appendingPathComponent("activity.json")
    }

    private static func normalizedCLIPath(_ path: String) -> String {
        let trimmed = path.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return "autopsy" }
        return homebrewOptCLIPath(for: trimmed) ?? trimmed
    }

    private static func homebrewOptCLIPath(for path: String) -> String? {
        let parts = path.split(separator: "/", omittingEmptySubsequences: false).map(String.init)
        guard let cellarIndex = parts.firstIndex(of: "Cellar"),
              cellarIndex + 5 < parts.count,
              parts[cellarIndex + 1] == "autopsy-memory",
              parts[cellarIndex + 3] == "libexec",
              parts[cellarIndex + 4] == "bin",
              parts[cellarIndex + 5] == "autopsy"
        else {
            return nil
        }
        let prefix = parts[..<cellarIndex].joined(separator: "/")
        let normalizedPrefix = prefix.isEmpty ? "/" : prefix
        return "\(normalizedPrefix)/opt/autopsy-memory/bin/autopsy"
    }

    func start() {
        guard activityWatcher == nil else { return }
        loadActivitySnapshotFromDisk()
        startActivitySnapshotWatcher()
        refresh()
        bootstrapActivitySnapshotIfNeeded()
    }

    func refresh(includeLaunchAgent: Bool = true) {
        loadActivitySnapshotFromDisk()
        if includeLaunchAgent {
            Task {
                await loadLaunchAgentStatus()
            }
            Task {
                await loadInstructionStatus()
            }
            Task {
                await loadSetupStatus()
            }
            Task {
                await loadSoftwareUpdateStatus()
            }
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

    func quit() {
        Task {
            if launchAtLoginEnabled || launchAtLoginLoaded {
                await updateLaunchAgent(enabled: false)
            }
            NSApplication.shared.terminate(nil)
        }
    }

    func installInstructions(agent: String) {
        Task {
            await updateInstructions(agent: agent)
        }
    }

    func installAllInstructions() {
        Task {
            await updateInstructions(agent: "all")
        }
    }

    func repairSetup() {
        Task {
            await repairAutopsySetup()
        }
    }

    func copyInstructions() {
        Task {
            await copyInstructionsToPasteboard()
        }
    }

    func checkForSoftwareUpdates() {
        Task {
            await loadSoftwareUpdateStatus(refreshTaps: true)
        }
    }

    func updateAutopsy() {
        Task {
            await updateAutopsyFromHomebrew()
        }
    }

    private func startActivitySnapshotWatcher() {
        activityWatcher = ActivitySnapshotWatcher(url: activitySnapshotURL) { [weak self] in
            self?.loadActivitySnapshotFromDisk()
        }
        activityWatcher?.start()
    }

    private func loadActivitySnapshotFromDisk() {
        guard FileManager.default.fileExists(atPath: activitySnapshotURL.path) else { return }

        do {
            let data = try Data(contentsOf: activitySnapshotURL)
            let decoded = try JSONDecoder().decode(ActivityPayload.self, from: data)
            payload = decoded
            let attributes = try? FileManager.default.attributesOfItem(atPath: activitySnapshotURL.path)
            lastRefresh = attributes?[.modificationDate] as? Date ?? Date()
            errorMessage = nil
            if let output = String(data: data, encoding: .utf8) {
                cacheActivityPayload(output)
            }
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    private func bootstrapActivitySnapshotIfNeeded() {
        guard !hasBootstrappedActivitySnapshot else { return }
        guard !FileManager.default.fileExists(atPath: activitySnapshotURL.path) else { return }
        hasBootstrappedActivitySnapshot = true
        Task {
            await bootstrapActivitySnapshot()
        }
    }

    private func bootstrapActivitySnapshot() async {
        isLoading = true
        errorMessage = nil
        defer {
            isLoading = false
        }

        do {
            let output = try await AutopsyCLI(executable: cliPath, timeoutSeconds: 20).run([
                "activity",
                "--writes-limit",
                "20",
                "--consults-limit",
                "20",
            ])
            if let decoded = try? JSONDecoder().decode(ActivityPayload.self, from: Data(output.utf8)) {
                payload = decoded
                lastRefresh = Date()
                cacheActivityPayload(output)
            }
            loadActivitySnapshotFromDisk()
        } catch {
            if payload == nil {
                errorMessage = error.localizedDescription
            }
        }
    }

    private func loadLaunchAgentStatus() async {
        launchAgentError = nil
        do {
            let output = try await AutopsyCLI(executable: cliPath, timeoutSeconds: 10).run(["menubar", "--launch-agent-status"])
            launchAgentStatus = try JSONDecoder().decode(LaunchAgentStatus.self, from: Data(output.utf8))
            UserDefaults.standard.set(output, forKey: Defaults.cachedLaunchAgentStatus)
        } catch {
            launchAgentError = error.localizedDescription
        }
    }

    private func loadInstructionStatus() async {
        instructionStatusError = nil
        do {
            let output = try await AutopsyCLI(executable: cliPath, timeoutSeconds: 20).run([
                "init",
                "--check",
                "--global",
                "--agent",
                "all",
            ])
            instructionStatus = try JSONDecoder().decode(InstructionStatusPayload.self, from: Data(output.utf8))
            UserDefaults.standard.set(output, forKey: Defaults.cachedInstructionStatus)
        } catch {
            instructionStatusError = error.localizedDescription
        }
    }

    private func loadSetupStatus() async {
        setupStatusError = nil
        do {
            let output = try await AutopsyCLI(executable: cliPath, timeoutSeconds: 40).run([
                "install",
                "--dry-run",
                "--skip-doctor",
                "--release",
            ])
            setupStatus = try JSONDecoder().decode(SetupStatusPayload.self, from: Data(output.utf8))
            UserDefaults.standard.set(output, forKey: Defaults.cachedSetupStatus)
        } catch {
            setupStatusError = error.localizedDescription
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
            UserDefaults.standard.set(output, forKey: Defaults.cachedLaunchAgentStatus)
            lastActionMessage = enabled ? "Opens at login" : "Login startup disabled"
            await loadSetupStatus()
        } catch {
            launchAgentError = error.localizedDescription
        }
    }

    private func updateInstructions(agent: String) async {
        isManagingInstructions = true
        instructionStatusError = nil
        lastActionMessage = nil
        defer {
            isManagingInstructions = false
        }

        do {
            _ = try await AutopsyCLI(executable: cliPath, timeoutSeconds: 90).run([
                "init",
                "--global",
                "--agent",
                agent,
                "--yes",
            ])
            lastActionMessage = agent == "all" ? "Instructions installed" : "\(agentDisplayName(agent)) instructions installed"
            await loadInstructionStatus()
            await loadSetupStatus()
            loadActivitySnapshotFromDisk()
        } catch {
            instructionStatusError = error.localizedDescription
        }
    }

    private func repairAutopsySetup() async {
        guard !isRepairingSetup else { return }
        isRepairingSetup = true
        setupStatusError = nil
        launchAgentError = nil
        instructionStatusError = nil
        lastActionMessage = nil
        defer {
            isRepairingSetup = false
        }

        do {
            let output = try await AutopsyCLI(executable: cliPath, timeoutSeconds: 300).run([
                "install",
                "--release",
            ])
            setupStatus = try? JSONDecoder().decode(SetupStatusPayload.self, from: Data(output.utf8))
            if setupStatus != nil {
                UserDefaults.standard.set(output, forKey: Defaults.cachedSetupStatus)
            }
            lastActionMessage = "Setup repaired"
            await loadLaunchAgentStatus()
            await loadInstructionStatus()
            await loadSetupStatus()
            loadActivitySnapshotFromDisk()
        } catch {
            setupStatusError = error.localizedDescription
        }
    }

    private func copyInstructionsToPasteboard() async {
        isCopyingInstructions = true
        instructionStatusError = nil
        lastActionMessage = nil
        defer {
            isCopyingInstructions = false
        }

        do {
            let output = try await AutopsyCLI(executable: cliPath, timeoutSeconds: 15).run(["instructions"])
            let text = output.trimmingCharacters(in: .whitespacesAndNewlines)
            NSPasteboard.general.clearContents()
            NSPasteboard.general.setString(text, forType: .string)
            lastActionMessage = "Instructions copied"
            clearCopiedInstructionsMessageAfterDelay()
        } catch {
            instructionStatusError = error.localizedDescription
        }
    }

    private func clearCopiedInstructionsMessageAfterDelay() {
        Task { [weak self] in
            try? await Task.sleep(nanoseconds: 2_000_000_000)
            await MainActor.run {
                guard self?.lastActionMessage == "Instructions copied" else { return }
                self?.lastActionMessage = nil
            }
        }
    }

    private func loadSoftwareUpdateStatus(refreshTaps: Bool = false) async {
        guard !isCheckingForSoftwareUpdates && !isUpdatingAutopsy else { return }
        isCheckingForSoftwareUpdates = true
        softwareUpdateError = nil
        defer {
            isCheckingForSoftwareUpdates = false
        }

        do {
            softwareUpdateStatus = try await AutopsyUpdater().checkStatus(refreshTaps: refreshTaps)
        } catch {
            softwareUpdateError = error.localizedDescription
        }
    }

    private func updateAutopsyFromHomebrew() async {
        guard !isUpdatingAutopsy else { return }
        isUpdatingAutopsy = true
        softwareUpdateError = nil
        lastActionMessage = nil
        defer {
            isUpdatingAutopsy = false
        }

        do {
            try await AutopsyUpdater().update()
            softwareUpdateStatus = try? await AutopsyUpdater().checkStatus()
            await loadLaunchAgentStatus()
            await loadSetupStatus()
            lastActionMessage = "Autopsy updated"
            if launchAtLoginLoaded {
                DispatchQueue.main.asyncAfter(deadline: .now() + 0.8) {
                    NSApplication.shared.terminate(nil)
                }
            }
        } catch {
            softwareUpdateError = error.localizedDescription
        }
    }

    private func loadCachedState() {
        let defaults = UserDefaults.standard
        if let cachedActivity = defaults.string(forKey: Defaults.cachedActivityPayload),
           let data = cachedActivity.data(using: .utf8),
           let decoded = try? JSONDecoder().decode(ActivityPayload.self, from: data) {
            payload = decoded
            lastRefresh = defaults.object(forKey: Defaults.cachedActivityDate) as? Date
        }

        if let cachedLaunchAgent = defaults.string(forKey: Defaults.cachedLaunchAgentStatus),
           let data = cachedLaunchAgent.data(using: .utf8),
           let decoded = try? JSONDecoder().decode(LaunchAgentStatus.self, from: data) {
            launchAgentStatus = decoded
        }

        if let cachedInstructionStatus = defaults.string(forKey: Defaults.cachedInstructionStatus),
           let data = cachedInstructionStatus.data(using: .utf8),
           let decoded = try? JSONDecoder().decode(InstructionStatusPayload.self, from: data) {
            instructionStatus = decoded
        }

        if let cachedSetupStatus = defaults.string(forKey: Defaults.cachedSetupStatus),
           let data = cachedSetupStatus.data(using: .utf8),
           let decoded = try? JSONDecoder().decode(SetupStatusPayload.self, from: data) {
            setupStatus = decoded
        }
    }

    private func cacheActivityPayload(_ output: String) {
        let defaults = UserDefaults.standard
        defaults.set(output, forKey: Defaults.cachedActivityPayload)
        defaults.set(lastRefresh, forKey: Defaults.cachedActivityDate)
    }
}

private func agentDisplayName(_ agent: String) -> String {
    switch agent {
    case "codex":
        return "Codex"
    case "claude":
        return "Claude Code"
    case "gemini":
        return "Gemini CLI"
    case "opencode":
        return "OpenCode"
    case "cursor":
        return "Cursor"
    case "copilot":
        return "GitHub Copilot"
    case "windsurf":
        return "Windsurf"
    default:
        return agent
    }
}

private func instructionDescription(_ agent: String) -> String {
    switch agent {
    case "codex":
        return "Codex global instructions"
    case "claude":
        return "Claude Code global memory"
    case "gemini":
        return "Gemini CLI global context"
    case "opencode":
        return "OpenCode global instructions"
    case "cursor":
        return "Cursor project rules"
    case "copilot":
        return "GitHub Copilot instructions"
    case "windsurf":
        return "Windsurf rules"
    default:
        return "\(agentDisplayName(agent)) global instructions"
    }
}

private extension String {
    func clippedForMenuBar(limit: Int = 30) -> String {
        guard count > limit, limit > 3 else { return self }
        return "\(prefix(limit - 3))..."
    }
}
