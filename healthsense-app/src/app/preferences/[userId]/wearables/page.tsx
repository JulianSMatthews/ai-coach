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
  const prefs = data.coaching_preferences || {};
  const textScale = prefs.text_scale ? Number.parseFloat(prefs.text_scale) : undefined;
  const themePreference = prefs.theme || "light";
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
          interactionDaysCount={data.engagement_summary?.interaction_days_count ?? null}
          userFirstName={data.user?.first_name || null}
        />
      </div>

      <section className="coach-scrollbar mx-auto min-h-0 w-full max-w-4xl flex-1 overflow-x-hidden overflow-y-auto">
        <Card className="shadow-[0_20px_70px_-50px_rgba(30,27,22,0.35)]">
          <WearablesPanel
            userId={String(userId)}
            providers={wearables.providers || []}
            initialMessage={wearableMessage}
            initialStatus={wearableStatus}
          />
        </Card>
      </section>
    </PageShell>
  );
}
