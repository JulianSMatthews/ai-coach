import AdminNav from "@/components/AdminNav";
import CopyValueField from "@/components/CopyValueField";
import { getAdminMarketingFunnel } from "@/lib/api";

export const dynamic = "force-dynamic";

function normalizeHsAppBase(raw: string | null | undefined): string | null {
  const nodeEnv = (process.env.NODE_ENV || "").toLowerCase();
  const isDev = nodeEnv === "development";
  const isHosted =
    (process.env.ENV || "").toLowerCase() === "production" ||
    (process.env.RENDER || "").toLowerCase() === "true" ||
    Boolean((process.env.RENDER_EXTERNAL_URL || "").trim());
  const allowLocalInDev =
    isDev &&
    !isHosted &&
    (process.env.HSAPP_ALLOW_LOCALHOST_URLS || "").trim() === "1";
  const input = String(raw || "").trim();
  if (!input) return null;
  try {
    const parsed = new URL(input.startsWith("http://") || input.startsWith("https://") ? input : `https://${input}`);
    const host = parsed.hostname.toLowerCase();
    const isLocalHost =
      host === "localhost" ||
      host === "127.0.0.1" ||
      host === "0.0.0.0" ||
      host.endsWith(".local");
    if (isLocalHost && (!allowLocalInDev || isHosted)) return null;
    if (!isDev && parsed.protocol !== "https:") return null;
    return parsed.origin;
  } catch {
    return null;
  }
}

function resolveLandingPageBase(): string {
  const rawCandidates = [
    process.env.NEXT_PUBLIC_LANDING_PAGE_BASE_URL,
    process.env.LANDING_PAGE_PUBLIC_URL,
  ];
  for (const raw of rawCandidates) {
    const normalized = normalizeHsAppBase(raw);
    if (normalized) return normalized;
  }
  return "https://coachsense.ai";
}

type ReportingSearchParams = {
  tab?: string;
  period?: string;
  start?: string;
  end?: string;
  user_id?: string;
  source?: string;
  campaign?: string;
  launch_source?: string;
  launch_campaign?: string;
  launch_utm_source?: string;
  launch_utm_medium?: string;
  launch_utm_campaign?: string;
  launch_campaign_id?: string;
  launch_adset_id?: string;
  launch_ad_id?: string;
  launch_placement?: string;
  launch_site_source_name?: string;
  launch_intro_avatar?: string;
};

type ReportingTab = "launch" | "marketing";
type ReportingWindow = {
  period: string;
  days?: number;
  hours?: number;
  custom: boolean;
};

const REPORTING_PERIOD_OPTIONS = [
  { value: "3h", label: "Last 3 hours" },
  { value: "6h", label: "Last 6 hours" },
  { value: "12h", label: "Last 12 hours" },
  { value: "24h", label: "Last 24 hours" },
  { value: "7", label: "Last 7 days" },
  { value: "14", label: "Last 14 days" },
  { value: "30", label: "Last 30 days" },
  { value: "90", label: "Last 90 days" },
  { value: "custom", label: "Custom" },
] as const;

function getTrimmedParam(value: string | undefined, fallback = ""): string {
  const trimmed = typeof value === "string" ? value.trim() : "";
  return trimmed || fallback;
}

function resolveReportingTab(raw: string | undefined): ReportingTab {
  if (raw === "launch" || raw === "marketing") return raw;
  return "marketing";
}

function resolveReportingWindow(raw: string | undefined): ReportingWindow {
  const token = String(raw || "7").trim().toLowerCase();
  if (token === "custom") return { period: "custom", custom: true };
  const hourMatch = token.match(/^(\d+)h$/);
  if (hourMatch) {
    const hours = Math.max(1, Math.min(24 * 365, Number(hourMatch[1] || 24)));
    return { period: `${hours}h`, hours, custom: false };
  }
  const parsedDays = Number(token.replace(/d$/, ""));
  if (Number.isFinite(parsedDays) && parsedDays > 0) {
    const days = Math.max(1, Math.min(365, Math.trunc(parsedDays)));
    return { period: String(days), days, custom: false };
  }
  return { period: "7", days: 7, custom: false };
}

function buildReportingTabHref(params: ReportingSearchParams, tab: ReportingTab): string {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (typeof value !== "string") continue;
    const trimmed = value.trim();
    if (!trimmed || key === "tab") continue;
    query.set(key, trimmed);
  }
  query.set("tab", tab);
  return `/admin/reporting?${query.toString()}`;
}

function tabLinkClass(active: boolean): string {
  if (active) {
    return "rounded-full border border-[var(--accent)] bg-[var(--accent)] px-4 py-2 text-xs uppercase tracking-[0.2em] text-white";
  }
  return "rounded-full border border-[#efe7db] bg-[#fdfaf4] px-4 py-2 text-xs uppercase tracking-[0.2em] text-[#3c332b]";
}

function buildLaunchUrl(
  landingPageBase: string,
  leadStartKey: string,
  params: {
    source: string;
    campaign: string;
    utmSource: string;
    utmMedium: string;
    utmCampaign: string;
    campaignId: string;
    adsetId: string;
    adId: string;
    placement: string;
    siteSourceName: string;
    introAvatar?: string;
    isTest?: boolean;
  },
): string {
  const query = new URLSearchParams();
  if (leadStartKey) query.set("k", leadStartKey);
  if (params.isTest) query.set("test", "1");
  query.set("source", params.source);
  query.set("campaign", params.campaign);
  query.set("utm_source", params.utmSource);
  query.set("utm_medium", params.utmMedium);
  query.set("utm_campaign", params.utmCampaign);
  if (params.campaignId) query.set("campaign_id", params.campaignId);
  if (params.adsetId) query.set("adset_id", params.adsetId);
  if (params.adId) query.set("ad_id", params.adId);
  if (params.placement) query.set("placement", params.placement);
  if (params.siteSourceName) query.set("site_source_name", params.siteSourceName);
  if (params.introAvatar === "1" || params.introAvatar === "0") {
    query.set("intro_avatar", params.introAvatar);
  }
  return `${landingPageBase}/ig/start?${query.toString()}`;
}

export default async function ReportingPage({
  searchParams,
}: {
  searchParams: Promise<ReportingSearchParams>;
}) {
  const resolvedSearchParams = (await searchParams) || {};
  const activeTab = resolveReportingTab(
    typeof resolvedSearchParams?.tab === "string" ? resolvedSearchParams.tab : undefined,
  );
  const windowSelection = resolveReportingWindow(
    typeof resolvedSearchParams?.period === "string" ? resolvedSearchParams.period : "7",
  );
  const period = windowSelection.period;
  const start = typeof resolvedSearchParams?.start === "string" ? resolvedSearchParams.start : undefined;
  const end = typeof resolvedSearchParams?.end === "string" ? resolvedSearchParams.end : undefined;
  const userIdRaw = typeof resolvedSearchParams?.user_id === "string" ? resolvedSearchParams.user_id : "";
  const sourceRaw = typeof resolvedSearchParams?.source === "string" ? resolvedSearchParams.source : "";
  const campaignRaw = typeof resolvedSearchParams?.campaign === "string" ? resolvedSearchParams.campaign : "";
  const launchSourceRaw =
    typeof resolvedSearchParams?.launch_source === "string" ? resolvedSearchParams.launch_source : "";
  const launchCampaignRaw =
    typeof resolvedSearchParams?.launch_campaign === "string" ? resolvedSearchParams.launch_campaign : "";
  const launchUtmSourceRaw =
    typeof resolvedSearchParams?.launch_utm_source === "string" ? resolvedSearchParams.launch_utm_source : "";
  const launchUtmMediumRaw =
    typeof resolvedSearchParams?.launch_utm_medium === "string" ? resolvedSearchParams.launch_utm_medium : "";
  const launchUtmCampaignRaw =
    typeof resolvedSearchParams?.launch_utm_campaign === "string" ? resolvedSearchParams.launch_utm_campaign : "";
  const launchCampaignIdRaw =
    typeof resolvedSearchParams?.launch_campaign_id === "string"
      ? resolvedSearchParams.launch_campaign_id
      : "";
  const launchAdsetIdRaw =
    typeof resolvedSearchParams?.launch_adset_id === "string" ? resolvedSearchParams.launch_adset_id : "";
  const launchAdIdRaw =
    typeof resolvedSearchParams?.launch_ad_id === "string" ? resolvedSearchParams.launch_ad_id : "";
  const launchPlacementRaw =
    typeof resolvedSearchParams?.launch_placement === "string" ? resolvedSearchParams.launch_placement : "";
  const launchSiteSourceNameRaw =
    typeof resolvedSearchParams?.launch_site_source_name === "string"
      ? resolvedSearchParams.launch_site_source_name
      : "";
  const launchIntroAvatarRaw =
    typeof resolvedSearchParams?.launch_intro_avatar === "string"
      ? resolvedSearchParams.launch_intro_avatar
      : "";
  const userId = userIdRaw ? Number(userIdRaw) : undefined;

  const marketing = await getAdminMarketingFunnel({
    days: windowSelection.days,
    hours: windowSelection.hours,
    start: windowSelection.custom ? start : undefined,
    end: windowSelection.custom ? end : undefined,
    user_id: Number.isFinite(userId) ? userId : undefined,
    source: sourceRaw || undefined,
    campaign: campaignRaw || undefined,
  });
  const landingPageBase = resolveLandingPageBase();
  const leadStartKey = (process.env.PUBLIC_LEAD_START_KEY || "").trim();
  const sourceToken = getTrimmedParam(launchSourceRaw || sourceRaw, "instagram");
  const campaignToken = getTrimmedParam(launchCampaignRaw || campaignRaw, "assessment_launch");
  const utmSourceToken = getTrimmedParam(launchUtmSourceRaw, sourceToken);
  const utmMediumToken = getTrimmedParam(launchUtmMediumRaw, "paid_social");
  const utmCampaignToken = getTrimmedParam(launchUtmCampaignRaw, campaignToken);
  const campaignIdToken = getTrimmedParam(launchCampaignIdRaw);
  const adsetIdToken = getTrimmedParam(launchAdsetIdRaw);
  const adIdToken = getTrimmedParam(launchAdIdRaw);
  const placementToken = getTrimmedParam(launchPlacementRaw);
  const siteSourceNameToken = getTrimmedParam(launchSiteSourceNameRaw);
  const introAvatarToken = getTrimmedParam(launchIntroAvatarRaw, "1") === "0" ? "0" : "1";
  const metaLaunchUrl = buildLaunchUrl(landingPageBase, leadStartKey, {
    source: sourceToken,
    campaign: campaignToken,
    utmSource: utmSourceToken,
    utmMedium: utmMediumToken,
    utmCampaign: utmCampaignToken,
    campaignId: campaignIdToken,
    adsetId: adsetIdToken,
    adId: adIdToken,
    placement: placementToken,
    siteSourceName: siteSourceNameToken,
    introAvatar: introAvatarToken,
  });
  const previewLaunchUrl = metaLaunchUrl;
  const testLaunchUrl = buildLaunchUrl(landingPageBase, leadStartKey, {
    source: sourceToken,
    campaign: campaignToken,
    utmSource: utmSourceToken,
    utmMedium: "test",
    utmCampaign: utmCampaignToken,
    campaignId: campaignIdToken,
    adsetId: adsetIdToken,
    adId: adIdToken,
    placement: placementToken,
    siteSourceName: siteSourceNameToken,
    introAvatar: introAvatarToken,
    isTest: true,
  });
  const avatarTestLaunchUrl = buildLaunchUrl(landingPageBase, leadStartKey, {
    source: sourceToken,
    campaign: campaignToken,
    utmSource: utmSourceToken,
    utmMedium: "test",
    utmCampaign: utmCampaignToken,
    campaignId: campaignIdToken,
    adsetId: adsetIdToken,
    adId: adIdToken,
    placement: placementToken,
    siteSourceName: siteSourceNameToken,
    introAvatar: "1",
    isTest: true,
  });
  const noAvatarTestLaunchUrl = buildLaunchUrl(landingPageBase, leadStartKey, {
    source: sourceToken,
    campaign: campaignToken,
    utmSource: utmSourceToken,
    utmMedium: "test",
    utmCampaign: utmCampaignToken,
    campaignId: campaignIdToken,
    adsetId: adsetIdToken,
    adId: adIdToken,
    placement: placementToken,
    siteSourceName: siteSourceNameToken,
    introAvatar: "0",
    isTest: true,
  });
  const launchTabHref = buildReportingTabHref(resolvedSearchParams, "launch");
  const marketingTabHref = buildReportingTabHref(resolvedSearchParams, "marketing");

  return (
    <main className="min-h-screen bg-[#f7f4ee] px-6 py-10 text-[#1e1b16]">
      <div className="mx-auto w-full max-w-5xl space-y-6">
        <AdminNav
          title="Reporting"
          subtitle="Landing URL and marketing reporting."
        />

        <section className="rounded-3xl border border-[#e7e1d6] bg-white p-6">
          <p className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Tabs</p>
          <div className="mt-3 flex flex-wrap gap-3">
            <a
              href={launchTabHref}
              className={tabLinkClass(activeTab === "launch")}
            >
              Landing URL
            </a>
            <a
              href={marketingTabHref}
              className={tabLinkClass(activeTab === "marketing")}
            >
              Marketing
            </a>
          </div>
        </section>

        {activeTab === "launch" ? (
          <section id="reporting-launch" className="rounded-3xl border border-[#e7e1d6] bg-white p-6">
            <div className="flex flex-wrap items-end justify-between gap-4">
              <div>
                <p className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Landing URL</p>
                <p className="mt-2 text-sm text-[#6b6257]">
                  Generate a live or test landing URL with the parameters you want to send.
                </p>
              </div>
            </div>
            <div className="mt-4 rounded-2xl border border-[#efe7db] bg-[#fdfaf4] p-4">
              <p className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Launch URL builder</p>
              <form method="get" className="mt-4 grid gap-3 md:grid-cols-2 xl:grid-cols-3">
                <input type="hidden" name="tab" value="launch" />
                <input type="hidden" name="period" value={period} />
                <input type="hidden" name="start" value={start || ""} />
                <input type="hidden" name="end" value={end || ""} />
                <input type="hidden" name="user_id" value={userIdRaw} />
                <input type="hidden" name="source" value={sourceRaw} />
                <input type="hidden" name="campaign" value={campaignRaw} />
                <div>
                  <label className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Source</label>
                  <input
                    type="text"
                    name="launch_source"
                    defaultValue={sourceToken}
                    className="mt-2 w-full rounded-xl border border-[#efe7db] bg-white px-3 py-2 text-sm"
                  />
                </div>
                <div>
                  <label className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Campaign</label>
                  <input
                    type="text"
                    name="launch_campaign"
                    defaultValue={campaignToken}
                    className="mt-2 w-full rounded-xl border border-[#efe7db] bg-white px-3 py-2 text-sm"
                  />
                </div>
                <div>
                  <label className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">UTM source</label>
                  <input
                    type="text"
                    name="launch_utm_source"
                    defaultValue={utmSourceToken}
                    className="mt-2 w-full rounded-xl border border-[#efe7db] bg-white px-3 py-2 text-sm"
                  />
                </div>
                <div>
                  <label className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">UTM medium</label>
                  <input
                    type="text"
                    name="launch_utm_medium"
                    defaultValue={utmMediumToken}
                    className="mt-2 w-full rounded-xl border border-[#efe7db] bg-white px-3 py-2 text-sm"
                  />
                </div>
                <div>
                  <label className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">UTM campaign</label>
                  <input
                    type="text"
                    name="launch_utm_campaign"
                    defaultValue={utmCampaignToken}
                    className="mt-2 w-full rounded-xl border border-[#efe7db] bg-white px-3 py-2 text-sm"
                  />
                </div>
                <div>
                  <label className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Campaign ID</label>
                  <input
                    type="text"
                    name="launch_campaign_id"
                    defaultValue={campaignIdToken}
                    className="mt-2 w-full rounded-xl border border-[#efe7db] bg-white px-3 py-2 text-sm"
                  />
                </div>
                <div>
                  <label className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Adset ID</label>
                  <input
                    type="text"
                    name="launch_adset_id"
                    defaultValue={adsetIdToken}
                    className="mt-2 w-full rounded-xl border border-[#efe7db] bg-white px-3 py-2 text-sm"
                  />
                </div>
                <div>
                  <label className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Ad ID</label>
                  <input
                    type="text"
                    name="launch_ad_id"
                    defaultValue={adIdToken}
                    className="mt-2 w-full rounded-xl border border-[#efe7db] bg-white px-3 py-2 text-sm"
                  />
                </div>
                <div>
                  <label className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Placement</label>
                  <input
                    type="text"
                    name="launch_placement"
                    defaultValue={placementToken}
                    className="mt-2 w-full rounded-xl border border-[#efe7db] bg-white px-3 py-2 text-sm"
                  />
                </div>
                <div>
                  <label className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Site source name</label>
                  <input
                    type="text"
                    name="launch_site_source_name"
                    defaultValue={siteSourceNameToken}
                    className="mt-2 w-full rounded-xl border border-[#efe7db] bg-white px-3 py-2 text-sm"
                  />
                </div>
                <div>
                  <label className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Landing intro avatar</label>
                  <select
                    name="launch_intro_avatar"
                    defaultValue={introAvatarToken}
                    className="mt-2 w-full rounded-xl border border-[#efe7db] bg-white px-3 py-2 text-sm"
                  >
                    <option value="1">On</option>
                    <option value="0">Off</option>
                  </select>
                </div>
                <div className="md:col-span-2 xl:col-span-3">
                  <button
                    type="submit"
                    className="rounded-full border border-[var(--accent)] bg-[var(--accent)] px-5 py-2 text-xs uppercase tracking-[0.2em] text-white"
                  >
                    Generate launch URLs
                  </button>
                </div>
              </form>
              <p className="mt-3 text-sm text-[#6b6257]">
                Shared key: {leadStartKey ? "included automatically" : "not set on healthsense-admin"}
              </p>
              <p className="mt-1 text-sm text-[#6b6257]">
                Landing intro avatar: {introAvatarToken === "1" ? "on" : "off"}
              </p>
              <div className="mt-3">
                <p className="mb-2 text-xs uppercase tracking-[0.2em] text-[#6b6257]">Live URL</p>
                <CopyValueField value={metaLaunchUrl} />
              </div>
              <div className="mt-3">
                <p className="mb-2 text-xs uppercase tracking-[0.2em] text-[#6b6257]">Test URL</p>
                <CopyValueField value={testLaunchUrl} buttonLabel="Copy test URL" />
              </div>
              <div className="mt-4 flex flex-wrap gap-3">
                <a
                  href={previewLaunchUrl}
                  target="_blank"
                  rel="noreferrer"
                  className="rounded-full border border-[#efe7db] bg-white px-4 py-2 text-xs uppercase tracking-[0.2em] text-[#3c332b]"
                >
                  Open live landing
                </a>
                <a
                  href={testLaunchUrl}
                  target="_blank"
                  rel="noreferrer"
                  className="rounded-full border border-[var(--accent)] bg-[var(--accent)] px-4 py-2 text-xs uppercase tracking-[0.2em] text-white"
                >
                  Open test landing
                </a>
                <a
                  href={avatarTestLaunchUrl}
                  target="_blank"
                  rel="noreferrer"
                  className="rounded-full border border-[#efe7db] bg-white px-4 py-2 text-xs uppercase tracking-[0.2em] text-[#3c332b]"
                >
                  Open test landing with avatar
                </a>
                <a
                  href={noAvatarTestLaunchUrl}
                  target="_blank"
                  rel="noreferrer"
                  className="rounded-full border border-[#efe7db] bg-white px-4 py-2 text-xs uppercase tracking-[0.2em] text-[#3c332b]"
                >
                  Open test landing without avatar
                </a>
              </div>
              <p className="mt-3 text-sm text-[#6b6257]">
                Test launches are marked as test traffic and excluded from this reporting funnel.
              </p>
            </div>
          </section>
        ) : null}

        {activeTab === "marketing" ? (
        <section id="reporting-marketing" className="rounded-3xl border border-[#e7e1d6] bg-white p-6">
          <div className="flex flex-wrap items-end justify-between gap-4">
            <div>
              <p className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Marketing</p>
              <p className="mt-2 text-sm text-[#6b6257]">
                Window: {marketing?.window?.start_utc ?? "—"} → {marketing?.window?.end_utc ?? "—"}
              </p>
            </div>
            <div className="max-w-md rounded-2xl border border-[#efe7db] bg-[#fdfaf4] px-4 py-3 text-sm text-[#6b6257]">
              Acquisition reporting now follows website interest and app activation. Confirmed store downloads will be
              added when App Store Connect and Google Play reporting are connected.
            </div>
          </div>
          <form method="get" className="mt-4 flex flex-wrap items-end gap-3">
            <input type="hidden" name="tab" value="marketing" />
            <input type="hidden" name="launch_source" value={launchSourceRaw} />
            <input type="hidden" name="launch_campaign" value={launchCampaignRaw} />
            <input type="hidden" name="launch_utm_source" value={launchUtmSourceRaw} />
            <input type="hidden" name="launch_utm_medium" value={launchUtmMediumRaw} />
            <input type="hidden" name="launch_utm_campaign" value={launchUtmCampaignRaw} />
            <input type="hidden" name="launch_campaign_id" value={launchCampaignIdRaw} />
            <input type="hidden" name="launch_adset_id" value={launchAdsetIdRaw} />
            <input type="hidden" name="launch_ad_id" value={launchAdIdRaw} />
            <input type="hidden" name="launch_placement" value={launchPlacementRaw} />
            <input type="hidden" name="launch_site_source_name" value={launchSiteSourceNameRaw} />
            <input type="hidden" name="launch_intro_avatar" value={introAvatarToken} />
            <div>
              <label className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Period</label>
              <select
                name="period"
                defaultValue={period}
                className="mt-2 w-full rounded-xl border border-[#efe7db] bg-white px-3 py-2 text-sm"
              >
                {REPORTING_PERIOD_OPTIONS.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Start</label>
              <input
                type="date"
                name="start"
                defaultValue={start || ""}
                className="mt-2 w-full rounded-xl border border-[#efe7db] bg-white px-3 py-2 text-sm"
              />
            </div>
            <div>
              <label className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">End</label>
              <input
                type="date"
                name="end"
                defaultValue={end || ""}
                className="mt-2 w-full rounded-xl border border-[#efe7db] bg-white px-3 py-2 text-sm"
              />
            </div>
            <button
              type="submit"
              className="rounded-full border border-[var(--accent)] bg-[var(--accent)] px-5 py-2 text-xs uppercase tracking-[0.2em] text-white"
            >
              Run marketing report
            </button>
          </form>
          <div className="mt-4 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            <div className="rounded-2xl border border-[#1d6a4f] bg-[#eef8f3] p-4">
              <p className="text-xs uppercase tracking-[0.2em] text-[#35634f]">coachsense.ai homepage views</p>
              <p className="mt-2 text-2xl font-semibold text-[#153f30]">
                {marketing?.acquisition?.coachsense_ai_homepage_views ?? 0}
              </p>
              <p className="mt-1 text-xs text-[#527363]">Page loads in the selected window</p>
            </div>
            <div className="rounded-2xl border border-[#d5cbbd] bg-[#fdfaf4] p-4">
              <p className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Download button clicks</p>
              <p className="mt-2 text-2xl font-semibold">{marketing?.acquisition?.download_button_clicks ?? 0}</p>
              <p className="mt-1 text-xs text-[#8a8176]">Interest signal, not a confirmed download</p>
            </div>
            <div className="rounded-2xl border border-[#1d4ed8] bg-[#eef4ff] p-4">
              <p className="text-xs uppercase tracking-[0.2em] text-[#365e9d]">First app activations</p>
              <p className="mt-2 text-2xl font-semibold text-[#193f78]">{marketing?.acquisition?.first_app_activations ?? 0}</p>
              <p className="mt-1 text-xs text-[#5875a1]">Users reaching their first app login</p>
            </div>
            <div className="rounded-2xl border border-dashed border-[#c9c0b4] bg-[#f7f4ee] p-4">
              <p className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Confirmed store downloads</p>
              <p className="mt-2 text-2xl font-semibold">—</p>
              <p className="mt-1 text-xs text-[#8a8176]">Awaiting Apple and Google store connections</p>
            </div>
          </div>

          <div className="mt-4">
            <details className="rounded-2xl border border-[#efe7db] bg-white" open>
              <summary className="cursor-pointer px-4 py-3 text-sm font-medium text-[#3c332b]">
                Download clicks by source ({marketing?.acquisition?.download_clicks_by_source?.length ?? 0})
              </summary>
              <div className="overflow-x-auto border-t border-[#efe7db]">
                <table className="min-w-full text-left text-sm">
                  <thead className="bg-[#f7f4ee] text-xs uppercase tracking-[0.2em] text-[#6b6257]">
                    <tr>
                      <th className="px-4 py-3">Source</th>
                      <th className="px-4 py-3">Download button clicks</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(marketing?.acquisition?.download_clicks_by_source || []).map((row) => (
                      <tr key={row.source} className="border-t border-[#efe7db]">
                        <td className="px-4 py-3">{row.source || "unknown"}</td>
                        <td className="px-4 py-3">{row.clicks ?? 0}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </details>
          </div>
        </section>
        ) : null}

      </div>
    </main>
  );
}
