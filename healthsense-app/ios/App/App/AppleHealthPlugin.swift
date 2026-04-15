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

    private var stepCountType: HKQuantityType? {
        HKObjectType.quantityType(forIdentifier: .stepCount)
    }

    private var heartRateVariabilityType: HKQuantityType? {
        HKObjectType.quantityType(forIdentifier: .heartRateVariabilitySDNN)
    }

    private var activeCardioMinutesType: HKQuantityType? {
        HKObjectType.quantityType(forIdentifier: .appleExerciseTime)
    }

    private func restingHeartRateUnit() -> HKUnit {
        HKUnit.count().unitDivided(by: HKUnit.minute())
    }

    private func stepCountUnit() -> HKUnit {
        HKUnit.count()
    }

    private func heartRateVariabilityUnit() -> HKUnit {
        HKUnit.secondUnit(with: .milli)
    }

    private func activeCardioMinutesUnit() -> HKUnit {
        HKUnit.minute()
    }

    private func sourceObject(source: HKSource, sourceRevision: HKSourceRevision? = nil, device: HKDevice? = nil) -> JSObject {
        var object: JSObject = [
            "name": source.name,
            "bundleIdentifier": source.bundleIdentifier,
        ]
        if let productType = sourceRevision?.productType, !productType.isEmpty {
            object["productType"] = productType
        }
        if let version = sourceRevision?.version, !version.isEmpty {
            object["version"] = version
        }
        if let device = device {
            var deviceObject: JSObject = [:]
            if let name = device.name, !name.isEmpty {
                deviceObject["name"] = name
            }
            if let manufacturer = device.manufacturer, !manufacturer.isEmpty {
                deviceObject["manufacturer"] = manufacturer
            }
            if let model = device.model, !model.isEmpty {
                deviceObject["model"] = model
            }
            if let hardwareVersion = device.hardwareVersion, !hardwareVersion.isEmpty {
                deviceObject["hardwareVersion"] = hardwareVersion
            }
            if let softwareVersion = device.softwareVersion, !softwareVersion.isEmpty {
                deviceObject["softwareVersion"] = softwareVersion
            }
            if !deviceObject.isEmpty {
                object["device"] = deviceObject
            }
        }
        return object
    }

    private func sourceKey(_ source: JSObject) -> String {
        let device = source["device"] as? JSObject
        return [
            source["name"] as? String,
            source["bundleIdentifier"] as? String,
            source["productType"] as? String,
            device?["name"] as? String,
            device?["model"] as? String,
        ]
            .compactMap { value in
                guard let value else { return nil }
                let token = value.trimmingCharacters(in: .whitespacesAndNewlines)
                return token.isEmpty ? nil : token
            }
            .joined(separator: "|")
    }

    private func recordSource(
        _ source: JSObject,
        metricDate: String,
        value: Double,
        valueKey: String,
        weight: Double,
        sourcesByDay: inout [String: [String: JSObject]]
    ) {
        let key = sourceKey(source)
        guard !key.isEmpty else { return }
        var daySources = sourcesByDay[metricDate] ?? [:]
        var row = daySources[key] ?? source
        let sampleCount = (row["sampleCount"] as? Int ?? 0) + 1
        let totalValue = (row["totalValue"] as? Double ?? 0) + value
        let sortValue = (row["sortValue"] as? Double ?? 0) + weight
        row["sampleCount"] = sampleCount
        row["totalValue"] = totalValue
        row["sortValue"] = sortValue
        row[valueKey] = round(totalValue * 10) / 10
        daySources[key] = row
        sourcesByDay[metricDate] = daySources
    }

    private func publicSourceObject(_ source: JSObject) -> JSObject {
        var object = source
        object.removeValue(forKey: "totalValue")
        object.removeValue(forKey: "sortValue")
        return object
    }

    private func sourceSummary(metricDate: String, sourcesByDay: [String: [String: JSObject]]) -> JSObject? {
        guard let daySources = sourcesByDay[metricDate], !daySources.isEmpty else {
            return nil
        }
        let sources = daySources.values.sorted { left, right in
            let leftValue = left["sortValue"] as? Double ?? Double(left["sampleCount"] as? Int ?? 0)
            let rightValue = right["sortValue"] as? Double ?? Double(right["sampleCount"] as? Int ?? 0)
            return leftValue > rightValue
        }
        let publicSources = sources.map { publicSourceObject($0) }
        guard let primary = publicSources.first else {
            return nil
        }
        return [
            "primary": primary,
            "sources": publicSources,
            "sourceCount": publicSources.count,
        ]
    }

    private func isoDayString(_ value: Date) -> String {
        let formatter = DateFormatter()
        formatter.calendar = Calendar.autoupdatingCurrent
        formatter.locale = Locale(identifier: "en_GB")
        formatter.timeZone = TimeZone.autoupdatingCurrent
        formatter.dateFormat = "yyyy-MM-dd"
        return formatter.string(from: value)
    }

    private func aggregateRestingHeartRateSamples(_ quantitySamples: [HKQuantitySample]) -> [JSObject] {
        var totalsByDay: [String: Double] = [:]
        var countsByDay: [String: Int] = [:]
        var sourcesByDay: [String: [String: JSObject]] = [:]

        for sample in quantitySamples {
            let metricDate = isoDayString(sample.endDate)
            let bpm = sample.quantity.doubleValue(for: restingHeartRateUnit())
            guard bpm > 0 else { continue }
            totalsByDay[metricDate, default: 0] += bpm
            countsByDay[metricDate, default: 0] += 1
            recordSource(
                sourceObject(source: sample.sourceRevision.source, sourceRevision: sample.sourceRevision, device: sample.device),
                metricDate: metricDate,
                value: bpm,
                valueKey: "restingHeartRateBpm",
                weight: 1,
                sourcesByDay: &sourcesByDay
            )
        }

        return totalsByDay.keys
            .sorted()
            .compactMap { metricDate in
                guard let total = totalsByDay[metricDate], let count = countsByDay[metricDate], count > 0 else {
                    return nil
                }
                let average = round((total / Double(count)) * 10) / 10
                guard average > 0 else { return nil }
                var row: JSObject = [
                    "metricDate": metricDate,
                    "restingHeartRateBpm": average,
                ]
                if let summary = sourceSummary(metricDate: metricDate, sourcesByDay: sourcesByDay) {
                    row["restingHeartRateSource"] = summary
                }
                return row
            }
    }

    private func aggregateHeartRateVariabilitySamples(_ quantitySamples: [HKQuantitySample]) -> [JSObject] {
        var totalsByDay: [String: Double] = [:]
        var countsByDay: [String: Int] = [:]
        var sourcesByDay: [String: [String: JSObject]] = [:]

        for sample in quantitySamples {
            let metricDate = isoDayString(sample.endDate)
            let hrvMs = sample.quantity.doubleValue(for: heartRateVariabilityUnit())
            guard hrvMs > 0 else { continue }
            totalsByDay[metricDate, default: 0] += hrvMs
            countsByDay[metricDate, default: 0] += 1
            recordSource(
                sourceObject(source: sample.sourceRevision.source, sourceRevision: sample.sourceRevision, device: sample.device),
                metricDate: metricDate,
                value: hrvMs,
                valueKey: "heartRateVariabilityMs",
                weight: 1,
                sourcesByDay: &sourcesByDay
            )
        }

        return totalsByDay.keys
            .sorted()
            .compactMap { metricDate in
                guard let total = totalsByDay[metricDate], let count = countsByDay[metricDate], count > 0 else {
                    return nil
                }
                let average = round((total / Double(count)) * 10) / 10
                guard average > 0 else { return nil }
                var row: JSObject = [
                    "metricDate": metricDate,
                    "heartRateVariabilityMs": average,
                ]
                if let summary = sourceSummary(metricDate: metricDate, sourcesByDay: sourcesByDay) {
                    row["heartRateVariabilitySource"] = summary
                }
                return row
            }
    }

    private func mergeBiometricSamples(
        restingHeartRateSamples: [JSObject],
        heartRateVariabilitySamples: [JSObject],
        stepSamples: [JSObject],
        activeCardioMinutesSamples: [JSObject]
    ) -> [JSObject] {
        var byDay: [String: JSObject] = [:]

        for sample in restingHeartRateSamples {
            let metricDate = String(sample["metricDate"] as? String ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
            guard !metricDate.isEmpty else { continue }
            byDay[metricDate] = sample
        }

        for sample in heartRateVariabilitySamples {
            let metricDate = String(sample["metricDate"] as? String ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
            guard !metricDate.isEmpty else { continue }
            var row = byDay[metricDate] ?? ["metricDate": metricDate]
            if let hrvMs = sample["heartRateVariabilityMs"] {
                row["heartRateVariabilityMs"] = hrvMs
            }
            if let source = sample["heartRateVariabilitySource"] {
                row["heartRateVariabilitySource"] = source
            }
            byDay[metricDate] = row
        }

        for sample in stepSamples {
            let metricDate = String(sample["metricDate"] as? String ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
            guard !metricDate.isEmpty else { continue }
            var row = byDay[metricDate] ?? ["metricDate": metricDate]
            if let steps = sample["steps"] {
                row["steps"] = steps
            }
            if let source = sample["stepsSource"] {
                row["stepsSource"] = source
            }
            byDay[metricDate] = row
        }

        for sample in activeCardioMinutesSamples {
            let metricDate = String(sample["metricDate"] as? String ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
            guard !metricDate.isEmpty else { continue }
            var row = byDay[metricDate] ?? ["metricDate": metricDate]
            if let activeCardioMinutes = sample["activeCardioMinutes"] {
                row["activeCardioMinutes"] = activeCardioMinutes
            }
            if let source = sample["activeCardioMinutesSource"] {
                row["activeCardioMinutesSource"] = source
            }
            byDay[metricDate] = row
        }

        return byDay.keys.sorted().compactMap { byDay[$0] }
    }

    private func fetchRestingHeartRateSamples(
        quantityType: HKQuantityType,
        predicate: NSPredicate?,
        sortDescriptors: [NSSortDescriptor],
        limit: Int,
        completion: @escaping ([JSObject]?, Error?) -> Void
    ) {
        let query = HKSampleQuery(
            sampleType: quantityType,
            predicate: predicate,
            limit: limit,
            sortDescriptors: sortDescriptors
        ) { _, results, error in
            if let error {
                completion(nil, error)
                return
            }
            let quantitySamples = (results as? [HKQuantitySample]) ?? []
            completion(self.aggregateRestingHeartRateSamples(quantitySamples), nil)
        }
        healthStore.execute(query)
    }

    private func fetchHeartRateVariabilitySamples(
        quantityType: HKQuantityType,
        predicate: NSPredicate?,
        sortDescriptors: [NSSortDescriptor],
        limit: Int,
        completion: @escaping ([JSObject]?, Error?) -> Void
    ) {
        let query = HKSampleQuery(
            sampleType: quantityType,
            predicate: predicate,
            limit: limit,
            sortDescriptors: sortDescriptors
        ) { _, results, error in
            if let error {
                completion(nil, error)
                return
            }
            let quantitySamples = (results as? [HKQuantitySample]) ?? []
            completion(self.aggregateHeartRateVariabilitySamples(quantitySamples), nil)
        }
        healthStore.execute(query)
    }

    private func fetchStepSamples(
        quantityType: HKQuantityType,
        predicate: NSPredicate?,
        startDate: Date,
        endDate: Date,
        completion: @escaping ([JSObject]?, Error?) -> Void
    ) {
        let interval = DateComponents(day: 1)
        let anchorDate = Calendar.autoupdatingCurrent.startOfDay(for: endDate)
        var sourcesByDay: [String: [String: JSObject]] = [:]
        let query = HKStatisticsCollectionQuery(
            quantityType: quantityType,
            quantitySamplePredicate: predicate,
            options: [.cumulativeSum, .separateBySource],
            anchorDate: anchorDate,
            intervalComponents: interval
        )
        query.initialResultsHandler = { _, results, error in
            if let error {
                completion(nil, error)
                return
            }
            var samples: [JSObject] = []
            results?.enumerateStatistics(from: startDate, to: endDate) { statistics, _ in
                guard let quantity = statistics.sumQuantity() else {
                    return
                }
                let metricDate = self.isoDayString(statistics.startDate)
                let steps = Int(round(quantity.doubleValue(for: self.stepCountUnit())))
                guard steps >= 0 else { return }
                if let sources = statistics.sources {
                    for source in sources {
                        guard let sourceQuantity = statistics.sumQuantity(for: source) else { continue }
                        let sourceSteps = sourceQuantity.doubleValue(for: self.stepCountUnit())
                        guard sourceSteps > 0 else { continue }
                        self.recordSource(
                            self.sourceObject(source: source),
                            metricDate: metricDate,
                            value: sourceSteps,
                            valueKey: "steps",
                            weight: sourceSteps,
                            sourcesByDay: &sourcesByDay
                        )
                    }
                }
                var row: JSObject = [
                    "metricDate": metricDate,
                    "steps": steps,
                ]
                if let summary = self.sourceSummary(metricDate: metricDate, sourcesByDay: sourcesByDay) {
                    row["stepsSource"] = summary
                }
                samples.append(row)
            }
            completion(samples, nil)
        }
        healthStore.execute(query)
    }

    private func fetchActiveCardioMinutesSamples(
        quantityType: HKQuantityType,
        predicate: NSPredicate?,
        startDate: Date,
        endDate: Date,
        completion: @escaping ([JSObject]?, Error?) -> Void
    ) {
        let interval = DateComponents(day: 1)
        let anchorDate = Calendar.autoupdatingCurrent.startOfDay(for: endDate)
        var sourcesByDay: [String: [String: JSObject]] = [:]
        let query = HKStatisticsCollectionQuery(
            quantityType: quantityType,
            quantitySamplePredicate: predicate,
            options: [.cumulativeSum, .separateBySource],
            anchorDate: anchorDate,
            intervalComponents: interval
        )
        query.initialResultsHandler = { _, results, error in
            if let error {
                completion(nil, error)
                return
            }
            var samples: [JSObject] = []
            results?.enumerateStatistics(from: startDate, to: endDate) { statistics, _ in
                guard let quantity = statistics.sumQuantity() else {
                    return
                }
                let metricDate = self.isoDayString(statistics.startDate)
                let activeCardioMinutes = Int(round(quantity.doubleValue(for: self.activeCardioMinutesUnit())))
                guard activeCardioMinutes >= 0 else { return }
                if let sources = statistics.sources {
                    for source in sources {
                        guard let sourceQuantity = statistics.sumQuantity(for: source) else { continue }
                        let sourceMinutes = sourceQuantity.doubleValue(for: self.activeCardioMinutesUnit())
                        guard sourceMinutes > 0 else { continue }
                        self.recordSource(
                            self.sourceObject(source: source),
                            metricDate: metricDate,
                            value: sourceMinutes,
                            valueKey: "activeCardioMinutes",
                            weight: sourceMinutes,
                            sourcesByDay: &sourcesByDay
                        )
                    }
                }
                var row: JSObject = [
                    "metricDate": metricDate,
                    "activeCardioMinutes": activeCardioMinutes,
                ]
                if let summary = self.sourceSummary(metricDate: metricDate, sourcesByDay: sourcesByDay) {
                    row["activeCardioMinutesSource"] = summary
                }
                samples.append(row)
            }
            completion(samples, nil)
        }
        healthStore.execute(query)
    }

    private func resolveAuthorizationState(completion: @escaping (String) -> Void) {
        let quantityTypes = [restingHeartRateType, stepCountType, heartRateVariabilityType, activeCardioMinutesType].compactMap { $0 }
        guard HKHealthStore.isHealthDataAvailable(), !quantityTypes.isEmpty else {
            completion("unsupported")
            return
        }
        let readTypes: Set<HKObjectType> = Set(quantityTypes)
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
        let available = HKHealthStore.isHealthDataAvailable() && (restingHeartRateType != nil || stepCountType != nil || heartRateVariabilityType != nil || activeCardioMinutesType != nil)
        return [
            "available": available,
            "status": status,
        ]
    }

    @objc func authorizationStatus(_ call: CAPPluginCall) {
        resolveAuthorizationState { status in
            call.resolve(self.authorizationPayload(status: status))
        }
    }

    @objc func requestAuthorization(_ call: CAPPluginCall) {
        let quantityTypes = [restingHeartRateType, stepCountType, heartRateVariabilityType, activeCardioMinutesType].compactMap { $0 }
        guard HKHealthStore.isHealthDataAvailable(), !quantityTypes.isEmpty else {
            call.resolve(authorizationPayload(status: "unsupported"))
            return
        }
        let readTypes: Set<HKObjectType> = Set(quantityTypes)
        healthStore.requestAuthorization(toShare: nil, read: readTypes) { _, error in
            if let error {
                call.reject("Apple Health authorization failed: \(error.localizedDescription)")
                return
            }
            self.resolveAuthorizationState { status in
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
        let restingType = restingHeartRateType
        let hrvType = heartRateVariabilityType
        let stepType = stepCountType
        let activeType = activeCardioMinutesType
        guard HKHealthStore.isHealthDataAvailable(), restingType != nil || hrvType != nil || stepType != nil || activeType != nil else {
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
        let ascendingSort = [
            NSSortDescriptor(key: HKSampleSortIdentifierEndDate, ascending: true)
        ]
        let completeRestingHeartRateSamples = { (resolvedRestingSamples: [JSObject]) in
            let completeHeartRateVariabilitySamples = { (resolvedHrvSamples: [JSObject]) in
                let completeStepSamples = { (resolvedStepSamples: [JSObject]) in
                    guard let activeType = activeType else {
                        let merged = self.mergeBiometricSamples(
                            restingHeartRateSamples: resolvedRestingSamples,
                            heartRateVariabilitySamples: resolvedHrvSamples,
                            stepSamples: resolvedStepSamples,
                            activeCardioMinutesSamples: []
                        )
                        call.resolve([
                            "samples": merged,
                            "latestMetricDate": (merged.last?["metricDate"] as? String) ?? NSNull(),
                        ])
                        return
                    }
                    self.fetchActiveCardioMinutesSamples(
                        quantityType: activeType,
                        predicate: predicate,
                        startDate: startDate,
                        endDate: endDate
                    ) { activeCardioMinutesSamples, activeCardioMinutesError in
                        if let activeCardioMinutesError {
                            call.reject("Apple Health active cardio minutes query failed: \(activeCardioMinutesError.localizedDescription)")
                            return
                        }
                        let merged = self.mergeBiometricSamples(
                            restingHeartRateSamples: resolvedRestingSamples,
                            heartRateVariabilitySamples: resolvedHrvSamples,
                            stepSamples: resolvedStepSamples,
                            activeCardioMinutesSamples: activeCardioMinutesSamples ?? []
                        )
                        call.resolve([
                            "samples": merged,
                            "latestMetricDate": (merged.last?["metricDate"] as? String) ?? NSNull(),
                        ])
                    }
                }

                guard let stepType = stepType else {
                    completeStepSamples([])
                    return
                }
                self.fetchStepSamples(
                    quantityType: stepType,
                    predicate: predicate,
                    startDate: startDate,
                    endDate: endDate
                ) { stepSamples, stepError in
                    if let stepError {
                        call.reject("Apple Health step query failed: \(stepError.localizedDescription)")
                        return
                    }
                    completeStepSamples(stepSamples ?? [])
                }
            }

            guard let hrvType = hrvType else {
                completeHeartRateVariabilitySamples([])
                return
            }
            self.fetchHeartRateVariabilitySamples(
                quantityType: hrvType,
                predicate: predicate,
                sortDescriptors: ascendingSort,
                limit: HKObjectQueryNoLimit
            ) { hrvSamples, hrvError in
                if let hrvError {
                    call.reject("Apple Health HRV query failed: \(hrvError.localizedDescription)")
                    return
                }
                completeHeartRateVariabilitySamples(hrvSamples ?? [])
            }
        }

        guard let restingType = restingType else {
            completeRestingHeartRateSamples([])
            return
        }
        self.fetchRestingHeartRateSamples(
            quantityType: restingType,
            predicate: predicate,
            sortDescriptors: ascendingSort,
            limit: HKObjectQueryNoLimit
        ) { samples, error in
            if let error {
                call.reject("Apple Health resting heart rate query failed: \(error.localizedDescription)")
                return
            }
            let recentSamples = samples ?? []
            if !recentSamples.isEmpty {
                completeRestingHeartRateSamples(recentSamples)
                return
            }

            let descendingSort = [
                NSSortDescriptor(key: HKSampleSortIdentifierEndDate, ascending: false)
            ]
            self.fetchRestingHeartRateSamples(
                quantityType: restingType,
                predicate: nil,
                sortDescriptors: descendingSort,
                limit: 90
            ) { fallbackSamples, fallbackError in
                if let fallbackError {
                    call.reject("Apple Health resting heart rate query failed: \(fallbackError.localizedDescription)")
                    return
                }
                let samples = (fallbackSamples ?? []).sorted {
                    String($0["metricDate"] as? String ?? "") < String($1["metricDate"] as? String ?? "")
                }
                completeRestingHeartRateSamples(samples)
            }
        }
    }
}
