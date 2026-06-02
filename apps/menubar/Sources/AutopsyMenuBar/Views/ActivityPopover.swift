import AppKit
import SwiftUI

struct ActivityPopover: View {
    @ObservedObject var store: ActivityStore
    @State private var activeDetail: ActivityHoverDetail?
    @State private var detailClearGeneration = 0
    @State private var isDetailPanelHovered = false
    @State private var selectedActivityTab: ActivityTab = .writes

    private let menuHeight: CGFloat = 500

    var body: some View {
        HStack(alignment: .top, spacing: 0) {
            menuContent
            .frame(width: 360)
            .frame(height: menuHeight)

            if let activeDetail {
                Divider()
                    .frame(height: menuHeight)

                ActivityHoverDetailPanel(detail: activeDetail, store: store)
                    .frame(width: 310, height: menuHeight, alignment: .topLeading)
                    .onHover { hovering in
                        setDetailPanelHovered(hovering)
                    }
            }
        }
        .frame(width: activeDetail == nil ? 360 : 670, height: menuHeight, alignment: .leading)
        .animation(.easeInOut(duration: 0.14), value: activeDetail != nil)
    }

    private var menuContent: some View {
        VStack(spacing: 6) {
            if store.shouldShowOnboardingPrompt {
                OnboardingPrompt(
                    isLoading: store.isManagingInstructions,
                    install: store.installAllInstructions
                )
            }

            if !store.attentionEvents.isEmpty {
                SectionHeader("Attention")
                VStack(spacing: 2) {
                    ForEach(store.attentionEvents.prefix(2)) { event in
                        AttentionRow(event: event)
                    }
                }

                Divider()
            }

            ActivityTabBar(
                selectedTab: selectedActivityTab,
                selectTab: { tab in
                    selectedActivityTab = tab
                    closeDetail()
                }
            )

            activityList
                .frame(maxWidth: .infinity, maxHeight: .infinity)

            Divider()

            AgentInstructionsRow(
                targets: store.instructionTargets,
                isLoading: store.instructionStatus == nil || store.isManagingInstructions,
                activeDetail: activeDetail,
                activateDetail: activateDetail,
                deactivateDetail: deactivateDetail
            )

            MenuActionRowButton(title: "Health", systemImage: "stethoscope") {
                closeDetail()
                store.runHealth()
            }
            .onHover { hovering in
                if hovering {
                    closeDetail()
                }
            }

            MenuActionRowButton(title: "Backup", systemImage: "externaldrive") {
                closeDetail()
                store.runBackup()
            }
            .onHover { hovering in
                if hovering {
                    closeDetail()
                }
            }

            if store.cliPath != store.detectedCLIPath {
                MenuActionRowButton(title: "Use Detected Command", systemImage: "location") {
                    closeDetail()
                    store.resetCLIPath()
                }
                .onHover { hovering in
                    if hovering {
                        closeDetail()
                    }
                }
            }

            if store.launchAtLoginLoaded {
                MenuActionRowButton(title: "Restart", systemImage: "arrow.clockwise") {
                    closeDetail()
                    NSApplication.shared.terminate(nil)
                }
                .onHover { hovering in
                    if hovering {
                        closeDetail()
                    }
                }
            }

            MenuActionRowButton(title: "Quit", systemImage: "power") {
                closeDetail()
                store.quit()
            }
            .onHover { hovering in
                if hovering {
                    closeDetail()
                }
            }
        }
        .padding(8)
        .frame(width: 360, height: menuHeight, alignment: .top)
    }

    private var activityList: some View {
        List {
            switch selectedActivityTab {
            case .writes:
                if store.recentWrites.isEmpty {
                    EmptyActivityRow(text: "No memory writes yet")
                        .plainMenuListRow()
                } else {
                    ForEach(store.recentWrites.prefix(20)) { write in
                        WriteRow(
                            write: write,
                            activeDetail: activeDetail,
                            activateDetail: activateDetail,
                            deactivateDetail: deactivateDetail
                        )
                        .plainMenuListRow()
                    }
                }
            case .consults:
                if store.recentConsults.isEmpty {
                    EmptyActivityRow(text: "No consult telemetry yet")
                        .plainMenuListRow()
                } else {
                    ForEach(store.recentConsults.prefix(20)) { consult in
                        ConsultRow(
                            consult: consult,
                            activeDetail: activeDetail,
                            activateDetail: activateDetail,
                            deactivateDetail: deactivateDetail
                        )
                        .plainMenuListRow()
                    }
                }
            }
        }
        .environment(\.defaultMinListRowHeight, 1)
        .listStyle(.plain)
        .scrollContentBackground(.hidden)
    }

    private func activateDetail(_ detail: ActivityHoverDetail) {
        detailClearGeneration += 1
        activeDetail = detail
    }

    private func deactivateDetail(_ detail: ActivityHoverDetail) {
        guard activeDetail?.id == detail.id else { return }
        scheduleDetailClose()
    }

    private func setDetailPanelHovered(_ hovering: Bool) {
        isDetailPanelHovered = hovering
        if hovering {
            detailClearGeneration += 1
        } else {
            scheduleDetailClose()
        }
    }

    private func scheduleDetailClose() {
        let generation = detailClearGeneration + 1
        detailClearGeneration = generation
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.28) {
            if detailClearGeneration == generation && !isDetailPanelHovered {
                activeDetail = nil
            }
        }
    }

    private func closeDetail() {
        detailClearGeneration += 1
        isDetailPanelHovered = false
        activeDetail = nil
    }
}

private enum ActivityHoverDetail: Identifiable {
    case write(MemoryWrite)
    case consult(ConsultEvent)
    case instructions

    var id: String {
        switch self {
        case .write(let write):
            return "write-\(write.id)"
        case .consult(let consult):
            return "consult-\(consult.id)"
        case .instructions:
            return "instructions"
        }
    }
}

private enum ActivityTab: String, CaseIterable, Identifiable {
    case writes
    case consults

    var id: String { rawValue }

    var title: String {
        switch self {
        case .writes:
            return "Writes"
        case .consults:
            return "Consults"
        }
    }
}

private extension View {
    func plainMenuListRow() -> some View {
        self
            .listRowInsets(EdgeInsets())
            .listRowSeparator(.hidden)
            .listRowBackground(Color.clear)
    }
}

private struct SectionHeader: View {
    var title: String
    var isLoading = false

    init(_ title: String, isLoading: Bool = false) {
        self.title = title
        self.isLoading = isLoading
    }

    var body: some View {
        HStack(spacing: 6) {
            Text(title)
                .font(.caption.weight(.semibold))
                .foregroundStyle(.secondary)

            Spacer()

            if isLoading {
                ProgressView()
                    .controlSize(.small)
                    .scaleEffect(0.55)
                    .frame(width: 12, height: 12)
            }
        }
        .padding(.horizontal, 8)
        .padding(.top, 1)
    }
}

private struct ActivityTabBar: View {
    let selectedTab: ActivityTab
    let selectTab: (ActivityTab) -> Void

    var body: some View {
        HStack(spacing: 2) {
            ForEach(ActivityTab.allCases) { tab in
                Button {
                    selectTab(tab)
                } label: {
                    Text(tab.title)
                        .font(.caption.weight(.medium))
                        .foregroundStyle(selectedTab == tab ? .primary : .secondary)
                        .frame(maxWidth: .infinity)
                        .padding(.vertical, 5)
                        .contentShape(Rectangle())
                        .background(
                            RoundedRectangle(cornerRadius: 5)
                                .fill(selectedTab == tab ? Color.secondary.opacity(0.16) : Color.clear)
                        )
                }
                .buttonStyle(.plain)
            }
        }
        .frame(maxWidth: .infinity)
        .padding(2)
        .background(
            RoundedRectangle(cornerRadius: 7)
                .fill(Color.secondary.opacity(0.08))
        )
        .padding(.horizontal, 8)
    }
}

private struct OnboardingPrompt: View {
    let isLoading: Bool
    let install: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text("Set Up Autopsy")
                .font(.caption.weight(.semibold))
                .foregroundStyle(.secondary)

            Button(action: install) {
                HStack(spacing: 8) {
                    if isLoading {
                        ProgressView()
                            .controlSize(.small)
                            .scaleEffect(0.7)
                            .frame(width: 14, height: 14)
                    } else {
                        Image(systemName: "wand.and.stars")
                            .font(.system(size: 12, weight: .semibold))
                            .frame(width: 14)
                            .foregroundStyle(.secondary)
                    }

                    Text("Install Agent Instructions")
                        .font(.subheadline)
                    Spacer()
                }
                .padding(.horizontal, 8)
                .padding(.vertical, 6)
                .contentShape(Rectangle())
                .background(
                    RoundedRectangle(cornerRadius: 6)
                        .fill(Color.secondary.opacity(0.1))
                )
            }
            .buttonStyle(.plain)
            .disabled(isLoading)
        }
        .padding(.horizontal, 8)
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
    var activeDetail: ActivityHoverDetail?
    let activateDetail: (ActivityHoverDetail) -> Void
    let deactivateDetail: (ActivityHoverDetail) -> Void
    @State private var isHovered = false

    var body: some View {
        let detail = ActivityHoverDetail.write(write)
        let isActive = activeDetail?.id == detail.id

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
                }
            }

            Image(systemName: "chevron.right")
                .font(.system(size: 9, weight: .semibold))
                .foregroundStyle(.tertiary)
                .frame(width: 8)
                .opacity(isActive || isHovered ? 1 : 0)
        }
        .padding(.horizontal, 8)
        .padding(.vertical, 4)
        .frame(maxWidth: .infinity, alignment: .leading)
        .contentShape(Rectangle())
        .background(
            RoundedRectangle(cornerRadius: 6)
                .fill((isActive || isHovered) ? Color.secondary.opacity(0.14) : Color.clear)
        )
        .onHover { hovering in
            isHovered = hovering
            if hovering {
                activateDetail(detail)
            } else {
                deactivateDetail(detail)
            }
        }
        .onTapGesture {
            activateDetail(detail)
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

private struct ConsultRow: View {
    var consult: ConsultEvent
    var activeDetail: ActivityHoverDetail?
    let activateDetail: (ActivityHoverDetail) -> Void
    let deactivateDetail: (ActivityHoverDetail) -> Void
    @State private var isHovered = false

    var body: some View {
        let detail = ActivityHoverDetail.consult(consult)
        let isActive = activeDetail?.id == detail.id

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
                    Spacer(minLength: 8)
                    Text(relativeLabel(consult.accessedAt))
                        .font(.caption2)
                        .foregroundStyle(.tertiary)
                }
                Text("\(consult.memoryCount ?? 0) memories supplied")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }

            Image(systemName: "chevron.right")
                .font(.system(size: 9, weight: .semibold))
                .foregroundStyle(.tertiary)
                .frame(width: 8)
                .opacity(isActive || isHovered ? 1 : 0)
        }
        .padding(.horizontal, 8)
        .padding(.vertical, 4)
        .frame(maxWidth: .infinity, alignment: .leading)
        .contentShape(Rectangle())
        .background(
            RoundedRectangle(cornerRadius: 6)
                .fill((isActive || isHovered) ? Color.secondary.opacity(0.14) : Color.clear)
        )
        .onHover { hovering in
            isHovered = hovering
            if hovering {
                activateDetail(detail)
            } else {
                deactivateDetail(detail)
            }
        }
        .onTapGesture {
            activateDetail(detail)
        }
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

private struct AgentInstructionsRow: View {
    let targets: [InstructionTarget]
    let isLoading: Bool
    var activeDetail: ActivityHoverDetail?
    let activateDetail: (ActivityHoverDetail) -> Void
    let deactivateDetail: (ActivityHoverDetail) -> Void
    @State private var isHovered = false

    private var isActive: Bool {
        activeDetail?.id == ActivityHoverDetail.instructions.id
    }

    private var statusText: String {
        let installedCount = targets.filter(instructionIsInstalled).count
        if installedCount == 0 {
            return "Not installed"
        }
        return installedCount == 1 ? "1 installed" : "\(installedCount) installed"
    }

    var body: some View {
        HStack(spacing: 8) {
            if isLoading {
                ProgressView()
                    .controlSize(.small)
                    .scaleEffect(0.7)
                    .frame(width: 14, height: 14)
            } else {
                Image(systemName: targets.allSatisfy(instructionIsInstalled) ? "checkmark.seal" : "exclamationmark.circle")
                    .font(.system(size: 12, weight: .semibold))
                    .frame(width: 14)
                    .foregroundStyle(.secondary)
            }

            Text("Agent Instructions")
                .font(.subheadline)
            Spacer()
            Text(statusText)
                .font(.caption)
                .foregroundStyle(.secondary)
            Image(systemName: "chevron.right")
                .font(.system(size: 9, weight: .semibold))
                .foregroundStyle(.tertiary)
                .frame(width: 8)
        }
        .padding(.horizontal, 8)
        .padding(.vertical, 6)
        .contentShape(Rectangle())
        .background(
            RoundedRectangle(cornerRadius: 6)
                .fill((isActive || isHovered) ? Color.secondary.opacity(0.14) : Color.clear)
        )
        .onHover { hovering in
            isHovered = hovering
            if hovering {
                activateDetail(.instructions)
            } else {
                deactivateDetail(.instructions)
            }
        }
        .onTapGesture {
            activateDetail(.instructions)
        }
    }
}

private struct ActivityHoverDetailPanel: View {
    let detail: ActivityHoverDetail
    @ObservedObject var store: ActivityStore

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 10) {
                switch detail {
                case .write(let write):
                    WriteDetailView(write: write)
                case .consult(let consult):
                    ConsultDetailView(consult: consult)
                case .instructions:
                    InstructionsDetailView(store: store)
                }
            }
            .frame(maxWidth: .infinity, alignment: .topLeading)
            .padding(.horizontal, 12)
            .padding(.vertical, 10)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(Color.secondary.opacity(0.04))
    }
}

private struct InstructionsDetailView: View {
    @ObservedObject var store: ActivityStore

    var body: some View {
        VStack(alignment: .leading, spacing: 9) {
            DetailEyebrow("Agent Instructions")
            DetailTitle("Autopsy Setup")

            if let error = nonEmpty(store.instructionStatusError) {
                DetailBody(error)
            }

            VStack(alignment: .leading, spacing: 6) {
                ForEach(store.instructionTargets) { target in
                    InstructionTargetRow(
                        target: target,
                        isLoading: store.isManagingInstructions,
                        install: {
                            if let agent = target.agent {
                                store.installInstructions(agent: agent)
                            }
                        }
                    )
                }
            }

            if !store.instructionTargets.allSatisfy(instructionIsInstalled) {
                Divider()

                Button(action: store.installAllInstructions) {
                    HStack(spacing: 8) {
                        if store.isManagingInstructions {
                            ProgressView()
                                .controlSize(.small)
                                .scaleEffect(0.7)
                                .frame(width: 14, height: 14)
                        } else {
                            Image(systemName: "square.and.arrow.down")
                                .font(.system(size: 12, weight: .semibold))
                                .frame(width: 14)
                                .foregroundStyle(.secondary)
                        }
                        Text("Install All")
                            .font(.subheadline)
                        Spacer()
                    }
                    .padding(.horizontal, 8)
                    .padding(.vertical, 6)
                    .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
                .disabled(store.isManagingInstructions)
            }
        }
    }
}

private struct InstructionTargetRow: View {
    let target: InstructionTarget
    let isLoading: Bool
    let install: () -> Void

    var body: some View {
        HStack(alignment: .top, spacing: 8) {
            Image(systemName: instructionIsInstalled(target) ? "checkmark" : "minus")
                .font(.system(size: 11, weight: .semibold))
                .frame(width: 14)
                .foregroundStyle(.secondary)

            VStack(alignment: .leading, spacing: 2) {
                Text(agentDisplayName(target.agent))
                    .font(.subheadline)
                Text(instructionStatusText(target))
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
                if let path = nonEmpty(target.path) {
                    Text(path)
                        .font(.system(.caption2, design: .monospaced))
                        .foregroundStyle(.tertiary)
                        .lineLimit(1)
                }
            }

            Spacer(minLength: 8)

            if !instructionIsInstalled(target) {
                Button(action: install) {
                    if isLoading {
                        ProgressView()
                            .controlSize(.small)
                            .scaleEffect(0.7)
                            .frame(width: 24, height: 20)
                    } else {
                        Text("Install")
                            .font(.caption.weight(.medium))
                    }
                }
                .buttonStyle(.plain)
                .disabled(isLoading)
            }
        }
        .padding(.horizontal, 8)
        .padding(.vertical, 6)
        .background(
            RoundedRectangle(cornerRadius: 6)
                .fill(Color.secondary.opacity(0.08))
        )
    }
}

private struct WriteDetailView: View {
    let write: MemoryWrite

    var body: some View {
        VStack(alignment: .leading, spacing: 9) {
            DetailEyebrow("Memory Write")
            DetailTitle(write.title ?? "Untitled memory")

            if let summary = nonEmpty(write.summary) {
                ExpandableDetailText(summary, collapsedLineLimit: 8)
            }

            Divider()

            DetailField(label: "Kind", value: write.kind)
            DetailField(label: "Memory Type", value: write.memoryType)
            DetailField(label: "Updated", value: timestampLabel(write.updatedAt) ?? write.updatedAt)
            DetailField(label: "Source", value: write.source)
            DetailField(label: "Repositories", value: joined(write.repositories))
            DetailField(label: "Severity", value: write.severity)
            DetailField(label: "Stable Key", value: write.stableKey, monospaced: true)
        }
    }
}

private struct ConsultDetailView: View {
    let consult: ConsultEvent

    var body: some View {
        VStack(alignment: .leading, spacing: 9) {
            DetailEyebrow("Consult")
            DetailTitle(queryLabel)

            Divider()

            DetailField(label: "Accessed", value: timestampLabel(consult.accessedAt) ?? consult.accessedAt)
            DetailField(label: "Source", value: consult.source)
            DetailField(label: "Memories", value: "\(consult.memoryCount ?? consult.memories?.count ?? 0) supplied")
            DetailField(label: "Severity", value: consult.severity)

            if let memories = consult.memories, !memories.isEmpty {
                Divider()

                Text("Supplied Memories")
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(.secondary)

                VStack(alignment: .leading, spacing: 6) {
                    ForEach(memories.prefix(5)) { memory in
                        ConsultMemoryDetailRow(memory: memory)
                    }
                }
            }
        }
    }

    private var queryLabel: String {
        guard let query = consult.query, !query.isEmpty else {
            return consult.source ?? "Consult"
        }
        return query
    }
}

private struct ConsultMemoryDetailRow: View {
    let memory: ConsultMemory

    var body: some View {
        VStack(alignment: .leading, spacing: 2) {
            HStack(spacing: 6) {
                if let kind = nonEmpty(memory.kind) {
                    Text(kind)
                        .font(.caption2.weight(.medium))
                        .foregroundStyle(.secondary)
                }
                if let accessCount = memory.accessCount {
                    Text("\(accessCount) reads")
                        .font(.caption2)
                        .foregroundStyle(.tertiary)
                }
            }

            Text(memory.title ?? memory.stableKey ?? "Memory")
                .font(.caption)
                .lineLimit(2)

            if let summary = nonEmpty(memory.summary) {
                ExpandableDetailText(summary, collapsedLineLimit: 4, font: .caption2)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(.horizontal, 8)
        .padding(.vertical, 6)
        .background(
            RoundedRectangle(cornerRadius: 6)
                .fill(Color.secondary.opacity(0.08))
        )
    }
}

private struct DetailEyebrow: View {
    let text: String

    init(_ text: String) {
        self.text = text
    }

    var body: some View {
        Text(text.uppercased())
            .font(.caption2.weight(.semibold))
            .foregroundStyle(.tertiary)
    }
}

private struct DetailTitle: View {
    let text: String

    init(_ text: String) {
        self.text = text
    }

    var body: some View {
        Text(text)
            .font(.system(size: 13, weight: .semibold))
            .foregroundStyle(.primary)
            .fixedSize(horizontal: false, vertical: true)
            .textSelection(.enabled)
    }
}

private struct DetailBody: View {
    let text: String

    init(_ text: String) {
        self.text = text
    }

    var body: some View {
        Text(text)
            .font(.caption)
            .foregroundStyle(.secondary)
            .lineLimit(8)
            .fixedSize(horizontal: false, vertical: true)
            .textSelection(.enabled)
    }
}

private struct ExpandableDetailText: View {
    let text: String
    var collapsedLineLimit: Int
    var font: Font
    @State private var isExpanded = false

    init(_ text: String, collapsedLineLimit: Int = 8, font: Font = .caption) {
        self.text = text
        self.collapsedLineLimit = collapsedLineLimit
        self.font = font
    }

    private var needsToggle: Bool {
        let roughCollapsedCharacterLimit = max(90, collapsedLineLimit * 30)
        return text.count > roughCollapsedCharacterLimit || text.filter(\.isNewline).count >= collapsedLineLimit
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(text)
                .font(font)
                .foregroundStyle(.secondary)
                .lineLimit(isExpanded ? nil : collapsedLineLimit)
                .fixedSize(horizontal: false, vertical: true)
                .textSelection(.enabled)

            if needsToggle {
                Button(isExpanded ? "Show Less" : "Show More") {
                    isExpanded.toggle()
                }
                .font(.caption2.weight(.medium))
                .buttonStyle(.plain)
            }
        }
    }
}

private struct DetailField: View {
    let label: String
    let value: String?
    var monospaced = false

    var body: some View {
        if let value = nonEmpty(value) {
            VStack(alignment: .leading, spacing: 1) {
                Text(label)
                    .font(.caption2.weight(.medium))
                    .foregroundStyle(.tertiary)
                Text(value)
                    .font(monospaced ? .system(.caption, design: .monospaced) : .caption)
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
                    .textSelection(.enabled)
            }
        }
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

private func relativeLabel(_ value: String?) -> String {
    guard let value, !value.isEmpty else { return "" }
    guard let date = isoDate(value) else { return "" }
    return date.formatted(.relative(presentation: .numeric, unitsStyle: .abbreviated))
}

private func timestampLabel(_ value: String?) -> String? {
    guard let value = nonEmpty(value), let date = isoDate(value) else { return nil }
    return date.formatted(date: .abbreviated, time: .shortened)
}

private func isoDate(_ value: String) -> Date? {
    let formatter = ISO8601DateFormatter()
    formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
    return formatter.date(from: value) ?? ISO8601DateFormatter().date(from: value)
}

private func compactLabel(_ value: String?, fallback: String, limit: Int = 30) -> String {
    guard let value, !value.isEmpty else { return fallback }
    return value.clippedForMenuBar(limit: limit)
}

private func nonEmpty(_ value: String?) -> String? {
    guard let value else { return nil }
    let trimmed = value.trimmingCharacters(in: .whitespacesAndNewlines)
    return trimmed.isEmpty ? nil : trimmed
}

private func joined(_ values: [String]?) -> String? {
    guard let values else { return nil }
    let nonEmptyValues = values.compactMap(nonEmpty)
    return nonEmptyValues.isEmpty ? nil : nonEmptyValues.joined(separator: ", ")
}

private func agentDisplayName(_ agent: String?) -> String {
    switch agent {
    case "codex":
        return "Codex"
    case "claude":
        return "Claude Code"
    case "gemini":
        return "Gemini CLI"
    case "opencode":
        return "OpenCode"
    case "cursor":
        return "Cursor"
    case "copilot":
        return "GitHub Copilot"
    case "windsurf":
        return "Windsurf"
    default:
        return agent ?? "Agent"
    }
}

private func instructionIsInstalled(_ target: InstructionTarget) -> Bool {
    target.state == "managed"
}

private func instructionStatusText(_ target: InstructionTarget) -> String {
    if instructionIsInstalled(target) {
        return "Installed"
    }
    if let state = nonEmpty(target.state), state != "missing" {
        return state.capitalized
    }
    return "Not installed"
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
