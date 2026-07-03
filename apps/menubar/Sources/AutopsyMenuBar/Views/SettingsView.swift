import SwiftUI

struct SettingsView: View {
    @ObservedObject var store: ActivityStore

    var body: some View {
        TabView {
            AboutSettingsTab(store: store)
                .tabItem {
                    Label("About", systemImage: "info.circle")
                }

            MemorySettingsTab(store: store)
                .tabItem {
                    Label("Memory", systemImage: "brain.head.profile")
                }

            SharedSettingsTab(store: store)
                .tabItem {
                    Label("Shared", systemImage: "person.2")
                }
        }
        .frame(width: 640, height: 560)
    }
}

private struct AboutSettingsTab: View {
    @ObservedObject var store: ActivityStore

    var body: some View {
        Form {
            Section {
                LabeledContent("Application", value: "Autopsy")
                LabeledContent("Version", value: appVersion)
                LabeledContent("Command", value: store.cliPath)
            }

            Section {
                LabeledContent("Status", value: store.statusSummary)
                if let lastRefresh = store.lastRefresh {
                    LabeledContent("Last Activity", value: lastRefresh.formatted(date: .abbreviated, time: .shortened))
                }
            }
        }
        .formStyle(.grouped)
        .padding(24)
    }

    private var appVersion: String {
        let version = Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String
        let build = Bundle.main.object(forInfoDictionaryKey: "CFBundleVersion") as? String
        let displayVersion = version?.trimmingCharacters(in: .whitespacesAndNewlines)
        let displayBuild = build?.trimmingCharacters(in: .whitespacesAndNewlines)
        if let displayVersion, !displayVersion.isEmpty,
           let displayBuild, !displayBuild.isEmpty,
           displayVersion != displayBuild {
            return "\(displayVersion) (\(displayBuild))"
        }
        if let displayVersion, !displayVersion.isEmpty {
            return displayVersion
        }
        return "Local build"
    }
}

private struct MemorySettingsTab: View {
    @ObservedObject var store: ActivityStore

    var body: some View {
        Form {
            Section {
                LabeledContent("Workspace", value: store.workspaceTitle)
                if !store.workspacePath.isEmpty {
                    LabeledContent("Path") {
                        Text(store.workspacePath)
                            .font(.system(.caption, design: .monospaced))
                            .foregroundStyle(.secondary)
                            .lineLimit(2)
                            .textSelection(.enabled)
                    }
                }
                LabeledContent("Instructions", value: store.hasInstalledInstructions ? "Installed" : "Not installed")
            }

            Section {
                HStack {
                    Button("Install Agent Instructions") {
                        store.installAllInstructions()
                    }
                    .disabled(store.isManagingInstructions)

                    Button("Copy Instructions") {
                        store.copyInstructions()
                    }
                    .disabled(store.isCopyingInstructions)
                }
            }

            if let message = store.instructionStatusError, !message.isEmpty {
                Section {
                    Text(message)
                        .font(.footnote)
                        .foregroundStyle(.red)
                }
            }
        }
        .formStyle(.grouped)
        .padding(24)
        .onAppear {
            store.refresh(includeLaunchAgent: true)
        }
    }
}

private struct SharedSettingsTab: View {
    @ObservedObject var store: ActivityStore
    @State private var newUserEmail = ""
    @State private var newUserName = ""
    @State private var accessCheckRepoScope = ""
    @State private var accessCheckMode = "read"
    @State private var teamStatusAuditLastHours = ""
    @State private var teamStatusAuditSince = ""
    @State private var teamStatusAuditUntil = ""
    @State private var policyRepoScope = ""
    @State private var policyRelationLabels = ""
    @State private var policyMemoryKinds = ""
    @State private var policyMinFactRating = "0"
    @State private var policyAllowSharedRelations = true
    @State private var policyAllowPersonalRelations = true
    @State private var policyAllowMemoryWrites = true
    @State private var policyNotes = ""
    @State private var inviteRepoScope = ""
    @State private var inviteRole = "writer"
    @State private var inviteTokenLabel = "menubar-invite"
    @State private var inviteTokenExpiresAt = ""
    @State private var grantUserID = ""
    @State private var grantRepoScope = ""
    @State private var grantRole = "reader"
    @State private var handoffSourceUserID = ""
    @State private var handoffTargetUserID = ""
    @State private var handoffSourceRoleAfter = "writer"
    @State private var sharedMemoryStableKey = ""
    @State private var sharedMemoryRepoScope = ""
    @State private var sharedMemoryKind = "observation"
    @State private var sharedMemoryReason = ""
    @State private var sharedMemoryVersionID = ""
    @State private var sharedMemoryExpectedVersionNS = ""
    @State private var sharedContextQuery = ""
    @State private var sharedContextRepoScope = ""
    @State private var sharedContextIncludeArchived = false
    @State private var sharedContextIncludeRelations = true
    @State private var sharedContextMinFactRating = ""
    @State private var sharedRelationSourceKey = ""
    @State private var sharedRelationTargetKey = ""
    @State private var sharedRelationRepoScope = ""
    @State private var sharedRelation = "references"
    @State private var sharedRelationFact = ""
    @State private var sharedRelationFactRating = "0.5"
    @State private var sharedRelationID = ""
    @State private var personalLinkKey = ""
    @State private var personalSharedKey = ""
    @State private var personalLinkRepoScope = ""
    @State private var personalRelation = "references"
    @State private var personalFact = ""
    @State private var personalFactRating = "0.5"
    @State private var personalRelationID = ""
    @State private var personalContextIncludeArchived = false
    @State private var personalContextIncludeRelations = true
    @State private var personalContextMinFactRating = ""
    @State private var tokenUserID = ""
    @State private var tokenLabel = "menubar"
    @State private var tokenExpiresAt = ""
    @State private var revokeTokenID = ""
    @State private var revokeTokenRepoScope = ""
    @State private var tokenInventoryStatus = "all"
    @State private var tokenInventoryHygiene = "all"
    @State private var tokenInventoryScope = "all"
    @State private var confirmTokenInventoryRevoke = false
    @State private var confirmScopedTokenRevoke = false
    @State private var auditRepoScope = ""
    @State private var auditLastHours = ""
    @State private var auditSince = ""
    @State private var auditUntil = ""
    @State private var auditReceiptID = ""
    @State private var auditReceiptHash = ""
    @State private var auditReceiptRepoScope = ""
    @State private var auditReceiptAction = ""
    @State private var auditReceiptTarget = ""

    private let roles = ["reader", "writer", "owner"]
    private let sourceRoleAfterOptions = ["writer", "reader", "none"]
    private let accessModes = ["read", "write", "admin"]
    private let relationOptions = ["references", "depends_on", "informed_by", "implements", "answers", "refines"]
    private let tokenInventoryStatuses = ["all", "active", "revoked", "expired"]
    private let tokenInventoryHygieneFilters = ["all", "no_expiration", "never_used", "stale", "disabled_user"]
    private let tokenInventoryScopes = ["all", "global", "scoped"]

    var body: some View {
        Form {
            Section {
                LabeledContent("Shared Memory", value: store.sharedServerStatusText)
                if !store.sharedServerEndpoint.isEmpty {
                    LabeledContent("Endpoint", value: store.sharedServerEndpoint)
                }
                if !store.sharedServerGraphSlug.isEmpty {
                    LabeledContent("Graph", value: store.sharedServerGraphSlug)
                }
                if !store.sharedServerUserText.isEmpty {
                    LabeledContent("User", value: store.sharedServerUserText)
                }
                if !store.sharedServerFeaturesText.isEmpty {
                    LabeledContent("Features", value: store.sharedServerFeaturesText)
                }
                if !store.sharedServerAuditWindowText.isEmpty {
                    LabeledContent("Audit Window", value: store.sharedServerAuditWindowText)
                }
                if !store.sharedServerStorageText.isEmpty {
                    LabeledContent("Storage", value: store.sharedServerStorageText)
                }
                if !store.sharedServerUsersText.isEmpty {
                    LabeledContent("Team Users", value: store.sharedServerUsersText)
                }
                if !store.sharedServerGrantsText.isEmpty {
                    LabeledContent("Repo Grants", value: store.sharedServerGrantsText)
                }
                if !store.sharedServerPoliciesText.isEmpty {
                    LabeledContent("Repo Policies", value: store.sharedServerPoliciesText)
                }
                if !store.sharedServerTokensText.isEmpty {
                    LabeledContent("Invite Tokens", value: store.sharedServerTokensText)
                }
                if !store.sharedServerInviteExpirationText.isEmpty {
                    LabeledContent("Invite Expiry", value: store.sharedServerInviteExpirationText)
                }
                if !store.sharedServerAuditIntegrityText.isEmpty {
                    LabeledContent("Audit Integrity", value: store.sharedServerAuditIntegrityText)
                }
                if !store.sharedServerAuditAccessText.isEmpty {
                    LabeledContent("Audit Access", value: store.sharedServerAuditAccessText)
                }
                if !store.sharedServerSharedReadAccessText.isEmpty {
                    LabeledContent("Shared Reads", value: store.sharedServerSharedReadAccessText)
                }
                if !store.sharedServerRelationPolicyConflictsText.isEmpty {
                    LabeledContent("Policy Conflicts", value: store.sharedServerRelationPolicyConflictsText)
                }
                if !store.sharedServerMemoryPolicyConflictsText.isEmpty {
                    LabeledContent("Memory Conflicts", value: store.sharedServerMemoryPolicyConflictsText)
                }
                HStack {
                    Button("Use Owner Config") {
                        store.configureSharedServerFromOwnerConfig()
                    }
                    .disabled(sharedActionDisabled)

                    Button("Check Server") {
                        store.checkSharedServer()
                    }
                    .disabled(sharedActionDisabled)

                    Button("Refresh Team") {
                        store.refreshSharedServerTeam(
                            lastHours: teamStatusAuditLastHours,
                            since: teamStatusAuditSince,
                            until: teamStatusAuditUntil
                        )
                    }
                    .disabled(sharedActionDisabled)

                    Button("Copy Storage") {
                        store.copySharedServerStorageStatus()
                    }
                    .disabled(sharedActionDisabled)
                }

                TextField("Team Audit Hours", text: $teamStatusAuditLastHours)
                    .textFieldStyle(.roundedBorder)
                HStack {
                    TextField("Team Audit Since", text: $teamStatusAuditSince)
                        .textFieldStyle(.roundedBorder)
                    TextField("Team Audit Until", text: $teamStatusAuditUntil)
                        .textFieldStyle(.roundedBorder)
                }
            }

            Section("Access Check") {
                TextField("Repo Scope", text: $accessCheckRepoScope)
                    .textFieldStyle(.roundedBorder)
                Picker("Mode", selection: $accessCheckMode) {
                    ForEach(accessModes, id: \.self) { mode in
                        Text(mode.capitalized).tag(mode)
                    }
                }
                .pickerStyle(.segmented)
                Button("Copy Access") {
                    store.copySharedServerAccessCheck(repoScope: accessCheckRepoScope, mode: accessCheckMode)
                }
                .disabled(sharedActionDisabled)
            }

            Section("Repo Policy") {
                TextField("Policy Repo Scope", text: $policyRepoScope)
                    .textFieldStyle(.roundedBorder)
                TextField("Allowed Relation Labels", text: $policyRelationLabels)
                    .textFieldStyle(.roundedBorder)
                TextField("Allowed Memory Kinds", text: $policyMemoryKinds)
                    .textFieldStyle(.roundedBorder)
                TextField("Minimum Fact Rating", text: $policyMinFactRating)
                    .textFieldStyle(.roundedBorder)
                Toggle("Allow Shared Relations", isOn: $policyAllowSharedRelations)
                Toggle("Allow Personal Links", isOn: $policyAllowPersonalRelations)
                Toggle("Allow Memory Writes", isOn: $policyAllowMemoryWrites)
                TextField("Policy Notes", text: $policyNotes)
                    .textFieldStyle(.roundedBorder)
                HStack {
                    Button("Copy Policy") {
                        store.copySharedServerRepoPolicy(repoScope: policyRepoScope)
                    }
                    .disabled(sharedActionDisabled)

                    Button("Copy Inventory") {
                        store.copySharedServerRepoPolicyInventory(repoScope: policyRepoScope)
                    }
                    .disabled(sharedActionDisabled)

                    Button("Save Policy") {
                        store.updateSharedServerRepoPolicy(
                            repoScope: policyRepoScope,
                            relationLabels: policyRelationLabels,
                            memoryKinds: policyMemoryKinds,
                            minFactRating: policyMinFactRating,
                            allowSharedRelations: policyAllowSharedRelations,
                            allowPersonalRelations: policyAllowPersonalRelations,
                            allowMemoryWrites: policyAllowMemoryWrites,
                            notes: policyNotes
                        )
                    }
                    .disabled(sharedActionDisabled)

                    Button("Reset Policy") {
                        store.resetSharedServerRepoPolicy(repoScope: policyRepoScope)
                    }
                    .disabled(sharedActionDisabled)
                }
            }

            Section("Invite User") {
                TextField("Email", text: $newUserEmail)
                    .textFieldStyle(.roundedBorder)
                TextField("Name", text: $newUserName)
                    .textFieldStyle(.roundedBorder)
                TextField("Repo Scope", text: $inviteRepoScope)
                    .textFieldStyle(.roundedBorder)
                Picker("Role", selection: $inviteRole) {
                    ForEach(roles, id: \.self) { role in
                        Text(role.capitalized).tag(role)
                    }
                }
                .pickerStyle(.segmented)
                TextField("Token Label", text: $inviteTokenLabel)
                    .textFieldStyle(.roundedBorder)
                TextField("Token Expires At", text: $inviteTokenExpiresAt)
                    .textFieldStyle(.roundedBorder)
                Button("Invite User") {
                    store.inviteSharedServerUser(
                        email: newUserEmail,
                        name: newUserName,
                        repoScope: inviteRepoScope,
                        role: inviteRole,
                        label: inviteTokenLabel,
                        expiresAt: inviteTokenExpiresAt
                    )
                }
                .disabled(sharedActionDisabled || newUserEmail.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
            }

            Section("Shared Memories") {
                TextField("Stable Key", text: $sharedMemoryStableKey)
                    .textFieldStyle(.roundedBorder)
                TextField("Repo Scope", text: $sharedMemoryRepoScope)
                    .textFieldStyle(.roundedBorder)
                TextField("Memory Kind", text: $sharedMemoryKind)
                    .textFieldStyle(.roundedBorder)
                TextField("Reason", text: $sharedMemoryReason)
                    .textFieldStyle(.roundedBorder)
                TextField("Version ID", text: $sharedMemoryVersionID)
                    .textFieldStyle(.roundedBorder)
                TextField("Expected Version NS", text: $sharedMemoryExpectedVersionNS)
                    .textFieldStyle(.roundedBorder)
                HStack {
                    Button("Archive") {
                        store.archiveSharedServerMemory(
                            stableKey: sharedMemoryStableKey,
                            repoScope: sharedMemoryRepoScope,
                            expectedVersionNS: sharedMemoryExpectedVersionNS,
                            reason: sharedMemoryReason
                        )
                    }
                    .disabled(sharedActionDisabled || sharedMemoryStableKey.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)

                    Button("Restore") {
                        store.restoreSharedServerMemory(
                            stableKey: sharedMemoryStableKey,
                            repoScope: sharedMemoryRepoScope,
                            expectedVersionNS: sharedMemoryExpectedVersionNS,
                            kind: sharedMemoryKind,
                            reason: sharedMemoryReason
                        )
                    }
                    .disabled(sharedActionDisabled || sharedMemoryStableKey.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)

                    Button("Restore Version") {
                        store.restoreSharedServerMemoryVersion(
                            stableKey: sharedMemoryStableKey,
                            versionID: sharedMemoryVersionID,
                            expectedVersionNS: sharedMemoryExpectedVersionNS,
                            repoScope: sharedMemoryRepoScope,
                            kind: sharedMemoryKind,
                            reason: sharedMemoryReason
                        )
                    }
                    .disabled(
                        sharedActionDisabled
                            || sharedMemoryStableKey.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
                            || sharedMemoryVersionID.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
                            || sharedMemoryKind.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
                    )

                    Button("Check Policy") {
                        store.checkSharedServerMemoryPolicy(
                            repoScope: sharedMemoryRepoScope,
                            kind: sharedMemoryKind
                        )
                    }
                    .disabled(
                        sharedActionDisabled
                            || sharedMemoryKind.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
                    )
                }
                HStack {
                    Button("Copy Active") {
                        store.copySharedServerMemories(repoScope: sharedMemoryRepoScope, includeArchived: false)
                    }
                    .disabled(sharedActionDisabled)

                    Button("Copy All") {
                        store.copySharedServerMemories(repoScope: sharedMemoryRepoScope, includeArchived: true)
                    }
                    .disabled(sharedActionDisabled)

                    Button("Copy History") {
                        store.copySharedServerMemoryHistory(
                            stableKey: sharedMemoryStableKey,
                            repoScope: sharedMemoryRepoScope
                        )
                    }
                    .disabled(sharedActionDisabled || sharedMemoryStableKey.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                }
            }

            Section("Shared Context") {
                TextField("Query", text: $sharedContextQuery)
                    .textFieldStyle(.roundedBorder)
                TextField("Repo Scope", text: $sharedContextRepoScope)
                    .textFieldStyle(.roundedBorder)
                TextField("Min Fact Rating", text: $sharedContextMinFactRating)
                    .textFieldStyle(.roundedBorder)
                Toggle("Include Relations", isOn: $sharedContextIncludeRelations)
                Toggle("Include Archived", isOn: $sharedContextIncludeArchived)
                Button("Copy Context") {
                    store.copySharedServerContext(
                        repoScope: sharedContextRepoScope,
                        query: sharedContextQuery,
                        includeArchived: sharedContextIncludeArchived,
                        includeRelations: sharedContextIncludeRelations,
                        minFactRating: sharedContextMinFactRating
                    )
                }
                .disabled(sharedActionDisabled)
            }

            Section("Shared Relations") {
                TextField("Source Stable Key", text: $sharedRelationSourceKey)
                    .textFieldStyle(.roundedBorder)
                TextField("Target Stable Key", text: $sharedRelationTargetKey)
                    .textFieldStyle(.roundedBorder)
                TextField("Repo Scope", text: $sharedRelationRepoScope)
                    .textFieldStyle(.roundedBorder)
                Picker("Relation", selection: $sharedRelation) {
                    ForEach(relationOptions, id: \.self) { relation in
                        Text(relation).tag(relation)
                    }
                }
                .pickerStyle(.menu)
                TextField("Fact", text: $sharedRelationFact)
                    .textFieldStyle(.roundedBorder)
                TextField("Fact Rating", text: $sharedRelationFactRating)
                    .textFieldStyle(.roundedBorder)
                HStack {
                    Button("Relate") {
                        store.relateSharedServerMemories(
                            sourceKey: sharedRelationSourceKey,
                            targetKey: sharedRelationTargetKey,
                            repoScope: sharedRelationRepoScope,
                            relation: sharedRelation,
                            fact: sharedRelationFact,
                            factRating: sharedRelationFactRating
                        )
                    }
                    .disabled(
                        sharedActionDisabled
                            || sharedRelationSourceKey.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
                            || sharedRelationTargetKey.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
                    )

                    Button("Check Policy") {
                        store.checkSharedServerRelationPolicy(
                            repoScope: sharedRelationRepoScope,
                            relation: sharedRelation,
                            factRating: sharedRelationFactRating,
                            relationScope: "shared"
                        )
                    }
                    .disabled(sharedActionDisabled || sharedRelation.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)

                    Button("Copy Relations") {
                        store.copySharedServerRelations(
                            repoScope: sharedRelationRepoScope,
                            sourceKey: sharedRelationSourceKey,
                            targetKey: sharedRelationTargetKey
                        )
                    }
                    .disabled(sharedActionDisabled)
                }

                Divider()

                TextField("Relation ID", text: $sharedRelationID)
                    .textFieldStyle(.roundedBorder)
                Button("Unrelate") {
                    store.unrelateSharedServerRelation(
                        relationID: sharedRelationID,
                        repoScope: sharedRelationRepoScope
                    )
                }
                .disabled(sharedActionDisabled || sharedRelationID.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
            }

            Section("Personal Links") {
                TextField("Personal Stable Key", text: $personalLinkKey)
                    .textFieldStyle(.roundedBorder)
                TextField("Shared Stable Key", text: $personalSharedKey)
                    .textFieldStyle(.roundedBorder)
                TextField("Repo Scope", text: $personalLinkRepoScope)
                    .textFieldStyle(.roundedBorder)
                Picker("Relation", selection: $personalRelation) {
                    ForEach(relationOptions, id: \.self) { relation in
                        Text(relation).tag(relation)
                    }
                }
                .pickerStyle(.menu)
                TextField("Fact", text: $personalFact)
                    .textFieldStyle(.roundedBorder)
                TextField("Fact Rating", text: $personalFactRating)
                    .textFieldStyle(.roundedBorder)
                HStack {
                    Button("Link") {
                        store.linkSharedServerPersonalMemory(
                            personalKey: personalLinkKey,
                            sharedKey: personalSharedKey,
                            repoScope: personalLinkRepoScope,
                            relation: personalRelation,
                            fact: personalFact,
                            factRating: personalFactRating
                        )
                    }
                    .disabled(
                        sharedActionDisabled
                            || personalLinkKey.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
                            || personalSharedKey.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
                    )

                    Button("Check Policy") {
                        store.checkSharedServerRelationPolicy(
                            repoScope: personalLinkRepoScope,
                            relation: personalRelation,
                            factRating: personalFactRating,
                            relationScope: "personal"
                        )
                    }
                    .disabled(sharedActionDisabled || personalRelation.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)

                    Button("Copy Links") {
                        store.copySharedServerPersonalLinks(
                            repoScope: personalLinkRepoScope,
                            personalKey: personalLinkKey,
                            sharedKey: personalSharedKey
                        )
                    }
                    .disabled(sharedActionDisabled)
                }

                HStack {
                    Toggle("Context Relations", isOn: $personalContextIncludeRelations)
                    Toggle("Archived Targets", isOn: $personalContextIncludeArchived)
                }
                TextField("Min Fact Rating", text: $personalContextMinFactRating)
                    .textFieldStyle(.roundedBorder)

                Button("Copy Linked Context") {
                    store.copySharedServerPersonalContext(
                        repoScope: personalLinkRepoScope,
                        personalKey: personalLinkKey,
                        includeArchived: personalContextIncludeArchived,
                        includeRelations: personalContextIncludeRelations,
                        minFactRating: personalContextMinFactRating
                    )
                }
                .disabled(sharedActionDisabled)

                Divider()

                TextField("Relation ID", text: $personalRelationID)
                    .textFieldStyle(.roundedBorder)
                Button("Unlink") {
                    store.unlinkSharedServerPersonalRelation(
                        relationID: personalRelationID,
                        repoScope: personalLinkRepoScope
                    )
                }
                .disabled(sharedActionDisabled || personalRelationID.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
            }

            Section("Advanced Repo Access") {
                TextField("User ID", text: $grantUserID)
                    .textFieldStyle(.roundedBorder)
                TextField("Repo Scope", text: $grantRepoScope)
                    .textFieldStyle(.roundedBorder)
                Picker("Role", selection: $grantRole) {
                    ForEach(roles, id: \.self) { role in
                        Text(role.capitalized).tag(role)
                    }
                }
                .pickerStyle(.segmented)
                HStack {
                    Button("Grant") {
                        store.grantSharedServerAccess(userID: grantUserID, repoScope: grantRepoScope, role: grantRole)
                    }
                    .disabled(sharedActionDisabled || grantUserID.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)

                    Button("Revoke") {
                        store.revokeSharedServerAccess(userID: grantUserID, repoScope: grantRepoScope)
                    }
                    .disabled(sharedActionDisabled || grantUserID.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                }

                HStack {
                    Button("Copy Users") {
                        store.copySharedServerUsers()
                    }
                    .disabled(sharedActionDisabled)

                    Button("Copy Grants") {
                        store.copySharedServerGrants(repoScope: grantRepoScope)
                    }
                    .disabled(sharedActionDisabled)
                }

                Divider()

                TextField("From Owner ID", text: $handoffSourceUserID)
                    .textFieldStyle(.roundedBorder)
                TextField("To Owner ID", text: $handoffTargetUserID)
                    .textFieldStyle(.roundedBorder)
                Picker("Source After", selection: $handoffSourceRoleAfter) {
                    ForEach(sourceRoleAfterOptions, id: \.self) { role in
                        Text(role == "none" ? "Remove" : role.capitalized).tag(role)
                    }
                }
                .pickerStyle(.segmented)
                Button("Handoff Owner") {
                    store.handoffSharedServerOwner(
                        fromUserID: handoffSourceUserID,
                        toUserID: handoffTargetUserID,
                        repoScope: grantRepoScope,
                        sourceRoleAfter: handoffSourceRoleAfter
                    )
                }
                .disabled(
                    sharedActionDisabled ||
                    handoffSourceUserID.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty ||
                    handoffTargetUserID.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
                )

                Divider()

                HStack {
                    Button("Disable User") {
                        store.disableSharedServerUser(userID: grantUserID)
                    }
                    .disabled(sharedActionDisabled || grantUserID.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)

                    Button("Enable User") {
                        store.enableSharedServerUser(userID: grantUserID)
                    }
                    .disabled(sharedActionDisabled || grantUserID.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                }
            }

            Section("Tokens And Audit") {
                TextField("Token User ID", text: $tokenUserID)
                    .textFieldStyle(.roundedBorder)
                TextField("Token Label", text: $tokenLabel)
                    .textFieldStyle(.roundedBorder)
                TextField("Token Expires At", text: $tokenExpiresAt)
                    .textFieldStyle(.roundedBorder)
                Button("Issue Token") {
                    store.issueSharedServerToken(userID: tokenUserID, label: tokenLabel, expiresAt: tokenExpiresAt)
                }
                .disabled(sharedActionDisabled || tokenUserID.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)

                Divider()

                TextField("Revoke Token ID", text: $revokeTokenID)
                    .textFieldStyle(.roundedBorder)
                TextField("Token Repo Scope", text: $revokeTokenRepoScope)
                    .textFieldStyle(.roundedBorder)
                Picker("Inventory Status", selection: $tokenInventoryStatus) {
                    ForEach(tokenInventoryStatuses, id: \.self) { value in
                        Text(tokenInventoryLabel(value)).tag(value)
                    }
                }
                .pickerStyle(.segmented)
                Picker("Inventory Hygiene", selection: $tokenInventoryHygiene) {
                    ForEach(tokenInventoryHygieneFilters, id: \.self) { value in
                        Text(tokenInventoryLabel(value)).tag(value)
                    }
                }
                .pickerStyle(.menu)
                Picker("Inventory Scope", selection: $tokenInventoryScope) {
                    ForEach(tokenInventoryScopes, id: \.self) { value in
                        Text(tokenInventoryLabel(value)).tag(value)
                    }
                }
                .pickerStyle(.segmented)
                HStack {
                    Button("Copy Token Inventory") {
                        store.copySharedServerAdminTokens(
                            statusFilter: tokenInventoryStatus,
                            hygieneFilter: tokenInventoryHygiene,
                            scopeFilter: tokenInventoryScope
                        )
                    }
                    .disabled(sharedActionDisabled)

                    Button("Copy Revoke Preview") {
                        store.copySharedServerTokenRevokePreview(
                            statusFilter: tokenInventoryStatus,
                            hygieneFilter: tokenInventoryHygiene,
                            scopeFilter: tokenInventoryScope
                        )
                    }
                    .disabled(sharedActionDisabled || !tokenInventoryHasBulkFilter)

                    Button("Copy Invite Tokens") {
                        store.copySharedServerScopedTokens(
                            repoScope: revokeTokenRepoScope,
                            statusFilter: tokenInventoryStatus,
                            hygieneFilter: tokenInventoryHygiene
                        )
                    }
                    .disabled(sharedActionDisabled)

                    Button("Revoke Token") {
                        store.revokeSharedServerToken(tokenID: revokeTokenID, repoScope: revokeTokenRepoScope)
                    }
                    .disabled(sharedActionDisabled || revokeTokenID.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                }
                Toggle("Confirm Matching Revoke", isOn: $confirmTokenInventoryRevoke)
                    .disabled(sharedActionDisabled || !tokenInventoryHasBulkFilter)
                Button("Revoke Matching Tokens") {
                    store.revokeSharedServerMatchingTokens(
                        statusFilter: tokenInventoryStatus,
                        hygieneFilter: tokenInventoryHygiene,
                        scopeFilter: tokenInventoryScope
                    )
                    confirmTokenInventoryRevoke = false
                }
                .disabled(sharedActionDisabled || !tokenInventoryHasBulkFilter || !confirmTokenInventoryRevoke)

                HStack {
                    Button("Copy Scoped Preview") {
                        store.copySharedServerScopedTokenRevokePreview(
                            repoScope: revokeTokenRepoScope,
                            statusFilter: tokenInventoryStatus,
                            hygieneFilter: tokenInventoryHygiene
                        )
                    }
                    .disabled(sharedActionDisabled || !scopedTokenHasBulkFilter)

                    Button("Revoke Scoped Tokens") {
                        store.revokeSharedServerMatchingScopedTokens(
                            repoScope: revokeTokenRepoScope,
                            statusFilter: tokenInventoryStatus,
                            hygieneFilter: tokenInventoryHygiene
                        )
                        confirmScopedTokenRevoke = false
                    }
                    .disabled(sharedActionDisabled || !scopedTokenHasBulkFilter || !confirmScopedTokenRevoke)
                }
                Toggle("Confirm Scoped Revoke", isOn: $confirmScopedTokenRevoke)
                    .disabled(sharedActionDisabled || !scopedTokenHasBulkFilter)

                Divider()

                TextField("Audit Repo Scope", text: $auditRepoScope)
                    .textFieldStyle(.roundedBorder)
                TextField("Audit Hours", text: $auditLastHours)
                    .textFieldStyle(.roundedBorder)
                HStack {
                    TextField("Audit Since", text: $auditSince)
                        .textFieldStyle(.roundedBorder)
                    TextField("Audit Until", text: $auditUntil)
                        .textFieldStyle(.roundedBorder)
                }
                HStack {
                    Button("Copy Audit") {
                        store.copySharedServerAudit(repoScope: auditRepoScope, lastHours: auditLastHours, since: auditSince, until: auditUntil)
                    }
                    .disabled(sharedActionDisabled)

                    Button("Copy Activity") {
                        store.copySharedServerActivityAudit(repoScope: auditRepoScope, lastHours: auditLastHours, since: auditSince, until: auditUntil)
                    }
                    .disabled(sharedActionDisabled)
                }

                HStack {
                    Button("Copy Access Changes") {
                        store.copySharedServerAccessChangeAudit(repoScope: auditRepoScope, lastHours: auditLastHours, since: auditSince, until: auditUntil)
                    }
                    .disabled(sharedActionDisabled)

                    Button("Copy Context Audit") {
                        store.copySharedServerContextAudit(repoScope: auditRepoScope, lastHours: auditLastHours, since: auditSince, until: auditUntil)
                    }
                    .disabled(sharedActionDisabled)

                    Button("Copy Integrity") {
                        store.copySharedServerAuditIntegrity(repoScope: auditRepoScope, lastHours: auditLastHours, since: auditSince, until: auditUntil)
                    }
                    .disabled(sharedActionDisabled)
                }

                HStack {
                    Button("Copy Security") {
                        store.copySharedServerSecurityAudit(lastHours: auditLastHours, since: auditSince, until: auditUntil)
                    }
                    .disabled(sharedActionDisabled)
                }

                Divider()

                TextField("Receipt Audit ID", text: $auditReceiptID)
                    .textFieldStyle(.roundedBorder)
                TextField("Receipt Integrity Hash", text: $auditReceiptHash)
                    .textFieldStyle(.roundedBorder)
                TextField("Receipt Repo Scope", text: $auditReceiptRepoScope)
                    .textFieldStyle(.roundedBorder)
                HStack {
                    TextField("Expected Action", text: $auditReceiptAction)
                        .textFieldStyle(.roundedBorder)
                    TextField("Expected Target", text: $auditReceiptTarget)
                        .textFieldStyle(.roundedBorder)
                }
                Button("Verify Receipt") {
                    store.verifySharedServerAuditReceipt(
                        auditID: auditReceiptID,
                        integrityHash: auditReceiptHash,
                        repoScope: auditReceiptRepoScope,
                        action: auditReceiptAction,
                        target: auditReceiptTarget
                    )
                }
                .disabled(
                    sharedActionDisabled ||
                    auditReceiptID.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty ||
                    auditReceiptHash.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
                )
            }

            if let message = store.lastActionMessage, !message.isEmpty {
                Section {
                    Text(message)
                        .font(.footnote)
                        .foregroundStyle(.secondary)
                }
            }

            if let message = store.sharedServerError, !message.isEmpty {
                Section {
                    Text(message)
                        .font(.footnote)
                        .foregroundStyle(.red)
                }
            }
        }
        .formStyle(.grouped)
        .padding(24)
        .onAppear {
            if grantRepoScope.isEmpty {
                grantRepoScope = store.sharedServerDefaultRepoScope
            }
            if inviteRepoScope.isEmpty {
                inviteRepoScope = store.sharedServerDefaultRepoScope
            }
            if policyRepoScope.isEmpty {
                policyRepoScope = store.sharedServerDefaultRepoScope
            }
            if auditRepoScope.isEmpty {
                auditRepoScope = store.sharedServerDefaultRepoScope
            }
            if auditReceiptRepoScope.isEmpty {
                auditReceiptRepoScope = store.sharedServerDefaultRepoScope
            }
            if sharedMemoryRepoScope.isEmpty {
                sharedMemoryRepoScope = store.sharedServerDefaultRepoScope
            }
            if sharedContextRepoScope.isEmpty {
                sharedContextRepoScope = store.sharedServerDefaultRepoScope
            }
            if sharedRelationRepoScope.isEmpty {
                sharedRelationRepoScope = store.sharedServerDefaultRepoScope
            }
            if personalLinkRepoScope.isEmpty {
                personalLinkRepoScope = store.sharedServerDefaultRepoScope
            }
            store.refreshSharedServerTeam()
        }
    }

    private var sharedActionDisabled: Bool {
        store.isCheckingSharedServer || store.isManagingSharedAccess
    }

    private var tokenInventoryHasBulkFilter: Bool {
        tokenInventoryStatus != "all" || tokenInventoryHygiene != "all" || tokenInventoryScope != "all"
    }

    private var scopedTokenHasBulkFilter: Bool {
        tokenInventoryStatus != "all" || tokenInventoryHygiene != "all"
    }

    private func tokenInventoryLabel(_ value: String) -> String {
        switch value {
        case "no_expiration":
            return "No Expiry"
        case "never_used":
            return "Never Used"
        case "disabled_user":
            return "Disabled User"
        default:
            return value.replacingOccurrences(of: "_", with: " ").capitalized
        }
    }
}
