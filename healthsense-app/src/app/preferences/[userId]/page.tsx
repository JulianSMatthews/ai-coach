import { getUserStatus } from "@/lib/api";
import { Card, PageShell } from "@/components/ui";
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
      <header className="rounded-3xl border border-[var(--border-strong)] bg-[var(--surface-translucent)] p-4 shadow-[0_30px_80px_-60px_var(--shadow-strong)] backdrop-blur">
        <p className="text-[11px] uppercase tracking-[0.22em] text-[var(--text-secondary)]">Preferences</p>
        <h1 className="mt-2 text-[22px] leading-7">Preferences</h1>
        <p className="mt-1 text-[13px] text-[var(--text-secondary)]">{displayFirstName} · Account and display</p>
      </header>

      <section className="grid gap-6">
        <Card className="shadow-[0_20px_70px_-50px_rgba(30,27,22,0.35)]">
          <h2 className="text-base font-semibold">Set your preferences</h2>
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
