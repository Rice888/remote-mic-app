import Foundation
import Testing
@testable import RemoteMic

@Suite("External Bluetooth transport")
struct ExternalBluetoothTests {
    @Test func framingPreservesSplitPacketsAndSequence() throws {
        var framer = ExternalBluetoothFramer()
        let first = Data(#"{"v":1,"seq":1,"type":"ready"}"#.utf8)
        #expect(try framer.append(first).isEmpty)
        let packets = try framer.append(Data("\n{\"v\":1,\"seq\":2,\"type\":\"hid\",\"report_id\":1,\"data\":\"AAAAAAAAAAA=\"}\n".utf8))
        #expect(packets.map(\.type) == ["ready", "hid"])
        #expect(packets.last?.data == Data(repeating: 0, count: 8))
    }

    @Test func malformedOversizedAndMissingSequenceFailClosed() {
        for bytes in [Data("{bad}\n".utf8),
                      Data("{\"v\":1,\"seq\":2,\"type\":\"ready\"}\n".utf8),
                      Data(repeating: 65, count: 16_385),
                      Data("{\"v\":2,\"seq\":1,\"type\":\"ready\"}\n".utf8),
                      Data("{\"v\":1,\"seq\":1,\"type\":\"audio\"}\n".utf8)] {
            var framer = ExternalBluetoothFramer()
            #expect(throws: (any Error).self) { try framer.append(bytes) }
        }
    }

    @Test func rc003KeyboardAndLegacyConsumerReportsRetainPressAndRelease() throws {
        let report = Data([0, 0, 0x51, 0, 0, 0, 0, 0])
        let normalized = try #require(ExternalBluetoothHID.normalize(report))
        #expect(RemoteHIDReportParser.usages(reportID: 1, data: normalized) == [0x51])
        let release = try #require(ExternalBluetoothHID.normalize(Data(repeating: 0, count: 8)))
        #expect(RemoteHIDReportParser.usages(reportID: 1, data: release) == [])
        let consumer = Data([0x81, 0, 0, 0, 0, 0])
        #expect(ExternalBluetoothHID.normalize(consumer) == consumer)
        #expect(ExternalBluetoothHID.normalize(Data([0, 0, 1, 0, 0, 0, 0, 0])) == nil)
        #expect(ExternalBluetoothHID.normalize(Data([1, 2, 3])) == nil)
    }

    @Test func externalReportsUseConfiguredActionsAndReleaseOnPermissionLoss() throws {
        let suite = "ExternalBluetoothMappingTests.\(UUID().uuidString)"
        let defaults = try #require(UserDefaults(suiteName: suite))
        defer { defaults.removePersistentDomain(forName: suite) }
        let settings = AppSettings(defaults: defaults)
        let profileID = settings.registerBluetoothRemote(identifier: UUID())
        settings.customMappingEnabled = true
        settings.setAction(.arrowDown, for: .down)
        settings.setAction(.disabled, for: .down, trigger: .doubleClick)
        settings.setAction(.disabled, for: .down, trigger: .longPress)
        var allowed = true
        var performed: [ConfiguredButtonAction] = []
        var active = Set<RemoteButton>()
        let suppressor = KeyboardEventSuppressor()
        let monitor = HIDRemoteMonitor(settings: settings, profileID: profileID,
            eventSuppressor: suppressor, ownsEventSuppressor: false,
            runtimePermissions: { allowed },
            actionPerformer: { _, _, action in performed.append(action); return true },
            diagnosticLogger: { _ in })
        monitor.onActiveButtons = { _, buttons in active = buttons }
        let down = Data([0x51, 0, 0, 0, 0, 0])
        monitor.handleExternalReport(down)
        #expect(active == [.down])
        #expect(performed.count == 1)
        #expect(performed.first?.action == .arrowDown)
        #expect(!suppressor.isRunning)
        allowed = false
        monitor.handleExternalReport(down)
        #expect(active.isEmpty)
        #expect(performed.count == 1)
        monitor.stop()
    }

    @Test func absentConfigurationKeepsSystemBluetoothAndRoundTripsSelection() throws {
        let suite = "ExternalBluetoothTests.\(UUID().uuidString)"
        let defaults = try #require(UserDefaults(suiteName: suite))
        defer { defaults.removePersistentDomain(forName: suite) }
        // Exercise the data contract without launching hardware or touching other app defaults.
        let original = ExternalBluetoothConfiguration()
        #expect(original.mode == .system)
        var selected = original
        selected.mode = .ub500
        selected.remoteAddress = "00:11:22:33:44:55"
        let data = try JSONEncoder().encode(selected)
        defaults.set(data, forKey: "externalBluetooth.configuration.v1")
        let restored = try JSONDecoder().decode(ExternalBluetoothConfiguration.self, from: data)
        #expect(restored == selected)
        selected.mode = .system
        #expect(selected.isValid)
    }
}
