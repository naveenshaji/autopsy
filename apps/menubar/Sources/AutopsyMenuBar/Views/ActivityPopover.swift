import AppKit
import SwiftUI

struct ActivityPopover: View {
    @ObservedObject var store: ActivityStore

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            header

            Divider()

            VStack(spacing: 2) {
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
                Divider()
                SectionHeader("Attention")
                VStack(spacing: 2) {
                    ForEach(store.attentionEvents.prefix(2)) { event in
                        AttentionRow(event: event)
                    }
                }
            }

            Divider()

            SectionHeader("Recent Writes")
            VStack(spacing: 2) {
                if store.recentWrites.isEmpty {
                    EmptyActivityRow(text: "No memory writes yet")
                } else {
                    ForEach(store.recentWrites.prefix(3)) { write in
                        WriteRow(write: write)
                    }
                }
            }

            Divider()

            SectionHeader("Recent Consults")
            VStack(spacing: 2) {
                if store.recentConsults.isEmpty {
                    EmptyActivityRow(text: "No consult telemetry yet")
                } else {
                    ForEach(store.recentConsults.prefix(2)) { consult in
                        ConsultRow(consult: consult)
                    }
                }
            }

            Divider()
                .padding(.vertical, 2)

            VStack(spacing: 2) {
                MenuActionRowButton(title: "Health", systemImage: "stethoscope") {
                    store.runHealth()
                }

                MenuActionRowButton(title: "Backup", systemImage: "externaldrive") {
                    store.runBackup()
                }

                MenuToggleRowButton(
                    title: "Notify on Writes",
                    isOn: store.notifyOnWrites,
                    isDisabled: !store.notificationsAvailable
                ) {
                    if store.notificationsAvailable {
                        store.notifyOnWrites.toggle()
                    }
                }
                .help(store.notificationsAvailable ? "Notify when memory is written" : "Notifications require the app bundle")

                MenuActionRowButton(title: "Settings", systemImage: "gearshape") {
                    NSApp.sendAction(Selector(("showSettingsWindow:")), to: nil, from: nil)
                }
                .keyboardShortcut(",", modifiers: .command)

                MenuActionRowButton(title: "Quit", systemImage: "power") {
                    NSApplication.shared.terminate(nil)
                }
                .keyboardShortcut("q", modifiers: .command)
            }
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 8)
        .frame(width: 360)
    }

    private var header: some View {
        HStack(spacing: 10) {
            Image(systemName: store.menuBarSystemImage)
                .font(.system(size: 15, weight: .semibold))
                .symbolRenderingMode(.hierarchical)
                .frame(width: 18)

            VStack(alignment: .leading, spacing: 1) {
                Text("Autopsy")
                    .font(.system(size: 13, weight: .medium))
                Text(store.workspaceTitle)
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
                    .help(store.workspacePath.isEmpty ? store.workspaceTitle : store.workspacePath)
            }

            Spacer()

            HoverIconButton(
                systemImage: "arrow.clockwise",
                helpText: "Refresh",
                isLoading: store.isLoading,
                isDisabled: store.isLoading
            ) {
                store.refresh()
            }
            .keyboardShortcut("r", modifiers: .command)
        }
    }

    private var refreshLabel: String {
        if store.isLoading {
            if let lastRefresh = store.lastRefresh {
                return "Refreshing - updated \(lastRefresh.formatted(date: .omitted, time: .shortened))"
            }
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

private struct SectionHeader: View {
    var title: String

    init(_ title: String) {
        self.title = title
    }

    var body: some View {
        Text(title)
            .font(.caption.weight(.semibold))
            .foregroundStyle(.secondary)
            .padding(.horizontal, 8)
            .padding(.top, 1)
    }
}

private struct StatusRow: View {
    var title: String
    var detail: String
    var footnote: String?
    var systemImage: String
    var isError = false

    var body: some View {
        HStack(alignment: .top, spacing: 8) {
            Image(systemName: systemImage)
                .font(.system(size: 12, weight: .semibold))
                .frame(width: 14)
                .foregroundStyle(isError ? AnyShapeStyle(.red) : AnyShapeStyle(.secondary))

            VStack(alignment: .leading, spacing: 1) {
                Text(title)
                    .font(.subheadline)
                Text(detail.clippedForMenuBarDetail(limit: 80))
                    .font(.caption)
                    .foregroundStyle(isError ? AnyShapeStyle(.red) : AnyShapeStyle(.secondary))
                    .lineLimit(2)
                    .help(detail)
                if let footnote, !footnote.isEmpty {
                    Text(footnote)
                        .font(.caption2)
                        .foregroundStyle(.tertiary)
                        .lineLimit(1)
                        .help(footnote)
                }
            }

            Spacer(minLength: 8)
        }
        .padding(.horizontal, 8)
        .padding(.vertical, 5)
    }
}

private struct EmptyActivityRow: View {
    var text: String

    var body: some View {
        Text(text)
            .font(.footnote)
            .foregroundStyle(.secondary)
            .padding(.horizontal, 8)
            .padding(.vertical, 4)
    }
}

private struct WriteRow: View {
    var write: MemoryWrite

    var body: some View {
        HStack(alignment: .top, spacing: 8) {
            Image(systemName: writeIcon)
                .font(.system(size: 12, weight: .semibold))
                .frame(width: 14)
                .foregroundStyle(.secondary)

            VStack(alignment: .leading, spacing: 1) {
                HStack(spacing: 8) {
                    Text(compactLabel(write.title, fallback: "Untitled memory"))
                        .font(.subheadline)
                        .lineLimit(1)
                        .help(write.title ?? "Untitled memory")
                    Spacer(minLength: 8)
                    Text(relativeLabel(write.updatedAt))
                        .font(.caption2)
                        .foregroundStyle(.tertiary)
                }
                if let summary = write.summary, !summary.isEmpty {
                    Text(summary.clippedForMenuBarDetail())
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .lineLimit(2)
                        .help(summary)
                }
            }
        }
        .padding(.horizontal, 8)
        .padding(.vertical, 4)
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

private struct ConsultRow: View {
    var consult: ConsultEvent

    var body: some View {
        HStack(alignment: .top, spacing: 8) {
            Image(systemName: "magnifyingglass")
                .font(.system(size: 12, weight: .semibold))
                .frame(width: 14)
                .foregroundStyle(.secondary)

            VStack(alignment: .leading, spacing: 1) {
                HStack(spacing: 8) {
                    Text(compactLabel(queryLabel, fallback: "Consult"))
                        .font(.subheadline)
                        .lineLimit(1)
                        .help(queryLabel)
                    Spacer(minLength: 8)
                    Text(relativeLabel(consult.accessedAt))
                        .font(.caption2)
                        .foregroundStyle(.tertiary)
                }
                Text("\(consult.memoryCount ?? 0) memories supplied")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
        }
        .padding(.horizontal, 8)
        .padding(.vertical, 4)
    }

    private var queryLabel: String {
        guard let query = consult.query, !query.isEmpty else {
            return consult.source ?? "Consult"
        }
        return query
    }
}

private struct AttentionRow: View {
    var event: AttentionEvent

    var body: some View {
        HStack(alignment: .top, spacing: 8) {
            Image(systemName: "exclamationmark.triangle")
                .font(.system(size: 12, weight: .semibold))
                .frame(width: 14)
                .foregroundStyle(.red)

            VStack(alignment: .leading, spacing: 1) {
                Text(compactLabel(event.title, fallback: "Needs attention"))
                    .font(.subheadline)
                    .lineLimit(1)
                    .help(event.title ?? "Needs attention")
                if let summary = event.summary, !summary.isEmpty {
                    Text(summary.clippedForMenuBarDetail())
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .lineLimit(2)
                        .help(summary)
                }
            }
        }
        .padding(.horizontal, 8)
        .padding(.vertical, 4)
    }
}

private struct MenuActionRowButton: View {
    let title: String
    let systemImage: String
    var isDisabled = false
    let action: () -> Void
    @State private var isHovered = false

    var body: some View {
        Button(action: action) {
            HStack(spacing: 8) {
                Image(systemName: systemImage)
                    .font(.system(size: 12, weight: .semibold))
                    .frame(width: 14)
                    .foregroundStyle(isDisabled ? .tertiary : .secondary)
                Text(title)
                    .font(.subheadline)
                    .foregroundStyle(isDisabled ? .secondary : .primary)
                Spacer()
            }
            .padding(.horizontal, 8)
            .padding(.vertical, 6)
            .contentShape(Rectangle())
            .background(
                RoundedRectangle(cornerRadius: 6)
                    .fill((isHovered && !isDisabled) ? Color.secondary.opacity(0.14) : Color.clear)
            )
            .animation(.easeInOut(duration: 0.15), value: isHovered)
        }
        .buttonStyle(.plain)
        .disabled(isDisabled)
        .accessibilityLabel(title)
        .accessibilityIdentifier(title)
        .help(title)
        .onHover { hovering in
            isHovered = hovering
        }
    }
}

private struct MenuToggleRowButton: View {
    let title: String
    let isOn: Bool
    var isDisabled = false
    let action: () -> Void
    @State private var isHovered = false

    var body: some View {
        Button(action: action) {
            HStack(spacing: 8) {
                Image(systemName: isOn ? "checkmark" : "minus")
                    .font(.system(size: 11, weight: .semibold))
                    .frame(width: 14)
                    .foregroundStyle(isDisabled ? .tertiary : .secondary)
                Text(title)
                    .font(.subheadline)
                    .foregroundStyle(isDisabled ? .secondary : .primary)
                Spacer()
            }
            .padding(.horizontal, 8)
            .padding(.vertical, 6)
            .contentShape(Rectangle())
            .background(
                RoundedRectangle(cornerRadius: 6)
                    .fill((isHovered && !isDisabled) ? Color.secondary.opacity(0.14) : Color.clear)
            )
            .animation(.easeInOut(duration: 0.15), value: isHovered)
        }
        .buttonStyle(.plain)
        .disabled(isDisabled)
        .accessibilityLabel(title)
        .accessibilityValue(isOn ? "On" : "Off")
        .accessibilityIdentifier(title)
        .help(title)
        .onHover { hovering in
            isHovered = hovering
        }
    }
}

private struct HoverIconButton: View {
    let systemImage: String
    let helpText: String
    var isLoading = false
    var isDisabled = false
    let action: () -> Void
    @State private var isHovered = false

    var body: some View {
        Button(action: action) {
            ZStack {
                RoundedRectangle(cornerRadius: 6)
                    .fill(isHovered && !isDisabled ? Color.secondary.opacity(0.14) : Color.clear)
                    .frame(width: 26, height: 24)
                if isLoading {
                    ProgressView()
                        .controlSize(.small)
                        .scaleEffect(0.7)
                        .frame(width: 14, height: 14)
                } else {
                    Image(systemName: systemImage)
                        .font(.system(size: 12, weight: .semibold))
                        .foregroundStyle(isDisabled ? .tertiary : .secondary)
                }
            }
        }
        .buttonStyle(.plain)
        .disabled(isDisabled)
        .accessibilityLabel(helpText)
        .accessibilityIdentifier(helpText)
        .help(helpText)
        .onHover { hovering in
            isHovered = hovering
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

private func compactLabel(_ value: String?, fallback: String, limit: Int = 30) -> String {
    guard let value, !value.isEmpty else { return fallback }
    return value.clippedForMenuBar(limit: limit)
}

private extension String {
    func clippedForMenuBar(limit: Int = 30) -> String {
        guard count > limit, limit > 3 else { return self }
        return "\(prefix(limit - 3))..."
    }

    func clippedForMenuBarDetail(limit: Int = 120) -> String {
        clippedForMenuBar(limit: limit)
    }
}
