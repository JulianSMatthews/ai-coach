import Foundation
import Capacitor
import HealthKit

@objc(AppleHealthPlugin)
public class AppleHealthPlugin: CAPPlugin, CAPBridgedPlugin {
    public let identifier = "AppleHealthPlugin"
    public let jsName = "AppleHealth"
    public let pluginMethods: [CAPPluginMethod] = [
        CAPPluginMethod(name: "authorizationStatus", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "requestAuthorization", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "openSettings", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "getRecentRestingHeartRate", returnType: CAPPluginReturnPromise),
    ]

    private let healthStore = HKHealthStore()

    private var restingHeartRateType: HKQuantityType? {
        HKObjectType.quantityType(forIdentifier: .restingHeartRate)
    }

    private func restingHeartRateUnit() -> HKUnit {
        HKUnit.count().unitDivided(by: HKUnit.minute())
    }

    private func isoDayString(_ value: Date) -> String {
        let formatter = DateFormatter()
        formatter.calendar = Calendar.autoupdatingCurrent
        formatter.locale = Locale(identifier: "en_GB")
        formatter.timeZone = TimeZone.autoupdatingCurrent
        formatter.dateFormat = "yyyy-MM-dd"
        return formatter.string(from: value)
    }

    private func resolveAuthorizationState(for quantityType: HKQuantityType?, completion: @escaping (String) -> Void) {
        guard HKHealthStore.isHealthDataAvailable(), let quantityType else {
            completion("unsupported")
            return
        }
        let readTypes: Set<HKObjectType> = [quantityType]
        healthStore.getRequestStatusForAuthorization(toShare: [], read: readTypes) { status, error in
            if error != nil {
                completion("unsupported")
                return
            }
            switch status {
            case .shouldRequest:
                completion("not_determined")
            case .unnecessary:
                // For read-only permissions, HealthKit does not expose a reliable
                // granted-vs-denied read status here. Treat prior requests as ready
                // to query and let the query result distinguish value vs no data.
                completion("authorized")
            case .unknown:
                completion("unsupported")
            @unknown default:
                completion("unsupported")
            }
        }
    }

    private func authorizationPayload(status: String) -> JSObject {
        let available = HKHealthStore.isHealthDataAvailable() && restingHeartRateType != nil
        return [
            "available": available,
            "status": status,
        ]
    }

    @objc func authorizationStatus(_ call: CAPPluginCall) {
        resolveAuthorizationState(for: restingHeartRateType) { status in
            call.resolve(self.authorizationPayload(status: status))
        }
    }

    @objc func requestAuthorization(_ call: CAPPluginCall) {
        guard HKHealthStore.isHealthDataAvailable(), let quantityType = restingHeartRateType else {
            call.resolve(authorizationPayload(status: "unsupported"))
            return
        }
        let readTypes: Set<HKObjectType> = [quantityType]
        healthStore.requestAuthorization(toShare: nil, read: readTypes) { _, error in
            if let error {
                call.reject("Apple Health authorization failed: \(error.localizedDescription)")
                return
            }
            self.resolveAuthorizationState(for: quantityType) { status in
                call.resolve(self.authorizationPayload(status: status))
            }
        }
    }

    @objc func openSettings(_ call: CAPPluginCall) {
        DispatchQueue.main.async {
            guard let url = URL(string: UIApplication.openSettingsURLString) else {
                call.reject("Could not resolve the iOS Settings URL.")
                return
            }
            UIApplication.shared.open(url, options: [:]) { success in
                call.resolve([
                    "ok": success
                ])
            }
        }
    }

    @objc func getRecentRestingHeartRate(_ call: CAPPluginCall) {
        guard HKHealthStore.isHealthDataAvailable(), let quantityType = restingHeartRateType else {
            call.resolve([
                "samples": [],
                "latestMetricDate": NSNull(),
            ])
            return
        }

        let days = max(7, min(30, call.getInt("days") ?? 21))
        let calendar = Calendar.autoupdatingCurrent
        let endDate = Date()
        let anchorDate = calendar.startOfDay(for: endDate)
        guard let startDate = calendar.date(byAdding: .day, value: -(days - 1), to: anchorDate) else {
            call.reject("Could not resolve Apple Health date range.")
            return
        }

        let predicate = HKQuery.predicateForSamples(
            withStart: startDate,
            end: endDate,
            options: [.strictStartDate],
        )
        let interval = DateComponents(day: 1)
        let query = HKStatisticsCollectionQuery(
            quantityType: quantityType,
            quantitySamplePredicate: predicate,
            options: [.discreteAverage],
            anchorDate: anchorDate,
            intervalComponents: interval,
        )

        query.initialResultsHandler = { _, results, error in
            if let error {
                call.reject("Apple Health resting heart rate query failed: \(error.localizedDescription)")
                return
            }
            var samples: [JSObject] = []
            results?.enumerateStatistics(from: startDate, to: endDate) { statistics, _ in
                guard let quantity = statistics.averageQuantity() else {
                    return
                }
                let bpm = round(quantity.doubleValue(for: self.restingHeartRateUnit()) * 10) / 10
                if bpm <= 0 {
                    return
                }
                samples.append([
                    "metricDate": self.isoDayString(statistics.startDate),
                    "restingHeartRateBpm": bpm,
                ])
            }
            call.resolve([
                "samples": samples,
                "latestMetricDate": (samples.last?["metricDate"] as? String) ?? NSNull(),
            ])
        }
        healthStore.execute(query)
    }
}
