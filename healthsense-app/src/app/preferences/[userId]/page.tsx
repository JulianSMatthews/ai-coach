import { getUserStatus } from "@/lib/api";
import Link from "next/link";
import { PageShell } from "@/components/ui";
import PreferencesForm from "./PreferencesForm";
import TextScale from "@/components/TextScale";
import AppNav from "@/components/AppNav";

type PageProps = {
  params: Promise<{ userId: string }>;
};

function isTruthyToken(value: string | string[] | undefined): boolean {
  const raw = Array.isArray(value) ? value[0] : value;
  const token = String(raw || "").trim().toLowerCase();
  return token === "1" || token === "true" || token === "yes" || token === "on";
}

export default async function PreferencesPage(props: PageProps) {
  const { userId } = await props.params;
  const data = await getUserStatus(userId);
  const user = data.user || {};
  const prefs = data.coaching_preferences || {};
  const textScale = prefs.text_scale ? Number.parseFloat(prefs.text_scale) : undefined;
  const themePreference = prefs.theme || "light";
  const promptState = (data.prompt_state_override || "").toLowerCase();
  const promptBadge =
    promptState && promptState !== "live"
      ? `${promptState.charAt(0).toUpperCase()}${promptState.slice(1)} mode`
      : "";
  const defaultPillarKeys = new Set(["reflection", "purpose", "resilience", "recovery"]);
  const initialPillarSelections = Object.fromEntries(
    ["reflection", "purpose", "resilience", "recovery"].map((key) => {
      const raw = String((prefs as Record<string, unknown>)[`home_pillar_${key}`] || "").trim().toLowerCase();
      const selected = raw ? isTruthyToken(raw) : defaultPillarKeys.has(key);
      return [key, selected];
    }),
  );

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
          userFirstName={user.first_name || null}
        />
      </div>

      <section className="coach-scrollbar mx-auto flex min-h-0 w-full max-w-4xl flex-1 flex-col gap-4 overflow-x-hidden overflow-y-auto">
        <Link
          href="/"
          className="flex h-11 w-11 items-center justify-center rounded-full border border-[var(--border)] bg-[var(--surface)] text-[var(--text-primary)] shadow-[0_10px_26px_-22px_rgba(30,27,22,0.45)]"
          aria-label="Back to home"
        >
          <span className="text-3xl leading-none">‹</span>
        </Link>
        <PreferencesForm
          userId={String(userId)}
          initialEmail={user.email || ""}
          initialTheme={themePreference}
          initialPillarSelections={initialPillarSelections}
        />
      </section>

    </PageShell>
  );
}
