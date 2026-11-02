import Darwin
import Foundation

struct ExternalBluetoothPacket: Decodable {
    let v: Int
    let seq: UInt64
    let type: String
    let data: Data?
    let report_id: UInt32?
    let code: String?
}

/// Bounded, ordered framing. A malformed frame terminates the session; no silent audio loss.
struct ExternalBluetoothFramer {
    private var pending = Data()
    private var sequence: UInt64 = 0
    mutating func append(_ bytes: Data) throws -> [ExternalBluetoothPacket] {
        var result: [ExternalBluetoothPacket] = []
        for byte in bytes {
            guard pending.count < 16_384 else { throw Failure.invalidFrame }
            if byte != 10 { pending.append(byte); continue }
            let packet = try JSONDecoder().decode(ExternalBluetoothPacket.self, from: pending)
            pending.removeAll(keepingCapacity: true)
            guard packet.v == 1, packet.seq == sequence + 1,
                  ["ready", "control", "audio", "hid", "battery", "model", "error", "disconnected"].contains(packet.type)
            else { throw Failure.invalidFrame }
            if ["control", "audio", "hid", "battery", "model"].contains(packet.type) {
                guard let data = packet.data, !data.isEmpty, data.count <= 4_096 else {
                    throw Failure.invalidFrame
                }
            }
            if packet.type == "hid" {
                guard packet.report_id == 1 else { throw Failure.invalidFrame }
            }
            sequence = packet.seq
            result.append(packet)
        }
        return result
    }
    enum Failure: Error { case invalidFrame }
}

/// One owner per process; callbacks execute in pipe order on the main thread.
final class ExternalBluetoothTransport: @unchecked Sendable {
    private let process = Process()
    private let input = Pipe()
    private let output = Pipe()
    private let errors = Pipe()
    private static let queue = DispatchQueue(label: "SayAll.externalBluetooth.usbOwner")
    private let lifecycleLock = NSLock()
    private var framer = ExternalBluetoothFramer()
    private var stopped = false
    private var callback: ((ExternalBluetoothPacket?) -> Void)?

    func start(configuration: ExternalBluetoothConfiguration,
               receive: @escaping (ExternalBluetoothPacket?) -> Void) throws {
        callback = receive
        process.executableURL = configuration.pythonURL
        process.arguments = [configuration.scriptURL.path,
                             "--address", configuration.remoteAddress,
                             "--firmware", configuration.directoryURL.appendingPathComponent("firmware").path,
                             "--keys", configuration.directoryURL.appendingPathComponent("bonds.json").path]
        var environment = ProcessInfo.processInfo.environment
        environment["PYTHONUNBUFFERED"] = "1"
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        process.environment = environment
        process.standardInput = input
        process.standardOutput = output
        process.standardError = errors
        // Third-party tracebacks are intentionally drained without logging device addresses/data.
        errors.fileHandleForReading.readabilityHandler = { handle in _ = handle.availableData }
        Self.queue.async { [self] in
            self.lifecycleLock.lock()
            if self.stopped { self.lifecycleLock.unlock(); return }
            do { try self.process.run() }
            catch {
                self.lifecycleLock.unlock()
                DispatchQueue.main.async { [weak self] in self?.callback?(nil) }
                return
            }
            self.lifecycleLock.unlock()
            while true {
                do {
                    guard let bytes = try self.output.fileHandleForReading.read(upToCount: 4_096),
                          !bytes.isEmpty else { break }
                    let packets = try self.framer.append(bytes)
                    // Backpressure bounds IPC memory while retaining key-up/audio order.
                    DispatchQueue.main.sync { [weak self] in
                        guard let self else { return }
                        for packet in packets { self.callback?(packet) }
                    }
                } catch { break }
            }
            if self.process.isRunning {
                self.process.terminate()
                let child = self.process
                DispatchQueue.global().asyncAfter(deadline: .now() + 2) {
                    if child.isRunning { kill(child.processIdentifier, SIGKILL) }
                }
            }
            self.process.waitUntilExit()
            DispatchQueue.main.async { [weak self] in self?.callback?(nil) }
        }
    }

    @discardableResult
    func write(_ data: Data) -> Bool {
        guard process.isRunning else { return false }
        let packet: [String: Any] = ["v": 1, "type": "tx", "data": data.base64EncodedString()]
        guard var line = try? JSONSerialization.data(withJSONObject: packet) else { return false }
        line.append(10)
        do { try input.fileHandleForWriting.write(contentsOf: line); return true }
        catch { return false }
    }

    func stop() {
        callback = nil
        errors.fileHandleForReading.readabilityHandler = nil
        lifecycleLock.lock()
        stopped = true
        defer { lifecycleLock.unlock() }
        try? input.fileHandleForWriting.close()
        if process.isRunning {
            process.terminate()
            let child = process
            DispatchQueue.global().asyncAfter(deadline: .now() + 2) {
                if child.isRunning { kill(child.processIdentifier, SIGKILL) }
            }
        }
    }
}
