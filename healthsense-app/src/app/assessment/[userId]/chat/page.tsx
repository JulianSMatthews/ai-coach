import Image from "next/image";
import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { getUserStatus, type UserStatusResponse } from "@/lib/api";
import { PageShell, SectionHeader } from "@/components/ui";
import TextScale from "@/components/TextScale";
import AppNav from "@/components/AppNav";
import AssessmentChatBox from "./AssessmentChatBox";

function isTruthyToken(value: string | string[] | undefined): boolean {
  const raw = Array.isArray(value) ? value[0] : value;
  const token = String(raw || "").trim().toLowerCase();
  return token === "1" || token === "true" || token === "yes" || token === "on";
}

type PageProps = {
  params: Promise<{ userId: string }>;
  searchParams?: Promise<Record<string, string | string[] | undefined>>;
};

export default async function AssessmentChatPage(props: PageProps) {
  const { userId } = await props.params;
  const resolvedSearchParams = (await props.searchParams) || {};
  const leadFlow = isTruthyToken(resolvedSearchParams.lead);
  const leadGuest = String(userId || "").trim().toLowerCase() === "lead";
  const cookieStore = await cookies();
  const sessionUserId = String(cookieStore.get("hs_user_id")?.value || "").trim();
  const leadToken = String(cookieStore.get("hs_lead_token")?.value || "").trim();

  if (leadFlow && leadGuest && !leadToken && /^\d+$/.test(sessionUserId)) {
    redirect(`/assessment/${encodeURIComponent(sessionUserId)}/chat?lead=1`);
  }

  const status: UserStatusResponse = leadGuest ? {} : await getUserStatus(userId);
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
      ? "Your assessment is in progress. Continue with Gia here using the guided question cards."
      : leadFlow
        ? ""
        : "Start your assessment with Gia here. Each question will guide you one step at a time.";

  return (
    <PageShell className="px-4 py-6 sm:px-6 sm:py-8" contentClassName="space-y-6">
      <TextScale defaultScale={textScale} />
      {!leadFlow ? <AppNav userId={userId} promptBadge={promptBadge} /> : null}
      <SectionHeader
        title={
          leadFlow ? (
            <span className="inline-flex flex-wrap items-center gap-3">
              <Image src="/healthsense-mark.svg" alt="HealthSense" width={34} height={34} className="h-8 w-8 flex-none" />
              <span>Find out your HealthSense Score</span>
            </span>
          ) : (
            "My Coach Gia"
          )
        }
      />

      <section className="space-y-4">
        {chatIntroText ? <p className="text-sm text-[#6b6257]">{chatIntroText}</p> : null}
        <AssessmentChatBox userId={userId} assessmentCompleted={assessmentCompleted} isLeadGuest={leadGuest} />
      </section>
    </PageShell>
  );
}
