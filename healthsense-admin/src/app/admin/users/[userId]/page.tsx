import Link from "next/link";
import AdminNav from "@/components/AdminNav";
import { getAdminUserAppState, getAdminUserDetails, type AdminUserAppState } from "@/lib/api";

type UserStatusPageProps = {
  params: Promise<{ userId: string }>;
};

export const dynamic = "force-dynamic";

function AppStateCard({
  title,
  eyebrow,
  rows,
}: {
  title: string;
  eyebrow: string;
  rows: Array<{ label: string; value: string | number | null | undefined }>;
}) {
  return (
    <div className="rounded-2xl border border-[#efe7db] bg-[#faf8f3] p-4">
      <p className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">{eyebrow}</p>
      <h3 className="mt-2 text-base font-semibold">{title}</h3>
      <div className="mt-3 space-y-2">
        {rows.map((row) => (
          <div key={row.label} className="flex items-start justify-between gap-3 text-sm">
            <span className="text-[#6b6257]">{row.label}</span>
            <span className="max-w-[65%] text-right font-medium">
              {row.value === null || row.value === undefined || row.value === "" ? "—" : row.value}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

export default async function UserStatusPage({ params }: UserStatusPageProps) {
  const resolvedParams = await params;
  const userId = Number(resolvedParams.userId);
  const detail = await getAdminUserDetails(userId);
  let appState: AdminUserAppState | null = null;
  let appStateError: string | null = null;
  try {
    appState = await getAdminUserAppState(userId);
  } catch (error) {
    appStateError = error instanceof Error ? error.message : String(error);
  }
  const user = detail.user as Record<string, unknown> | undefined;
  const status = detail.status as string | undefined;
  const latest = detail.latest_run as { id?: number; finished_at?: string } | undefined;
  const onboarding = (detail.onboarding || {}) as Record<string, unknown>;
  const introContent = (onboarding.intro_content || {}) as Record<string, unknown>;
  const weeklyPlan = (detail.current_weekly_plan || null) as Record<string, unknown> | null;
  const weeklyPlanKrs = Array.isArray(weeklyPlan?.krs) ? (weeklyPlan?.krs as Record<string, unknown>[]) : [];
  const fields = user ? Object.entries(user) : [];
  const firstAssessmentCompletedAt = onboarding.first_assessment_completed_at || onboarding.assessment_completed_at;
  const assessmentCompletedMet = Boolean(firstAssessmentCompletedAt);
  const firstLoginMet = Boolean(onboarding.first_app_login_at);
  const assessmentReviewMet = Boolean(onboarding.assessment_reviewed_at);
  const activationReady = Boolean(onboarding.coaching_activation_ready ?? (assessmentCompletedMet && firstLoginMet && assessmentReviewMet));
  const coachingEnabledNow = Boolean(onboarding.coaching_enabled_now);
  const onboardingFields = [
    [
      "first_assessment_completed_at",
      onboarding.first_assessment_completed_at || onboarding.assessment_completed_at,
    ],
    ["first_app_login_at", onboarding.first_app_login_at],
    ["assessment_reviewed_at", onboarding.assessment_reviewed_at],
    ["intro_content_presented_at", onboarding.intro_content_presented_at],
    ["intro_content_listened_at", onboarding.intro_content_listened_at],
    ["intro_content_read_at", onboarding.intro_content_read_at],
    ["intro_content_completed_at", onboarding.intro_content_completed_at],
    ["coaching_auto_enabled_at", onboarding.coaching_auto_enabled_at],
    ["coaching_first_day_sent_at", onboarding.coaching_first_day_sent_at],
  ] as const;
  const essentialActivationRows = [
    {
      label: "First Assessment Completed",
      met: assessmentCompletedMet,
      value: firstAssessmentCompletedAt,
    },
    {
      label: "First app login",
      met: firstLoginMet,
      value: onboarding.first_app_login_at,
    },
    {
      label: "Assessment reviewed",
      met: assessmentReviewMet,
      value: onboarding.assessment_reviewed_at,
    },
  ] as const;

  const formatValue = (value: unknown) => {
    if (value === null || value === undefined || value === "") return "—";
    if (typeof value === "boolean") return value ? "Yes" : "No";
    return String(value);
  };
  const formatDateTime = (value: unknown) => {
    if (!value) return "—";
    const raw = String(value);
    const dt = new Date(raw);
    if (Number.isNaN(dt.getTime())) return raw;
    return dt
      .toLocaleString("en-GB", {
        day: "2-digit",
        month: "2-digit",
        year: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
        hour12: false,
        timeZone: "Europe/London",
      })
      .replace(",", "");
  };
  const formatDate = (value: unknown) => {
    if (!value) return "—";
    const raw = String(value);
    const dt = new Date(raw);
    if (Number.isNaN(dt.getTime())) return raw;
    return dt.toLocaleDateString("en-GB", {
      day: "2-digit",
      month: "2-digit",
      year: "2-digit",
      timeZone: "Europe/London",
    });
  };
  const formatJourneyValue = (label: unknown, detail?: unknown) => {
    const primary = label === null || label === undefined || label === "" ? "" : String(label);
    const secondary = detail === null || detail === undefined || detail === "" ? "" : String(detail);
    if (primary && secondary) return `${primary} · ${secondary}`;
    return primary || secondary || "—";
  };
  const tracker = appState?.tracker;
  const trackerPillars = Array.isArray(tracker?.pillars) ? tracker.pillars : [];
  const dailyPlan = appState?.daily_plan || null;
  const journey = appState?.journey;
  const journeyDailyRecording = journey?.daily_recording;
  const journeyDailyPlan = journey?.daily_plan;
  const journeyTodaysFocus = journey?.todays_focus;
  const journeyGiaMessage = journey?.gia_message;
  const journeyBiometrics = journey?.biometrics;
  const objectives = appState?.weekly_objectives;
  const wearables = appState?.wearables;
  const connectedWearables = (wearables?.providers || [])
    .filter((provider) => provider?.connected)
    .map((provider) => provider?.label || provider?.provider)
    .filter(Boolean)
    .join(", ");
  const biometrics = appState?.biometrics;
  const pillarJourneySummary =
    (journeyDailyRecording?.pillars || [])
      .map((pillar) => {
        const label = String(pillar?.label || pillar?.pillar_key || "Pillar").trim();
        const status = String(pillar?.status || "open").trim().toLowerCase();
        const statusLabel = status === "today" ? "today" : status === "yesterday" ? "yesterday" : "open";
        return `${label}: ${statusLabel}`;
      })
      .join(" · ") ||
    trackerPillars
      .map((pillar) => `${pillar.label || pillar.pillar_key}: ${pillar.today_complete ? "today" : "open"}`)
      .join(" · ");
  const restingHrCoverage = journeyBiometrics?.resting_hr_date
    ? `${journeyBiometrics.resting_hr_today ? "Today" : formatDate(journeyBiometrics.resting_hr_date)}${biometrics?.resting_hr_bpm != null ? ` · ${biometrics.resting_hr_bpm} bpm` : ""}`
    : "No recent reading";
  const hrvCoverage = journeyBiometrics?.hrv_date
    ? `${journeyBiometrics.hrv_today ? "Today" : formatDate(journeyBiometrics.hrv_date)}${biometrics?.hrv_ms != null ? ` · ${biometrics.hrv_ms} ms` : ""}`
    : "No recent reading";
  const stepsCoverage = journeyBiometrics?.steps_date
    ? `${journeyBiometrics.steps_today ? "Today" : formatDate(journeyBiometrics.steps_date)}${biometrics?.steps_today != null ? ` · ${biometrics.steps_today}` : ""}`
    : "No recent reading";
  const urineCoverage = journeyBiometrics?.urine_date
    ? `${journeyBiometrics.urine_today ? "Today" : formatDate(journeyBiometrics.urine_date)}${journeyBiometrics?.urine_status ? ` · ${journeyBiometrics.urine_status}` : ""}`
    : "No urine test recorded";

  return (
    <main className="min-h-screen bg-[#f7f4ee] px-6 py-10 text-[#1e1b16]">
      <div className="mx-auto w-full max-w-5xl space-y-6">
        <AdminNav
          title={
            typeof user?.display_name === "string"
              ? `Details · ${user.display_name}`
              : `Details · #${userId}`
          }
          subtitle="User profile fields and latest assessment metadata."
        />

        <section className="rounded-3xl border border-[#e7e1d6] bg-white p-6">
          <div className="grid gap-4 md:grid-cols-2">
            <div>
              <p className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Status</p>
              <p className="mt-2 text-lg font-semibold capitalize">{status || "unknown"}</p>
              <p className="mt-1 text-sm text-[#6b6257]">
                Latest run: {latest?.id ? `#${latest.id}` : "—"}
              </p>
            </div>
            <div>
              <p className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Latest run finished</p>
              <p className="mt-2 text-sm text-[#6b6257]">{latest?.finished_at || "—"}</p>
            </div>
          </div>

          <div className="mt-6 overflow-hidden rounded-2xl border border-[#efe7db]">
            <div className="border-b border-[#efe7db] bg-[#faf7f1] px-4 py-3">
              <p className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">First-day coaching</p>
            </div>
            <table className="w-full text-left text-sm">
              <tbody className="divide-y divide-[#efe7db]">
                <tr>
                  <td className="px-4 py-3 font-medium">First day coaching sent on</td>
                  <td className="px-4 py-3 text-[#6b6257]">{formatValue(onboarding.coaching_first_day_sent_at)}</td>
                </tr>
              </tbody>
            </table>
          </div>

          <div className="mt-6 overflow-hidden rounded-2xl border border-[#efe7db]">
            <div className="border-b border-[#efe7db] bg-[#faf7f1] px-4 py-3">
              <p className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Coaching activation essentials</p>
            </div>
            <table className="w-full text-left text-sm">
              <thead className="bg-[#faf7f1] text-xs uppercase tracking-[0.2em] text-[#6b6257]">
                <tr>
                  <th className="px-4 py-3">Requirement</th>
                  <th className="px-4 py-3">Met</th>
                  <th className="px-4 py-3">Timestamp / Value</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[#efe7db]">
                {essentialActivationRows.map((row) => (
                  <tr key={row.label}>
                    <td className="px-4 py-3 font-medium">{row.label}</td>
                    <td className="px-4 py-3 text-[#6b6257]">{formatValue(row.met)}</td>
                    <td className="px-4 py-3 text-[#6b6257]">{formatValue(row.value)}</td>
                  </tr>
                ))}
                <tr>
                  <td className="px-4 py-3 font-medium">Activation ready</td>
                  <td className="px-4 py-3 text-[#6b6257]">{formatValue(activationReady)}</td>
                  <td className="px-4 py-3 text-[#6b6257]">All requirements above must be Yes</td>
                </tr>
                <tr>
                  <td className="px-4 py-3 font-medium">Coaching enabled now</td>
                  <td className="px-4 py-3 text-[#6b6257]">{formatValue(coachingEnabledNow)}</td>
                  <td className="px-4 py-3 text-[#6b6257]">{formatValue(onboarding.coaching_auto_enabled_at)}</td>
                </tr>
              </tbody>
            </table>
            <details className="border-t border-[#efe7db]">
              <summary className="cursor-pointer px-4 py-3 text-xs uppercase tracking-[0.2em] text-[#6b6257]">
                More onboarding diagnostics
              </summary>
              <div className="overflow-hidden border-t border-[#efe7db]">
                <table className="w-full text-left text-sm">
                  <thead className="bg-[#faf7f1] text-xs uppercase tracking-[0.2em] text-[#6b6257]">
                    <tr>
                      <th className="px-4 py-3">Field</th>
                      <th className="px-4 py-3">Value</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-[#efe7db]">
                    {onboardingFields.map(([key, value]) => (
                      <tr key={key}>
                        <td className="px-4 py-3 font-medium">{key}</td>
                        <td className="px-4 py-3 text-[#6b6257]">{formatValue(value)}</td>
                      </tr>
                    ))}
                    <tr>
                      <td className="px-4 py-3 font-medium">intro_content_id</td>
                      <td className="px-4 py-3 text-[#6b6257]">{formatValue(introContent.content_id)}</td>
                    </tr>
                    <tr>
                      <td className="px-4 py-3 font-medium">intro_content_title</td>
                      <td className="px-4 py-3 text-[#6b6257]">{formatValue(introContent.title)}</td>
                    </tr>
                    <tr>
                      <td className="px-4 py-3 font-medium">intro_content_podcast_url</td>
                      <td className="px-4 py-3 text-[#6b6257]">{formatValue(introContent.podcast_url)}</td>
                    </tr>
                    <tr>
                      <td className="px-4 py-3 font-medium">intro_content_body_present</td>
                      <td className="px-4 py-3 text-[#6b6257]">{formatValue(introContent.body_present)}</td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </details>
          </div>

          <div className="mt-6 rounded-2xl border border-[#efe7db] bg-white p-5">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <p className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">User app snapshot</p>
                <h2 className="mt-2 text-lg font-semibold">Current user app state</h2>
                <p className="mt-1 text-sm text-[#6b6257]">
                  Read-only overview of the user&apos;s current daily journey in the user app.
                </p>
              </div>
              {appState?.today ? (
                <span className="rounded-full border border-[#efe7db] bg-[#fdfaf4] px-3 py-1 text-xs uppercase tracking-[0.2em] text-[#6b6257]">
                  {appState.today}
                </span>
              ) : null}
            </div>

            {appStateError ? (
              <p className="mt-4 rounded-2xl border border-[#f2c1b5] bg-[#fef1ee] px-4 py-3 text-sm text-[#8c1d1d]">
                User app snapshot unavailable: {appStateError}
              </p>
            ) : (
              <div className="mt-4 grid gap-4 md:grid-cols-2">
                <AppStateCard
                  eyebrow="Daily journey"
                  title={journeyDailyRecording?.summary_label || (tracker?.today_complete ? "Complete today" : "Incomplete today")}
                  rows={[
                    {
                      label: "Daily recording",
                      value: journeyDailyRecording?.summary_label,
                    },
                    {
                      label: "Pillars",
                      value: pillarJourneySummary,
                    },
                    { label: "Plan date", value: dailyPlan?.plan_date },
                    {
                      label: "Daily plan",
                      value: formatJourneyValue(journeyDailyPlan?.label, journeyDailyPlan?.detail),
                    },
                    {
                      label: "Today's focus",
                      value: formatJourneyValue(journeyTodaysFocus?.label, journeyTodaysFocus?.detail),
                    },
                    {
                      label: "Gia message",
                      value: formatJourneyValue(journeyGiaMessage?.label, journeyGiaMessage?.detail),
                    },
                  ]}
                />
                <AppStateCard
                  eyebrow="Biometric coverage"
                  title={biometrics?.training_readiness_label || biometrics?.training_readiness_status || "No readiness data"}
                  rows={[
                    { label: "Training readiness", value: biometrics?.training_readiness_label || biometrics?.training_readiness_status || "—" },
                    { label: "Resting HR", value: restingHrCoverage },
                    { label: "HRV", value: hrvCoverage },
                    { label: "Steps", value: stepsCoverage },
                    { label: "Urine test", value: urineCoverage },
                  ]}
                />
                <AppStateCard
                  eyebrow="Weekly objectives"
                  title={`${objectives?.configured_count ?? 0} configured`}
                  rows={[
                    { label: "Week start", value: objectives?.week?.start },
                    { label: "Week end", value: objectives?.week?.end },
                    {
                      label: "Sections",
                      value: (objectives?.sections || [])
                        .map((section) => `${section.label || section.key}: ${section.configured_count ?? 0}/${section.total_count ?? 0}`)
                        .join(" · "),
                    },
                  ]}
                />
                <AppStateCard
                  eyebrow="Wearables"
                  title={`${wearables?.connected_count ?? 0} connected`}
                  rows={[
                    { label: "Connected", value: connectedWearables || "—" },
                    {
                      label: "Latest metric",
                      value: (wearables?.providers || [])
                        .filter((provider) => provider?.latest_metric_date)
                        .map((provider) => `${provider.label || provider.provider}: ${provider.latest_metric_date}`)
                        .slice(0, 3)
                        .join(" · "),
                    },
                  ]}
                />
                <AppStateCard
                  eyebrow="Billing"
                  title={String(appState?.billing?.status || "Not configured")}
                  rows={[
                    { label: "Provider", value: appState?.billing?.provider },
                    { label: "Status", value: appState?.billing?.status },
                  ]}
                />
              </div>
            )}

            {appState?.errors?.length ? (
              <details className="mt-4 rounded-2xl border border-[#efe7db] bg-[#faf8f3] px-4 py-3 text-sm">
                <summary className="cursor-pointer text-xs uppercase tracking-[0.2em] text-[#6b6257]">
                  Snapshot section warnings
                </summary>
                <div className="mt-3 space-y-2 text-[#6b6257]">
                  {appState.errors.map((error, index) => (
                    <p key={`${error.section || "section"}-${index}`}>
                      {error.section || "section"}: {error.message || "unavailable"}
                    </p>
                  ))}
                </div>
              </details>
            ) : null}
          </div>

          <div className="mt-6 overflow-hidden rounded-2xl border border-[#efe7db]">
            <div className="border-b border-[#efe7db] bg-[#faf7f1] px-4 py-3">
              <p className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">User fields</p>
            </div>
            <table className="w-full text-left text-sm">
              <thead className="bg-[#faf7f1] text-xs uppercase tracking-[0.2em] text-[#6b6257]">
                <tr>
                  <th className="px-4 py-3">Field</th>
                  <th className="px-4 py-3">Value</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[#efe7db]">
                {fields.map(([key, value]) => (
                  <tr key={key}>
                    <td className="px-4 py-3 font-medium">{key}</td>
                    <td className="px-4 py-3 text-[#6b6257]">{formatValue(value)}</td>
                  </tr>
                ))}
                {!fields.length ? (
                  <tr>
                    <td className="px-4 py-6 text-[#6b6257]" colSpan={2}>
                      No user fields available.
                    </td>
                  </tr>
                ) : null}
              </tbody>
            </table>
          </div>

          <div className="mt-6 overflow-hidden rounded-2xl border border-[#efe7db]">
            <div className="border-b border-[#efe7db] bg-[#faf7f1] px-4 py-3">
              <p className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Current weekly plan</p>
            </div>
            {!weeklyPlan ? (
              <div className="px-4 py-4 text-sm text-[#6b6257]">No weekly plan found.</div>
            ) : (
              <div className="space-y-4 p-4">
                <div className="grid gap-3 md:grid-cols-3">
                  <div>
                    <p className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Week</p>
                    <p className="mt-1 text-sm font-medium">{formatValue(weeklyPlan.week_no)}</p>
                  </div>
                  <div>
                    <p className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Start</p>
                    <p className="mt-1 text-sm text-[#6b6257]">{formatDateTime(weeklyPlan.starts_on)}</p>
                  </div>
                  <div>
                    <p className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">End</p>
                    <p className="mt-1 text-sm text-[#6b6257]">{formatDateTime(weeklyPlan.ends_on)}</p>
                  </div>
                </div>
                <div className="grid gap-3 md:grid-cols-2">
                  <div>
                    <p className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Source</p>
                    <p className="mt-1 text-sm text-[#6b6257]">{formatValue(weeklyPlan.source)}</p>
                  </div>
                  <div>
                    <p className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Notes</p>
                    <p className="mt-1 text-sm text-[#6b6257]">{formatValue(weeklyPlan.notes)}</p>
                  </div>
                </div>
                <div className="overflow-x-auto rounded-xl border border-[#efe7db]">
                  <table className="w-full min-w-[900px] text-left text-sm">
                    <thead className="bg-[#faf7f1] text-xs uppercase tracking-[0.2em] text-[#6b6257]">
                      <tr>
                        <th className="px-3 py-2">Order</th>
                        <th className="px-3 py-2">KR</th>
                        <th className="px-3 py-2">Pillar</th>
                        <th className="px-3 py-2">Target</th>
                        <th className="px-3 py-2">Current</th>
                        <th className="px-3 py-2">Habit steps</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-[#efe7db]">
                      {weeklyPlanKrs.map((kr, idx) => {
                        const habits = Array.isArray(kr.habit_steps) ? (kr.habit_steps as Record<string, unknown>[]) : [];
                        return (
                          <tr key={String(kr.id || idx)}>
                            <td className="px-3 py-2 text-[#6b6257]">
                              {formatValue(kr.priority_order)} {kr.role ? `(${String(kr.role)})` : ""}
                            </td>
                            <td className="px-3 py-2">{formatValue(kr.description)}</td>
                            <td className="px-3 py-2 text-[#6b6257]">{formatValue(kr.pillar_key)}</td>
                            <td className="px-3 py-2 text-[#6b6257]">{formatValue(kr.target_num)}</td>
                            <td className="px-3 py-2 text-[#6b6257]">{formatValue(kr.actual_num)}</td>
                            <td className="px-3 py-2 text-[#6b6257]">
                              {habits.length ? (
                                <div className="space-y-1">
                                  {habits.map((step, stepIdx) => (
                                    <p key={String(step.id || `${idx}-${stepIdx}`)}>
                                      {String(step.text || "")}
                                      {step.status ? ` (${String(step.status)})` : ""}
                                    </p>
                                  ))}
                                </div>
                              ) : (
                                "—"
                              )}
                            </td>
                          </tr>
                        );
                      })}
                      {!weeklyPlanKrs.length ? (
                        <tr>
                          <td className="px-3 py-4 text-[#6b6257]" colSpan={6}>
                            No KRs linked to this weekly plan.
                          </td>
                        </tr>
                      ) : null}
                    </tbody>
                  </table>
                </div>
              </div>
            )}
          </div>

          <div className="mt-6">
            <Link
              className="rounded-full border border-[#efe7db] px-4 py-2 text-xs uppercase tracking-[0.2em]"
              href="/admin/users"
            >
              Back to users
            </Link>
          </div>
        </section>
      </div>
    </main>
  );
}
