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
  const fields = user ? Object.entries(user) : [];
  const onboardingFields = [
    ["first_app_login_at", onboarding.first_app_login_at],
    ["assessment_reviewed_at", onboarding.assessment_reviewed_at],
    ["intro_content_presented_at", onboarding.intro_content_presented_at],
    ["intro_content_listened_at", onboarding.intro_content_listened_at],
    ["intro_content_read_at", onboarding.intro_content_read_at],
    ["intro_content_completed_at", onboarding.intro_content_completed_at],
    ["coaching_auto_enabled_at", onboarding.coaching_auto_enabled_at],
  ] as const;
  const checkFields = [
    ["intro_flow_enabled", onboardingChecks.intro_flow_enabled],
    ["intro_content_published", onboardingChecks.intro_content_published],
    ["intro_content_has_audio", onboardingChecks.intro_content_has_audio],
    ["intro_content_has_read", onboardingChecks.intro_content_has_read],
    ["intro_should_show_now", onboardingChecks.intro_should_show_now],
    ["first_login_met", onboardingChecks.first_login_met],
    ["assessment_review_met", onboardingChecks.assessment_review_met],
    ["intro_completed_met", onboardingChecks.intro_completed_met],
    ["coaching_activation_ready", onboardingChecks.coaching_activation_ready],
    ["coaching_enabled_now", onboardingChecks.coaching_enabled_now],
    ["coaching_auto_enabled_recorded", onboardingChecks.coaching_auto_enabled_recorded],
  ] as const;

  const formatValue = (value: unknown) => {
    if (value === null || value === undefined || value === "") return "—";
    if (typeof value === "boolean") return value ? "Yes" : "No";
    return String(value);
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
              <p className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Onboarding diagnostics</p>
            </div>
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
