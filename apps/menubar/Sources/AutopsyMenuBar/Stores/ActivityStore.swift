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
    @Published var sharedServerStatus: SharedServerPayload?
    @Published var sharedServerError: String?
    @Published var isCheckingSharedServer = false
    @Published var isManagingSharedAccess = false
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
    private let workerKeepaliveIntervalSeconds: UInt64 = 60
    private var activityWatcher: ActivitySnapshotWatcher?
    private var workerKeepaliveTask: Task<Void, Never>?
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
        workerKeepaliveTask?.cancel()
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

    var onboarding: OnboardingPayload? {
        payload?.onboarding
    }

    var hasEmptyMemoryState: Bool {
        onboarding?.empty == true || (!hasPriorMemory && payload?.workflow?.coverage == "none")
    }

    var onboardingTitle: String {
        let title = onboarding?.title?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        return title.isEmpty ? "No memory yet" : title
    }

    var onboardingMessage: String {
        let message = onboarding?.message?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        return message.isEmpty
            ? "Run autopsy install once, then keep using your coding agent. Memory writes and consults will appear here when agents use Autopsy."
            : message
    }

    var emptyWritesText: String {
        hasEmptyMemoryState
            ? "Memory writes appear after an agent records decisions, outcomes, or useful context."
            : "No memory writes in the recent activity window."
    }

    var emptyConsultsText: String {
        hasEmptyMemoryState
            ? "Consults appear when an agent asks Autopsy for prior context."
            : "No consults in the recent activity window."
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

    var currentSharedServer: SharedServerPayload? {
        sharedServerStatus ?? payload?.sharedServer
    }

    var sharedServerStatusText: String {
        if isCheckingSharedServer {
            return "Checking"
        }
        if let sharedServerError, !sharedServerError.isEmpty {
            return sharedServerError.clippedForMenuBar(limit: 28)
        }
        guard let currentSharedServer else {
            return "Not configured"
        }
        if currentSharedServer.remoteOK == true {
            return "Connected"
        }
        if currentSharedServer.configured == true {
            return currentSharedServer.status == "error" ? "Connection failed" : "Configured"
        }
        return "Not configured"
    }

    var sharedServerEndpoint: String {
        currentSharedServer?.baseURL ?? ""
    }

    var sharedServerGraphSlug: String {
        currentSharedServer?.graphSlug ?? ""
    }

    var sharedServerDefaultRepoScope: String {
        workspacePath.isEmpty ? "*" : workspacePath
    }

    var sharedServerUserText: String {
        guard let me = currentSharedServer?.me else { return "" }
        if let email = me.email, !email.isEmpty {
            return email
        }
        return me.id ?? ""
    }

    var sharedServerUsersText: String {
        guard let team = currentSharedServer?.team else { return "" }
        if let count = team.usersCount {
            return "\(count)"
        }
        if let error = team.usersError, !error.isEmpty {
            return error.clippedForMenuBar(limit: 28)
        }
        return ""
    }

    var sharedServerGrantsText: String {
        guard let team = currentSharedServer?.team else { return "" }
        if let count = team.grantsCount {
            if let roleCounts = team.roleCounts, !roleCounts.isEmpty {
                let roles = roleCounts
                    .sorted { $0.key < $1.key }
                    .map { "\($0.key): \($0.value)" }
                    .joined(separator: ", ")
                return "\(count) (\(roles))"
            }
            return "\(count)"
        }
        if let error = team.grantsError, !error.isEmpty {
            return error.clippedForMenuBar(limit: 28)
        }
        return ""
    }

    var shouldShowOnboardingPrompt: Bool {
        (hasEmptyMemoryState || instructionStatus != nil) && !hasPriorMemory && !hasInstalledInstructions
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

                if menubar.installed == true {
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
        startWorkerKeepalive()
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
                await loadSharedServerStatus()
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

    func configureSharedServerFromOwnerConfig() {
        Task {
            await configureSharedServer()
        }
    }

    func checkSharedServer() {
        Task {
            await loadSharedServerStatus(checkRemote: true)
        }
    }

    func refreshSharedServerTeam() {
        Task {
            await loadSharedServerTeamStatus()
        }
    }

    func createSharedServerUser(email: String, name: String) {
        Task {
            await createSharedUser(email: email, name: name)
        }
    }

    func inviteSharedServerUser(email: String, name: String, repoScope: String, role: String, label: String) {
        Task {
            await inviteSharedUser(email: email, name: name, repoScope: repoScope, role: role, label: label)
        }
    }

    func grantSharedServerAccess(userID: String, repoScope: String, role: String) {
        Task {
            await grantSharedAccess(userID: userID, repoScope: repoScope, role: role)
        }
    }

    func revokeSharedServerAccess(userID: String, repoScope: String) {
        Task {
            await revokeSharedAccess(userID: userID, repoScope: repoScope)
        }
    }

    func archiveSharedServerMemory(stableKey: String, repoScope: String, reason: String) {
        Task {
            await updateSharedMemoryLifecycle(action: "archive", stableKey: stableKey, repoScope: repoScope, reason: reason)
        }
    }

    func restoreSharedServerMemory(stableKey: String, repoScope: String, reason: String) {
        Task {
            await updateSharedMemoryLifecycle(action: "restore", stableKey: stableKey, repoScope: repoScope, reason: reason)
        }
    }

    func copySharedServerMemories(repoScope: String, includeArchived: Bool) {
        Task {
            await copySharedMemories(repoScope: repoScope, includeArchived: includeArchived)
        }
    }

    func issueSharedServerToken(userID: String, label: String) {
        Task {
            await issueSharedToken(userID: userID, label: label)
        }
    }

    func revokeSharedServerToken(tokenID: String, repoScope: String) {
        Task {
            await revokeSharedToken(tokenID: tokenID, repoScope: repoScope)
        }
    }

    func copySharedServerAudit(repoScope: String) {
        Task {
            await copySharedAudit(repoScope: repoScope)
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

    private func startWorkerKeepalive() {
        guard workerKeepaliveTask == nil else { return }
        workerKeepaliveTask = Task { [weak self] in
            while !Task.isCancelled {
                await self?.keepWorkerAlive()
                try? await Task.sleep(nanoseconds: (self?.workerKeepaliveIntervalSeconds ?? 60) * 1_000_000_000)
            }
        }
    }

    private func keepWorkerAlive() async {
        do {
            _ = try await AutopsyCLI(executable: cliPath, timeoutSeconds: 25).run([
                "menubar",
                "--keep-worker-alive",
            ])
        } catch {
            // Silent by design: the next visible memory request will surface persistent worker issues.
        }
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

    private func loadSharedServerStatus(checkRemote: Bool = false) async {
        guard !isCheckingSharedServer else { return }
        isCheckingSharedServer = true
        sharedServerError = nil
        defer {
            isCheckingSharedServer = false
        }

        do {
            let command = checkRemote ? "health" : "status"
            let output = try await AutopsyCLI(executable: cliPath, timeoutSeconds: checkRemote ? 20 : 10).run([
                "shared-server",
                command,
            ])
            sharedServerStatus = try JSONDecoder().decode(SharedServerPayload.self, from: Data(output.utf8))
        } catch {
            sharedServerError = error.localizedDescription
        }
    }

    private func loadSharedServerTeamStatus() async {
        guard !isCheckingSharedServer else { return }
        isCheckingSharedServer = true
        sharedServerError = nil
        defer {
            isCheckingSharedServer = false
        }

        do {
            let output = try await AutopsyCLI(executable: cliPath, timeoutSeconds: 25).run([
                "shared-server",
                "team-status",
            ])
            sharedServerStatus = try JSONDecoder().decode(SharedServerPayload.self, from: Data(output.utf8))
        } catch {
            sharedServerError = error.localizedDescription
        }
    }

    private func configureSharedServer() async {
        guard !isCheckingSharedServer else { return }
        isCheckingSharedServer = true
        sharedServerError = nil
        lastActionMessage = nil
        defer {
            isCheckingSharedServer = false
        }

        do {
            let output = try await AutopsyCLI(executable: cliPath, timeoutSeconds: 15).run([
                "shared-server",
                "configure",
                "--from-owner-config",
            ])
            sharedServerStatus = try JSONDecoder().decode(SharedServerPayload.self, from: Data(output.utf8))
            lastActionMessage = "Shared memory configured"
        } catch {
            sharedServerError = error.localizedDescription
        }
    }

    private func createSharedUser(email: String, name: String) async {
        let trimmedEmail = email.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmedEmail.isEmpty else {
            sharedServerError = "Email required"
            return
        }
        guard !isManagingSharedAccess else { return }
        isManagingSharedAccess = true
        sharedServerError = nil
        lastActionMessage = nil
        defer {
            isManagingSharedAccess = false
        }

        do {
            let output = try await AutopsyCLI(executable: cliPath, timeoutSeconds: 20).run([
                "shared-server",
                "create-user",
                "--email",
                trimmedEmail,
                "--name",
                name.trimmingCharacters(in: .whitespacesAndNewlines),
            ])
            if let userID = jsonObject(from: output)?["id"] as? String, !userID.isEmpty {
                NSPasteboard.general.clearContents()
                NSPasteboard.general.setString(userID, forType: .string)
                lastActionMessage = "Shared user ID copied"
                clearLastActionMessageAfterDelay(expected: "Shared user ID copied")
            } else {
                lastActionMessage = "Shared user created"
            }
            await loadSharedServerTeamStatus()
        } catch {
            sharedServerError = error.localizedDescription
        }
    }

    private func grantSharedAccess(userID: String, repoScope: String, role: String) async {
        let trimmedUserID = userID.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmedUserID.isEmpty else {
            sharedServerError = "User ID required"
            return
        }
        await runSharedAccessCommand(
            [
                "shared-server",
                "grant",
                "--user-id",
                trimmedUserID,
                "--role",
                role,
                "--repo-scope",
                normalizedRepoScope(repoScope),
            ],
            successMessage: "Shared grant updated"
        )
    }

    private func inviteSharedUser(email: String, name: String, repoScope: String, role: String, label: String) async {
        let trimmedEmail = email.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmedEmail.isEmpty else {
            sharedServerError = "Email required"
            return
        }
        guard !isManagingSharedAccess else { return }
        isManagingSharedAccess = true
        sharedServerError = nil
        lastActionMessage = nil
        defer {
            isManagingSharedAccess = false
        }

        do {
            let trimmedLabel = label.trimmingCharacters(in: .whitespacesAndNewlines)
            let output = try await AutopsyCLI(executable: cliPath, timeoutSeconds: 20).run([
                "shared-server",
                "invite",
                "--email",
                trimmedEmail,
                "--name",
                name.trimmingCharacters(in: .whitespacesAndNewlines),
                "--repo-scope",
                normalizedRepoScope(repoScope),
                "--role",
                role,
                "--label",
                trimmedLabel.isEmpty ? "menubar-invite" : trimmedLabel,
            ])
            let invitePayload = jsonObject(from: output)
            guard let token = invitePayload?["token"] as? String, !token.isEmpty else {
                throw CLIError.failed("shared server did not return an invite token")
            }
            let tokenRecord = invitePayload?["token_record"] as? [String: Any]
            let tokenID = tokenRecord?["id"] as? String
            NSPasteboard.general.clearContents()
            NSPasteboard.general.setString(token, forType: .string)
            if let tokenID, !tokenID.isEmpty {
                lastActionMessage = "Invite token copied; ID \(tokenID)"
                clearLastActionMessageAfterDelay(expected: "Invite token copied; ID \(tokenID)")
            } else {
                lastActionMessage = "Invite token copied"
                clearLastActionMessageAfterDelay(expected: "Invite token copied")
            }
            await loadSharedServerTeamStatus()
        } catch {
            sharedServerError = error.localizedDescription
        }
    }

    private func revokeSharedAccess(userID: String, repoScope: String) async {
        let trimmedUserID = userID.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmedUserID.isEmpty else {
            sharedServerError = "User ID required"
            return
        }
        await runSharedAccessCommand(
            [
                "shared-server",
                "revoke-grant",
                "--user-id",
                trimmedUserID,
                "--repo-scope",
                normalizedRepoScope(repoScope),
            ],
            successMessage: "Shared grant revoked"
        )
    }

    private func issueSharedToken(userID: String, label: String) async {
        let trimmedUserID = userID.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmedUserID.isEmpty else {
            sharedServerError = "User ID required"
            return
        }
        guard !isManagingSharedAccess else { return }
        isManagingSharedAccess = true
        sharedServerError = nil
        lastActionMessage = nil
        defer {
            isManagingSharedAccess = false
        }

        do {
            let output = try await AutopsyCLI(executable: cliPath, timeoutSeconds: 20).run([
                "shared-server",
                "create-token",
                "--user-id",
                trimmedUserID,
                "--label",
                label.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty ? "menubar" : label.trimmingCharacters(in: .whitespacesAndNewlines),
            ])
            guard let token = jsonObject(from: output)?["token"] as? String, !token.isEmpty else {
                throw CLIError.failed("shared server did not return a token")
            }
            NSPasteboard.general.clearContents()
            NSPasteboard.general.setString(token, forType: .string)
            lastActionMessage = "Shared token copied"
            clearLastActionMessageAfterDelay(expected: "Shared token copied")
            await loadSharedServerTeamStatus()
        } catch {
            sharedServerError = error.localizedDescription
        }
    }

    private func updateSharedMemoryLifecycle(action: String, stableKey: String, repoScope: String, reason: String) async {
        let trimmedStableKey = stableKey.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmedStableKey.isEmpty else {
            sharedServerError = "Stable key required"
            return
        }
        await runSharedAccessCommand(
            [
                "shared-server",
                action,
                trimmedStableKey,
                "--repo-scope",
                normalizedRepoScope(repoScope),
                "--reason",
                reason.trimmingCharacters(in: .whitespacesAndNewlines),
            ],
            successMessage: action == "restore" ? "Shared memory restored" : "Shared memory archived"
        )
    }

    private func copySharedMemories(repoScope: String, includeArchived: Bool) async {
        guard !isManagingSharedAccess else { return }
        isManagingSharedAccess = true
        sharedServerError = nil
        lastActionMessage = nil
        defer {
            isManagingSharedAccess = false
        }

        do {
            var arguments = [
                "shared-server",
                "list",
                "--repo-scope",
                normalizedRepoScope(repoScope),
                "--limit",
                "50",
            ]
            if includeArchived {
                arguments.append("--include-archived")
            }
            let output = try await AutopsyCLI(executable: cliPath, timeoutSeconds: 20).run(arguments)
            NSPasteboard.general.clearContents()
            NSPasteboard.general.setString(output.trimmingCharacters(in: .whitespacesAndNewlines), forType: .string)
            lastActionMessage = includeArchived ? "Shared memories copied with archive" : "Shared memories copied"
            clearLastActionMessageAfterDelay(expected: lastActionMessage ?? "")
        } catch {
            sharedServerError = error.localizedDescription
        }
    }

    private func revokeSharedToken(tokenID: String, repoScope: String) async {
        let trimmedTokenID = tokenID.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmedTokenID.isEmpty else {
            sharedServerError = "Token ID required"
            return
        }
        await runSharedAccessCommand(
            [
                "shared-server",
                "revoke-token",
                trimmedTokenID,
                "--repo-scope",
                normalizedRepoScope(repoScope),
            ],
            successMessage: "Shared token revoked"
        )
    }

    private func copySharedAudit(repoScope: String) async {
        guard !isManagingSharedAccess else { return }
        isManagingSharedAccess = true
        sharedServerError = nil
        lastActionMessage = nil
        defer {
            isManagingSharedAccess = false
        }

        do {
            let output = try await AutopsyCLI(executable: cliPath, timeoutSeconds: 20).run([
                "shared-server",
                "audit",
                "--repo-scope",
                normalizedRepoScope(repoScope),
                "--limit",
                "50",
            ])
            NSPasteboard.general.clearContents()
            NSPasteboard.general.setString(output.trimmingCharacters(in: .whitespacesAndNewlines), forType: .string)
            lastActionMessage = "Shared audit copied"
            clearLastActionMessageAfterDelay(expected: "Shared audit copied")
        } catch {
            sharedServerError = error.localizedDescription
        }
    }

    private func runSharedAccessCommand(_ arguments: [String], successMessage: String) async {
        guard !isManagingSharedAccess else { return }
        isManagingSharedAccess = true
        sharedServerError = nil
        lastActionMessage = nil
        defer {
            isManagingSharedAccess = false
        }

        do {
            _ = try await AutopsyCLI(executable: cliPath, timeoutSeconds: 20).run(arguments)
            lastActionMessage = successMessage
            await loadSharedServerTeamStatus()
        } catch {
            sharedServerError = error.localizedDescription
        }
    }

    private func normalizedRepoScope(_ value: String) -> String {
        let trimmed = value.trimmingCharacters(in: .whitespacesAndNewlines)
        return trimmed.isEmpty ? sharedServerDefaultRepoScope : trimmed
    }

    private func jsonObject(from output: String) -> [String: Any]? {
        guard let data = output.data(using: .utf8),
              let object = try? JSONSerialization.jsonObject(with: data),
              let dictionary = object as? [String: Any]
        else {
            return nil
        }
        return dictionary
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
            clearLastActionMessageAfterDelay(expected: "Instructions copied")
        } catch {
            instructionStatusError = error.localizedDescription
        }
    }

    private func clearLastActionMessageAfterDelay(expected: String) {
        Task { [weak self] in
            try? await Task.sleep(nanoseconds: 2_000_000_000)
            await MainActor.run {
                guard self?.lastActionMessage == expected else { return }
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
