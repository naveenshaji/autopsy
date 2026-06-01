import SwiftUI

struct SettingsView: View {
    @ObservedObject var store: ActivityStore

    var body: some View {
        Form {
            Section("Command") {
                TextField("autopsy command", text: $store.cliPath)
                    .textFieldStyle(.roundedBorder)
                Button {
                    store.resetCLIPath()
                } label: {
                    Label("Use Detected Command", systemImage: "location")
                }
                .controlSize(.small)
                Text("Use an absolute path if the app cannot find the CLI from PATH.")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                Text(store.detectedCLIPath)
                    .font(.caption2.monospaced())
                    .foregroundStyle(.tertiary)
                    .lineLimit(1)
            }

            Section("Startup") {
                Toggle(
                    "Open Autopsy at Login",
                    isOn: Binding(
                        get: { store.launchAtLoginEnabled },
                        set: { store.setLaunchAtLogin($0) }
                    )
                )
                .disabled(store.isManagingLaunchAgent)

                HStack(spacing: 6) {
                    if store.isManagingLaunchAgent {
                        ProgressView()
                            .controlSize(.small)
                    }
                    Text(store.launchAtLoginStatusText)
                        .font(.caption)
                        .foregroundStyle(store.launchAgentError == nil ? AnyShapeStyle(.secondary) : AnyShapeStyle(.red))
                        .lineLimit(2)
                }
            }

            Section("Notifications") {
                Toggle("Notify when a memory is written", isOn: $store.notifyOnWrites)
                    .disabled(!store.notificationsAvailable)
                Text("Successful writes stay quiet by default. Enable this only when you want a visible capture trail.")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                if !store.notificationsAvailable {
                    Text("Notifications require launching Autopsy as a macOS app bundle.")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
            }
        }
        .padding(20)
        .frame(width: 420)
    }
}
