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
  const themePreference = prefs.theme || "dark";
  const promptState = (data.prompt_state_override || "").toLowerCase();
  const promptBadge =
    promptState && promptState !== "live"
      ? `${promptState.charAt(0).toUpperCase()}${promptState.slice(1)} mode`
      : "";
  const displayName = user.display_name || user.first_name || "User";
  const displayFirstName = displayName.split(" ")[0];

  return (
    <PageShell defaultTheme={themePreference}>
      <TextScale defaultScale={textScale} />
      <AppNav userId={userId} promptBadge={promptBadge} />
      <SectionHeader
        eyebrow="Preferences"
        title="Preferences"
        subtitle={`${displayFirstName} · Account and display`}
      />

      <section className="grid gap-6">
        <Card className="shadow-[0_20px_70px_-50px_rgba(30,27,22,0.35)]">
          <h2 className="text-xl">Set your preferences</h2>
          <div className="mt-4">
            <PreferencesForm
              userId={String(userId)}
              initialEmail={user.email || ""}
              initialTheme={themePreference}
            />
          </div>
        </Card>
      </section>

    </PageShell>
  );
}
