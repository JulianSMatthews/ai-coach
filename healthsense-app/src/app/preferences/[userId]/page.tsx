import { getUserStatus } from "@/lib/api";
import Link from "next/link";
import { Card, PageShell } from "@/components/ui";
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
  const nutritionPillarEnabled = isTruthyToken(prefs.home_pillar_nutrition);
  const trainingPillarEnabled = isTruthyToken(prefs.home_pillar_training);
  const promptState = (data.prompt_state_override || "").toLowerCase();
  const promptBadge =
    promptState && promptState !== "live"
      ? `${promptState.charAt(0).toUpperCase()}${promptState.slice(1)} mode`
      : "";

  return (
    <PageShell defaultTheme={themePreference}>
      <TextScale defaultScale={textScale} />
      <AppNav
        userId={userId}
        promptBadge={promptBadge}
        interactionDaysCount={data.engagement_summary?.interaction_days_count ?? null}
        userFirstName={user.first_name || null}
      />

      <section className="grid gap-4">
        <Link
          href={`/assessment/${encodeURIComponent(userId)}/chat`}
          className="flex h-11 w-11 items-center justify-center rounded-full border border-[var(--border)] bg-[var(--surface)] text-[var(--text-primary)] shadow-[0_10px_26px_-22px_rgba(30,27,22,0.45)]"
          aria-label="Back to home"
        >
          <span className="text-3xl leading-none">‹</span>
        </Link>
        <Card className="shadow-[0_20px_70px_-50px_rgba(30,27,22,0.35)]">
          <h2 className="text-base font-semibold">Set your preferences</h2>
          <div className="mt-4">
            <PreferencesForm
              userId={String(userId)}
              initialEmail={user.email || ""}
              initialTheme={themePreference}
              initialNutritionPillarEnabled={nutritionPillarEnabled}
              initialTrainingPillarEnabled={trainingPillarEnabled}
            />
          </div>
        </Card>
      </section>

    </PageShell>
  );
}
