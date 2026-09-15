// Read-only on-device OCR for locating captions already burned into generated clips.
import Foundation
import Vision

let paths = try JSONSerialization.jsonObject(with: Data(contentsOf: URL(fileURLWithPath: CommandLine.arguments[1]))) as! [String]
for path in paths {
    autoreleasepool {
        do {
            let request = VNRecognizeTextRequest()
            request.recognitionLevel = .accurate
            request.recognitionLanguages = ["zh-Hans", "en-US"]
            request.usesLanguageCorrection = false
            request.regionOfInterest = CGRect(x: 0, y: 0, width: 1, height: 0.30)
            try VNImageRequestHandler(url: URL(fileURLWithPath: path), options: [:]).perform([request])
            let rows: [[String: Any]] = (request.results ?? []).compactMap { item in
                guard let candidate = item.topCandidates(1).first else { return nil }
                let b = item.boundingBox
                return ["text": candidate.string, "confidence": candidate.confidence,
                        "box": [b.minX, b.minY, b.width, b.height]]
            }
            let data = try JSONSerialization.data(withJSONObject: ["path": path, "rows": rows], options: [.sortedKeys])
            print(String(data: data, encoding: .utf8)!)
        } catch {
            fputs("OCR failed: \(path): \(error)\n", stderr)
            exit(1)
        }
    }
}
