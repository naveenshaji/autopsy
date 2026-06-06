import SwiftUI

struct SettingsView: View {
    @ObservedObject var store: ActivityStore

    var body: some View {
        TabView {
            AboutSettingsTab(store: store)
                .tabItem {
                    Label("About", systemImage: "info.circle")
                }

            ContextGraphSettingsTab(store: store)
                .tabItem {
                    Label("Context Graph", systemImage: "point.3.connected.trianglepath.dotted")
                }

            MemorySettingsTab(store: store)
                .tabItem {
                    Label("Memory", systemImage: "brain.head.profile")
                }
        }
        .frame(width: 560, height: 360)
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

private struct ContextGraphSettingsTab: View {
    @ObservedObject var store: ActivityStore

    var body: some View {
        Form {
            Section {
                Toggle("Enable Context Graph", isOn: Binding(
                    get: { store.contextGraphEnabled },
                    set: { store.setContextGraphEnabled($0) }
                ))
                .disabled(store.isUpdatingContextGraphSettings)

                Picker("Capture Mode", selection: Binding(
                    get: { store.contextGraphMode },
                    set: { store.setContextGraphMode($0) }
                )) {
                    Text("CLI").tag("cli")
                    Text("Hooks").tag("hooks")
                }
                .pickerStyle(.segmented)
                .disabled(!store.contextGraphEnabled || store.isUpdatingContextGraphSettings)

                Toggle("Multi-turn Context", isOn: Binding(
                    get: { store.contextGraphMultiTurn },
                    set: { store.setContextGraphMultiTurn($0) }
                ))
                .disabled(!store.contextGraphEnabled || store.isUpdatingContextGraphSettings)
            }

            Section {
                LabeledContent("Status") {
                    HStack(spacing: 8) {
                        if store.isUpdatingContextGraphSettings {
                            ProgressView()
                                .controlSize(.small)
                        }
                        Text(store.contextGraphStatusText)
                            .foregroundStyle(.secondary)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                }

                if let path = store.contextGraphSettings?.path, !path.isEmpty {
                    LabeledContent("Settings File") {
                        Text(path)
                            .font(.system(.caption, design: .monospaced))
                            .foregroundStyle(.secondary)
                            .lineLimit(2)
                            .textSelection(.enabled)
                    }
                }
            }

            Section {
                Text(explanation)
                    .font(.footnote)
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
        .formStyle(.grouped)
        .padding(24)
        .onAppear {
            store.refresh(includeLaunchAgent: true)
        }
    }

    private var explanation: String {
        if !store.contextGraphEnabled {
            return "Disabled mode makes stale graph commands return a disabled setting response without recording events."
        }
        if store.contextGraphMode == "hooks" {
            return "Hook mode is Codex-oriented. Stale context-event calls return a hook-mode response, and Codex instructions are rewritten to stop asking agents to call it."
        }
        if store.contextGraphMultiTurn {
            return "Multi-turn mode keeps prior turn commands visible in the graph while still collapsing repeated file reads into a single node."
        }
        return "Current-turn mode keeps the graph focused on the latest run. Codex instructions open the graph in the in-app Browser instead of the macOS default browser."
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
