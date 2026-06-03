import Foundation

struct SoftwareUpdateStatus {
    var installedVersion: String?
    var latestVersion: String?
    var isInstalledWithHomebrew: Bool
    var updateAvailable: Bool
    var message: String
}

struct AutopsyUpdater {
    private let formulaName = "autopsy-memory"

    func checkStatus(refreshTaps: Bool = false) async throws -> SoftwareUpdateStatus {
        if refreshTaps {
            _ = try await runBrew(["update"], timeoutSeconds: 180, disableAutoUpdate: false)
        }
        let output = try await runBrew(["info", "--json=v2", formulaName], timeoutSeconds: 45, disableAutoUpdate: true)
        let payload = try JSONDecoder().decode(BrewInfoPayload.self, from: Data(output.utf8))
        guard let formula = payload.formulae.first else {
            return SoftwareUpdateStatus(
                installedVersion: nil,
                latestVersion: nil,
                isInstalledWithHomebrew: false,
                updateAvailable: false,
                message: "Homebrew install not found"
            )
        }

        let installedVersion = formula.linkedKeg ?? formula.installed.last?.version
        let latestVersion = formula.versions.stable
        let updateAvailable = formula.outdated == true
        let message: String
        if installedVersion == nil {
            message = "Homebrew install not found"
        } else if updateAvailable, let latestVersion {
            message = "Update \(latestVersion) available"
        } else {
            message = "Up to date"
        }

        return SoftwareUpdateStatus(
            installedVersion: installedVersion,
            latestVersion: latestVersion,
            isInstalledWithHomebrew: installedVersion != nil,
            updateAvailable: updateAvailable,
            message: message
        )
    }

    func update() async throws {
        _ = try await runBrew(["update"], timeoutSeconds: 180, disableAutoUpdate: false)
        _ = try await runBrew(["upgrade", formulaName], timeoutSeconds: 900, disableAutoUpdate: true)
    }

    private func runBrew(_ arguments: [String], timeoutSeconds: TimeInterval, disableAutoUpdate: Bool) async throws -> String {
        try await Task.detached(priority: .utility) {
            let process = Process()
            let outputPipe = Pipe()
            let errorPipe = Pipe()
            let timedOut = UpdateLockedFlag()

            process.executableURL = URL(fileURLWithPath: "/usr/bin/env")
            process.arguments = ["brew"] + arguments

            var environment = ProcessInfo.processInfo.environment
            let fallbackPath = "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
            if let existingPath = environment["PATH"], !existingPath.isEmpty {
                environment["PATH"] = "\(existingPath):\(fallbackPath)"
            } else {
                environment["PATH"] = fallbackPath
            }
            environment["HOMEBREW_NO_ENV_HINTS"] = "1"
            if disableAutoUpdate {
                environment["HOMEBREW_NO_AUTO_UPDATE"] = "1"
            }
            process.environment = environment
            process.standardOutput = outputPipe
            process.standardError = errorPipe

            try process.run()
            DispatchQueue.global(qos: .utility).asyncAfter(deadline: .now() + timeoutSeconds) {
                if process.isRunning {
                    timedOut.set()
                    process.terminate()
                }
            }
            process.waitUntilExit()

            let outputData = outputPipe.fileHandleForReading.readDataToEndOfFile()
            let errorData = errorPipe.fileHandleForReading.readDataToEndOfFile()
            let output = String(data: outputData, encoding: .utf8) ?? ""
            let error = String(data: errorData, encoding: .utf8) ?? ""

            if timedOut.value {
                throw CLIError.timedOut(Int(timeoutSeconds))
            }
            guard process.terminationStatus == 0 else {
                let message = error.trimmingCharacters(in: .whitespacesAndNewlines)
                throw CLIError.failed(message.isEmpty ? "brew exited with \(process.terminationStatus)" : message)
            }
            return output
        }.value
    }
}

private struct BrewInfoPayload: Decodable {
    var formulae: [BrewFormula]
}

private struct BrewFormula: Decodable {
    var versions: BrewVersions
    var installed: [BrewInstalled]
    var linkedKeg: String?
    var outdated: Bool?

    enum CodingKeys: String, CodingKey {
        case versions
        case installed
        case linkedKeg = "linked_keg"
        case outdated
    }
}

private struct BrewVersions: Decodable {
    var stable: String?
}

private struct BrewInstalled: Decodable {
    var version: String?
}

private final class UpdateLockedFlag: @unchecked Sendable {
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
