import AppKit
import SwiftUI

struct ActivityPopover: View {
    @ObservedObject var store: ActivityStore

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            header
            statusLine
            activitySnapshot

            if let message = store.errorMessage {
                AttentionBanner(title: "Autopsy unavailable", summary: message)
            } else if !store.attentionEvents.isEmpty {
                ForEach(store.attentionEvents.prefix(2)) { event in
                    AttentionBanner(title: event.title ?? "Needs attention", summary: event.summary ?? "")
                }
            }

            Divider()

            ActivitySection(title: "Recent writes", emptyText: "No memory writes yet", isEmpty: store.recentWrites.isEmpty) {
                ForEach(store.recentWrites.prefix(4)) { write in
                    WriteRow(write: write)
                }
            }

            ActivitySection(title: "Recent consults", emptyText: "No consult telemetry yet", isEmpty: store.recentConsults.isEmpty) {
                ForEach(store.recentConsults.prefix(3)) { consult in
                    ConsultRow(consult: consult)
                }
            }

            Divider()
            controls
        }
        .padding(16)
        .frame(width: 420)
    }

    private var header: some View {
        HStack(spacing: 10) {
            Image(systemName: store.menuBarSystemImage)
                .font(.system(size: 17, weight: .semibold))
                .symbolRenderingMode(.hierarchical)
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
            Button {
                store.refresh()
            } label: {
                Image(systemName: "arrow.clockwise")
            }
            .buttonStyle(.borderless)
            .help("Refresh")
            .disabled(store.isLoading)
        }
    }

    private var activitySnapshot: some View {
        HStack(spacing: 6) {
            ActivityCountPill(systemImage: "square.and.pencil", value: store.recentWrites.count, label: "writes")
            ActivityCountPill(systemImage: "magnifyingglass", value: store.recentConsults.count, label: "consults")
            if !store.attentionEvents.isEmpty {
                ActivityCountPill(systemImage: "exclamationmark.triangle", value: store.attentionEvents.count, label: "attention")
            }
            Spacer(minLength: 0)
        }
    }

    private var statusLine: some View {
        VStack(alignment: .leading, spacing: 5) {
            Text(store.statusSummary)
                .font(.callout)
                .foregroundStyle(store.errorMessage == nil ? AnyShapeStyle(.secondary) : AnyShapeStyle(.red))
                .lineLimit(2)
            HStack(spacing: 8) {
                if store.isLoading {
                    ProgressView()
                        .controlSize(.small)
                    Text("Refreshing")
                } else if let lastRefresh = store.lastRefresh {
                    Text("Updated \(lastRefresh.formatted(date: .omitted, time: .shortened))")
                } else {
                    Text("Not refreshed")
                }
                if let message = store.lastActionMessage {
                    Text(message)
                        .foregroundStyle(.secondary)
                }
            }
            .font(.caption)
            .foregroundStyle(.tertiary)
            .lineLimit(1)
        }
    }

    private var controls: some View {
        VStack(alignment: .leading, spacing: 10) {
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
                Spacer()
                Button {
                    NSApplication.shared.terminate(nil)
                } label: {
                    Label("Quit", systemImage: "power")
                }
            }
            .controlSize(.small)

            Toggle("Notify on writes", isOn: $store.notifyOnWrites)
                .font(.caption)
                .toggleStyle(.switch)
                .disabled(!store.notificationsAvailable)

            HStack(spacing: 6) {
                Image(systemName: store.launchAtLoginEnabled ? "checkmark.circle" : "circle")
                Text(store.launchAtLoginStatusText)
                    .lineLimit(1)
                Spacer(minLength: 0)
            }
            .font(.caption)
            .foregroundStyle(store.launchAgentError == nil ? AnyShapeStyle(.tertiary) : AnyShapeStyle(.red))
        }
    }
}

struct ActivityCountPill: View {
    var systemImage: String
    var value: Int
    var label: String

    var body: some View {
        Label {
            Text("\(value) \(label)")
        } icon: {
            Image(systemName: systemImage)
        }
        .font(.caption2.weight(.medium))
        .foregroundStyle(.secondary)
        .padding(.horizontal, 7)
        .padding(.vertical, 4)
        .background(Color.secondary.opacity(0.10), in: Capsule())
    }
}

struct ActivitySection<Content: View>: View {
    var title: String
    var emptyText: String
    var isEmpty: Bool
    @ViewBuilder var content: Content

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(title.uppercased())
                .font(.caption2.weight(.semibold))
                .foregroundStyle(.tertiary)
            if isEmpty {
                Text(emptyText)
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(.vertical, 4)
            } else {
                content
            }
        }
    }
}

struct WriteRow: View {
    var write: MemoryWrite

    var body: some View {
        HStack(alignment: .top, spacing: 9) {
            KindPill(text: write.kind ?? "memory")
            VStack(alignment: .leading, spacing: 3) {
                HStack(spacing: 6) {
                    Text(write.title ?? "Untitled memory")
                        .font(.callout.weight(.semibold))
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
        }
        .padding(.vertical, 2)
    }
}

struct ConsultRow: View {
    var consult: ConsultEvent

    var body: some View {
        HStack(alignment: .top, spacing: 9) {
            Image(systemName: "magnifyingglass")
                .font(.caption.weight(.semibold))
                .foregroundStyle(.secondary)
                .frame(width: 46, alignment: .leading)
            VStack(alignment: .leading, spacing: 3) {
                HStack(spacing: 6) {
                    Text(queryLabel)
                        .font(.callout.weight(.semibold))
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
        }
        .padding(.vertical, 2)
    }

    private var queryLabel: String {
        guard let query = consult.query, !query.isEmpty else {
            return consult.source ?? "Consult"
        }
        return query
    }
}

struct AttentionBanner: View {
    var title: String
    var summary: String

    var body: some View {
        VStack(alignment: .leading, spacing: 3) {
            Text(title)
                .font(.callout.weight(.semibold))
            if !summary.isEmpty {
                Text(summary)
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .lineLimit(3)
            }
        }
        .padding(10)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 8, style: .continuous))
    }
}

struct KindPill: View {
    var text: String

    var body: some View {
        Text(text.uppercased())
            .font(.system(size: 9, weight: .semibold, design: .monospaced))
            .foregroundStyle(.secondary)
            .frame(width: 46, alignment: .leading)
            .lineLimit(1)
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
