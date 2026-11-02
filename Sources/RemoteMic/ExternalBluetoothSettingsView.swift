import AppKit
import SwiftUI

struct ExternalBluetoothSettingsView: View {
    @ObservedObject var model: BridgeAppModel
    @ObservedObject var settings: AppSettings
    @State private var draft = ExternalBluetoothConfiguration()

    var body: some View {
        GlassPanel {
            VStack(alignment: .leading, spacing: 12) {
                Text("connection.external.title").font(.system(size: 13, weight: .semibold))
                Picker("connection.external.title", selection: $draft.mode) {
                    Text("connection.external.system").tag(ExternalBluetoothConfiguration.Mode.system)
                    Text("connection.external.ub500").tag(ExternalBluetoothConfiguration.Mode.ub500)
                }
                .pickerStyle(.segmented)
                if draft.mode == .ub500 {
                    Text("connection.external.description")
                        .font(.system(size: 12)).foregroundStyle(.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                    TextField("connection.external.address", text: $draft.remoteAddress)
                        .textFieldStyle(.roundedBorder)
                        .font(.system(size: 12, design: .monospaced))
                        .accessibilityLabel(Text("connection.external.address"))
                    HStack {
                        Button("connection.external.choose_directory", action: chooseDirectory)
                        Text(URL(fileURLWithPath: draft.directory).lastPathComponent)
                            .font(.system(size: 12)).lineLimit(1).truncationMode(.middle)
                    }
                    if !draft.isValid {
                        Text("connection.external.setup_required")
                            .font(.system(size: 12)).foregroundStyle(.secondary)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                }
                Button("connection.external.apply") {
                    model.applyExternalBluetoothConfiguration(draft)
                    draft = settings.externalBluetoothConfiguration
                }
                .disabled(model.isStreaming || !draft.isValid)
                if model.isStreaming {
                    Text("connection.external.stop_voice_first").font(.system(size: 12))
                }
            }
            .disabled(model.isStreaming)
        }
        .onAppear { draft = settings.externalBluetoothConfiguration }
    }

    private func chooseDirectory() {
        let panel = NSOpenPanel()
        panel.canChooseDirectories = true
        panel.canChooseFiles = false
        panel.allowsMultipleSelection = false
        panel.directoryURL = draft.directoryURL
        if panel.runModal() == .OK, let url = panel.url { draft.directory = url.path }
    }
}
