import { getUserStatus } from "@/lib/api";
import { Badge, Card, PageShell, SectionHeader } from "@/components/ui";
import PreferencesForm from "./PreferencesForm";
import TextScale from "@/components/TextScale";
import LogoutButton from "@/components/LogoutButton";
import MobileTabBar from "@/components/MobileTabBar";

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
      <nav className="sticky top-0 z-10 -mx-6 mb-4 hidden flex-wrap items-center gap-2 border-y border-[#efe7db] bg-[#fbf7f0]/90 px-6 py-3 text-xs uppercase tracking-[0.2em] text-[#6b6257] backdrop-blur md:static md:mx-0 md:mb-6 md:flex md:border md:border-[#efe7db] md:rounded-full md:px-6 md:py-3">
        <a href={`/progress/${userId}`} className="flex items-center" aria-label="HealthSense home">
          <img src="/healthsense-logo.svg" alt="HealthSense" className="h-6 w-auto" />
        </a>
        <a className="rounded-full border border-[#efe7db] bg-white px-3 py-1" href={`/progress/${userId}`}>
          Home
        </a>
        <a className="rounded-full border border-[#efe7db] bg-white px-3 py-1" href={`/assessment/${userId}`}>
          Assessment
        </a>
        <a className="rounded-full border border-[#efe7db] bg-white px-3 py-1" href={`/library/${userId}`}>
          Library
        </a>
        <a className="rounded-full border border-[#efe7db] bg-white px-3 py-1" href={`/preferences/${userId}`}>
          Preferences
        </a>
        <a className="rounded-full border border-[#efe7db] bg-white px-3 py-1" href={`/history/${userId}`}>
          History
        </a>
        {promptBadge ? <Badge label={promptBadge} /> : null}
        <LogoutButton />
      </nav>
      <MobileTabBar userId={userId} active="preferences" />
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
