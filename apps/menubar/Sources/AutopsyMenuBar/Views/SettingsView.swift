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
    @State private var inviteRepoScope = ""
    @State private var inviteRole = "writer"
    @State private var inviteTokenLabel = "menubar-invite"
    @State private var grantUserID = ""
    @State private var grantRepoScope = ""
    @State private var grantRole = "reader"
    @State private var sharedMemoryStableKey = ""
    @State private var sharedMemoryRepoScope = ""
    @State private var sharedMemoryReason = ""
    @State private var sharedContextQuery = ""
    @State private var sharedContextRepoScope = ""
    @State private var sharedContextIncludeArchived = false
    @State private var sharedContextIncludeRelations = true
    @State private var sharedRelationSourceKey = ""
    @State private var sharedRelationTargetKey = ""
    @State private var sharedRelationRepoScope = ""
    @State private var sharedRelation = "references"
    @State private var sharedRelationFact = ""
    @State private var sharedRelationID = ""
    @State private var personalLinkKey = ""
    @State private var personalSharedKey = ""
    @State private var personalLinkRepoScope = ""
    @State private var personalRelation = "references"
    @State private var personalFact = ""
    @State private var personalRelationID = ""
    @State private var tokenUserID = ""
    @State private var tokenLabel = "menubar"
    @State private var revokeTokenID = ""
    @State private var revokeTokenRepoScope = ""
    @State private var auditRepoScope = ""

    private let roles = ["reader", "writer", "owner"]
    private let relationOptions = ["references", "depends_on", "informed_by", "implements", "answers", "refines"]

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
                if !store.sharedServerUsersText.isEmpty {
                    LabeledContent("Team Users", value: store.sharedServerUsersText)
                }
                if !store.sharedServerGrantsText.isEmpty {
                    LabeledContent("Repo Grants", value: store.sharedServerGrantsText)
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
                        store.refreshSharedServerTeam()
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
                Button("Invite User") {
                    store.inviteSharedServerUser(
                        email: newUserEmail,
                        name: newUserName,
                        repoScope: inviteRepoScope,
                        role: inviteRole,
                        label: inviteTokenLabel
                    )
                }
                .disabled(sharedActionDisabled || newUserEmail.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
            }

            Section("Shared Memories") {
                TextField("Stable Key", text: $sharedMemoryStableKey)
                    .textFieldStyle(.roundedBorder)
                TextField("Repo Scope", text: $sharedMemoryRepoScope)
                    .textFieldStyle(.roundedBorder)
                TextField("Reason", text: $sharedMemoryReason)
                    .textFieldStyle(.roundedBorder)
                HStack {
                    Button("Archive") {
                        store.archiveSharedServerMemory(
                            stableKey: sharedMemoryStableKey,
                            repoScope: sharedMemoryRepoScope,
                            reason: sharedMemoryReason
                        )
                    }
                    .disabled(sharedActionDisabled || sharedMemoryStableKey.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)

                    Button("Restore") {
                        store.restoreSharedServerMemory(
                            stableKey: sharedMemoryStableKey,
                            repoScope: sharedMemoryRepoScope,
                            reason: sharedMemoryReason
                        )
                    }
                    .disabled(sharedActionDisabled || sharedMemoryStableKey.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
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
                }
            }

            Section("Shared Context") {
                TextField("Query", text: $sharedContextQuery)
                    .textFieldStyle(.roundedBorder)
                TextField("Repo Scope", text: $sharedContextRepoScope)
                    .textFieldStyle(.roundedBorder)
                Toggle("Include Relations", isOn: $sharedContextIncludeRelations)
                Toggle("Include Archived", isOn: $sharedContextIncludeArchived)
                Button("Copy Context") {
                    store.copySharedServerContext(
                        repoScope: sharedContextRepoScope,
                        query: sharedContextQuery,
                        includeArchived: sharedContextIncludeArchived,
                        includeRelations: sharedContextIncludeRelations
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
                HStack {
                    Button("Relate") {
                        store.relateSharedServerMemories(
                            sourceKey: sharedRelationSourceKey,
                            targetKey: sharedRelationTargetKey,
                            repoScope: sharedRelationRepoScope,
                            relation: sharedRelation,
                            fact: sharedRelationFact
                        )
                    }
                    .disabled(
                        sharedActionDisabled
                            || sharedRelationSourceKey.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
                            || sharedRelationTargetKey.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
                    )

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
                HStack {
                    Button("Link") {
                        store.linkSharedServerPersonalMemory(
                            personalKey: personalLinkKey,
                            sharedKey: personalSharedKey,
                            repoScope: personalLinkRepoScope,
                            relation: personalRelation,
                            fact: personalFact
                        )
                    }
                    .disabled(
                        sharedActionDisabled
                            || personalLinkKey.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
                            || personalSharedKey.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
                    )

                    Button("Copy Links") {
                        store.copySharedServerPersonalLinks(
                            repoScope: personalLinkRepoScope,
                            personalKey: personalLinkKey,
                            sharedKey: personalSharedKey
                        )
                    }
                    .disabled(sharedActionDisabled)
                }

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
            }

            Section("Tokens And Audit") {
                TextField("Token User ID", text: $tokenUserID)
                    .textFieldStyle(.roundedBorder)
                TextField("Token Label", text: $tokenLabel)
                    .textFieldStyle(.roundedBorder)
                Button("Issue Token") {
                    store.issueSharedServerToken(userID: tokenUserID, label: tokenLabel)
                }
                .disabled(sharedActionDisabled || tokenUserID.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)

                Divider()

                TextField("Revoke Token ID", text: $revokeTokenID)
                    .textFieldStyle(.roundedBorder)
                TextField("Token Repo Scope", text: $revokeTokenRepoScope)
                    .textFieldStyle(.roundedBorder)
                Button("Revoke Token") {
                    store.revokeSharedServerToken(tokenID: revokeTokenID, repoScope: revokeTokenRepoScope)
                }
                .disabled(sharedActionDisabled || revokeTokenID.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)

                Divider()

                TextField("Audit Repo Scope", text: $auditRepoScope)
                    .textFieldStyle(.roundedBorder)
                Button("Copy Audit") {
                    store.copySharedServerAudit(repoScope: auditRepoScope)
                }
                .disabled(sharedActionDisabled)
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
            if auditRepoScope.isEmpty {
                auditRepoScope = store.sharedServerDefaultRepoScope
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
}
