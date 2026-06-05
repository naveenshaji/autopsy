import AppKit
import SwiftUI

struct ActivityPopover: View {
    @ObservedObject var store: ActivityStore
    @State private var activeDetail: ActivityHoverDetail?
    @State private var detailClearGeneration = 0
    @State private var isDetailPanelHovered = false
    @State private var selectedActivityTab: ActivityTab = .writes
    @State private var userSelectedActivityTab = false

    private let menuHeight: CGFloat = 500
    private let menuWidth: CGFloat = 360
    private let detailWidth: CGFloat = 310
    private let compactDetailThreshold: CGFloat = 760

    var body: some View {
        Group {
            if usesCompactDetailLayout {
                compactBody
            } else {
                sideBySideBody
            }
        }
        .onAppear {
            handlePopoverAppear()
        }
        .onChange(of: activitySignature) { _ in
            selectDefaultActivityIfNeeded()
        }
    }

    private var usesCompactDetailLayout: Bool {
        let screenWidth = NSScreen.main?.visibleFrame.width ?? compactDetailThreshold
        return screenWidth < compactDetailThreshold
    }

    private var sideBySideBody: some View {
        HStack(alignment: .top, spacing: 0) {
            menuContent(hoverDetailsEnabled: true)
                .frame(width: menuWidth)
                .frame(height: menuHeight)

            if let activeDetail {
                Divider()
                    .frame(height: menuHeight)

                ActivityHoverDetailPanel(detail: activeDetail, store: store)
                    .frame(width: detailWidth, height: menuHeight, alignment: .topLeading)
                    .onHover { hovering in
                        setDetailPanelHovered(hovering)
                    }
            } else {
                Color.clear
                    .frame(width: detailWidth + 1, height: menuHeight)
            }
        }
        .frame(width: menuWidth + detailWidth + 1, height: menuHeight, alignment: .leading)
        .animation(.easeInOut(duration: 0.12), value: activeDetail?.id)
    }

    private var compactBody: some View {
        ZStack(alignment: .topLeading) {
            menuContent(hoverDetailsEnabled: false)
                .frame(width: menuWidth, height: menuHeight)

            if let activeDetail {
                CompactActivityDetailPanel(detail: activeDetail, store: store, close: closeDetail)
                    .frame(width: menuWidth, height: menuHeight)
                    .transition(.opacity)
            }
        }
        .frame(width: menuWidth, height: menuHeight, alignment: .topLeading)
        .animation(.easeInOut(duration: 0.12), value: activeDetail?.id)
    }

    private func menuContent(hoverDetailsEnabled: Bool) -> some View {
        VStack(spacing: 6) {
            if store.shouldShowOnboardingPrompt {
                OnboardingPrompt(
                    title: store.onboardingTitle,
                    message: store.onboardingMessage,
                    isLoading: store.isRepairingSetup || store.isManagingInstructions,
                    install: store.repairSetup
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
                writesCount: store.recentWrites.count,
                consultsCount: store.recentConsults.count,
                selectTab: { tab in
                    userSelectedActivityTab = true
                    selectedActivityTab = tab
                    selectFirstDetail(for: tab)
                }
            )

            activityList(hoverDetailsEnabled: hoverDetailsEnabled)
                .frame(maxWidth: .infinity, maxHeight: .infinity)

            Divider()

            AgentInstructionsRow(
                targets: store.instructionTargets,
                isLoading: store.instructionStatus == nil || store.isManagingInstructions,
                activeDetail: activeDetail,
                hoverDetailsEnabled: hoverDetailsEnabled,
                activateDetail: activateDetail,
                deactivateDetail: deactivateDetail
            )

            MenuStatusActionRowButton(
                title: store.softwareUpdateTitle,
                detail: store.softwareUpdateStatusText,
                systemImage: store.softwareUpdateSystemImage,
                isLoading: store.isCheckingForSoftwareUpdates || store.isUpdatingAutopsy,
                isDisabled: store.isUpdatingAutopsy
            ) {
                if store.softwareUpdateStatus?.updateAvailable == true {
                    store.updateAutopsy()
                } else {
                    store.checkForSoftwareUpdates()
                }
            }

            if store.cliPath != store.detectedCLIPath {
                MenuActionRowButton(title: "Use Detected Command", systemImage: "location") {
                    store.resetCLIPath()
                }
            }

            MenuActionRowButton(title: "Quit", systemImage: "power") {
                store.quit()
            }
        }
        .padding(8)
        .frame(width: menuWidth, height: menuHeight, alignment: .top)
    }

    private func activityList(hoverDetailsEnabled: Bool) -> some View {
        List {
            switch selectedActivityTab {
            case .writes:
                if store.recentWrites.isEmpty {
                    EmptyActivityRow(text: store.emptyWritesText)
                        .plainMenuListRow()
                } else {
                    ForEach(store.recentWrites.prefix(20)) { write in
                        WriteRow(
                            write: write,
                            activeDetail: activeDetail,
                            hoverDetailsEnabled: hoverDetailsEnabled,
                            activateDetail: activateDetail,
                            deactivateDetail: deactivateDetail
                        )
                        .plainMenuListRow()
                    }
                }
            case .consults:
                if store.recentConsults.isEmpty {
                    EmptyActivityRow(text: store.emptyConsultsText)
                        .plainMenuListRow()
                } else {
                    ForEach(store.recentConsults.prefix(20)) { consult in
                        ConsultRow(
                            consult: consult,
                            activeDetail: activeDetail,
                            hoverDetailsEnabled: hoverDetailsEnabled,
                            activateDetail: activateDetail,
                            deactivateDetail: deactivateDetail
                        )
                        .plainMenuListRow()
                    }
                }
            }
        }
        .environment(\.defaultMinListRowHeight, 18)
        .listStyle(.plain)
        .scrollContentBackground(.hidden)
    }

    private func activateDetail(_ detail: ActivityHoverDetail) {
        detailClearGeneration += 1
        activeDetail = detail
    }

    private var activitySignature: String {
        [
            store.recentWrites.first?.updatedAt ?? "",
            store.recentConsults.first?.accessedAt ?? "",
            "\(store.recentWrites.count)",
            "\(store.recentConsults.count)",
        ].joined(separator: "|")
    }

    private func handlePopoverAppear() {
        userSelectedActivityTab = false
        store.refresh(includeLaunchAgent: false)
        selectDefaultActivityIfNeeded(force: true)
    }

    private func selectDefaultActivityIfNeeded(force: Bool = false) {
        guard !userSelectedActivityTab else { return }

        if let write = store.recentWrites.first {
            selectedActivityTab = .writes
            setDefaultDetail(.write(write), force: force)
            return
        }

        if let consult = store.recentConsults.first {
            selectedActivityTab = .consults
            setDefaultDetail(.consult(consult), force: force)
            return
        }

        activeDetail = nil
    }

    private func selectFirstDetail(for tab: ActivityTab) {
        guard !usesCompactDetailLayout else {
            activeDetail = nil
            return
        }

        switch tab {
        case .writes:
            if let write = store.recentWrites.first {
                activateDetail(.write(write))
            } else {
                activeDetail = nil
            }
        case .consults:
            if let consult = store.recentConsults.first {
                activateDetail(.consult(consult))
            } else {
                activeDetail = nil
            }
        }
    }

    private func setDefaultDetail(_ detail: ActivityHoverDetail, force: Bool) {
        guard !usesCompactDetailLayout else {
            activeDetail = nil
            return
        }
        guard force || activeDetail?.id != detail.id else { return }
        activateDetail(detail)
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
                restoreFallbackDetail()
            }
        }
    }

    private func closeDetail() {
        detailClearGeneration += 1
        isDetailPanelHovered = false
        activeDetail = nil
    }

    private func restoreFallbackDetail() {
        if usesCompactDetailLayout {
            activeDetail = nil
            return
        }
        if userSelectedActivityTab {
            selectFirstDetail(for: selectedActivityTab)
        } else {
            selectDefaultActivityIfNeeded(force: true)
        }
    }
}

private enum ActivityHoverDetail: Identifiable {
    case write(MemoryWrite)
    case consult(ConsultEvent)
    case setupHealth
    case instructions

    var id: String {
        switch self {
        case .write(let write):
            return "write-\(write.id)"
        case .consult(let consult):
            return "consult-\(consult.id)"
        case .setupHealth:
            return "setup-health"
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
    let writesCount: Int
    let consultsCount: Int
    let selectTab: (ActivityTab) -> Void

    var body: some View {
        HStack(spacing: 2) {
            ForEach(ActivityTab.allCases) { tab in
                Button {
                    selectTab(tab)
                } label: {
                    HStack(spacing: 5) {
                        Text(tab.title)
                        Text("\(count(for: tab))")
                            .font(.caption2.weight(.semibold))
                            .foregroundStyle(.tertiary)
                    }
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

    private func count(for tab: ActivityTab) -> Int {
        switch tab {
        case .writes:
            return writesCount
        case .consults:
            return consultsCount
        }
    }
}

private struct OnboardingPrompt: View {
    let title: String
    let message: String
    let isLoading: Bool
    let install: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 7) {
            Text(title)
                .font(.caption.weight(.semibold))
                .foregroundStyle(.secondary)

            Text(message)
                .font(.caption)
                .foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)

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

                    Text("Run Setup")
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
        .padding(.vertical, 2)
    }
}

private struct EmptyActivityRow: View {
    var text: String

    var body: some View {
        Text(text)
            .font(.footnote)
            .foregroundStyle(.secondary)
            .fixedSize(horizontal: false, vertical: true)
            .padding(.horizontal, 8)
            .padding(.vertical, 8)
    }
}

private struct WriteRow: View {
    var write: MemoryWrite
    var activeDetail: ActivityHoverDetail?
    var hoverDetailsEnabled: Bool
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
        }
        .padding(.trailing, 16)
        .padding(.horizontal, 8)
        .padding(.vertical, 4)
        .frame(maxWidth: .infinity, alignment: .leading)
        .contentShape(Rectangle())
        .background(
            RoundedRectangle(cornerRadius: 6)
                .fill((isActive || isHovered) ? Color.secondary.opacity(0.14) : Color.clear)
        )
        .overlay(alignment: .trailing) {
            Image(systemName: "chevron.right")
                .font(.system(size: 9, weight: .semibold))
                .foregroundStyle(.tertiary)
                .frame(width: 8)
                .padding(.trailing, 8)
                .opacity(isActive || isHovered ? 1 : 0)
        }
        .onHover { hovering in
            isHovered = hovering
            guard hoverDetailsEnabled else { return }
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
    var hoverDetailsEnabled: Bool
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
        }
        .padding(.trailing, 16)
        .padding(.horizontal, 8)
        .padding(.vertical, 4)
        .frame(maxWidth: .infinity, alignment: .leading)
        .contentShape(Rectangle())
        .background(
            RoundedRectangle(cornerRadius: 6)
                .fill((isActive || isHovered) ? Color.secondary.opacity(0.14) : Color.clear)
        )
        .overlay(alignment: .trailing) {
            Image(systemName: "chevron.right")
                .font(.system(size: 9, weight: .semibold))
                .foregroundStyle(.tertiary)
                .frame(width: 8)
                .padding(.trailing, 8)
                .opacity(isActive || isHovered ? 1 : 0)
        }
        .onHover { hovering in
            isHovered = hovering
            guard hoverDetailsEnabled else { return }
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

private struct SetupHealthRow: View {
    let issues: [SetupHealthIssue]
    let statusText: String
    let isLoading: Bool
    var activeDetail: ActivityHoverDetail?
    var hoverDetailsEnabled: Bool
    let activateDetail: (ActivityHoverDetail) -> Void
    let deactivateDetail: (ActivityHoverDetail) -> Void
    @State private var isHovered = false

    private var isActive: Bool {
        activeDetail?.id == ActivityHoverDetail.setupHealth.id
    }

    var body: some View {
        let detail = ActivityHoverDetail.setupHealth

        HStack(spacing: 8) {
            if isLoading {
                ProgressView()
                    .controlSize(.small)
                    .scaleEffect(0.7)
                    .frame(width: 14, height: 14)
            } else {
                Image(systemName: issues.first?.systemImage ?? "exclamationmark.triangle")
                    .font(.system(size: 12, weight: .semibold))
                    .frame(width: 14)
                    .foregroundStyle(.orange)
            }

            Text(isLoading ? "Repairing Setup" : "Setup Needs Attention")
                .font(.subheadline)
            Spacer(minLength: 8)
            Text(statusText)
                .font(.caption)
                .foregroundStyle(.secondary)
                .lineLimit(1)
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
            guard hoverDetailsEnabled else { return }
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
}

private struct AgentInstructionsRow: View {
    let targets: [InstructionTarget]
    let isLoading: Bool
    var activeDetail: ActivityHoverDetail?
    var hoverDetailsEnabled: Bool
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
            guard hoverDetailsEnabled else { return }
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

private struct CompactActivityDetailPanel: View {
    let detail: ActivityHoverDetail
    @ObservedObject var store: ActivityStore
    let close: () -> Void

    var body: some View {
        VStack(spacing: 0) {
            HStack {
                Button(action: close) {
                    Image(systemName: "chevron.left")
                        .font(.system(size: 12, weight: .semibold))
                        .frame(width: 24, height: 22)
                        .contentShape(Rectangle())
                }
                .buttonStyle(.plain)

                Spacer()
            }
            .padding(.horizontal, 8)
            .padding(.vertical, 6)

            Divider()

            ActivityHoverDetailPanel(detail: detail, store: store)
        }
        .background(Color(nsColor: .windowBackgroundColor))
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
                case .setupHealth:
                    SetupHealthDetailView(store: store)
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

private struct SetupHealthDetailView: View {
    @ObservedObject var store: ActivityStore

    var body: some View {
        VStack(alignment: .leading, spacing: 9) {
            DetailEyebrow("Setup")
            DetailTitle(store.isRepairingSetup ? "Repairing Autopsy" : "Setup Needs Attention")

            if store.setupHealthIssues.isEmpty {
                DetailBody(store.isRepairingSetup ? "Autopsy is repairing the command, agent instructions, and menu bar startup." : "Setup looks ready.")
            } else {
                VStack(alignment: .leading, spacing: 6) {
                    ForEach(store.setupHealthIssues) { issue in
                        SetupIssueRow(issue: issue)
                    }
                }
            }

            Button(action: store.repairSetup) {
                HStack(spacing: 8) {
                    if store.isRepairingSetup {
                        ProgressView()
                            .controlSize(.small)
                            .scaleEffect(0.7)
                            .frame(width: 14, height: 14)
                    } else {
                        Image(systemName: "wrench.and.screwdriver")
                            .font(.system(size: 12, weight: .semibold))
                            .frame(width: 14)
                            .foregroundStyle(.secondary)
                    }
                    Text(store.isRepairingSetup ? "Repairing" : "Repair Setup")
                        .font(.subheadline)
                    Spacer()
                }
                .padding(.horizontal, 8)
                .padding(.vertical, 6)
                .contentShape(Rectangle())
                .background(
                    RoundedRectangle(cornerRadius: 6)
                        .fill(Color.secondary.opacity(0.08))
                )
            }
            .buttonStyle(.plain)
            .disabled(store.isRepairingSetup)

            if store.lastActionMessage == "Setup repaired" {
                DetailBody("Setup repaired.")
            }
        }
    }
}

private struct SetupIssueRow: View {
    let issue: SetupHealthIssue

    var body: some View {
        HStack(alignment: .top, spacing: 8) {
            Image(systemName: issue.systemImage)
                .font(.system(size: 11, weight: .semibold))
                .frame(width: 14)
                .foregroundStyle(.secondary)

            VStack(alignment: .leading, spacing: 2) {
                Text(issue.title)
                    .font(.subheadline)
                Text(issue.detail)
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
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

private struct InstructionsDetailView: View {
    @ObservedObject var store: ActivityStore

    var body: some View {
        VStack(alignment: .leading, spacing: 9) {
            DetailEyebrow("Agent Instructions")
            DetailTitle("Autopsy Setup")

            DetailBody("Manual setup: copy these instructions and paste them into your agent's global instructions file.\nUse the install buttons below when Autopsy can manage the file automatically.")

            Button(action: store.copyInstructions) {
                HStack(spacing: 8) {
                    if store.isCopyingInstructions {
                        ProgressView()
                            .controlSize(.small)
                            .scaleEffect(0.7)
                            .frame(width: 14, height: 14)
                    } else {
                        Image(systemName: "doc.on.doc")
                            .font(.system(size: 12, weight: .semibold))
                            .frame(width: 14)
                            .foregroundStyle(.secondary)
                    }
                    Text("Copy Instructions")
                        .font(.subheadline)
                    Spacer()
                }
                .padding(.horizontal, 8)
                .padding(.vertical, 6)
                .contentShape(Rectangle())
                .background(
                    RoundedRectangle(cornerRadius: 6)
                        .fill(Color.secondary.opacity(0.08))
                )
            }
            .buttonStyle(.plain)
            .disabled(store.isCopyingInstructions)

            if store.lastActionMessage == "Instructions copied" {
                DetailBody("Copied to clipboard.")
            }

            if store.instructionStatusError != nil {
                DetailBody("Instruction status could not be refreshed.")
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

private struct MenuStatusActionRowButton: View {
    let title: String
    let detail: String
    let systemImage: String
    var isLoading = false
    var isDisabled = false
    let action: () -> Void
    @State private var isHovered = false

    var body: some View {
        Button(action: action) {
            HStack(spacing: 8) {
                if isLoading {
                    ProgressView()
                        .controlSize(.small)
                        .scaleEffect(0.7)
                        .frame(width: 14, height: 14)
                } else {
                    Image(systemName: systemImage)
                        .font(.system(size: 12, weight: .semibold))
                        .frame(width: 14)
                        .foregroundStyle(isDisabled ? .tertiary : .secondary)
                }

                Text(title)
                    .font(.subheadline)
                    .foregroundStyle(isDisabled ? .secondary : .primary)
                    .lineLimit(1)

                Spacer(minLength: 8)

                Text(detail)
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
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
        .help("\(title): \(detail)")
        .onHover { hovering in
            isHovered = hovering
        }
    }
}

private func relativeLabel(_ value: String?) -> String {
    guard let value, !value.isEmpty else { return "" }
    guard let date = isoDate(value) else { return "" }
    return compactRelativeLabel(since: date)
}

private func timestampLabel(_ value: String?) -> String? {
    relativeLabel(value)
}

private func compactRelativeLabel(since date: Date, now: Date = Date()) -> String {
    let elapsedSeconds = max(0, Int(now.timeIntervalSince(date)))
    if elapsedSeconds < 60 {
        return "\(max(1, elapsedSeconds))s"
    }

    let minutes = elapsedSeconds / 60
    if minutes < 60 {
        return "\(minutes)m"
    }

    let hours = elapsedSeconds / 3_600
    if hours < 24 {
        return "\(hours)h"
    }

    let days = elapsedSeconds / 86_400
    if days < 7 {
        return "\(days)d"
    }
    if days < 21 {
        return "\(max(1, days / 7))wk"
    }
    if days < 30 {
        return "\(days)d"
    }

    let months = days / 30
    if months < 12 {
        return "\(max(1, months))mo"
    }

    return "\(max(1, days / 365))y"
}

private func isoDate(_ value: String) -> Date? {
    let formatter = ISO8601DateFormatter()
    formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
    return formatter.date(from: value) ?? ISO8601DateFormatter().date(from: value)
}

private func compactLabel(_ value: String?, fallback: String, limit: Int = 72) -> String {
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
