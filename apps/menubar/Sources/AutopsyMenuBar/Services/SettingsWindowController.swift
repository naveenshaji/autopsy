import AppKit
import SwiftUI

@MainActor
final class SettingsWindowController {
    static let shared = SettingsWindowController()

    private var window: NSWindow?

    private init() {}

    func show(store: ActivityStore) {
        let settingsWindow: NSWindow
        if let window {
            settingsWindow = window
        } else {
            let hostingView = NSHostingView(rootView: SettingsView(store: store))
            settingsWindow = NSWindow(
                contentRect: NSRect(x: 0, y: 0, width: 560, height: 360),
                styleMask: [.titled, .closable, .miniaturizable],
                backing: .buffered,
                defer: false
            )
            settingsWindow.title = "Settings"
            settingsWindow.contentView = hostingView
            settingsWindow.isReleasedWhenClosed = false
            settingsWindow.center()
            self.window = settingsWindow
        }

        NSApp.activate(ignoringOtherApps: true)
        settingsWindow.makeKeyAndOrderFront(nil)
    }
}
