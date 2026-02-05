import { getUserStatus } from "@/lib/api";
import { Card, PageShell, SectionHeader } from "@/components/ui";
import PreferencesForm from "./PreferencesForm";
import TextScale from "@/components/TextScale";
import AppNav from "@/components/AppNav";

type PageProps = {
  params: Promise<{ userId: string }>;
};

export default async function PreferencesPage(props: PageProps) {
  const { userId } = await props.params;
  const data = await getUserStatus(userId);
  const user = data.user || {};
  const prefs = data.coaching_preferences || {};
  const textScale = prefs.text_scale ? Number.parseFloat(prefs.text_scale) : undefined;
  const promptState = (data.prompt_state_override || "").toLowerCase();
  const promptBadge =
    promptState && promptState !== "live"
      ? `${promptState.charAt(0).toUpperCase()}${promptState.slice(1)} mode`
      : "";

  return (
    <PageShell>
      <TextScale defaultScale={textScale} />
      <AppNav userId={userId} promptBadge={promptBadge} />
      <SectionHeader
        eyebrow="Coaching preferences"
        title="Coach my coach"
        subtitle={`${user.display_name || user.first_name || "User"} · Preferences & delivery`}
      />

      <section className="grid gap-6">
        <Card className="shadow-[0_20px_70px_-50px_rgba(30,27,22,0.35)]">
          <h2 className="text-xl">Set your preferences</h2>
          <div className="mt-4">
            <PreferencesForm
              userId={String(userId)}
              initialEmail={user.email || ""}
              initialNote={prefs.note || ""}
              initialVoice={prefs.voice || ""}
              initialSchedule={prefs.schedule || {}}
              initialTextScale={prefs.text_scale || "1.0"}
              initialTrainingObjective={prefs.training_objective || ""}
              initialPreferredChannel={prefs.preferred_channel || "whatsapp"}
              initialMarketingOptIn={prefs.marketing_opt_in || ""}
            />
          </div>
        </Card>
      </section>

      <section className="mt-6 grid gap-6 lg:grid-cols-[1fr_1fr]">
        <Card>
          <h2 className="text-xl">Update via WhatsApp</h2>
          <p className="mt-3 text-sm text-[#6b6257]">
            Send these commands from your WhatsApp number to update preferences.
          </p>
          <ul className="mt-4 space-y-2 text-sm text-[#3c332b]">
            <li>coachmycoach &lt;note&gt;</li>
            <li>coachmycoach clear</li>
            <li>coachmycoach male | female</li>
            <li>coachmycoach time &lt;day&gt; &lt;HH:MM&gt;</li>
          </ul>
        </Card>
      </section>
    </PageShell>
  );
}
