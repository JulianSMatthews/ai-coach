import { getUserStatus, getWearables } from "@/lib/api";
import AppNav from "@/components/AppNav";
import TextScale from "@/components/TextScale";
import { Card, PageShell } from "@/components/ui";
import WearablesPanel from "../WearablesPanel";

type PageProps = {
  params: Promise<{ userId: string }>;
  searchParams?: Promise<Record<string, string | string[] | undefined>>;
};

export default async function WearablesPage(props: PageProps) {
  const { userId } = await props.params;
  const searchParams = props.searchParams ? await props.searchParams : {};
  const [data, wearables] = await Promise.all([getUserStatus(userId), getWearables(userId)]);
  const user = data.user || {};
  const prefs = data.coaching_preferences || {};
  const textScale = prefs.text_scale ? Number.parseFloat(prefs.text_scale) : undefined;
  const themePreference = prefs.theme || "dark";
  const promptState = (data.prompt_state_override || "").toLowerCase();
  const promptBadge =
    promptState && promptState !== "live"
      ? `${promptState.charAt(0).toUpperCase()}${promptState.slice(1)} mode`
      : "";
  const firstValue = (value: string | string[] | undefined) =>
    String(Array.isArray(value) ? value[0] : value || "").trim();
  const wearableStatus = firstValue(searchParams?.wearable_status);
  const wearableMessage = firstValue(searchParams?.wearable_message) || null;
  const displayName = user.display_name || user.first_name || "User";
  const displayFirstName = displayName.split(" ")[0];

  return (
    <PageShell defaultTheme={themePreference}>
      <TextScale defaultScale={textScale} />
      <AppNav userId={userId} promptBadge={promptBadge} />
      <header className="rounded-3xl border border-[var(--border-strong)] bg-[var(--surface-translucent)] p-4 shadow-[0_30px_80px_-60px_var(--shadow-strong)] backdrop-blur">
        <p className="text-[11px] uppercase tracking-[0.22em] text-[var(--text-secondary)]">Wearables</p>
        <h1 className="mt-2 text-[22px] leading-7">Wearables</h1>
        <p className="mt-1 text-[13px] text-[var(--text-secondary)]">{displayFirstName} · Connected health data</p>
      </header>

      <Card className="shadow-[0_20px_70px_-50px_rgba(30,27,22,0.35)]">
        <WearablesPanel
          userId={String(userId)}
          providers={wearables.providers || []}
          initialMessage={wearableMessage}
          initialStatus={wearableStatus}
        />
      </Card>
    </PageShell>
  );
}
