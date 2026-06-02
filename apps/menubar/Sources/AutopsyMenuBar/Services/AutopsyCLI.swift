import Foundation

struct AutopsyCLI {
    var executable: String
    var timeoutSeconds: TimeInterval = 20

    func run(_ arguments: [String]) async throws -> String {
        try await Task.detached(priority: .utility) {
            let process = Process()
            let outputPipe = Pipe()
            let errorPipe = Pipe()
            let timedOut = LockedFlag()

            let executable = executable.trimmingCharacters(in: .whitespacesAndNewlines)
            if executable.contains("/") {
                process.executableURL = URL(fileURLWithPath: executable)
                process.arguments = arguments
            } else {
                process.executableURL = URL(fileURLWithPath: "/usr/bin/env")
                process.arguments = [executable.isEmpty ? "autopsy" : executable] + arguments
            }

            var environment = ProcessInfo.processInfo.environment
            let fallbackPath = "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
            if let existingPath = environment["PATH"], !existingPath.isEmpty {
                environment["PATH"] = "\(existingPath):\(fallbackPath)"
            } else {
                environment["PATH"] = fallbackPath
            }
            if environment["AUTOPSY_UNIFIED_MEMORY"] == nil {
                environment["AUTOPSY_UNIFIED_MEMORY"] = "1"
            }
            if environment["AUTOPSY_FALKORDB_MODULE_PATH"] == nil,
               let modulePath = inferredHomebrewNativeModulePath(for: executable),
               FileManager.default.isExecutableFile(atPath: modulePath) {
                environment["AUTOPSY_FALKORDB_MODULE_PATH"] = modulePath
            }
            process.environment = environment
            process.standardOutput = outputPipe
            process.standardError = errorPipe

            try process.run()
            if timeoutSeconds > 0 {
                DispatchQueue.global(qos: .utility).asyncAfter(deadline: .now() + timeoutSeconds) {
                    if process.isRunning {
                        timedOut.set()
                        process.terminate()
                    }
                }
            }
            process.waitUntilExit()

            let output = outputPipe.fileHandleForReading.readDataToEndOfFile()
            let error = errorPipe.fileHandleForReading.readDataToEndOfFile()
            let outputText = String(data: output, encoding: .utf8) ?? ""
            let errorText = String(data: error, encoding: .utf8) ?? ""

            if timedOut.value {
                throw CLIError.timedOut(Int(timeoutSeconds))
            }
            guard process.terminationStatus == 0 else {
                let message = errorText.trimmingCharacters(in: .whitespacesAndNewlines)
                throw CLIError.failed(message.isEmpty ? "autopsy exited with \(process.terminationStatus)" : message)
            }
            return outputText
        }.value
    }
}

private func inferredHomebrewNativeModulePath(for executable: String) -> String? {
    let parts = executable.split(separator: "/", omittingEmptySubsequences: false).map(String.init)
    guard let cellarIndex = parts.firstIndex(of: "Cellar"),
          cellarIndex + 5 < parts.count,
          parts[cellarIndex + 1] == "autopsy-memory",
          parts[cellarIndex + 3] == "libexec",
          parts[cellarIndex + 4] == "bin",
          parts[cellarIndex + 5] == "autopsy"
    else {
        return nil
    }
    let cellarRoot = parts[...(cellarIndex + 2)].joined(separator: "/")
    let normalizedRoot = cellarRoot.isEmpty ? "/" : cellarRoot
    return "\(normalizedRoot)/libexec/share/autopsy/falkordb.so"
}

enum CLIError: LocalizedError {
    case failed(String)
    case timedOut(Int)

    var errorDescription: String? {
        switch self {
        case .failed(let message):
            return message
        case .timedOut(let seconds):
            return "autopsy did not respond within \(seconds)s"
        }
    }
}

private final class LockedFlag: @unchecked Sendable {
    private let lock = NSLock()
    private var storage = false

    var value: Bool {
        lock.lock()
        defer { lock.unlock() }
        return storage
    }

    func set() {
        lock.lock()
        storage = true
        lock.unlock()
    }
}
