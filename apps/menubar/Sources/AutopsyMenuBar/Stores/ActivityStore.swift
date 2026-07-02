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
    private static let sharedSecurityAuditActions = [
        "auth_failure",
        "authorization_denied",
        "disable_user",
        "enable_user",
        "grant_access",
        "handoff_owner",
        "invite_user",
        "revoke_grant",
        "revoke_scoped_token",
        "reset_repo_policy",
        "update_repo_policy",
    ]
    private static let sharedAccessChangeAuditActions = [
        "grant_access",
        "handoff_owner",
        "invite_user",
        "revoke_grant",
        "revoke_scoped_token",
        "reset_repo_policy",
        "update_repo_policy",
    ]
    private static let sharedActivityAuditActions = [
        "read_users",
        "read_user_tokens",
        "read_scoped_tokens",
        "read_grants",
        "read_access_check",
        "read_repo_policy",
        "read_repo_policies",
        "read_audit_events",
        "read_audit_integrity",
        "verify_audit_receipt",
        "read_memories",
        "read_memory_history",
        "read_shared_relations",
    ]
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

    var sharedServerFeaturesText: String {
        guard let sharedServer = currentSharedServer else { return "" }
        if let capabilities = sharedServer.capabilities {
            let enabled = [
                ("owner_handoff", "owner handoff"),
                ("grant_downgrade_token_revocation", "downgrade cleanup"),
                ("tamper_evident_audit_chain", "audit chain"),
                ("repo_policies", "repo policies"),
                ("repo_policy_inventory", "policy inventory"),
                ("mutation_audit_receipts", "audit receipts"),
                ("audit_receipt_verification", "audit verification"),
                ("personal_shared_relations", "personal links"),
                ("unsafe_shared_write_guard", "write guard"),
            ].compactMap { key, label in
                capabilities.capabilities?[key] == true ? label : nil
            }
            if !enabled.isEmpty {
                return enabled.joined(separator: ", ").clippedForMenuBar(limit: 80)
            }
            if let features = capabilities.features, !features.isEmpty {
                return "\(features.count) features"
            }
        }
        if let error = sharedServer.capabilitiesError, !error.isEmpty {
            return error.clippedForMenuBar(limit: 28)
        }
        return ""
    }

    var sharedServerUsersText: String {
        guard let team = currentSharedServer?.team else { return "" }
        if let count = team.usersCount {
            let disabled = team.disabledUsersCount ?? 0
            if disabled > 0 {
                var parts = ["disabled: \(disabled)"]
                if let active = team.activeUsersCount {
                    parts.insert("active: \(active)", at: 0)
                }
                return "\(count) (\(parts.joined(separator: ", ")))"
            }
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
            var parts: [String] = []
            if let roleCounts = team.roleCounts, !roleCounts.isEmpty {
                parts.append(contentsOf: roleCounts
                    .sorted { $0.key < $1.key }
                    .map { "\($0.key): \($0.value)" })
            }
            if let activeOwners = team.activeOwnerGrantsCount {
                parts.append("active owners: \(activeOwners)")
            }
            if team.lastOwnerGrantRisk == true {
                parts.append("last owner")
            }
            if let disabledOwners = team.disabledOwnerGrantsCount, disabledOwners > 0 {
                parts.append("disabled owners: \(disabledOwners)")
            }
            if let disabled = team.disabledGrantsCount, disabled > 0 {
                parts.append("disabled: \(disabled)")
            }
            return parts.isEmpty ? "\(count)" : "\(count) (\(parts.joined(separator: ", ")))"
        }
        if let error = team.grantsError, !error.isEmpty {
            return error.clippedForMenuBar(limit: 28)
        }
        return ""
    }

    var sharedServerTokensText: String {
        guard let team = currentSharedServer?.team else { return "" }
        if let count = team.tokensCount {
            var parts: [String] = []
            if let active = team.activeTokensCount {
                parts.append("active: \(active)")
            }
            if let expired = team.expiredTokensCount, expired > 0 {
                parts.append("expired: \(expired)")
            }
            if let revoked = team.revokedTokensCount, revoked > 0 {
                parts.append("revoked: \(revoked)")
            }
            if let disabled = team.disabledTokensCount, disabled > 0 {
                parts.append("disabled: \(disabled)")
            }
            if parts.isEmpty {
                return "\(count)"
            }
            return "\(count) (\(parts.joined(separator: ", ")))"
        }
        if let error = team.tokensError, !error.isEmpty {
            return error.clippedForMenuBar(limit: 28)
        }
        return ""
    }

    var sharedServerPoliciesText: String {
        guard let team = currentSharedServer?.team else { return "" }
        if let count = team.policiesCount {
            var parts: [String] = []
            if let constrained = team.constrainedPoliciesCount, constrained > 0 {
                parts.append("constrained: \(constrained)")
            }
            if let disabledShared = team.disabledSharedPolicyCount, disabledShared > 0 {
                parts.append("shared disabled: \(disabledShared)")
            }
            if let disabledPersonal = team.disabledPersonalPolicyCount, disabledPersonal > 0 {
                parts.append("personal disabled: \(disabledPersonal)")
            }
            if team.policyInventoryRepoFilterPresent == true {
                parts.append("repo filtered")
            }
            return parts.isEmpty ? "\(count)" : "\(count) (\(parts.joined(separator: ", ")))"
        }
        if let error = team.policiesError, !error.isEmpty {
            return error.clippedForMenuBar(limit: 28)
        }
        return ""
    }

    var sharedServerAuditIntegrityText: String {
        guard let team = currentSharedServer?.team else { return "" }
        if let integrity = team.auditIntegrity {
            let status = integrity.status ?? ""
            var parts = [status.isEmpty ? "unknown" : status]
            if let counts = integrity.integrityCounts {
                let missing = counts["missing"] ?? 0
                let mismatch = counts["mismatch"] ?? 0
                if missing > 0 {
                    parts.append("missing: \(missing)")
                }
                if mismatch > 0 {
                    parts.append("mismatch: \(mismatch)")
                }
            }
            if let chain = integrity.chain {
                if let breaks = chain.chainBreakCount, breaks > 0 {
                    parts.append("breaks: \(breaks)")
                } else if let status = chain.status, !status.isEmpty {
                    parts.append("chain: \(status)")
                }
                if let externalGaps = chain.externalGapCount, externalGaps > 0 {
                    parts.append("gaps: \(externalGaps)")
                }
            }
            return parts.joined(separator: ", ")
        }
        if let error = team.auditIntegrityError, !error.isEmpty {
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

    func copySharedServerAccessCheck(repoScope: String, mode: String) {
        Task {
            await copySharedAccessCheck(repoScope: repoScope, mode: mode)
        }
    }

    func copySharedServerRepoPolicy(repoScope: String) {
        Task {
            await copySharedRepoPolicy(repoScope: repoScope)
        }
    }

    func copySharedServerRepoPolicyInventory(repoScope: String) {
        Task {
            await copySharedRepoPolicyInventory(repoScope: repoScope)
        }
    }

    func updateSharedServerRepoPolicy(
        repoScope: String,
        relationLabels: String,
        minFactRating: String,
        allowSharedRelations: Bool,
        allowPersonalRelations: Bool,
        notes: String
    ) {
        Task {
            await updateSharedRepoPolicy(
                repoScope: repoScope,
                relationLabels: relationLabels,
                minFactRating: minFactRating,
                allowSharedRelations: allowSharedRelations,
                allowPersonalRelations: allowPersonalRelations,
                notes: notes
            )
        }
    }

    func resetSharedServerRepoPolicy(repoScope: String) {
        Task {
            await resetSharedRepoPolicy(repoScope: repoScope)
        }
    }

    func copySharedServerUsers() {
        Task {
            await copySharedUsers()
        }
    }

    func copySharedServerGrants(repoScope: String) {
        Task {
            await copySharedGrants(repoScope: repoScope)
        }
    }

    func createSharedServerUser(email: String, name: String) {
        Task {
            await createSharedUser(email: email, name: name)
        }
    }

    func inviteSharedServerUser(email: String, name: String, repoScope: String, role: String, label: String, expiresAt: String) {
        Task {
            await inviteSharedUser(email: email, name: name, repoScope: repoScope, role: role, label: label, expiresAt: expiresAt)
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

    func handoffSharedServerOwner(fromUserID: String, toUserID: String, repoScope: String, sourceRoleAfter: String) {
        Task {
            await handoffSharedOwner(
                fromUserID: fromUserID,
                toUserID: toUserID,
                repoScope: repoScope,
                sourceRoleAfter: sourceRoleAfter
            )
        }
    }

    func disableSharedServerUser(userID: String) {
        Task {
            await updateSharedUserLifecycle(action: "disable-user", userID: userID)
        }
    }

    func enableSharedServerUser(userID: String) {
        Task {
            await updateSharedUserLifecycle(action: "enable-user", userID: userID)
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

    func restoreSharedServerMemoryVersion(stableKey: String, versionID: String, expectedVersionNS: String, repoScope: String, reason: String) {
        Task {
            await restoreSharedMemoryVersion(
                stableKey: stableKey,
                versionID: versionID,
                expectedVersionNS: expectedVersionNS,
                repoScope: repoScope,
                reason: reason
            )
        }
    }

    func copySharedServerMemories(repoScope: String, includeArchived: Bool) {
        Task {
            await copySharedMemories(repoScope: repoScope, includeArchived: includeArchived)
        }
    }

    func copySharedServerMemoryHistory(stableKey: String, repoScope: String) {
        Task {
            await copySharedMemoryHistory(stableKey: stableKey, repoScope: repoScope)
        }
    }

    func copySharedServerContext(repoScope: String, query: String, includeArchived: Bool, includeRelations: Bool, minFactRating: String) {
        Task {
            await copySharedContext(repoScope: repoScope, query: query, includeArchived: includeArchived, includeRelations: includeRelations, minFactRating: minFactRating)
        }
    }

    func relateSharedServerMemories(sourceKey: String, targetKey: String, repoScope: String, relation: String, fact: String, factRating: String) {
        Task {
            await relateSharedMemories(sourceKey: sourceKey, targetKey: targetKey, repoScope: repoScope, relation: relation, fact: fact, factRating: factRating)
        }
    }

    func copySharedServerRelations(repoScope: String, sourceKey: String, targetKey: String) {
        Task {
            await copySharedRelations(repoScope: repoScope, sourceKey: sourceKey, targetKey: targetKey)
        }
    }

    func unrelateSharedServerRelation(relationID: String, repoScope: String) {
        Task {
            await unrelateSharedMemory(relationID: relationID, repoScope: repoScope)
        }
    }

    func linkSharedServerPersonalMemory(personalKey: String, sharedKey: String, repoScope: String, relation: String, fact: String, factRating: String) {
        Task {
            await linkPersonalSharedMemory(personalKey: personalKey, sharedKey: sharedKey, repoScope: repoScope, relation: relation, fact: fact, factRating: factRating)
        }
    }

    func copySharedServerPersonalLinks(repoScope: String, personalKey: String, sharedKey: String) {
        Task {
            await copySharedPersonalLinks(repoScope: repoScope, personalKey: personalKey, sharedKey: sharedKey)
        }
    }

    func copySharedServerPersonalContext(repoScope: String, personalKey: String, includeArchived: Bool, includeRelations: Bool, minFactRating: String) {
        Task {
            await copySharedPersonalContext(repoScope: repoScope, personalKey: personalKey, includeArchived: includeArchived, includeRelations: includeRelations, minFactRating: minFactRating)
        }
    }

    func unlinkSharedServerPersonalRelation(relationID: String, repoScope: String) {
        Task {
            await unlinkPersonalSharedMemory(relationID: relationID, repoScope: repoScope)
        }
    }

    func issueSharedServerToken(userID: String, label: String, expiresAt: String) {
        Task {
            await issueSharedToken(userID: userID, label: label, expiresAt: expiresAt)
        }
    }

    func revokeSharedServerToken(tokenID: String, repoScope: String) {
        Task {
            await revokeSharedToken(tokenID: tokenID, repoScope: repoScope)
        }
    }

    func copySharedServerScopedTokens(repoScope: String) {
        Task {
            await copySharedScopedTokens(repoScope: repoScope)
        }
    }

    func copySharedServerAudit(repoScope: String) {
        Task {
            await copySharedAudit(repoScope: repoScope)
        }
    }

    func copySharedServerContextAudit(repoScope: String) {
        Task {
            await copySharedContextAudit(repoScope: repoScope)
        }
    }

    func copySharedServerActivityAudit(repoScope: String) {
        Task {
            await copySharedActivityAudit(repoScope: repoScope)
        }
    }

    func copySharedServerAccessChangeAudit(repoScope: String) {
        Task {
            await copySharedAccessChangeAudit(repoScope: repoScope)
        }
    }

    func copySharedServerSecurityAudit() {
        Task {
            await copySharedSecurityAudit()
        }
    }

    func copySharedServerAuditIntegrity(repoScope: String) {
        Task {
            await copySharedAuditIntegrity(repoScope: repoScope)
        }
    }

    func verifySharedServerAuditReceipt(auditID: String, integrityHash: String, repoScope: String, action: String, target: String) {
        Task {
            await verifySharedAuditReceipt(
                auditID: auditID,
                integrityHash: integrityHash,
                repoScope: repoScope,
                action: action,
                target: target
            )
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
            let repoScope = sharedServerDefaultRepoScope
            let output = try await AutopsyCLI(executable: cliPath, timeoutSeconds: 25).run([
                "shared-server",
                "team-status",
                "--repo-scope",
                repoScope,
            ])
            sharedServerStatus = try JSONDecoder().decode(SharedServerPayload.self, from: Data(output.utf8))
        } catch {
            sharedServerError = error.localizedDescription
        }
    }

    private func copySharedAccessCheck(repoScope: String, mode: String) async {
        guard !isManagingSharedAccess else { return }
        isManagingSharedAccess = true
        sharedServerError = nil
        lastActionMessage = nil
        defer {
            isManagingSharedAccess = false
        }

        do {
            let scope = normalizedRepoScope(repoScope)
            let output = try await AutopsyCLI(executable: cliPath, timeoutSeconds: 15).run([
                "shared-server",
                "access-check",
                "--repo-scope",
                scope,
                "--mode",
                mode.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty ? "read" : mode.trimmingCharacters(in: .whitespacesAndNewlines),
            ])
            NSPasteboard.general.clearContents()
            NSPasteboard.general.setString(sharedAccessCheckReport(from: output, repoScope: scope), forType: .string)
            lastActionMessage = "Access check copied"
            clearLastActionMessageAfterDelay(expected: "Access check copied")
        } catch {
            sharedServerError = error.localizedDescription
        }
    }

    private func copySharedRepoPolicy(repoScope: String) async {
        guard !isManagingSharedAccess else { return }
        isManagingSharedAccess = true
        sharedServerError = nil
        lastActionMessage = nil
        defer {
            isManagingSharedAccess = false
        }

        do {
            let scope = normalizedRepoScope(repoScope)
            let output = try await AutopsyCLI(executable: cliPath, timeoutSeconds: 15).run([
                "shared-server",
                "policy",
                "--repo-scope",
                scope,
            ])
            NSPasteboard.general.clearContents()
            NSPasteboard.general.setString(sharedRepoPolicyReport(from: output, repoScope: scope), forType: .string)
            lastActionMessage = "Policy copied"
            clearLastActionMessageAfterDelay(expected: "Policy copied")
        } catch {
            sharedServerError = error.localizedDescription
        }
    }

    private func copySharedRepoPolicyInventory(repoScope: String) async {
        guard !isManagingSharedAccess else { return }
        isManagingSharedAccess = true
        sharedServerError = nil
        lastActionMessage = nil
        defer {
            isManagingSharedAccess = false
        }

        do {
            let filter = repoScope.trimmingCharacters(in: .whitespacesAndNewlines)
            var arguments = [
                "shared-server",
                "policies",
            ]
            if !filter.isEmpty {
                arguments += ["--repo-scope", filter]
            }
            let output = try await AutopsyCLI(executable: cliPath, timeoutSeconds: 15).run(arguments)
            NSPasteboard.general.clearContents()
            NSPasteboard.general.setString(sharedRepoPolicyInventoryReport(from: output, repoScope: filter), forType: .string)
            lastActionMessage = "Policy inventory copied"
            clearLastActionMessageAfterDelay(expected: "Policy inventory copied")
        } catch {
            sharedServerError = error.localizedDescription
        }
    }

    private func updateSharedRepoPolicy(
        repoScope: String,
        relationLabels: String,
        minFactRating: String,
        allowSharedRelations: Bool,
        allowPersonalRelations: Bool,
        notes: String
    ) async {
        let scope = normalizedRepoScope(repoScope)
        var arguments = [
            "shared-server",
            "update-policy",
            "--repo-scope",
            scope,
        ]
        let labels = relationLabels.trimmingCharacters(in: .whitespacesAndNewlines)
        if labels.isEmpty {
            arguments.append("--clear-relation-labels")
        } else {
            arguments += ["--allowed-relation-label", labels]
        }
        let rating = minFactRating.trimmingCharacters(in: .whitespacesAndNewlines)
        if !rating.isEmpty {
            arguments += ["--min-fact-rating", rating]
        }
        arguments.append(allowSharedRelations ? "--allow-shared-relations" : "--disable-shared-relations")
        arguments.append(allowPersonalRelations ? "--allow-personal-relations" : "--disable-personal-relations")
        arguments += ["--policy-notes", notes.trimmingCharacters(in: .whitespacesAndNewlines)]
        await runSharedAccessCommand(arguments, successMessage: "Policy updated", refreshTeam: false)
    }

    private func resetSharedRepoPolicy(repoScope: String) async {
        await runSharedAccessCommand(
            [
                "shared-server",
                "reset-policy",
                "--repo-scope",
                normalizedRepoScope(repoScope),
            ],
            successMessage: "Policy reset",
            refreshTeam: false
        )
    }

    private func copySharedUsers() async {
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
                "users",
            ])
            NSPasteboard.general.clearContents()
            NSPasteboard.general.setString(sharedUsersReport(from: output), forType: .string)
            lastActionMessage = "Shared users copied"
            clearLastActionMessageAfterDelay(expected: "Shared users copied")
        } catch {
            sharedServerError = error.localizedDescription
        }
    }

    private func copySharedGrants(repoScope: String) async {
        guard !isManagingSharedAccess else { return }
        isManagingSharedAccess = true
        sharedServerError = nil
        lastActionMessage = nil
        defer {
            isManagingSharedAccess = false
        }

        do {
            let scope = normalizedRepoScope(repoScope)
            let output = try await AutopsyCLI(executable: cliPath, timeoutSeconds: 20).run([
                "shared-server",
                "grants",
                "--repo-scope",
                scope,
            ])
            NSPasteboard.general.clearContents()
            NSPasteboard.general.setString(sharedGrantsReport(from: output, repoScope: scope), forType: .string)
            lastActionMessage = "Shared grants copied"
            clearLastActionMessageAfterDelay(expected: "Shared grants copied")
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
            successMessage: "Shared grant updated",
            successMessageFromOutput: { output in
                guard let payload = self.jsonObject(from: output) else {
                    return "Shared grant updated"
                }
                let revoked = self.auditInt(payload["revoked_scoped_token_count"]) ?? 0
                let alreadyRevoked = self.auditInt(payload["already_revoked_scoped_token_count"]) ?? 0
                var details: [String] = []
                if revoked > 0 {
                    details.append("\(revoked) stale invite token\(revoked == 1 ? "" : "s") revoked")
                }
                if alreadyRevoked > 0 {
                    details.append("\(alreadyRevoked) stale invite token\(alreadyRevoked == 1 ? "" : "s") already revoked")
                }
                guard !details.isEmpty else {
                    return "Shared grant updated"
                }
                return "Shared grant updated; \(details.joined(separator: ", "))"
            }
        )
    }

    private func inviteSharedUser(email: String, name: String, repoScope: String, role: String, label: String, expiresAt: String) async {
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
            let trimmedExpiresAt = expiresAt.trimmingCharacters(in: .whitespacesAndNewlines)
            var arguments = [
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
            ]
            if !trimmedExpiresAt.isEmpty {
                arguments.append(contentsOf: ["--expires-at", trimmedExpiresAt])
            }
            let output = try await AutopsyCLI(executable: cliPath, timeoutSeconds: 20).run(arguments)
            let invitePayload = jsonObject(from: output)
            guard let token = invitePayload?["token"] as? String, !token.isEmpty else {
                throw CLIError.failed("shared server did not return an invite token")
            }
            let tokenRecord = invitePayload?["token_record"] as? [String: Any]
            let tokenID = tokenRecord?["id"] as? String
            NSPasteboard.general.clearContents()
            NSPasteboard.general.setString(token, forType: .string)
            let message: String
            if let tokenID, !tokenID.isEmpty {
                message = messageWithAuditReceipt("Invite token copied; ID \(tokenID)", payload: invitePayload)
            } else {
                message = messageWithAuditReceipt("Invite token copied", payload: invitePayload)
            }
            lastActionMessage = message
            clearLastActionMessageAfterDelay(expected: message)
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
            successMessage: "Shared grant revoked",
            successMessageFromOutput: { output in
                guard let payload = self.jsonObject(from: output) else {
                    return "Shared grant revoked"
                }
                let revoked = self.auditInt(payload["revoked_scoped_token_count"]) ?? 0
                let alreadyRevoked = self.auditInt(payload["already_revoked_scoped_token_count"]) ?? 0
                var details: [String] = []
                if revoked > 0 {
                    details.append("\(revoked) invite token\(revoked == 1 ? "" : "s") revoked")
                }
                if alreadyRevoked > 0 {
                    details.append("\(alreadyRevoked) invite token\(alreadyRevoked == 1 ? "" : "s") already revoked")
                }
                guard !details.isEmpty else {
                    return "Shared grant revoked"
                }
                return "Shared grant revoked; \(details.joined(separator: ", "))"
            }
        )
    }

    private func handoffSharedOwner(fromUserID: String, toUserID: String, repoScope: String, sourceRoleAfter: String) async {
        let trimmedFromUserID = fromUserID.trimmingCharacters(in: .whitespacesAndNewlines)
        let trimmedToUserID = toUserID.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmedFromUserID.isEmpty, !trimmedToUserID.isEmpty else {
            sharedServerError = "Owner IDs required"
            return
        }
        guard trimmedFromUserID != trimmedToUserID else {
            sharedServerError = "Owner IDs must differ"
            return
        }
        await runSharedAccessCommand(
            [
                "shared-server",
                "handoff-owner",
                "--from-user-id",
                trimmedFromUserID,
                "--to-user-id",
                trimmedToUserID,
                "--repo-scope",
                normalizedRepoScope(repoScope),
                "--source-role-after",
                sourceRoleAfter,
            ],
            successMessage: "Shared owner handed off",
            successMessageFromOutput: { output in
                guard let payload = self.jsonObject(from: output) else {
                    return "Shared owner handed off"
                }
                let sourceAfter = self.auditString(payload["source_role_after"]) ?? sourceRoleAfter
                let revoked = self.auditInt(payload["revoked_scoped_token_count"]) ?? 0
                let alreadyRevoked = self.auditInt(payload["already_revoked_scoped_token_count"]) ?? 0
                var details: [String] = []
                if sourceAfter == "none" {
                    details.append("source removed")
                } else if !sourceAfter.isEmpty {
                    details.append("source \(sourceAfter)")
                }
                if revoked > 0 {
                    details.append("\(revoked) invite token\(revoked == 1 ? "" : "s") revoked")
                }
                if alreadyRevoked > 0 {
                    details.append("\(alreadyRevoked) invite token\(alreadyRevoked == 1 ? "" : "s") already revoked")
                }
                guard !details.isEmpty else {
                    return "Shared owner handed off"
                }
                return "Shared owner handed off; \(details.joined(separator: ", "))"
            }
        )
    }

    private func updateSharedUserLifecycle(action: String, userID: String) async {
        let trimmedUserID = userID.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmedUserID.isEmpty else {
            sharedServerError = "User ID required"
            return
        }
        let isDisable = action == "disable-user"
        await runSharedAccessCommand(
            [
                "shared-server",
                action,
                "--user-id",
                trimmedUserID,
            ],
            successMessage: isDisable ? "Shared user disabled" : "Shared user enabled",
            successMessageFromOutput: { output in
                guard let payload = self.jsonObject(from: output) else {
                    return isDisable ? "Shared user disabled" : "Shared user enabled"
                }
                if isDisable, self.auditBool(payload["already_disabled"]) == true {
                    return "Shared user already disabled"
                }
                if !isDisable, self.auditBool(payload["already_enabled"]) == true {
                    return "Shared user already enabled"
                }
                return isDisable ? "Shared user disabled" : "Shared user enabled"
            }
        )
    }

    private func issueSharedToken(userID: String, label: String, expiresAt: String) async {
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
            let trimmedLabel = label.trimmingCharacters(in: .whitespacesAndNewlines)
            let trimmedExpiresAt = expiresAt.trimmingCharacters(in: .whitespacesAndNewlines)
            var arguments = [
                "shared-server",
                "create-token",
                "--user-id",
                trimmedUserID,
                "--label",
                trimmedLabel.isEmpty ? "menubar" : trimmedLabel,
            ]
            if !trimmedExpiresAt.isEmpty {
                arguments.append(contentsOf: ["--expires-at", trimmedExpiresAt])
            }
            let output = try await AutopsyCLI(executable: cliPath, timeoutSeconds: 20).run(arguments)
            let payload = jsonObject(from: output)
            guard let token = payload?["token"] as? String, !token.isEmpty else {
                throw CLIError.failed("shared server did not return a token")
            }
            NSPasteboard.general.clearContents()
            NSPasteboard.general.setString(token, forType: .string)
            let message = messageWithAuditReceipt("Shared token copied", payload: payload)
            lastActionMessage = message
            clearLastActionMessageAfterDelay(expected: message)
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

    private func restoreSharedMemoryVersion(stableKey: String, versionID: String, expectedVersionNS: String, repoScope: String, reason: String) async {
        let trimmedStableKey = stableKey.trimmingCharacters(in: .whitespacesAndNewlines)
        let trimmedVersionID = versionID.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmedStableKey.isEmpty else {
            sharedServerError = "Stable key required"
            return
        }
        guard !trimmedVersionID.isEmpty else {
            sharedServerError = "Version ID required"
            return
        }
        var arguments = [
            "shared-server",
            "restore-version",
            trimmedStableKey,
            "--repo-scope",
            normalizedRepoScope(repoScope),
            "--version-id",
            trimmedVersionID,
            "--reason",
            reason.trimmingCharacters(in: .whitespacesAndNewlines),
        ]
        let trimmedExpected = expectedVersionNS.trimmingCharacters(in: .whitespacesAndNewlines)
        if !trimmedExpected.isEmpty {
            arguments += ["--expected-version-ns", trimmedExpected]
        }
        await runSharedAccessCommand(arguments, successMessage: "Shared version restored")
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

    private func copySharedMemoryHistory(stableKey: String, repoScope: String) async {
        let trimmedStableKey = stableKey.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmedStableKey.isEmpty else {
            sharedServerError = "Stable key required"
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
                "memory-history",
                trimmedStableKey,
                "--repo-scope",
                normalizedRepoScope(repoScope),
                "--limit",
                "20",
            ])
            NSPasteboard.general.clearContents()
            NSPasteboard.general.setString(output.trimmingCharacters(in: .whitespacesAndNewlines), forType: .string)
            lastActionMessage = "Shared history copied"
            clearLastActionMessageAfterDelay(expected: "Shared history copied")
        } catch {
            sharedServerError = error.localizedDescription
        }
    }

    private func copySharedContext(repoScope: String, query: String, includeArchived: Bool, includeRelations: Bool, minFactRating: String) async {
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
                "context",
                "--repo-scope",
                normalizedRepoScope(repoScope),
                "--query",
                query.trimmingCharacters(in: .whitespacesAndNewlines),
                "--limit",
                "8",
            ]
            if includeArchived {
                arguments.append("--include-archived")
            }
            if !includeRelations {
                arguments.append("--no-relations")
            }
            let trimmedMinFactRating = minFactRating.trimmingCharacters(in: .whitespacesAndNewlines)
            if !trimmedMinFactRating.isEmpty {
                arguments += ["--min-fact-rating", trimmedMinFactRating]
            }
            let output = try await AutopsyCLI(executable: cliPath, timeoutSeconds: 20).run(arguments)
            NSPasteboard.general.clearContents()
            NSPasteboard.general.setString(output.trimmingCharacters(in: .whitespacesAndNewlines), forType: .string)
            lastActionMessage = "Shared context copied"
            clearLastActionMessageAfterDelay(expected: "Shared context copied")
        } catch {
            sharedServerError = error.localizedDescription
        }
    }

    private func relateSharedMemories(sourceKey: String, targetKey: String, repoScope: String, relation: String, fact: String, factRating: String) async {
        let trimmedSourceKey = sourceKey.trimmingCharacters(in: .whitespacesAndNewlines)
        let trimmedTargetKey = targetKey.trimmingCharacters(in: .whitespacesAndNewlines)
        let trimmedRelation = relation.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmedSourceKey.isEmpty else {
            sharedServerError = "Source key required"
            return
        }
        guard !trimmedTargetKey.isEmpty else {
            sharedServerError = "Target key required"
            return
        }
        guard !trimmedRelation.isEmpty else {
            sharedServerError = "Relation required"
            return
        }
        var arguments = [
            "shared-server",
            "relate",
            trimmedSourceKey,
            trimmedTargetKey,
            "--repo-scope",
            normalizedRepoScope(repoScope),
            "--relation",
            trimmedRelation,
            "--fact",
            fact.trimmingCharacters(in: .whitespacesAndNewlines),
        ]
        let trimmedFactRating = factRating.trimmingCharacters(in: .whitespacesAndNewlines)
        if !trimmedFactRating.isEmpty {
            arguments += ["--fact-rating", trimmedFactRating]
        }
        await runSharedAccessCommand(
            arguments,
            successMessage: "Shared relation created",
            refreshTeam: false
        )
    }

    private func copySharedRelations(repoScope: String, sourceKey: String, targetKey: String) async {
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
                "shared-relations",
                "--repo-scope",
                normalizedRepoScope(repoScope),
                "--limit",
                "50",
            ]
            let trimmedSourceKey = sourceKey.trimmingCharacters(in: .whitespacesAndNewlines)
            if !trimmedSourceKey.isEmpty {
                arguments += ["--source-key", trimmedSourceKey]
            }
            let trimmedTargetKey = targetKey.trimmingCharacters(in: .whitespacesAndNewlines)
            if !trimmedTargetKey.isEmpty {
                arguments += ["--target-shared-key", trimmedTargetKey]
            }
            let output = try await AutopsyCLI(executable: cliPath, timeoutSeconds: 20).run(arguments)
            NSPasteboard.general.clearContents()
            NSPasteboard.general.setString(output.trimmingCharacters(in: .whitespacesAndNewlines), forType: .string)
            lastActionMessage = "Shared relations copied"
            clearLastActionMessageAfterDelay(expected: "Shared relations copied")
        } catch {
            sharedServerError = error.localizedDescription
        }
    }

    private func unrelateSharedMemory(relationID: String, repoScope: String) async {
        let trimmedRelationID = relationID.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmedRelationID.isEmpty else {
            sharedServerError = "Relation ID required"
            return
        }
        await runSharedAccessCommand(
            [
                "shared-server",
                "unrelate",
                trimmedRelationID,
                "--repo-scope",
                normalizedRepoScope(repoScope),
            ],
            successMessage: "Shared relation removed",
            refreshTeam: false
        )
    }

    private func linkPersonalSharedMemory(personalKey: String, sharedKey: String, repoScope: String, relation: String, fact: String, factRating: String) async {
        let trimmedPersonalKey = personalKey.trimmingCharacters(in: .whitespacesAndNewlines)
        let trimmedSharedKey = sharedKey.trimmingCharacters(in: .whitespacesAndNewlines)
        let trimmedRelation = relation.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmedPersonalKey.isEmpty else {
            sharedServerError = "Personal key required"
            return
        }
        guard !trimmedSharedKey.isEmpty else {
            sharedServerError = "Shared key required"
            return
        }
        guard !trimmedRelation.isEmpty else {
            sharedServerError = "Relation required"
            return
        }
        var arguments = [
            "shared-server",
            "link",
            trimmedPersonalKey,
            trimmedSharedKey,
            "--repo-scope",
            normalizedRepoScope(repoScope),
            "--relation",
            trimmedRelation,
            "--fact",
            fact.trimmingCharacters(in: .whitespacesAndNewlines),
        ]
        let trimmedFactRating = factRating.trimmingCharacters(in: .whitespacesAndNewlines)
        if !trimmedFactRating.isEmpty {
            arguments += ["--fact-rating", trimmedFactRating]
        }
        await runSharedAccessCommand(
            arguments,
            successMessage: "Personal link created",
            refreshTeam: false
        )
    }

    private func copySharedPersonalLinks(repoScope: String, personalKey: String, sharedKey: String) async {
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
                "personal-links",
                "--repo-scope",
                normalizedRepoScope(repoScope),
                "--limit",
                "50",
            ]
            let trimmedPersonalKey = personalKey.trimmingCharacters(in: .whitespacesAndNewlines)
            if !trimmedPersonalKey.isEmpty {
                arguments += ["--personal-key", trimmedPersonalKey]
            }
            let trimmedSharedKey = sharedKey.trimmingCharacters(in: .whitespacesAndNewlines)
            if !trimmedSharedKey.isEmpty {
                arguments += ["--shared-key", trimmedSharedKey]
            }
            let output = try await AutopsyCLI(executable: cliPath, timeoutSeconds: 20).run(arguments)
            NSPasteboard.general.clearContents()
            NSPasteboard.general.setString(output.trimmingCharacters(in: .whitespacesAndNewlines), forType: .string)
            lastActionMessage = "Personal links copied"
            clearLastActionMessageAfterDelay(expected: "Personal links copied")
        } catch {
            sharedServerError = error.localizedDescription
        }
    }

    private func copySharedPersonalContext(repoScope: String, personalKey: String, includeArchived: Bool, includeRelations: Bool, minFactRating: String) async {
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
                "personal-context",
                "--repo-scope",
                normalizedRepoScope(repoScope),
                "--limit",
                "8",
            ]
            let trimmedPersonalKey = personalKey.trimmingCharacters(in: .whitespacesAndNewlines)
            if !trimmedPersonalKey.isEmpty {
                arguments += ["--personal-key", trimmedPersonalKey]
            }
            if includeArchived {
                arguments.append("--include-archived")
            }
            if !includeRelations {
                arguments.append("--no-relations")
            }
            let trimmedMinFactRating = minFactRating.trimmingCharacters(in: .whitespacesAndNewlines)
            if !trimmedMinFactRating.isEmpty {
                arguments += ["--min-fact-rating", trimmedMinFactRating]
            }
            let output = try await AutopsyCLI(executable: cliPath, timeoutSeconds: 20).run(arguments)
            NSPasteboard.general.clearContents()
            NSPasteboard.general.setString(output.trimmingCharacters(in: .whitespacesAndNewlines), forType: .string)
            lastActionMessage = "Linked context copied"
            clearLastActionMessageAfterDelay(expected: "Linked context copied")
        } catch {
            sharedServerError = error.localizedDescription
        }
    }

    private func unlinkPersonalSharedMemory(relationID: String, repoScope: String) async {
        let trimmedRelationID = relationID.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmedRelationID.isEmpty else {
            sharedServerError = "Relation ID required"
            return
        }
        await runSharedAccessCommand(
            [
                "shared-server",
                "unlink",
                trimmedRelationID,
                "--repo-scope",
                normalizedRepoScope(repoScope),
            ],
            successMessage: "Personal link removed",
            refreshTeam: false
        )
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
            successMessage: "Shared token revoked",
            successMessageFromOutput: { output in
                guard let payload = self.jsonObject(from: output),
                      (payload["already_revoked"] as? Bool) == true else {
                    return "Shared token revoked"
                }
                return "Shared token already revoked"
            }
        )
    }

    private func copySharedScopedTokens(repoScope: String) async {
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
                "scoped-tokens",
                "--repo-scope",
                normalizedRepoScope(repoScope),
            ])
            NSPasteboard.general.clearContents()
            NSPasteboard.general.setString(output.trimmingCharacters(in: .whitespacesAndNewlines), forType: .string)
            lastActionMessage = "Invite tokens copied"
            clearLastActionMessageAfterDelay(expected: "Invite tokens copied")
        } catch {
            sharedServerError = error.localizedDescription
        }
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

    private func copySharedContextAudit(repoScope: String) async {
        guard !isManagingSharedAccess else { return }
        isManagingSharedAccess = true
        sharedServerError = nil
        lastActionMessage = nil
        defer {
            isManagingSharedAccess = false
        }

        do {
            let scope = normalizedRepoScope(repoScope)
            let output = try await AutopsyCLI(executable: cliPath, timeoutSeconds: 20).run([
                "shared-server",
                "audit",
                "--repo-scope",
                scope,
                "--action",
                "read_shared_context",
                "--action",
                "read_personal_context",
                "--limit",
                "50",
            ])
            let summary = sharedContextAuditReport(from: output, repoScope: scope)
            NSPasteboard.general.clearContents()
            NSPasteboard.general.setString(summary, forType: .string)
            lastActionMessage = "Context audit copied"
            clearLastActionMessageAfterDelay(expected: "Context audit copied")
        } catch {
            sharedServerError = error.localizedDescription
        }
    }

    private func copySharedActivityAudit(repoScope: String) async {
        guard !isManagingSharedAccess else { return }
        isManagingSharedAccess = true
        sharedServerError = nil
        lastActionMessage = nil
        defer {
            isManagingSharedAccess = false
        }

        do {
            let scope = normalizedRepoScope(repoScope)
            var arguments = [
                "shared-server",
                "audit",
                "--repo-scope",
                scope,
            ]
            for action in Self.sharedActivityAuditActions {
                arguments += ["--action", action]
            }
            arguments += ["--limit", "50"]
            let output = try await AutopsyCLI(executable: cliPath, timeoutSeconds: 20).run(arguments)
            let summary = sharedActivityAuditReport(from: output, repoScope: scope)
            NSPasteboard.general.clearContents()
            NSPasteboard.general.setString(summary, forType: .string)
            lastActionMessage = "Activity audit copied"
            clearLastActionMessageAfterDelay(expected: "Activity audit copied")
        } catch {
            sharedServerError = error.localizedDescription
        }
    }

    private func copySharedAccessChangeAudit(repoScope: String) async {
        guard !isManagingSharedAccess else { return }
        isManagingSharedAccess = true
        sharedServerError = nil
        lastActionMessage = nil
        defer {
            isManagingSharedAccess = false
        }

        do {
            let scope = normalizedRepoScope(repoScope)
            var arguments = [
                "shared-server",
                "audit",
                "--repo-scope",
                scope,
            ]
            for action in Self.sharedAccessChangeAuditActions {
                arguments += ["--action", action]
            }
            arguments += ["--limit", "50"]
            let output = try await AutopsyCLI(executable: cliPath, timeoutSeconds: 20).run(arguments)
            let summary = sharedAccessChangeAuditReport(from: output, repoScope: scope)
            NSPasteboard.general.clearContents()
            NSPasteboard.general.setString(summary, forType: .string)
            lastActionMessage = "Access changes copied"
            clearLastActionMessageAfterDelay(expected: "Access changes copied")
        } catch {
            sharedServerError = error.localizedDescription
        }
    }

    private func copySharedSecurityAudit() async {
        guard !isManagingSharedAccess else { return }
        isManagingSharedAccess = true
        sharedServerError = nil
        lastActionMessage = nil
        defer {
            isManagingSharedAccess = false
        }

        do {
            var auditArguments = [
                "shared-server",
                "audit",
                "--global-audit",
            ]
            var integrityArguments = [
                "shared-server",
                "audit-integrity",
                "--global-audit",
            ]
            for action in Self.sharedSecurityAuditActions {
                auditArguments += ["--action", action]
                integrityArguments += ["--action", action]
            }
            auditArguments += ["--limit", "50"]
            integrityArguments += ["--limit", "50"]

            let cli = AutopsyCLI(executable: cliPath, timeoutSeconds: 20)
            let auditOutput = try await cli.run(auditArguments)
            let integrityOutput = try await cli.run(integrityArguments)
            let summary = sharedSecurityAuditReport(from: auditOutput, integrityOutput: integrityOutput)
            NSPasteboard.general.clearContents()
            NSPasteboard.general.setString(summary, forType: .string)
            lastActionMessage = "Security audit copied"
            clearLastActionMessageAfterDelay(expected: "Security audit copied")
        } catch {
            sharedServerError = error.localizedDescription
        }
    }

    private func copySharedAuditIntegrity(repoScope: String) async {
        guard !isManagingSharedAccess else { return }
        isManagingSharedAccess = true
        sharedServerError = nil
        lastActionMessage = nil
        defer {
            isManagingSharedAccess = false
        }

        do {
            let scope = normalizedRepoScope(repoScope)
            let output = try await AutopsyCLI(executable: cliPath, timeoutSeconds: 20).run([
                "shared-server",
                "audit-integrity",
                "--repo-scope",
                scope,
                "--limit",
                "50",
            ])
            let summary = sharedAuditIntegrityReport(from: output, repoScope: scope)
            NSPasteboard.general.clearContents()
            NSPasteboard.general.setString(summary, forType: .string)
            lastActionMessage = "Audit integrity copied"
            clearLastActionMessageAfterDelay(expected: "Audit integrity copied")
        } catch {
            sharedServerError = error.localizedDescription
        }
    }

    private func verifySharedAuditReceipt(
        auditID: String,
        integrityHash: String,
        repoScope: String,
        action: String,
        target: String
    ) async {
        guard !isManagingSharedAccess else { return }
        isManagingSharedAccess = true
        sharedServerError = nil
        lastActionMessage = nil
        defer {
            isManagingSharedAccess = false
        }

        do {
            let scope = normalizedRepoScope(repoScope)
            var arguments = [
                "shared-server",
                "verify-receipt",
                auditID.trimmingCharacters(in: .whitespacesAndNewlines),
                "--repo-scope",
                scope,
                "--integrity-hash",
                integrityHash.trimmingCharacters(in: .whitespacesAndNewlines),
            ]
            let normalizedAction = action.trimmingCharacters(in: .whitespacesAndNewlines)
            if !normalizedAction.isEmpty {
                arguments += ["--receipt-action", normalizedAction]
            }
            let normalizedTarget = target.trimmingCharacters(in: .whitespacesAndNewlines)
            if !normalizedTarget.isEmpty {
                arguments += ["--receipt-target", normalizedTarget]
            }
            let output = try await AutopsyCLI(executable: cliPath, timeoutSeconds: 20).run(arguments)
            let summary = sharedAuditReceiptVerificationReport(from: output, repoScope: scope)
            NSPasteboard.general.clearContents()
            NSPasteboard.general.setString(summary, forType: .string)
            let matches = auditBool(jsonObject(from: output)?["matches"]) == true
            lastActionMessage = matches ? "Receipt verified" : "Receipt mismatch copied"
            clearLastActionMessageAfterDelay(expected: lastActionMessage ?? "")
        } catch {
            sharedServerError = error.localizedDescription
        }
    }

    private func runSharedAccessCommand(
        _ arguments: [String],
        successMessage: String,
        refreshTeam: Bool = true,
        successMessageFromOutput: ((String) -> String)? = nil
    ) async {
        guard !isManagingSharedAccess else { return }
        isManagingSharedAccess = true
        sharedServerError = nil
        lastActionMessage = nil
        defer {
            isManagingSharedAccess = false
        }

        do {
            let output = try await AutopsyCLI(executable: cliPath, timeoutSeconds: 20).run(arguments)
            let message = successMessageFromOutput?(output) ?? successMessage
            lastActionMessage = messageWithAuditReceipt(message, output: output)
            if refreshTeam {
                await loadSharedServerTeamStatus()
            }
        } catch {
            sharedServerError = sharedAccessErrorMessage(error)
        }
    }

    private func sharedAccessErrorMessage(_ error: Error) -> String {
        let message = error.localizedDescription.trimmingCharacters(in: .whitespacesAndNewlines)
        guard message.contains("last active owner grant must remain") else {
            return message
        }
        var details: [String] = []
        if let repo = sharedErrorValue("repo", in: message), !repo.isEmpty {
            details.append("repo \(repo)")
        }
        if let activeOwners = sharedErrorValue("active_owners", in: message), !activeOwners.isEmpty {
            details.append("active owners \(activeOwners)")
        }
        details.append("keep one owner or ask a global admin")
        return "Cannot change last shared owner; \(details.joined(separator: ", "))"
    }

    private func sharedErrorValue(_ key: String, in message: String) -> String? {
        let prefix = "\(key)="
        for segment in message.split(separator: ";") {
            let trimmed = segment.trimmingCharacters(in: .whitespacesAndNewlines)
            if trimmed.hasPrefix(prefix) {
                return String(trimmed.dropFirst(prefix.count))
            }
        }
        return nil
    }

    private func normalizedRepoScope(_ value: String) -> String {
        let trimmed = value.trimmingCharacters(in: .whitespacesAndNewlines)
        return trimmed.isEmpty ? sharedServerDefaultRepoScope : trimmed
    }

    private func sharedUsersReport(from output: String) -> String {
        guard let payload = jsonObject(from: output),
              let rawItems = payload["items"] as? [Any]
        else {
            return output.trimmingCharacters(in: .whitespacesAndNewlines)
        }

        let items = rawItems.compactMap { $0 as? [String: Any] }
        let disabledCount = items.filter { auditBool($0["disabled"]) == true }.count
        var lines = [
            "Shared Users",
            "Users: \(items.count) (disabled \(disabledCount))",
            "",
        ]
        if items.isEmpty {
            lines.append("No shared users were returned.")
            return lines.joined(separator: "\n")
        }
        for item in items {
            let email = auditString(item["email"]) ?? "unknown email"
            let userID = auditString(item["id"]) ?? "unknown id"
            var parts = ["\(email)", "id \(userID)"]
            if let name = auditString(item["name"]), !name.isEmpty {
                parts.append("name \(name)")
            }
            if auditBool(item["disabled"]) == true {
                parts.append("disabled")
            }
            if let createdAt = auditString(item["created_at"]), !createdAt.isEmpty {
                parts.append("created \(createdAt)")
            }
            lines.append("- \(parts.joined(separator: ", "))")
        }
        return lines.joined(separator: "\n")
    }

    private func sharedGrantsReport(from output: String, repoScope: String) -> String {
        guard let payload = jsonObject(from: output),
              let rawItems = payload["items"] as? [Any]
        else {
            return output.trimmingCharacters(in: .whitespacesAndNewlines)
        }

        let items = rawItems.compactMap { $0 as? [String: Any] }
        let disabledCount = items.filter { auditBool($0["disabled"]) == true }.count
        let activeOwnerCount = items.filter { item in
            auditString(item["role"]) == "owner" && auditBool(item["disabled"]) != true
        }.count
        var lines = [
            "Shared Grants",
            "Repo: \(repoScope)",
            "Grants: \(items.count) (active owners \(activeOwnerCount), disabled \(disabledCount))",
            "",
        ]
        if items.isEmpty {
            lines.append("No shared grants were returned.")
            return lines.joined(separator: "\n")
        }
        for item in items {
            let email = auditString(item["email"]) ?? "unknown email"
            let userID = auditString(item["user_id"]) ?? "unknown user"
            let repo = auditString(item["repo"]) ?? "unknown repo"
            let role = auditString(item["role"]) ?? "unknown role"
            let capabilities = [
                auditBool(item["can_read"]) == true ? "read" : nil,
                auditBool(item["can_write"]) == true ? "write" : nil,
                auditBool(item["can_admin"]) == true ? "admin" : nil,
            ].compactMap { $0 }
            var parts = ["\(email)", "user \(userID)", "repo \(repo)", "role \(role)"]
            if !capabilities.isEmpty {
                parts.append("caps \(capabilities.joined(separator: "/"))")
            }
            if auditBool(item["disabled"]) == true {
                parts.append("disabled user")
            }
            if let updatedAt = auditString(item["updated_at"]), !updatedAt.isEmpty {
                parts.append("updated \(updatedAt)")
            }
            lines.append("- \(parts.joined(separator: ", "))")
        }
        return lines.joined(separator: "\n")
    }

    private func sharedRepoPolicyReport(from output: String, repoScope: String) -> String {
        guard let payload = jsonObject(from: output) else {
            return output.trimmingCharacters(in: .whitespacesAndNewlines)
        }

        let labels = (payload["allowed_relation_labels"] as? [Any] ?? [])
            .compactMap { auditString($0) }
        let policyRepo = auditString(payload["repo"]) ?? repoScope
        let requestedRepo = auditString(payload["requested_repo"]) ?? repoScope
        let inheritedFrom = auditString(payload["inherited_from"]) ?? ""
        let version = auditString(payload["version_ns"])
        let minFactRating = auditString(payload["min_fact_rating"]) ?? "0"
        let allowShared = auditBool(payload["allow_shared_relations"]) != false
        let allowPersonal = auditBool(payload["allow_personal_relations"]) != false
        let policyScope = inheritedFrom.isEmpty ? policyRepo : "\(policyRepo) inherited from \(inheritedFrom)"
        var lines = [
            "Shared Repo Policy",
            "Repo: \(requestedRepo)",
            "Policy scope: \(policyScope)",
            "Allowed relation labels: \(labels.isEmpty ? "any" : labels.joined(separator: ", "))",
            "Minimum fact rating: \(minFactRating)",
            "Shared relations: \(allowShared ? "allowed" : "disabled")",
            "Personal links: \(allowPersonal ? "allowed" : "disabled")",
        ]
        if let version {
            lines.append("Version: \(version)")
        }
        if let updatedAt = auditString(payload["updated_at"]) {
            lines.append("Updated: \(updatedAt)")
        }
        if let notes = auditString(payload["notes"]) {
            lines.append("")
            lines.append("Notes: \(notes)")
        }
        return lines.joined(separator: "\n")
    }

    private func sharedRepoPolicyInventoryReport(from output: String, repoScope: String) -> String {
        guard let payload = jsonObject(from: output) else {
            return output.trimmingCharacters(in: .whitespacesAndNewlines)
        }

        let items = (payload["items"] as? [Any] ?? [])
            .compactMap { $0 as? [String: Any] }
        let graph = auditString(payload["graph_slug"]) ?? "unknown"
        let filterPresent = auditBool(payload["repo_filter_present"]) == true
        let filter = auditString(payload["repo"]) ?? repoScope
        let itemCount = auditInt(payload["item_count"]) ?? items.count
        var lines = [
            "Shared Repo Policy Inventory",
            "Graph: \(graph)",
            "Filter: \(filterPresent ? (filter.isEmpty ? "repo" : filter) : "all explicit policies")",
            "Policies: \(itemCount)",
        ]
        if items.isEmpty {
            lines.append("")
            lines.append("No explicit repo policy overrides found.")
            return lines.joined(separator: "\n")
        }
        lines.append("")
        for item in items.prefix(20) {
            let repo = auditString(item["repo"]) ?? "unknown repo"
            let labels = (item["allowed_relation_labels"] as? [Any] ?? [])
                .compactMap { auditString($0) }
            let minFactRating = auditDecimal(item["min_fact_rating"]) ?? "0.00"
            let allowShared = auditBool(item["allow_shared_relations"]) != false
            let allowPersonal = auditBool(item["allow_personal_relations"]) != false
            var parts = [
                "labels \(labels.isEmpty ? "any" : labels.joined(separator: ","))",
                "min rating \(minFactRating)",
                "shared \(allowShared ? "allowed" : "disabled")",
                "personal \(allowPersonal ? "allowed" : "disabled")",
            ]
            if let version = auditString(item["version_ns"]) {
                parts.append("version \(version)")
            }
            if let updatedAt = auditString(item["updated_at"]), !updatedAt.isEmpty {
                parts.append("updated \(updatedAt)")
            }
            if let notes = auditString(item["notes"]), !notes.isEmpty {
                parts.append("notes \(notes)")
            }
            lines.append("- \(repo): \(parts.joined(separator: "; "))")
        }
        if items.count > 20 {
            lines.append("- \(items.count - 20) more policies omitted")
        }
        return lines.joined(separator: "\n")
    }

    private func sharedAccessCheckReport(from output: String, repoScope: String) -> String {
        guard let payload = jsonObject(from: output) else {
            return output.trimmingCharacters(in: .whitespacesAndNewlines)
        }

        let requestedRepo = auditString(payload["repo"]) ?? repoScope
        let mode = auditString(payload["mode"]) ?? "read"
        let reason = auditString(payload["reason"]) ?? "unknown"
        let effectiveRole = auditString(payload["effective_role"]) ?? "none"
        let allowed = auditBool(payload["allowed"]) == true
        let capabilities = payload["capabilities"] as? [String: Any] ?? [:]
        let capabilityNames = [
            auditBool(capabilities["can_read"]) == true ? "read" : nil,
            auditBool(capabilities["can_write"]) == true ? "write" : nil,
            auditBool(capabilities["can_admin"]) == true ? "admin" : nil,
        ].compactMap { $0 }
        let principal = payload["principal"] as? [String: Any] ?? [:]
        let principalEmail = auditString(principal["email"]) ?? auditString(principal["id"]) ?? "unknown principal"

        var lines = [
            "Autopsy Shared Access Check",
            "Repo: \(requestedRepo)",
            "Mode: \(mode)",
            "Allowed: \(allowed ? "yes" : "no")",
            "Reason: \(reason)",
            "Effective role: \(effectiveRole)",
            "Capabilities: \(capabilityNames.isEmpty ? "none" : capabilityNames.joined(separator: "/"))",
            "Principal: \(principalEmail)",
        ]

        if let tokenScope = payload["token_scope"] as? [String: Any] {
            if auditBool(tokenScope["scoped"]) == true {
                let tokenRepo = auditString(tokenScope["repo"]) ?? "unknown repo"
                let tokenRole = auditString(tokenScope["role"]) ?? "unknown role"
                let tokenMatches = auditBool(tokenScope["matches"]) == true ? "matches" : "does not match"
                lines.append("Token scope: \(tokenRole) on \(tokenRepo), \(tokenMatches)")
            } else {
                lines.append("Token scope: unscoped")
            }
        }

        if let repoPolicy = payload["repo_policy"] as? [String: Any] {
            lines.append("")
            if auditBool(repoPolicy["available"]) == true {
                let policyRepo = auditString(repoPolicy["repo"]) ?? requestedRepo
                let inheritedFrom = auditString(repoPolicy["inherited_from"]) ?? ""
                let version = auditString(repoPolicy["version_ns"])
                let labels = (repoPolicy["allowed_relation_labels"] as? [Any] ?? [])
                    .compactMap { auditString($0) }
                let minFactRating = auditDecimal(repoPolicy["min_fact_rating"]) ?? "0.00"
                let allowShared = auditBool(repoPolicy["allow_shared_relations"]) != false
                let allowPersonal = auditBool(repoPolicy["allow_personal_relations"]) != false
                let policyScope = inheritedFrom.isEmpty ? policyRepo : "\(policyRepo) inherited from \(inheritedFrom)"
                lines.append("Repo policy: \(policyScope)")
                lines.append("Allowed relation labels: \(labels.isEmpty ? "any" : labels.joined(separator: ", "))")
                lines.append("Minimum fact rating: \(minFactRating)")
                lines.append("Shared relations: \(allowShared ? "allowed" : "disabled")")
                lines.append("Personal links: \(allowPersonal ? "allowed" : "disabled")")
                if let version {
                    lines.append("Policy version: \(version)")
                }
                if let notes = auditString(repoPolicy["notes"]) {
                    lines.append("Policy notes: \(notes)")
                }
            } else {
                let policyReason = auditString(repoPolicy["reason"]) ?? "not available"
                lines.append("Repo policy: unavailable (\(policyReason))")
            }
        }

        let grants = (payload["matching_grants"] as? [Any] ?? [])
            .compactMap { $0 as? [String: Any] }
        lines.append("")
        lines.append("Matching grants: \(grants.count)")
        for grant in grants.prefix(8) {
            let repo = auditString(grant["repo"]) ?? "unknown repo"
            let role = auditString(grant["role"]) ?? "unknown role"
            let match = auditString(grant["match"]) ?? "match"
            let grantCapabilities = [
                auditBool(grant["can_read"]) == true ? "read" : nil,
                auditBool(grant["can_write"]) == true ? "write" : nil,
                auditBool(grant["can_admin"]) == true ? "admin" : nil,
            ].compactMap { $0 }
            let capText = grantCapabilities.isEmpty ? "none" : grantCapabilities.joined(separator: "/")
            lines.append("- \(repo), role \(role), \(match), caps \(capText)")
        }
        if grants.count > 8 {
            lines.append("- \(grants.count - 8) more grants omitted")
        }
        return lines.joined(separator: "\n")
    }

    private func sharedContextAuditReport(from output: String, repoScope: String) -> String {
        guard let payload = jsonObject(from: output),
              let rawItems = payload["items"] as? [Any]
        else {
            return output.trimmingCharacters(in: .whitespacesAndNewlines)
        }

        let items = rawItems.compactMap { $0 as? [String: Any] }
        let contextReads = items.filter { item in
            guard let action = auditString(item["action"]) else { return false }
            return action == "read_shared_context" || action == "read_personal_context"
        }

        var lines = [
            "Autopsy Shared Context Audit",
            "Repo: \(repoScope)",
            "Audit window: \(items.count) latest events",
            "Context reads: \(contextReads.count)",
        ]

        guard !contextReads.isEmpty else {
            lines.append("")
            lines.append("No shared context read events were found in the latest audit window.")
            return lines.joined(separator: "\n")
        }

        lines.append("")
        for item in contextReads.prefix(12) {
            lines.append(formatSharedContextAuditItem(item))
        }
        if contextReads.count > 12 {
            lines.append("- \(contextReads.count - 12) more context reads omitted")
        }
        return lines.joined(separator: "\n")
    }

    private func formatSharedContextAuditItem(_ item: [String: Any]) -> String {
        let action = auditString(item["action"]) ?? "read_context"
        let createdAt = auditString(item["created_at"]) ?? "unknown time"
        let repo = auditString(item["repo"]) ?? "unknown repo"
        let metadata = item["metadata"] as? [String: Any] ?? [:]
        let label = action == "read_personal_context" ? "linked context" : "shared context"

        var parts = [
            "items \(auditInt(metadata["item_count"]) ?? 0)",
            "relations \(auditInt(metadata["relation_count"]) ?? 0)",
        ]

        if action == "read_shared_context" {
            parts.insert("related \(auditInt(metadata["related_item_count"]) ?? 0)", at: 1)
            let adjacent = auditInt(metadata["adjacent_relation_count"]) ?? 0
            let adjacentCandidates = auditInt(metadata["adjacent_relation_candidate_count"]) ?? adjacent
            let search = auditInt(metadata["relation_search_count"]) ?? 0
            let searchCandidates = auditInt(metadata["relation_search_candidate_count"]) ?? search
            let deduped = auditInt(metadata["relation_deduped_candidate_count"]) ?? adjacentCandidates + searchCandidates
            let overlap = auditInt(metadata["relation_source_overlap_count"]) ?? 0
            parts.append("adjacent \(adjacent)/\(adjacentCandidates)")
            parts.append("search \(search)/\(searchCandidates)")
            parts.append("deduped \(deduped)")
            parts.append("overlap \(overlap)")
            if auditBool(metadata["query_present"]) == true {
                parts.append("query len \(auditInt(metadata["query_length"]) ?? 0)")
            }
        } else {
            parts.append("personal keys \(auditInt(metadata["personal_key_count"]) ?? 0)")
        }

        if let minFactRating = auditDecimal(metadata["min_fact_rating"]) {
            parts.append("min rating \(minFactRating)")
        }
        if let integrityStatus = auditString(item["integrity_status"]) {
            parts.append("integrity \(integrityStatus)")
        }
        parts.append("guard \(auditInt(metadata["read_guard_blocked_count"]) ?? 0)")

        return "- \(createdAt) \(label) \(repo): \(parts.joined(separator: ", "))"
    }

    private func sharedActivityAuditReport(from output: String, repoScope: String) -> String {
        guard let payload = jsonObject(from: output),
              let rawItems = payload["items"] as? [Any]
        else {
            return output.trimmingCharacters(in: .whitespacesAndNewlines)
        }

        let items = rawItems.compactMap { $0 as? [String: Any] }
        let activityReads = items.filter { item in
            guard let action = auditString(item["action"]) else { return false }
            return Self.sharedActivityAuditActions.contains(action)
        }
        let counts = Dictionary(grouping: activityReads) { item in
            auditString(item["action"]) ?? "unknown"
        }.mapValues(\.count)

        var lines = [
            "Autopsy Shared Activity Audit",
            "Repo: \(repoScope)",
            "Audit window: \(items.count) latest events",
            "Activity reads: \(activityReads.count)",
        ]

        let countSummary = Self.sharedActivityAuditActions
            .compactMap { action -> String? in
                guard let count = counts[action], count > 0 else { return nil }
                return "\(action) \(count)"
            }
        if !countSummary.isEmpty {
            lines.append("Counts: \(countSummary.joined(separator: ", "))")
        }

        guard !activityReads.isEmpty else {
            lines.append("")
            lines.append("No shared activity read events were found in the latest audit window.")
            return lines.joined(separator: "\n")
        }

        lines.append("")
        for item in activityReads.prefix(16) {
            lines.append(formatSharedActivityAuditItem(item))
        }
        if activityReads.count > 16 {
            lines.append("- \(activityReads.count - 16) more activity reads omitted")
        }
        return lines.joined(separator: "\n")
    }

    private func formatSharedActivityAuditItem(_ item: [String: Any]) -> String {
        let action = auditString(item["action"]) ?? "read_activity"
        let createdAt = auditString(item["created_at"]) ?? "unknown time"
        let repo = auditString(item["repo"]) ?? "unknown repo"
        let target = auditString(item["target"])
        let metadata = item["metadata"] as? [String: Any] ?? [:]

        var parts: [String] = []
        if let target {
            parts.append("target \(target)")
        }
        if let itemCount = auditInt(metadata["item_count"]) {
            parts.append("items \(itemCount)")
        }
        if let eventCount = auditInt(metadata["event_count"]) {
            parts.append("events \(eventCount)")
        }
        if let limit = auditInt(metadata["limit"]) {
            parts.append("limit \(limit)")
        }
        if let mode = auditString(metadata["mode"]) {
            parts.append("mode \(mode)")
        }
        if let allowed = auditBool(metadata["allowed"]) {
            parts.append("allowed \(allowed ? "yes" : "no")")
        }
        if let reason = auditString(metadata["reason"]) {
            parts.append("reason \(reason)")
        }
        if let effectiveRole = auditString(metadata["effective_role"]) {
            parts.append("role \(effectiveRole)")
        }
        if let policyRepo = auditString(metadata["policy_repo"]) {
            parts.append("policy \(policyRepo)")
        }
        if let inheritedFrom = auditString(metadata["policy_inherited_from"]), !inheritedFrom.isEmpty {
            parts.append("inherited \(inheritedFrom)")
        }
        if let labelCount = auditInt(metadata["allowed_relation_label_count"]) {
            parts.append("labels \(labelCount)")
        }
        if let minFactRating = auditDecimal(metadata["min_fact_rating"]) {
            parts.append("min rating \(minFactRating)")
        }
        if let allowShared = auditBool(metadata["allow_shared_relations"]) {
            parts.append("shared \(allowShared ? "allowed" : "disabled")")
        }
        if let allowPersonal = auditBool(metadata["allow_personal_relations"]) {
            parts.append("personal \(allowPersonal ? "allowed" : "disabled")")
        }
        if let status = auditString(metadata["status"]) {
            parts.append("status \(status)")
        }
        if let actionFilterCount = auditInt(metadata["action_filter_count"]) {
            parts.append("filters \(actionFilterCount)")
        }
        if let repoFilter = auditBool(metadata["repo_filter_present"]) {
            parts.append("repo filter \(repoFilter ? "yes" : "no")")
        }
        if let sourceFilter = auditBool(metadata["source_key_filter_present"]) {
            parts.append("source filter \(sourceFilter ? "yes" : "no")")
        }
        if let targetFilter = auditBool(metadata["target_key_filter_present"]) {
            parts.append("target filter \(targetFilter ? "yes" : "no")")
        }
        if let includeArchived = auditBool(metadata["include_archived"]) {
            parts.append("archived \(includeArchived ? "yes" : "no")")
        }
        if let integrityStatus = auditString(item["integrity_status"]) {
            parts.append("integrity \(integrityStatus)")
        }
        if parts.isEmpty {
            parts.append("recorded")
        }

        let label = action.replacingOccurrences(of: "_", with: " ")
        return "- \(createdAt) \(label) \(repo): \(parts.joined(separator: ", "))"
    }

    private func sharedAccessChangeAuditReport(from output: String, repoScope: String) -> String {
        guard let payload = jsonObject(from: output),
              let rawItems = payload["items"] as? [Any]
        else {
            return output.trimmingCharacters(in: .whitespacesAndNewlines)
        }

        let items = rawItems.compactMap { $0 as? [String: Any] }
        let accessChanges = items.filter { item in
            guard let action = auditString(item["action"]) else { return false }
            return Self.sharedAccessChangeAuditActions.contains(action)
        }
        let counts = Dictionary(grouping: accessChanges) { item in
            auditString(item["action"]) ?? "unknown"
        }.mapValues(\.count)
        let scopedActorChanges = accessChanges.filter { item in
            let metadata = item["metadata"] as? [String: Any] ?? [:]
            return auditBool(metadata["actor_token_scoped"]) == true
        }.count
        let revokedScopedTokens = accessChanges.reduce(0) { total, item in
            let metadata = item["metadata"] as? [String: Any] ?? [:]
            return total + (auditInt(metadata["revoked_scoped_token_count"]) ?? 0)
        }
        let alreadyRevokedScopedTokens = accessChanges.reduce(0) { total, item in
            let metadata = item["metadata"] as? [String: Any] ?? [:]
            return total + (auditInt(metadata["already_revoked_scoped_token_count"]) ?? 0)
        }

        var lines = [
            "Autopsy Shared Access Change Audit",
            "Repo: \(repoScope)",
            "Audit window: \(items.count) latest events",
            "Access changes: \(accessChanges.count)",
            "Scoped actor tokens: \(scopedActorChanges)",
            "Revoked scoped tokens: \(revokedScopedTokens)",
            "Already revoked scoped tokens: \(alreadyRevokedScopedTokens)",
        ]

        let countSummary = Self.sharedAccessChangeAuditActions
            .compactMap { action -> String? in
                guard let count = counts[action], count > 0 else { return nil }
                return "\(action) \(count)"
            }
        if !countSummary.isEmpty {
            lines.append("Counts: \(countSummary.joined(separator: ", "))")
        }

        guard !accessChanges.isEmpty else {
            lines.append("")
            lines.append("No shared access-change events were found in the latest audit window.")
            return lines.joined(separator: "\n")
        }

        lines.append("")
        for item in accessChanges.prefix(16) {
            lines.append(formatSharedAccessChangeAuditItem(item))
        }
        if accessChanges.count > 16 {
            lines.append("- \(accessChanges.count - 16) more access changes omitted")
        }
        return lines.joined(separator: "\n")
    }

    private func formatSharedAccessChangeAuditItem(_ item: [String: Any]) -> String {
        let action = auditString(item["action"]) ?? "access_change"
        let createdAt = auditString(item["created_at"]) ?? "unknown time"
        let repo = auditString(item["repo"]) ?? "unknown repo"
        let metadata = item["metadata"] as? [String: Any] ?? [:]

        var parts: [String] = []
        if let actor = auditString(item["actor_id"]) {
            parts.append("actor \(actor)")
        }
        if let target = auditString(item["target"]) {
            parts.append("target \(target)")
        }
        if let role = auditString(metadata["role"]), !role.isEmpty {
            parts.append("role \(role)")
        }
        if let toUserID = auditString(metadata["to_user_id"]), !toUserID.isEmpty {
            parts.append("new owner \(toUserID)")
        }
        if let sourceRoleAfter = auditString(metadata["source_role_after"]), !sourceRoleAfter.isEmpty {
            parts.append(sourceRoleAfter == "none" ? "source removed" : "source \(sourceRoleAfter)")
        }
        if let targetPreviousRole = auditString(metadata["target_previous_role"]), !targetPreviousRole.isEmpty {
            parts.append("previous target role \(targetPreviousRole)")
        }
        if let email = auditString(metadata["email"]), !email.isEmpty {
            parts.append("email \(email)")
        }
        if let issuedToken = auditString(metadata["token_id"]), !issuedToken.isEmpty {
            parts.append("issued token \(issuedToken)")
        }
        if let createdUser = auditBool(metadata["created_user"]) {
            parts.append("created user \(createdUser ? "yes" : "no")")
        }
        if let expiresAt = auditString(metadata["expires_at"]), !expiresAt.isEmpty {
            parts.append("expires \(expiresAt)")
        }
        if let alreadyRevoked = auditBool(metadata["already_revoked"]) {
            parts.append("already revoked \(alreadyRevoked ? "yes" : "no")")
        }
        if let revokedScopedTokens = auditInt(metadata["revoked_scoped_token_count"]) {
            parts.append("revoked scoped tokens \(revokedScopedTokens)")
        }
        if let alreadyRevokedScopedTokens = auditInt(metadata["already_revoked_scoped_token_count"]) {
            parts.append("already revoked scoped tokens \(alreadyRevokedScopedTokens)")
        }
        if let labelCount = auditInt(metadata["allowed_relation_label_count"]) {
            parts.append("labels \(labelCount)")
        }
        if let minFactRating = auditDecimal(metadata["min_fact_rating"]) {
            parts.append("min rating \(minFactRating)")
        }
        if let allowShared = auditBool(metadata["allow_shared_relations"]) {
            parts.append("shared relations \(allowShared ? "allowed" : "disabled")")
        }
        if let allowPersonal = auditBool(metadata["allow_personal_relations"]) {
            parts.append("personal links \(allowPersonal ? "allowed" : "disabled")")
        }
        if let deleted = auditBool(metadata["deleted"]) {
            parts.append("deleted \(deleted ? "yes" : "no")")
        }
        if let expectedVersion = auditString(metadata["expected_version_ns"]) {
            parts.append("expected version \(expectedVersion)")
        }
        if let version = auditString(metadata["version_ns"]) {
            parts.append("version \(version)")
        }
        if let previousVersion = auditString(metadata["previous_version_ns"]) {
            parts.append("previous version \(previousVersion)")
        }
        if let effectivePolicyRepo = auditString(metadata["effective_policy_repo"]) {
            parts.append("effective policy \(effectivePolicyRepo)")
        }
        if let inheritedFrom = auditString(metadata["effective_policy_inherited_from"]) {
            parts.append("inherited from \(inheritedFrom)")
        }
        if let effectiveVersion = auditString(metadata["effective_version_ns"]) {
            parts.append("effective version \(effectiveVersion)")
        }
        if let notesPresent = auditBool(metadata["notes_present"]) {
            parts.append("notes \(notesPresent ? "yes" : "no")")
        }
        parts += sharedActorTokenScopeParts(metadata)
        if let integrityStatus = auditString(item["integrity_status"]) {
            parts.append("integrity \(integrityStatus)")
        }
        if parts.isEmpty {
            parts.append("recorded")
        }

        return "- \(createdAt) \(sharedAccessChangeLabel(action)) \(repo): \(parts.joined(separator: ", "))"
    }

    private func sharedAccessChangeLabel(_ action: String) -> String {
        switch action {
        case "grant_access":
            return "grant access"
        case "handoff_owner":
            return "handoff owner"
        case "invite_user":
            return "invite user"
        case "revoke_grant":
            return "revoke grant"
        case "revoke_scoped_token":
            return "revoke scoped token"
        case "reset_repo_policy":
            return "reset repo policy"
        case "update_repo_policy":
            return "update repo policy"
        default:
            return action.replacingOccurrences(of: "_", with: " ")
        }
    }

    private func sharedActorTokenScopeParts(_ metadata: [String: Any]) -> [String] {
        guard let scoped = auditBool(metadata["actor_token_scoped"]) else {
            return []
        }
        if !scoped {
            return ["actor token direct"]
        }

        var parts = ["actor token scoped"]
        if let tokenID = auditString(metadata["actor_token_id"]), !tokenID.isEmpty {
            parts.append("actor token \(tokenID)")
        }
        let graph = auditString(metadata["actor_token_scope_graph_slug"]) ?? ""
        let repo = auditString(metadata["actor_token_scope_repo"]) ?? ""
        let role = auditString(metadata["actor_token_scope_role"]) ?? ""
        let scope = [graph, repo, role].filter { !$0.isEmpty }.joined(separator: " ")
        if !scope.isEmpty {
            parts.append("actor scope \(scope)")
        }
        if let matches = auditBool(metadata["actor_token_scope_matches"]) {
            parts.append("actor scope match \(matches ? "yes" : "no")")
        }
        return parts
    }

    private func sharedSecurityAuditReport(from auditOutput: String, integrityOutput: String) -> String {
        guard let payload = jsonObject(from: auditOutput),
              let rawItems = payload["items"] as? [Any]
        else {
            return auditOutput.trimmingCharacters(in: .whitespacesAndNewlines)
        }

        let items = rawItems.compactMap { $0 as? [String: Any] }
        let securityEvents = items.filter { item in
            guard let action = auditString(item["action"]) else { return false }
            return Self.sharedSecurityAuditActions.contains(action)
        }
        let authFailures = securityEvents.filter { item in
            auditString(item["action"]) == "auth_failure"
        }
        let authorizationDenials = securityEvents.filter { item in
            auditString(item["action"]) == "authorization_denied"
        }
        let userLifecycleEvents = securityEvents.filter { item in
            guard let action = auditString(item["action"]) else { return false }
            return action == "disable_user" || action == "enable_user"
        }
        let accessChangeEvents = securityEvents.filter { item in
            guard let action = auditString(item["action"]) else { return false }
            return Self.sharedAccessChangeAuditActions.contains(action)
        }
        let actionCounts = Dictionary(grouping: securityEvents) { item in
            auditString(item["action"]) ?? "unknown"
        }.mapValues(\.count)
        let reasonCounts = Dictionary(grouping: authFailures) { item in
            let metadata = item["metadata"] as? [String: Any] ?? [:]
            return auditString(metadata["reason"]) ?? "unknown"
        }.mapValues(\.count)
        let denialReasonCounts = Dictionary(grouping: authorizationDenials) { item in
            let metadata = item["metadata"] as? [String: Any] ?? [:]
            return auditString(metadata["reason"]) ?? "unknown"
        }.mapValues(\.count)
        let denialModeCounts = Dictionary(grouping: authorizationDenials) { item in
            let metadata = item["metadata"] as? [String: Any] ?? [:]
            return auditString(metadata["mode"]) ?? "unknown"
        }.mapValues(\.count)

        var fingerprintEventCount = 0
        var fingerprints: Set<String> = []
        var clientFingerprints: Set<String> = []
        var rateLimitedCount = 0
        for item in authFailures {
            let metadata = item["metadata"] as? [String: Any] ?? [:]
            if let fingerprint = auditString(metadata["token_fingerprint"]) {
                fingerprintEventCount += 1
                fingerprints.insert(fingerprint)
            }
            if let clientFingerprint = auditString(metadata["client_fingerprint"]) {
                clientFingerprints.insert(clientFingerprint)
            }
            if auditBool(metadata["rate_limited"]) == true {
                rateLimitedCount += 1
            }
        }
        let tokenScopedDenials = authorizationDenials.filter { item in
            let metadata = item["metadata"] as? [String: Any] ?? [:]
            return auditBool(metadata["token_scoped"]) == true
        }.count
        let tokenScopedAccessChanges = accessChangeEvents.filter { item in
            let metadata = item["metadata"] as? [String: Any] ?? [:]
            return auditBool(metadata["actor_token_scoped"]) == true
        }.count

        let integrityPayload = jsonObject(from: integrityOutput)
        let integrityCounts = integrityPayload?["integrity_counts"] as? [String: Any] ?? [:]
        let chain = integrityPayload?["chain"] as? [String: Any] ?? [:]
        let verified = auditInt(integrityCounts["verified"]) ?? 0
        let missing = auditInt(integrityCounts["missing"]) ?? 0
        let mismatch = auditInt(integrityCounts["mismatch"]) ?? 0
        let unknown = auditInt(integrityCounts["unknown"]) ?? 0
        let chainStatus = auditString(chain["status"]) ?? "unknown"
        let linkedPairs = auditInt(chain["linked_pairs"]) ?? 0
        let checkedPairs = auditInt(chain["checked_pairs"]) ?? 0
        let externalGaps = auditInt(chain["external_gap_count"]) ?? 0
        let chainBreaks = auditInt(chain["chain_break_count"]) ?? 0

        var lines = [
            "Autopsy Shared Security Audit",
            "Scope: global",
            "Filters: \(Self.sharedSecurityAuditActions.joined(separator: ", "))",
            "Audit window: \(items.count) latest events",
            "Security events: \(securityEvents.count)",
            "Auth failures: \(authFailures.count)",
            "Authorization denials: \(authorizationDenials.count)",
            "User lifecycle: \(userLifecycleEvents.count)",
            "Access changes: \(accessChangeEvents.count)",
            "Token fingerprints: \(fingerprints.count) unique across \(fingerprintEventCount) events",
            "Client fingerprints: \(clientFingerprints.count) unique",
            "Rate limited: \(rateLimitedCount)",
            "Token-scoped denials: \(tokenScopedDenials)",
            "Token-scoped access changes: \(tokenScopedAccessChanges)",
            "Integrity: \(auditString(integrityPayload?["status"]) ?? "unknown") (verified \(verified), missing \(missing), mismatch \(mismatch), unknown \(unknown))",
            "Chain: \(chainStatus), linked \(linkedPairs)/\(checkedPairs), gaps \(externalGaps), breaks \(chainBreaks)",
        ]

        let reasonSummary = reasonCounts
            .sorted { left, right in
                if left.value == right.value {
                    return left.key < right.key
                }
                return left.value > right.value
            }
            .map { "\($0.key) \($0.value)" }
        if !reasonSummary.isEmpty {
            lines.append("Reasons: \(reasonSummary.joined(separator: ", "))")
        }
        let denialReasonSummary = denialReasonCounts
            .sorted { left, right in
                if left.value == right.value {
                    return left.key < right.key
                }
                return left.value > right.value
            }
            .map { "\($0.key) \($0.value)" }
        if !denialReasonSummary.isEmpty {
            lines.append("Denial reasons: \(denialReasonSummary.joined(separator: ", "))")
        }
        let denialModeSummary = denialModeCounts
            .sorted { left, right in
                if left.value == right.value {
                    return left.key < right.key
                }
                return left.value > right.value
            }
            .map { "\($0.key) \($0.value)" }
        if !denialModeSummary.isEmpty {
            lines.append("Denial modes: \(denialModeSummary.joined(separator: ", "))")
        }
        let actionSummary = Self.sharedSecurityAuditActions
            .compactMap { action -> String? in
                guard let count = actionCounts[action], count > 0 else { return nil }
                return "\(action) \(count)"
            }
        if !actionSummary.isEmpty {
            lines.append("Actions: \(actionSummary.joined(separator: ", "))")
        }

        guard !securityEvents.isEmpty else {
            lines.append("")
            lines.append("No global security events were found in the latest audit window.")
            return lines.joined(separator: "\n")
        }

        lines.append("")
        for item in securityEvents.prefix(16) {
            lines.append(formatSharedSecurityAuditItem(item))
        }
        if securityEvents.count > 16 {
            lines.append("- \(securityEvents.count - 16) more security events omitted")
        }
        return lines.joined(separator: "\n")
    }

    private func formatSharedSecurityAuditItem(_ item: [String: Any]) -> String {
        let action = auditString(item["action"]) ?? "security_event"
        if action == "authorization_denied" {
            return formatSharedAuthorizationDeniedAuditItem(item)
        }
        if action == "disable_user" || action == "enable_user" {
            return formatSharedUserLifecycleAuditItem(item, action: action)
        }
        if Self.sharedAccessChangeAuditActions.contains(action) {
            return formatSharedAccessChangeAuditItem(item)
        }

        let createdAt = auditString(item["created_at"]) ?? "unknown time"
        let metadata = item["metadata"] as? [String: Any] ?? [:]

        var parts = [
            "reason \(auditString(metadata["reason"]) ?? "unknown")",
        ]
        if let actor = auditString(item["actor_id"]) {
            parts.append("actor \(actor)")
        }
        if let target = auditString(item["target"]) {
            parts.append("target \(target)")
        }
        if let clientFingerprint = auditString(metadata["client_fingerprint"]) {
            parts.append("client \(clientFingerprint)")
        }
        if let fingerprint = auditString(metadata["token_fingerprint"]) {
            parts.append("fingerprint \(fingerprint)")
        }
        if auditBool(metadata["rate_limited"]) == true {
            parts.append("rate limited")
            if let retryAfter = auditInt(metadata["retry_after_seconds"]) {
                parts.append("retry \(retryAfter)s")
            }
        }
        if let integrityStatus = auditString(item["integrity_status"]) {
            parts.append("integrity \(integrityStatus)")
        }

        return "- \(createdAt) auth failure: \(parts.joined(separator: ", "))"
    }

    private func formatSharedAuthorizationDeniedAuditItem(_ item: [String: Any]) -> String {
        let createdAt = auditString(item["created_at"]) ?? "unknown time"
        let metadata = item["metadata"] as? [String: Any] ?? [:]

        var parts = [
            "mode \(auditString(metadata["mode"]) ?? "unknown")",
            "reason \(auditString(metadata["reason"]) ?? "unknown")",
        ]
        if let actor = auditString(item["actor_id"]) {
            parts.append("actor \(actor)")
        }
        if let graph = auditString(item["graph_slug"]), !graph.isEmpty {
            parts.append("graph \(graph)")
        }
        if let repo = auditString(item["repo"]), !repo.isEmpty {
            parts.append("repo \(repo)")
        }
        if let effectiveRole = auditString(metadata["effective_role"]), !effectiveRole.isEmpty {
            parts.append("effective \(effectiveRole)")
        }
        if let grantCount = auditInt(metadata["matching_grant_count"]) {
            parts.append("matching grants \(grantCount)")
        }
        if let activeOwners = auditInt(metadata["active_owner_count"]) {
            parts.append("active owners \(activeOwners)")
        }
        if let removedOwners = auditInt(metadata["removed_owner_count"]) {
            parts.append("removing owners \(removedOwners)")
        }
        if let remainingOwners = auditInt(metadata["remaining_owner_count"]) {
            parts.append("remaining owners \(remainingOwners)")
        }
        if auditBool(metadata["token_scoped"]) == true {
            parts.append("token scoped")
            if let scopeRole = auditString(metadata["token_scope_role"]), !scopeRole.isEmpty {
                parts.append("scope role \(scopeRole)")
            }
            if let tokenID = auditString(metadata["token_id"]), !tokenID.isEmpty {
                parts.append("token \(tokenID)")
            }
            if let scopeMatches = auditBool(metadata["token_scope_matches"]) {
                parts.append("scope match \(scopeMatches ? "yes" : "no")")
            }
        }
        if let target = auditString(item["target"]) {
            parts.append("target \(target)")
        }
        if let integrityStatus = auditString(item["integrity_status"]) {
            parts.append("integrity \(integrityStatus)")
        }

        return "- \(createdAt) authorization denied: \(parts.joined(separator: ", "))"
    }

    private func formatSharedUserLifecycleAuditItem(_ item: [String: Any], action: String) -> String {
        let createdAt = auditString(item["created_at"]) ?? "unknown time"
        let metadata = item["metadata"] as? [String: Any] ?? [:]
        let label = action == "disable_user" ? "disable user" : "enable user"

        var parts: [String] = []
        if let actor = auditString(item["actor_id"]) {
            parts.append("actor \(actor)")
        }
        if let target = auditString(item["target"]) {
            parts.append("target \(target)")
        }
        if let previousDisabled = auditBool(metadata["previous_disabled"]) {
            parts.append("previous disabled \(previousDisabled ? "yes" : "no")")
        }
        if action == "disable_user", let alreadyDisabled = auditBool(metadata["already_disabled"]) {
            parts.append("already disabled \(alreadyDisabled ? "yes" : "no")")
        }
        if action == "enable_user", let alreadyEnabled = auditBool(metadata["already_enabled"]) {
            parts.append("already enabled \(alreadyEnabled ? "yes" : "no")")
        }
        if let integrityStatus = auditString(item["integrity_status"]) {
            parts.append("integrity \(integrityStatus)")
        }
        if parts.isEmpty {
            parts.append("recorded")
        }

        return "- \(createdAt) \(label): \(parts.joined(separator: ", "))"
    }

    private func sharedAuditIntegrityReport(from output: String, repoScope: String) -> String {
        guard let payload = jsonObject(from: output),
              let rawItems = payload["items"] as? [Any]
        else {
            return output.trimmingCharacters(in: .whitespacesAndNewlines)
        }

        let items = rawItems.compactMap { $0 as? [String: Any] }
        let serverCounts = payload["integrity_counts"] as? [String: Any] ?? [:]
        var counts = [
            "verified": auditInt(serverCounts["verified"]) ?? 0,
            "missing": auditInt(serverCounts["missing"]) ?? 0,
            "mismatch": auditInt(serverCounts["mismatch"]) ?? 0,
            "unknown": auditInt(serverCounts["unknown"]) ?? 0,
        ]
        if serverCounts.isEmpty {
            for item in items {
                let status = auditString(item["integrity_status"]) ?? "unknown"
                if counts.keys.contains(status) {
                    counts[status, default: 0] += 1
                } else {
                    counts["unknown", default: 0] += 1
                }
            }
        }

        let chain = payload["chain"] as? [String: Any] ?? [:]
        var linkedPairs = auditInt(chain["linked_pairs"]) ?? 0
        var checkedPairs = auditInt(chain["checked_pairs"]) ?? 0
        let uncheckablePairs = auditInt(chain["uncheckable_pairs"]) ?? 0
        let chainBreakCount = auditInt(chain["chain_break_count"]) ?? 0
        let externalGapCount = auditInt(chain["external_gap_count"]) ?? 0
        if chain.isEmpty && items.count >= 2 {
            for index in 0..<(items.count - 1) {
                guard let prevHash = auditString(items[index]["prev_hash"]),
                      let previousIntegrityHash = auditString(items[index + 1]["integrity_hash"])
                else {
                    continue
                }
                checkedPairs += 1
                if prevHash == previousIntegrityHash {
                    linkedPairs += 1
                }
            }
        }

        var lines = [
            "Autopsy Shared Audit Integrity",
            "Repo: \(repoScope)",
            "Status: \(auditString(payload["status"]) ?? "unknown")",
            "Audit window: \(auditInt(payload["event_count"]) ?? items.count) latest events",
            "Verified: \(counts["verified", default: 0])",
            "Missing: \(counts["missing", default: 0])",
            "Mismatch: \(counts["mismatch", default: 0])",
            "Unknown: \(counts["unknown", default: 0])",
            "Chain: \(auditString(chain["status"]) ?? "unknown")",
            "Linked pairs: \(linkedPairs)/\(checkedPairs)",
            "Uncheckable pairs: \(uncheckablePairs)",
            "External gaps: \(externalGapCount)",
            "Chain breaks: \(chainBreakCount)",
        ]

        if items.isEmpty {
            lines.append("")
            lines.append("No audit events were found in the latest audit window.")
            return lines.joined(separator: "\n")
        }

        lines.append("")
        for item in items.prefix(12) {
            let createdAt = auditString(item["created_at"]) ?? "unknown time"
            let action = auditString(item["action"]) ?? "unknown_action"
            let repo = auditString(item["repo"]) ?? "unknown repo"
            let status = auditString(item["integrity_status"]) ?? "unknown"
            let hash = shortAuditHash(auditString(item["integrity_hash"]))
            lines.append("- \(createdAt) \(action) \(repo): integrity \(status), hash \(hash)")
        }
        if items.count > 12 {
            lines.append("- \(items.count - 12) more audit events omitted")
        }
        return lines.joined(separator: "\n")
    }

    private func shortAuditHash(_ value: String?) -> String {
        guard let value, !value.isEmpty else {
            return "none"
        }
        return String(value.prefix(12))
    }

    private func sharedAuditReceiptVerificationReport(from output: String, repoScope: String) -> String {
        guard let payload = jsonObject(from: output) else {
            return output.trimmingCharacters(in: .whitespacesAndNewlines)
        }

        let event = payload["event"] as? [String: Any] ?? [:]
        let receipt = payload["receipt"] as? [String: Any] ?? [:]
        let checks = payload["checks"] as? [String: Any] ?? [:]
        let matches = auditBool(payload["matches"]) == true
        let integrityVerified = auditBool(payload["integrity_verified"]) == true
        let auditID = auditString(receipt["id"]) ?? auditString(event["id"]) ?? "unknown"
        let action = auditString(receipt["action"]) ?? auditString(event["action"]) ?? "unknown"
        let graphSlug = auditString(receipt["graph_slug"]) ?? auditString(event["graph_slug"]) ?? "unknown"
        let target = auditString(receipt["target"]) ?? auditString(event["target"]) ?? "none"
        let createdAt = auditString(receipt["created_at"]) ?? auditString(event["created_at"]) ?? "unknown"
        let integrityStatus = auditString(payload["integrity_status"]) ?? auditString(event["integrity_status"]) ?? "unknown"
        let integrityHash = auditString(receipt["integrity_hash"]) ?? auditString(event["integrity_hash"])
        let prevHash = auditString(receipt["prev_hash"]) ?? auditString(event["prev_hash"])

        var checkedCount = 0
        var mismatchLines: [String] = []
        for key in checks.keys.sorted() {
            guard let check = checks[key] as? [String: Any] else { continue }
            checkedCount += 1
            if auditBool(check["matches"]) == false {
                let expected = auditDisplayValue(check["expected"])
                let provided = auditDisplayValue(check["provided"])
                mismatchLines.append("- \(key): expected \(expected), provided \(provided)")
            }
        }

        var lines: [String] = [
            "Autopsy Audit Receipt Verification",
            "Repo: \(repoScope)",
            "Result: \(matches ? "matched" : "mismatch")",
            "Audit: \(auditID)",
            "Action: \(action)",
            "Graph: \(graphSlug)",
            "Target: \(target)",
            "Created: \(createdAt)",
            "Integrity: \(integrityStatus), verified \(integrityVerified ? "yes" : "no")",
            "Hash: \(shortAuditHash(integrityHash))",
            "Previous hash: \(shortAuditHash(prevHash))",
            "Checked fields: \(checkedCount)",
        ]

        lines.append("")
        if mismatchLines.isEmpty {
            lines.append("All supplied receipt fields matched.")
        } else {
            lines.append("Mismatches:")
            lines += mismatchLines
        }
        return lines.joined(separator: "\n")
    }

    private func messageWithAuditReceipt(_ message: String, output: String) -> String {
        messageWithAuditReceipt(message, payload: jsonObject(from: output))
    }

    private func messageWithAuditReceipt(_ message: String, payload: [String: Any]?) -> String {
        guard let receipt = auditReceiptSummary(from: payload) else {
            return message
        }
        return "\(message); \(receipt)"
    }

    private func auditReceiptSummary(from payload: [String: Any]?) -> String? {
        guard let audit = payload?["audit"] as? [String: Any] else {
            return nil
        }
        var parts: [String] = []
        if let id = auditString(audit["id"]) {
            parts.append("audit \(id)")
        }
        let hash = shortAuditHash(auditString(audit["integrity_hash"]))
        if hash != "none" {
            parts.append("hash \(hash)")
        }
        guard !parts.isEmpty else {
            return nil
        }
        return parts.joined(separator: ", ")
    }

    private func auditDisplayValue(_ value: Any?) -> String {
        if value == nil || value is NSNull {
            return "missing"
        }
        if let bool = auditBool(value) {
            return bool ? "true" : "false"
        }
        if let string = auditString(value) {
            return string
        }
        return String(describing: value!)
    }

    private func auditString(_ value: Any?) -> String? {
        if value is NSNull {
            return nil
        }
        if let string = value as? String {
            let trimmed = string.trimmingCharacters(in: .whitespacesAndNewlines)
            return trimmed.isEmpty ? nil : trimmed
        }
        if let number = value as? NSNumber {
            return number.stringValue
        }
        return nil
    }

    private func auditInt(_ value: Any?) -> Int? {
        if value is NSNull {
            return nil
        }
        if let integer = value as? Int {
            return integer
        }
        if let number = value as? NSNumber {
            return number.intValue
        }
        if let string = value as? String {
            return Int(string.trimmingCharacters(in: .whitespacesAndNewlines))
        }
        return nil
    }

    private func auditBool(_ value: Any?) -> Bool? {
        if value is NSNull {
            return nil
        }
        if let bool = value as? Bool {
            return bool
        }
        if let number = value as? NSNumber {
            return number.boolValue
        }
        if let string = value as? String {
            switch string.trimmingCharacters(in: .whitespacesAndNewlines).lowercased() {
            case "true", "1", "yes":
                return true
            case "false", "0", "no":
                return false
            default:
                return nil
            }
        }
        return nil
    }

    private func auditDecimal(_ value: Any?) -> String? {
        if value is NSNull {
            return nil
        }
        let doubleValue: Double?
        if let double = value as? Double {
            doubleValue = double
        } else if let integer = value as? Int {
            doubleValue = Double(integer)
        } else if let number = value as? NSNumber {
            doubleValue = number.doubleValue
        } else if let string = value as? String {
            doubleValue = Double(string.trimmingCharacters(in: .whitespacesAndNewlines))
        } else {
            doubleValue = nil
        }
        guard let doubleValue, doubleValue.isFinite else {
            return nil
        }
        return String(format: "%.2f", doubleValue)
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
