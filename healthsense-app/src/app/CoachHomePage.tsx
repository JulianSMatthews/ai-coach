import {
  getPillarTrackerSummary,
  getUserStatus,
  type PillarTrackerSummaryResponse,
  type UserStatusResponse,
} from "@/lib/api";
import AppNav from "@/components/AppNav";
import TextScale from "@/components/TextScale";
import { Card, PageShell } from "@/components/ui";
import AssessmentChatBox from "./assessment/[userId]/chat/AssessmentChatBox";
import CoachHomeTrackerPanel from "./CoachHomeTrackerPanel";

function parseApiErrorMessage(error: unknown): { status?: number; message: string } {
  const raw = error instanceof Error ? error.message : String(error || "");
  const match = raw.match(/^API\s+(\d+)\s+/i);
  const status = match ? Number.parseInt(match[1], 10) : undefined;
  return { status, message: raw };
}

export default async function CoachHomePage({ userId }: { userId: string }) {
  let status: UserStatusResponse = {};
  let statusLoadError: { status?: number; message: string } | null = null;
  try {
    status = await getUserStatus(userId);
  } catch (error) {
    statusLoadError = parseApiErrorMessage(error);
  }

  const prefs = status.coaching_preferences || {};
  const onboarding = status.onboarding || {};
  const textScale = prefs.text_scale ? Number.parseFloat(prefs.text_scale) : undefined;
  const themePreference = prefs.theme || "light";
  const promptState = (status.prompt_state_override || "").toLowerCase();
  const promptBadge =
    promptState && promptState !== "live"
      ? `${promptState.charAt(0).toUpperCase()}${promptState.slice(1)} mode`
      : "";

  let pillarTrackerSummary: PillarTrackerSummaryResponse | null = null;
  if (!statusLoadError) {
    try {
      pillarTrackerSummary = await getPillarTrackerSummary(userId);
    } catch {
      pillarTrackerSummary = null;
    }
  }

  if (statusLoadError) {
    const lowerStatusMessage = statusLoadError.message.toLowerCase();
    const shouldRelogin =
      statusLoadError.status === 401 ||
      statusLoadError.status === 403 ||
      statusLoadError.status === 404 ||
      lowerStatusMessage.includes("user not found") ||
      lowerStatusMessage.includes("invalid session") ||
      lowerStatusMessage.includes("session required");
    return (
      <PageShell defaultTheme={themePreference} className="px-3 py-4 sm:px-5 sm:py-6" contentClassName="flex min-h-[70dvh] items-center justify-center">
        <Card className="w-full max-w-[24rem] text-center shadow-[0_20px_70px_-50px_rgba(30,27,22,0.35)]">
          <p className="text-[1.75rem] font-semibold leading-tight text-[var(--text-primary)]">
            {shouldRelogin
              ? "Your session may have expired. Sign in again to continue."
              : "CoachSense is being worked on. Please try again shortly."}
          </p>
          <div className="mt-5">
            <a
              href={shouldRelogin ? `/login?resetSession=1&next=${encodeURIComponent("/")}` : "/"}
              className="inline-flex min-h-12 w-full items-center justify-center rounded-full border border-[var(--action-primary-border)] bg-[var(--action-primary-bg)] px-5 py-3 text-sm font-semibold text-[var(--action-primary-text)] transition active:scale-[0.98] sm:w-auto"
            >
              {shouldRelogin ? "Sign in again" : "Try again"}
            </a>
          </div>
        </Card>
      </PageShell>
    );
  }

  return (
    <PageShell
      defaultTheme={themePreference}
      className="h-[100dvh] overflow-hidden px-0 py-0 pt-[env(safe-area-inset-top)]"
      contentClassName="flex h-full min-w-0 flex-col overflow-hidden"
    >
      <TextScale defaultScale={textScale} />
      <div className="mx-auto w-full max-w-4xl shrink-0">
        <AppNav
          userId={userId}
          promptBadge={promptBadge}
          overallScore={status.latest_run?.combined_overall ?? null}
          interactionDaysCount={status.engagement_summary?.interaction_days_count ?? null}
          userFirstName={status.user?.first_name || null}
        />
      </div>

      <section className="min-h-0 flex-1 overflow-x-hidden">
        <AssessmentChatBox
          userId={userId}
          assessmentCompleted
          modernHomeOnly
          initialTrackerSummary={pillarTrackerSummary}
          initialInteractionDaysCount={status.engagement_summary?.interaction_days_count ?? null}
        />
        <CoachHomeTrackerPanel
          userId={userId}
          initialSummary={pillarTrackerSummary}
          initialAssessmentReviewed={Boolean(onboarding.assessment_reviewed_at)}
          initialInteractionDaysCount={status.engagement_summary?.interaction_days_count ?? null}
        />
      </section>
    </PageShell>
  );
}
