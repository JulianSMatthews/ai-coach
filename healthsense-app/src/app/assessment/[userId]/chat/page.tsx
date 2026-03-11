import { cookies } from "next/headers";
import { getUserStatus, type UserStatusResponse } from "@/lib/api";
import { Card, PageShell, SectionHeader } from "@/components/ui";
import TextScale from "@/components/TextScale";
import AppNav from "@/components/AppNav";
import AssessmentChatBox from "./AssessmentChatBox";
import LeadAssessmentBranding from "./LeadAssessmentBranding";

function isTruthyToken(value: string | string[] | undefined): boolean {
  const raw = Array.isArray(value) ? value[0] : value;
  const token = String(raw || "").trim().toLowerCase();
  return token === "1" || token === "true" || token === "yes" || token === "on";
}

function parseApiErrorMessage(error: unknown): { status?: number; message: string } {
  const raw = error instanceof Error ? error.message : String(error || "");
  const match = raw.match(/^API\s+(\d+)\s+/i);
  const status = match ? Number.parseInt(match[1], 10) : undefined;
  return { status, message: raw };
}

type PageProps = {
  params: Promise<{ userId: string }>;
  searchParams?: Promise<Record<string, string | string[] | undefined>>;
};

function firstSearchValue(value: string | string[] | undefined): string {
  return String(Array.isArray(value) ? value[0] : value || "").trim();
}

export default async function AssessmentChatPage(props: PageProps) {
  const { userId } = await props.params;
  const resolvedSearchParams = (await props.searchParams) || {};
  const chatPath = `/assessment/${encodeURIComponent(userId)}/chat${isTruthyToken(resolvedSearchParams.lead) ? "?lead=1" : ""}`;
  const reloginHref = `/login?next=${encodeURIComponent(chatPath)}`;
  const leadFlow = isTruthyToken(resolvedSearchParams.lead);
  const leadGuest = String(userId || "").trim().toLowerCase() === "lead";
  const cookieStore = await cookies();
  const leadToken = String(cookieStore.get("hs_lead_token")?.value || "").trim();
  const leadTokenParam = firstSearchValue(resolvedSearchParams.lt);

  const leadHeaderTitle = <LeadAssessmentBranding />;

  if (leadFlow && leadGuest && !leadToken && !leadTokenParam) {
    return (
      <PageShell className="px-4 py-6 sm:px-6 sm:py-8" contentClassName="space-y-6">
        <SectionHeader title={leadHeaderTitle} />
        <Card className="shadow-[0_20px_70px_-50px_rgba(30,27,22,0.35)]">
          <h2 className="text-xl">Assessment link expired</h2>
          <p className="mt-2 text-sm text-[#6b6257]">
            This link no longer has an active lead session. Reopen the latest assessment link to start a new session.
          </p>
        </Card>
      </PageShell>
    );
  }

  let status: UserStatusResponse = {};
  let statusLoadError: { status?: number; message: string } | null = null;
  if (!leadGuest) {
    try {
      status = await getUserStatus(userId);
    } catch (error) {
      statusLoadError = parseApiErrorMessage(error);
    }
  }
  const prefs = status.coaching_preferences || {};
  const textScale = prefs.text_scale ? Number.parseFloat(prefs.text_scale) : undefined;
  const promptState = (status.prompt_state_override || "").toLowerCase();
  const promptBadge =
    promptState && promptState !== "live"
      ? `${promptState.charAt(0).toUpperCase()}${promptState.slice(1)} mode`
      : "";
  const assessmentCompleted =
    status.status === "completed" ||
    Boolean(status.onboarding?.assessment_completed_at) ||
    Boolean(status.latest_run?.finished_at);
  const assessmentInProgress = status.status === "in_progress";
  const chatIntroText = assessmentCompleted
    ? "Your assessment is complete. Continue coaching with Gia in this chat."
    : assessmentInProgress
      ? ""
      : leadFlow
        ? ""
        : "Start your assessment with Gia here. Each question will guide you one step at a time.";
  if (statusLoadError && !leadFlow) {
    const shouldRelogin = statusLoadError.status === 401 || statusLoadError.status === 403;
    return (
      <PageShell className="px-4 py-6 sm:px-6 sm:py-8" contentClassName="space-y-6">
        <SectionHeader title="My Coach Gia" />
        <Card className="shadow-[0_20px_70px_-50px_rgba(30,27,22,0.35)]">
          <h2 className="text-xl">My Coach Gia is unavailable</h2>
          <p className="mt-2 text-sm text-[#6b6257]">
            {shouldRelogin
              ? "Your session may have expired. Sign in again to continue."
              : "We couldn’t load this chat right now. Please try again shortly."}
          </p>
          <div className="mt-4 flex flex-wrap gap-2">
            <a
              href={shouldRelogin ? reloginHref : chatPath}
              className="rounded-full border border-[var(--accent)] bg-[var(--accent)] px-4 py-2 text-xs uppercase tracking-[0.2em] text-white"
            >
              {shouldRelogin ? "sign in again" : "try again"}
            </a>
            <a
              href={`/assessment/${encodeURIComponent(userId)}`}
              className="rounded-full border border-[#efe7db] px-4 py-2 text-xs uppercase tracking-[0.2em]"
            >
              view assessment
            </a>
          </div>
        </Card>
      </PageShell>
    );
  }

  return (
    <PageShell className="px-4 py-6 sm:px-6 sm:py-8" contentClassName="space-y-6">
      <TextScale defaultScale={textScale} />
      {!leadFlow ? <AppNav userId={userId} promptBadge={promptBadge} /> : null}
      {!leadFlow ? <SectionHeader title="My Coach Gia" /> : null}

      <section className="space-y-4">
        {chatIntroText ? <p className="text-sm text-[#6b6257]">{chatIntroText}</p> : null}
        <AssessmentChatBox
          userId={userId}
          assessmentCompleted={assessmentCompleted}
          isLeadGuest={leadGuest}
          leadToken={leadToken || leadTokenParam || undefined}
          showLeadBranding={leadFlow}
        />
      </section>
    </PageShell>
  );
}
