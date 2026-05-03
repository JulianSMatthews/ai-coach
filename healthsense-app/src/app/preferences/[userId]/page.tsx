import { getUserStatus, getWearables } from "@/lib/api";
import { Card, PageShell, SectionHeader } from "@/components/ui";
import PreferencesForm from "./PreferencesForm";
import WearablesPanel from "./WearablesPanel";
import TextScale from "@/components/TextScale";
import AppNav from "@/components/AppNav";
import { DEFAULT_TEXT_SCALE_STRING } from "@/lib/textScale";

type PageProps = {
  params: Promise<{ userId: string }>;
  searchParams?: Promise<Record<string, string | string[] | undefined>>;
};

export default async function PreferencesPage(props: PageProps) {
  const { userId } = await props.params;
  const searchParams = props.searchParams ? await props.searchParams : {};
  const [data, wearables] = await Promise.all([
    getUserStatus(userId),
    getWearables(userId),
  ]);
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
      <SectionHeader
        eyebrow="Coaching preferences"
        title="Coach my coach"
        subtitle={`${displayFirstName} · Your preferences & delivery`}
      />

      <section className="grid gap-6">
        <Card className="shadow-[0_20px_70px_-50px_rgba(30,27,22,0.35)]">
          <h2 className="text-xl">Set your preferences</h2>
          <div className="mt-4">
            <PreferencesForm
              userId={String(userId)}
              initialEmail={user.email || ""}
              initialNote={prefs.note || ""}
              initialTextScale={prefs.text_scale || DEFAULT_TEXT_SCALE_STRING}
              initialTrainingObjective={prefs.training_objective || ""}
            />
          </div>
        </Card>

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
