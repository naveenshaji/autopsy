import SwiftUI

struct SettingsView: View {
    @ObservedObject var store: ActivityStore

    var body: some View {
        Form {
            Section("Command") {
                TextField("autopsy command", text: $store.cliPath)
                    .textFieldStyle(.roundedBorder)
                Text("Use an absolute path if the app cannot find the CLI from PATH.")
                    .font(.caption)
                    .foregroundStyle(.secondary)
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
