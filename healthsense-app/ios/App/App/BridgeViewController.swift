import UIKit
import Capacitor
import WebKit

class BridgeViewController: CAPBridgeViewController {
    override func webView(with frame: CGRect, configuration: WKWebViewConfiguration) -> WKWebView {
        // The hosted web app can update independently of this native binary.
        // Advertise microphone support only when this installed build declares it.
        let purpose = Bundle.main.object(forInfoDictionaryKey: "NSMicrophoneUsageDescription") as? String
        let microphoneReady = !(purpose?.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty ?? true)
        let capability = WKUserScript(
            source: "window.__healthsenseNativeMicrophoneReady = \(microphoneReady ? "true" : "false");",
            injectionTime: .atDocumentStart,
            forMainFrameOnly: true
        )
        configuration.userContentController.addUserScript(capability)
        return super.webView(with: frame, configuration: configuration)
    }

    override open func capacitorDidLoad() {
        super.capacitorDidLoad()
    }
}
