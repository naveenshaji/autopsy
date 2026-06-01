import Foundation

struct AutopsyCLI {
    var executable: String

    func run(_ arguments: [String]) async throws -> String {
        try await Task.detached(priority: .utility) {
            let process = Process()
            let outputPipe = Pipe()
            let errorPipe = Pipe()

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
            process.environment = environment
            process.standardOutput = outputPipe
            process.standardError = errorPipe

            try process.run()
            process.waitUntilExit()

            let output = outputPipe.fileHandleForReading.readDataToEndOfFile()
            let error = errorPipe.fileHandleForReading.readDataToEndOfFile()
            let outputText = String(data: output, encoding: .utf8) ?? ""
            let errorText = String(data: error, encoding: .utf8) ?? ""

            guard process.terminationStatus == 0 else {
                let message = errorText.trimmingCharacters(in: .whitespacesAndNewlines)
                throw CLIError.failed(message.isEmpty ? "autopsy exited with \(process.terminationStatus)" : message)
            }
            return outputText
        }.value
    }
}

enum CLIError: LocalizedError {
    case failed(String)

    var errorDescription: String? {
        switch self {
        case .failed(let message):
            return message
        }
    }
}
