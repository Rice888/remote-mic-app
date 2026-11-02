import Foundation

enum ExternalBluetoothHID {
    /// HOGP omits the report ID. RC003 sends an eight-byte keyboard array; older
    /// Xiaomi consumer reports contain three little-endian 16-bit usages.
    static func normalize(_ data: Data) -> Data? {
        if data.count == 6 { return data }
        guard data.count == 8, data[data.startIndex] == 0,
              data[data.startIndex + 1] == 0 else { return nil }
        var result = Data()
        for usage in data.dropFirst(2) {
            // Boot keyboard rollover is an error, never a mapped key.
            guard !(1...3).contains(usage) else { return nil }
            result.append(usage)
            result.append(0)
        }
        return result
    }
}
