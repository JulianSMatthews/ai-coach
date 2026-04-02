import { Capacitor, registerPlugin } from "@capacitor/core";
import type { AppleHealthRestingHeartRateResponse } from "@/lib/api";

export type AppleHealthAuthorizationState =
  | "authorized"
  | "denied"
  | "not_determined"
  | "unsupported";

export type AppleHealthAuthorizationResponse = {
  available?: boolean;
  status?: AppleHealthAuthorizationState;
};

export type AppleHealthRestingHeartRateSample = {
  metricDate: string;
  restingHeartRateBpm?: number;
  steps?: number;
};

type AppleHealthPlugin = {
  authorizationStatus(): Promise<AppleHealthAuthorizationResponse>;
  requestAuthorization(): Promise<AppleHealthAuthorizationResponse>;
  openSettings(): Promise<{ ok?: boolean }>;
  getRecentRestingHeartRate(options?: {
    days?: number;
  }): Promise<{
    samples?: AppleHealthRestingHeartRateSample[];
    latestMetricDate?: string | null;
  }>;
};

const AppleHealth = registerPlugin<AppleHealthPlugin>("AppleHealth");

export function canUseAppleHealth(): boolean {
  return Capacitor.isNativePlatform() && Capacitor.getPlatform() === "ios";
}

export async function getAppleHealthAuthorizationStatus(): Promise<AppleHealthAuthorizationResponse> {
  if (!canUseAppleHealth()) {
    return {
      available: false,
      status: "unsupported",
    };
  }
  return AppleHealth.authorizationStatus();
}

export async function requestAppleHealthAuthorization(): Promise<AppleHealthAuthorizationResponse> {
  if (!canUseAppleHealth()) {
    return {
      available: false,
      status: "unsupported",
    };
  }
  return AppleHealth.requestAuthorization();
}

export async function openAppleHealthSettings(): Promise<boolean> {
  if (!canUseAppleHealth()) return false;
  try {
    const result = await AppleHealth.openSettings();
    return Boolean(result?.ok);
  } catch {
    return false;
  }
}

export async function syncAppleHealthRestingHeartRate(
  userId: string,
  options?: { days?: number },
): Promise<AppleHealthRestingHeartRateResponse | null> {
  if (!canUseAppleHealth()) return null;
  const readings = await AppleHealth.getRecentRestingHeartRate({
    days: Math.max(7, Math.min(30, Number(options?.days) || 21)),
  });
  const samples = Array.isArray(readings?.samples)
    ? readings.samples
        .map((sample) => ({
          metric_date: String(sample?.metricDate || "").trim(),
          resting_hr_bpm:
            sample?.restingHeartRateBpm === null || sample?.restingHeartRateBpm === undefined
              ? null
              : Number(sample?.restingHeartRateBpm),
          steps:
            sample?.steps === null || sample?.steps === undefined
              ? null
              : Number(sample?.steps),
        }))
        .filter(
          (sample) =>
            Boolean(sample.metric_date) &&
            ((Number.isFinite(Number(sample.resting_hr_bpm)) && Number(sample.resting_hr_bpm) > 0) ||
              (Number.isFinite(Number(sample.steps)) && Number(sample.steps) >= 0)),
        )
    : [];
  if (!samples.length) return null;
  const res = await fetch("/api/apple-health/resting-heart-rate", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      userId,
      samples,
    }),
  });
  const text = await res.text().catch(() => "");
  if (!res.ok) {
    throw new Error(text || "Failed to sync Apple Health resting heart rate.");
  }
  return text ? (JSON.parse(text) as AppleHealthRestingHeartRateResponse) : null;
}
