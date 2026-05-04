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

  return (
    <PageShell defaultTheme={themePreference}>
      <TextScale defaultScale={textScale} />
      <AppNav userId={userId} promptBadge={promptBadge} />

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
