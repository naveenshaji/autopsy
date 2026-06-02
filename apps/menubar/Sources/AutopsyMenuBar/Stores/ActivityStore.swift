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
    }

    private var timer: Timer?

    init() {
        cliPath = UserDefaults.standard.string(forKey: Defaults.cliPath) ?? Self.defaultCLIPath
        loadCachedState()
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
        let knownAgents = ["codex", "claude", "gemini", "opencode"]
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
            Task {
                await loadInstructionStatus()
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

    private func loadActivity() async {
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
            let decoded = try JSONDecoder().decode(ActivityPayload.self, from: Data(output.utf8))
            payload = decoded
            lastRefresh = Date()
            cacheActivityPayload(output)
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
            await loadActivity()
        } catch {
            instructionStatusError = error.localizedDescription
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
    default:
        return "\(agentDisplayName(agent)) global instructions"
    }
}
