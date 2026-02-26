import Link from "next/link";
import AdminNav from "@/components/AdminNav";
import { getAdminUserDetails } from "@/lib/api";

type UserStatusPageProps = {
  params: Promise<{ userId: string }>;
};

export const dynamic = "force-dynamic";

export default async function UserStatusPage({ params }: UserStatusPageProps) {
  const resolvedParams = await params;
  const userId = Number(resolvedParams.userId);
  const detail = await getAdminUserDetails(userId);
  const user = detail.user as Record<string, unknown> | undefined;
  const status = detail.status as string | undefined;
  const latest = detail.latest_run as { id?: number; finished_at?: string } | undefined;
  const onboarding = (detail.onboarding || {}) as Record<string, unknown>;
  const onboardingChecks = (onboarding.checks || {}) as Record<string, unknown>;
  const introContent = (onboarding.intro_content || {}) as Record<string, unknown>;
  const weeklyPlan = (detail.current_weekly_plan || null) as Record<string, unknown> | null;
  const weeklyPlanKrs = Array.isArray(weeklyPlan?.krs) ? (weeklyPlan?.krs as Record<string, unknown>[]) : [];
  const fields = user ? Object.entries(user) : [];
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
  const checkFields = [
    ["assessment_completed_met", onboardingChecks.assessment_completed_met],
    ["first_login_met", onboardingChecks.first_login_met],
    ["assessment_review_met", onboardingChecks.assessment_review_met],
    ["intro_completed_met", onboardingChecks.intro_completed_met],
    ["coaching_activation_ready", onboardingChecks.coaching_activation_ready],
    ["coaching_enabled_now", onboardingChecks.coaching_enabled_now],
    ["coaching_auto_enabled_recorded", onboardingChecks.coaching_auto_enabled_recorded],
    ["intro_should_show_now", onboardingChecks.intro_should_show_now],
  ] as const;
  const essentialActivationRows = [
    {
      label: "First Assessment Completed",
      met: onboardingChecks.assessment_completed_met,
      value: onboarding.first_assessment_completed_at || onboarding.assessment_completed_at,
    },
    {
      label: "First app login",
      met: onboardingChecks.first_login_met,
      value: onboarding.first_app_login_at,
    },
    {
      label: "Assessment reviewed",
      met: onboardingChecks.assessment_review_met,
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
                <tr>
                  <td className="px-4 py-3 font-medium">Sent recorded</td>
                  <td className="px-4 py-3 text-[#6b6257]">
                    {formatValue(onboardingChecks.coaching_first_day_sent_recorded)}
                  </td>
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
                  <td className="px-4 py-3 text-[#6b6257]">{formatValue(onboardingChecks.coaching_activation_ready)}</td>
                  <td className="px-4 py-3 text-[#6b6257]">All requirements above must be Yes</td>
                </tr>
                <tr>
                  <td className="px-4 py-3 font-medium">Coaching enabled now</td>
                  <td className="px-4 py-3 text-[#6b6257]">{formatValue(onboardingChecks.coaching_enabled_now)}</td>
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
                    {checkFields.map(([key, value]) => (
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
