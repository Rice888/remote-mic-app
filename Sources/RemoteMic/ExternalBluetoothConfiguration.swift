import Foundation

/// Local machine paths and bonding identity are deliberately separate from portable mappings.
struct ExternalBluetoothConfiguration: Codable, Equatable {
    enum Mode: String, Codable, CaseIterable { case system, ub500 }
    var mode: Mode = .system
    var directory: String = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)
        .first!.appendingPathComponent("SayAll/ExternalBluetooth").path
    var remoteAddress: String = ""
    var identity: UUID = UUID()

    var directoryURL: URL { URL(fileURLWithPath: directory, isDirectory: true) }
    var pythonURL: URL { directoryURL.appendingPathComponent(".venv/bin/python3") }
    var scriptURL: URL { directoryURL.appendingPathComponent("bridge.py") }
    var isValid: Bool {
        guard mode == .ub500 else { return true }
        return remoteAddress.range(of: #"^(?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$"#,
                                   options: .regularExpression) != nil &&
            FileManager.default.isExecutableFile(atPath: pythonURL.path) &&
            FileManager.default.fileExists(atPath: scriptURL.path)
    }
}

extension AppSettings {
    var externalBluetoothConfiguration: ExternalBluetoothConfiguration {
        get {
            guard let data = configurationDefaults.data(forKey: "externalBluetooth.configuration.v1"),
                  let value = try? JSONDecoder().decode(ExternalBluetoothConfiguration.self, from: data)
            else { return ExternalBluetoothConfiguration() }
            return value
        }
        set {
            guard let data = try? JSONEncoder().encode(newValue) else { return }
            objectWillChange.send()
            configurationDefaults.set(data, forKey: "externalBluetooth.configuration.v1")
        }
    }
}
