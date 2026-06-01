import AppKit
import SwiftUI

@main
struct AutopsyMenuBarApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) private var appDelegate
    @StateObject private var store = ActivityStore()

    var body: some Scene {
        MenuBarExtra {
            ActivityPopover(store: store)
        } label: {
            Label("Autopsy", systemImage: store.menuBarSystemImage)
        }
        .menuBarExtraStyle(.window)
        .commands {
            CommandMenu("Autopsy") {
                Button("Refresh") {
                    store.refresh()
                }
                .keyboardShortcut("r", modifiers: .command)

                Divider()

                Button("Health") {
                    store.runHealth()
                }

                Button("Backup") {
                    store.runBackup()
                }
            }

            CommandGroup(replacing: .appSettings) {
                Button("Settings") {
                    NSApp.sendAction(Selector(("showSettingsWindow:")), to: nil, from: nil)
                }
                .keyboardShortcut(",", modifiers: .command)
            }

            CommandGroup(replacing: .appTermination) {
                Button("Quit Autopsy") {
                    NSApplication.shared.terminate(nil)
                }
                .keyboardShortcut("q", modifiers: .command)
            }
        }

        Settings {
            SettingsView(store: store)
        }
    }
}

final class AppDelegate: NSObject, NSApplicationDelegate {
    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.accessory)
    }
}
