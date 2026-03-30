import { cookies } from "next/headers";
import {
  getPillarTrackerSummary,
  getUserStatus,
  type PillarTrackerSummaryResponse,
  type UserStatusResponse,
} from "@/lib/api";
import { Card, PageShell, SectionHeader } from "@/components/ui";
import TextScale from "@/components/TextScale";
import AssessmentChatBox from "./AssessmentChatBox";
import LeadAssessmentBranding from "./LeadAssessmentBranding";
import LatestAssessmentPanel from "./LatestAssessmentPanel";
import type { AssessmentIntroAvatar } from "./AssessmentPromptCard";

type AppIntroHelpVideos = {
  habits?: AssessmentIntroAvatar | null;
  insight?: AssessmentIntroAvatar | null;
  ask?: AssessmentIntroAvatar | null;
  dailyTracking?: AssessmentIntroAvatar | null;
};

type IntroLibraryMediaBundle = {
  appIntroAvatar: AssessmentIntroAvatar | null;
  coachProductAvatar: AssessmentIntroAvatar | null;
  helpVideos: AppIntroHelpVideos;
};

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

function getApiBaseUrl(): string {
  const base = String(process.env.API_BASE_URL || "").trim();
  if (!base) {
    throw new Error("API_BASE_URL is not set");
  }
  return base.replace(/\/+$/, "");
}

function getAdminHeaders(): Record<string, string> {
  const token = String(process.env.ADMIN_API_TOKEN || "").trim();
  const adminUserId = String(process.env.ADMIN_USER_ID || "").trim();
  if (!token || !adminUserId) {
    throw new Error("ADMIN_API_TOKEN or ADMIN_USER_ID is not set");
  }
  return {
    "X-Admin-Token": token,
    "X-Admin-User-Id": adminUserId,
  };
}

async function getAssessmentIntroAvatar(forceEnabled = false): Promise<AssessmentIntroAvatar | null> {
  const avatarEnabled = isTruthyToken(process.env.NEXT_PUBLIC_ASSESSMENT_INTRO_AVATAR_ENABLED);
  const fallbackUrl = String(process.env.NEXT_PUBLIC_ASSESSMENT_INTRO_AVATAR_URL || "").trim();
  const fallbackPosterUrl = String(process.env.NEXT_PUBLIC_ASSESSMENT_INTRO_AVATAR_POSTER || "").trim();
  const fallbackTitle = String(
    process.env.NEXT_PUBLIC_ASSESSMENT_INTRO_AVATAR_TITLE || "Assessment introduction",
  ).trim();
  if (!forceEnabled && !avatarEnabled) {
    return null;
  }
  const fallbackAvatar: AssessmentIntroAvatar | null = fallbackUrl
    ? {
        url: fallbackUrl,
        title: fallbackTitle,
        posterUrl: fallbackPosterUrl || null,
      }
    : null;
  try {
    const res = await fetch(`${getApiBaseUrl()}/admin/library/assessment-intro`, {
      method: "GET",
      headers: getAdminHeaders(),
      cache: "no-store",
    });
    if (!res.ok) {
      return fallbackAvatar;
    }
    const payload = (await res.json().catch(() => ({}))) as {
      active?: boolean;
      assessment_intro_avatar?: {
        url?: string | null;
        title?: string | null;
        script?: string | null;
        poster_url?: string | null;
      } | null;
    };
    if (!payload.active) {
      return fallbackAvatar;
    }
    const avatar = payload.assessment_intro_avatar || null;
    const url = String(avatar?.url || "").trim() || fallbackUrl;
    if (!url) {
      return fallbackAvatar;
    }
    return {
      url,
      title: String(avatar?.title || "").trim() || fallbackTitle,
      posterUrl: String(avatar?.poster_url || "").trim() || fallbackPosterUrl || null,
      script: String(avatar?.script || "").trim() || null,
    };
  } catch {
    return fallbackAvatar;
  }
}

function mapIntroAvatar(
  avatar:
    | {
        url?: string | null;
        title?: string | null;
        script?: string | null;
        poster_url?: string | null;
      }
    | null
    | undefined,
  fallbackTitle: string,
): AssessmentIntroAvatar | null {
  const url = String(avatar?.url || "").trim();
  const title = String(avatar?.title || "").trim();
  const script = String(avatar?.script || "").trim();
  const posterUrl = String(avatar?.poster_url || "").trim();
  if (!url && !script && !title) {
    return null;
  }
  return {
    url: url || null,
    title: title || fallbackTitle,
    script: script || null,
    posterUrl: posterUrl || null,
  };
}

async function getAppIntroLibraryMedia(): Promise<IntroLibraryMediaBundle> {
  try {
    const res = await fetch(`${getApiBaseUrl()}/admin/library/intro`, {
      method: "GET",
      headers: getAdminHeaders(),
      cache: "no-store",
    });
    if (!res.ok) {
      return {
        appIntroAvatar: null,
        coachProductAvatar: null,
        helpVideos: {},
      };
    }
    const payload = (await res.json().catch(() => ({}))) as {
      app_intro_avatar?: {
        url?: string | null;
        title?: string | null;
        script?: string | null;
        poster_url?: string | null;
      } | null;
      coach_product_avatar?: {
        url?: string | null;
        title?: string | null;
        script?: string | null;
        poster_url?: string | null;
      } | null;
      app_habits_avatar?: {
        url?: string | null;
        title?: string | null;
        script?: string | null;
        poster_url?: string | null;
      } | null;
      app_insight_avatar?: {
        url?: string | null;
        title?: string | null;
        script?: string | null;
        poster_url?: string | null;
      } | null;
      app_ask_avatar?: {
        url?: string | null;
        title?: string | null;
        script?: string | null;
        poster_url?: string | null;
      } | null;
      app_daily_tracking_avatar?: {
        url?: string | null;
        title?: string | null;
        script?: string | null;
        poster_url?: string | null;
      } | null;
    };
    return {
      appIntroAvatar: mapIntroAvatar(payload.app_intro_avatar, "Welcome to HealthSense"),
      coachProductAvatar: mapIntroAvatar(payload.coach_product_avatar, "How HealthSense works"),
      helpVideos: {
        habits: mapIntroAvatar(payload.app_habits_avatar, "Habits"),
        insight: mapIntroAvatar(payload.app_insight_avatar, "Insight"),
        ask: mapIntroAvatar(payload.app_ask_avatar, "Ask"),
        dailyTracking: mapIntroAvatar(payload.app_daily_tracking_avatar, "Daily tracking"),
      },
    };
  } catch {
    return {
      appIntroAvatar: null,
      coachProductAvatar: null,
      helpVideos: {},
    };
  }
}

type PageProps = {
  params: Promise<{ userId: string }>;
  searchParams?: Promise<Record<string, string | string[] | undefined>>;
};

function firstSearchValue(value: string | string[] | undefined): string {
  return String(Array.isArray(value) ? value[0] : value || "").trim();
}

function resolveIntroAvatarOverride(value: string | string[] | undefined): boolean | null {
  const token = firstSearchValue(value).toLowerCase();
  if (!token) return null;
  if (token === "0" || token === "false" || token === "no" || token === "off") return false;
  if (token === "1" || token === "true" || token === "yes" || token === "on") return true;
  return null;
}

export default async function AssessmentChatPage(props: PageProps) {
  const { userId } = await props.params;
  const resolvedSearchParams = (await props.searchParams) || {};
  const pageShellClassName = "px-3 py-4 sm:px-5 sm:py-6";
  const pageContentClassName = "mx-auto max-w-4xl space-y-4 sm:space-y-5";
  const chatPath = `/assessment/${encodeURIComponent(userId)}/chat${isTruthyToken(resolvedSearchParams.lead) ? "?lead=1" : ""}`;
  const reloginHref = `/login?next=${encodeURIComponent(chatPath)}`;
  const leadFlow = isTruthyToken(resolvedSearchParams.lead);
  const leadGuest = String(userId || "").trim().toLowerCase() === "lead";
  const cookieStore = await cookies();
  const leadToken = String(cookieStore.get("hs_lead_token")?.value || "").trim();
  const leadTokenParam = firstSearchValue(resolvedSearchParams.lt);
  const introAvatarOverride = resolveIntroAvatarOverride(resolvedSearchParams.intro_avatar);
  const defaultIntroAvatarEnabled = isTruthyToken(process.env.NEXT_PUBLIC_ASSESSMENT_INTRO_AVATAR_ENABLED);
  const shouldLoadAssessmentIntroAvatar =
    leadFlow &&
    (introAvatarOverride === true || (introAvatarOverride !== false && defaultIntroAvatarEnabled));
  const assessmentIntroAvatar = shouldLoadAssessmentIntroAvatar
    ? await getAssessmentIntroAvatar(introAvatarOverride === true)
    : null;
  const introLibraryMedia = await getAppIntroLibraryMedia();
  const coachProductAvatar = introLibraryMedia.coachProductAvatar;

  const leadHeaderTitle = <LeadAssessmentBranding />;

  if (leadFlow && leadGuest && !leadToken && !leadTokenParam) {
    return (
      <PageShell className={pageShellClassName} contentClassName={pageContentClassName}>
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
  const onboarding = status.onboarding || {};
  const textScale = prefs.text_scale ? Number.parseFloat(prefs.text_scale) : undefined;
  const themePreference = prefs.theme || "dark";
  const assessmentCompleted =
    status.status === "completed" ||
    Boolean(onboarding.assessment_completed_at) ||
    Boolean(status.latest_run?.finished_at);
  const assessmentInProgress = status.status === "in_progress";
  const chatIntroText = assessmentCompleted
    ? ""
    : assessmentInProgress
      ? ""
      : leadFlow
      ? ""
      : "Start your assessment with Gia here. Each question will guide you one step at a time.";
  let pillarTrackerSummary: PillarTrackerSummaryResponse | null = null;
  if (!leadFlow && !leadGuest && assessmentCompleted && !assessmentInProgress) {
    try {
      pillarTrackerSummary = await getPillarTrackerSummary(userId);
    } catch {
      pillarTrackerSummary = null;
    }
  }
  if (statusLoadError && !leadFlow) {
    const shouldRelogin = statusLoadError.status === 401 || statusLoadError.status === 403;
    return (
      <PageShell defaultTheme={themePreference} className={pageShellClassName} contentClassName={pageContentClassName}>
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
          </div>
        </Card>
      </PageShell>
    );
  }

  return (
    <PageShell defaultTheme={themePreference} className={pageShellClassName} contentClassName={pageContentClassName}>
      <TextScale defaultScale={textScale} />

      <section className="space-y-3 sm:space-y-4">
        {chatIntroText ? <p className="text-sm text-[#6b6257]">{chatIntroText}</p> : null}
        <AssessmentChatBox
          userId={userId}
          assessmentCompleted={assessmentCompleted}
          isLeadGuest={leadGuest}
          leadToken={leadToken || leadTokenParam || undefined}
          showLeadBranding={leadFlow}
          introAvatar={assessmentIntroAvatar}
          coachProductAvatar={coachProductAvatar}
          introAvatarEnabledOverride={introAvatarOverride}
          initialTrackerSummary={pillarTrackerSummary}
        />
        {pillarTrackerSummary ? (
          <LatestAssessmentPanel
            userId={userId}
            initialSummary={pillarTrackerSummary}
            initialAssessmentCombinedScore={status.latest_run?.combined_overall ?? null}
            initialAssessmentReviewed={Boolean(onboarding.assessment_reviewed_at)}
          />
        ) : null}
      </section>
    </PageShell>
  );
}
