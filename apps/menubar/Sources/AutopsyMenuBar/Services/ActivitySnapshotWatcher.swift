import Darwin
import Foundation

final class ActivitySnapshotWatcher {
    private let url: URL
    private let onChange: @MainActor () -> Void
    private let queue = DispatchQueue(label: "com.naveenshaji.autopsy.activity-snapshot-watcher")
    private var source: DispatchSourceFileSystemObject?
    private var pendingWorkItem: DispatchWorkItem?

    init(url: URL, onChange: @escaping @MainActor () -> Void) {
        self.url = url
        self.onChange = onChange
    }

    deinit {
        stop()
    }

    func start() {
        stop()

        let directoryURL = url.deletingLastPathComponent()
        try? FileManager.default.createDirectory(at: directoryURL, withIntermediateDirectories: true)

        let fileDescriptor = open(directoryURL.path, O_EVTONLY)
        guard fileDescriptor >= 0 else { return }

        let source = DispatchSource.makeFileSystemObjectSource(
            fileDescriptor: fileDescriptor,
            eventMask: [.write, .rename, .delete, .extend, .attrib],
            queue: queue
        )
        source.setEventHandler { [weak self] in
            self?.scheduleChange()
        }
        source.setCancelHandler {
            close(fileDescriptor)
        }
        source.resume()
        self.source = source
    }

    func stop() {
        pendingWorkItem?.cancel()
        pendingWorkItem = nil
        source?.cancel()
        source = nil
    }

    private func scheduleChange() {
        pendingWorkItem?.cancel()
        let workItem = DispatchWorkItem { [weak self] in
            Task { @MainActor in
                self?.onChange()
            }
        }
        pendingWorkItem = workItem
        queue.asyncAfter(deadline: .now() + 0.08, execute: workItem)
    }
}
