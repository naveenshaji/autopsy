import AppKit
import SwiftUI

struct ActivityPopover: View {
    @ObservedObject var store: ActivityStore

    var body: some View {
        VStack(spacing: 0) {
            header
                .padding(.horizontal, 14)
                .padding(.vertical, 12)

            Divider()

            List {
                Section {
                    StatusRow(
                        title: "Status",
                        detail: store.statusSummary,
                        footnote: statusFootnote,
                        systemImage: store.errorMessage == nil ? "checkmark.circle" : "exclamationmark.triangle",
                        isError: store.errorMessage != nil
                    )
                    StatusRow(
                        title: "Activity",
                        detail: activitySummary,
                        systemImage: "chart.bar"
                    )
                    StatusRow(
                        title: "Login Startup",
                        detail: store.launchAtLoginStatusText,
                        systemImage: store.launchAtLoginEnabled ? "checkmark.circle" : "circle",
                        isError: store.launchAgentError != nil
                    )
                }

                if !store.attentionEvents.isEmpty {
                    Section("Attention") {
                        ForEach(store.attentionEvents.prefix(2)) { event in
                            AttentionRow(event: event)
                        }
                    }
                }

                Section("Recent Writes") {
                    if store.recentWrites.isEmpty {
                        EmptyActivityRow(text: "No memory writes yet")
                    } else {
                        ForEach(store.recentWrites.prefix(4)) { write in
                            WriteRow(write: write)
                        }
                    }
                }

                Section("Recent Consults") {
                    if store.recentConsults.isEmpty {
                        EmptyActivityRow(text: "No consult telemetry yet")
                    } else {
                        ForEach(store.recentConsults.prefix(3)) { consult in
                            ConsultRow(consult: consult)
                        }
                    }
                }
            }
            .listStyle(.inset)

            Divider()

            controls
                .padding(.horizontal, 14)
                .padding(.vertical, 10)
        }
        .frame(width: 420, height: 520)
    }

    private var header: some View {
        HStack(spacing: 10) {
            Image(systemName: store.menuBarSystemImage)
                .font(.title3)
                .symbolRenderingMode(.hierarchical)
                .frame(width: 22)

            VStack(alignment: .leading, spacing: 2) {
                Text("Autopsy")
                    .font(.headline)
                Text(store.workspaceTitle)
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
                    .help(store.workspacePath.isEmpty ? store.workspaceTitle : store.workspacePath)
            }

            Spacer()

            if store.isLoading {
                ProgressView()
                    .controlSize(.small)
            }

            Button {
                store.refresh()
            } label: {
                Label("Refresh", systemImage: "arrow.clockwise")
            }
            .labelStyle(.iconOnly)
            .keyboardShortcut("r", modifiers: .command)
            .help("Refresh")
            .disabled(store.isLoading)
        }
    }

    private var controls: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(spacing: 8) {
                Button {
                    store.runHealth()
                } label: {
                    Label("Health", systemImage: "stethoscope")
                }

                Button {
                    store.runBackup()
                } label: {
                    Label("Backup", systemImage: "externaldrive")
                }

                Button {
                    NSApp.sendAction(Selector(("showSettingsWindow:")), to: nil, from: nil)
                } label: {
                    Label("Settings", systemImage: "gearshape")
                }
                .keyboardShortcut(",", modifiers: .command)

                Spacer()

                Button {
                    NSApplication.shared.terminate(nil)
                } label: {
                    Label("Quit", systemImage: "power")
                }
                .keyboardShortcut("q", modifiers: .command)
            }

            Toggle("Notify on writes", isOn: $store.notifyOnWrites)
                .toggleStyle(.switch)
                .disabled(!store.notificationsAvailable)
                .help(store.notificationsAvailable ? "Notify when memory is written" : "Notifications require the app bundle")
        }
        .controlSize(.small)
    }

    private var refreshLabel: String {
        if store.isLoading {
            return "Refreshing"
        }
        if let lastRefresh = store.lastRefresh {
            return "Updated \(lastRefresh.formatted(date: .omitted, time: .shortened))"
        }
        return "Not refreshed"
    }

    private var statusFootnote: String {
        guard let message = store.lastActionMessage, !message.isEmpty else {
            return refreshLabel
        }
        return "\(refreshLabel) - \(message)"
    }

    private var activitySummary: String {
        var parts = [
            "\(store.recentWrites.count) writes",
            "\(store.recentConsults.count) consults",
        ]
        if !store.attentionEvents.isEmpty {
            parts.append("\(store.attentionEvents.count) attention")
        }
        return parts.joined(separator: ", ")
    }
}

struct StatusRow: View {
    var title: String
    var detail: String
    var footnote: String?
    var systemImage: String
    var isError = false

    var body: some View {
        Label {
            VStack(alignment: .leading, spacing: 2) {
                Text(title)
                    .font(.callout)
                Text(detail)
                    .font(.caption)
                    .foregroundStyle(isError ? AnyShapeStyle(.red) : AnyShapeStyle(.secondary))
                    .lineLimit(2)
                if let footnote, !footnote.isEmpty {
                    Text(footnote)
                        .font(.caption2)
                        .foregroundStyle(.tertiary)
                        .lineLimit(1)
                }
            }
        } icon: {
            Image(systemName: systemImage)
                .foregroundStyle(isError ? AnyShapeStyle(.red) : AnyShapeStyle(.secondary))
        }
    }
}

struct EmptyActivityRow: View {
    var text: String

    var body: some View {
        Text(text)
            .foregroundStyle(.secondary)
    }
}

struct WriteRow: View {
    var write: MemoryWrite

    var body: some View {
        Label {
            VStack(alignment: .leading, spacing: 2) {
                HStack(spacing: 8) {
                    Text(write.title ?? "Untitled memory")
                        .font(.callout)
                        .lineLimit(1)
                    Spacer(minLength: 8)
                    Text(relativeLabel(write.updatedAt))
                        .font(.caption)
                        .foregroundStyle(.tertiary)
                }
                if let summary = write.summary, !summary.isEmpty {
                    Text(summary)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .lineLimit(2)
                }
            }
        } icon: {
            Image(systemName: writeIcon)
                .foregroundStyle(.secondary)
        }
    }

    private var writeIcon: String {
        switch write.kind {
        case "decision":
            return "checkmark.seal"
        case "question", "open_question":
            return "questionmark.circle"
        case "procedure":
            return "list.bullet.rectangle"
        default:
            return "square.and.pencil"
        }
    }
}

struct ConsultRow: View {
    var consult: ConsultEvent

    var body: some View {
        Label {
            VStack(alignment: .leading, spacing: 2) {
                HStack(spacing: 8) {
                    Text(queryLabel)
                        .font(.callout)
                        .lineLimit(1)
                    Spacer(minLength: 8)
                    Text(relativeLabel(consult.accessedAt))
                        .font(.caption)
                        .foregroundStyle(.tertiary)
                }
                Text("\(consult.memoryCount ?? 0) memories supplied")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
        } icon: {
            Image(systemName: "magnifyingglass")
                .foregroundStyle(.secondary)
        }
    }

    private var queryLabel: String {
        guard let query = consult.query, !query.isEmpty else {
            return consult.source ?? "Consult"
        }
        return query
    }
}

struct AttentionRow: View {
    var event: AttentionEvent

    var body: some View {
        Label {
            VStack(alignment: .leading, spacing: 2) {
                Text(event.title ?? "Needs attention")
                    .font(.callout)
                    .lineLimit(1)
                if let summary = event.summary, !summary.isEmpty {
                    Text(summary)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .lineLimit(2)
                }
            }
        } icon: {
            Image(systemName: "exclamationmark.triangle")
                .foregroundStyle(.red)
        }
    }
}

private func relativeLabel(_ value: String?) -> String {
    guard let value, !value.isEmpty else { return "" }
    let formatter = ISO8601DateFormatter()
    formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
    let date = formatter.date(from: value) ?? ISO8601DateFormatter().date(from: value)
    guard let date else { return "" }
    return date.formatted(.relative(presentation: .numeric, unitsStyle: .abbreviated))
}
