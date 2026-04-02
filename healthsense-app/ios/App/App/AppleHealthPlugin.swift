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

    private func authorizationState(for quantityType: HKQuantityType?) -> String {
        guard HKHealthStore.isHealthDataAvailable(), let quantityType else {
            return "unsupported"
        }
        switch healthStore.authorizationStatus(for: quantityType) {
        case .notDetermined:
            return "not_determined"
        case .sharingDenied:
            return "denied"
        case .sharingAuthorized:
            return "authorized"
        @unknown default:
            return "unsupported"
        }
    }

    private func authorizationPayload() -> JSObject {
        let available = HKHealthStore.isHealthDataAvailable() && restingHeartRateType != nil
        return [
            "available": available,
            "status": authorizationState(for: restingHeartRateType),
        ]
    }

    @objc func authorizationStatus(_ call: CAPPluginCall) {
        call.resolve(authorizationPayload())
    }

    @objc func requestAuthorization(_ call: CAPPluginCall) {
        guard HKHealthStore.isHealthDataAvailable(), let quantityType = restingHeartRateType else {
            call.resolve(authorizationPayload())
            return
        }
        let readTypes: Set<HKObjectType> = [quantityType]
        healthStore.requestAuthorization(toShare: nil, read: readTypes) { _, error in
            if let error {
                call.reject("Apple Health authorization failed: \(error.localizedDescription)")
                return
            }
            call.resolve(self.authorizationPayload())
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
        guard authorizationState(for: quantityType) == "authorized" else {
            call.reject("Apple Health resting heart rate access is not authorised.")
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
