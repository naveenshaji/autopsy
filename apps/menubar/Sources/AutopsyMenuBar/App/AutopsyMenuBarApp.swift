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
    }
}

final class AppDelegate: NSObject, NSApplicationDelegate {
    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.accessory)
    }
}
