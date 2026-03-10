import { getUserStatus } from "@/lib/api";
import { Card, PageShell, SectionHeader } from "@/components/ui";
import TextScale from "@/components/TextScale";
import AppNav from "@/components/AppNav";
import AssessmentChatBox from "./AssessmentChatBox";

function isTruthyToken(value: string | string[] | undefined): boolean {
  const raw = Array.isArray(value) ? value[0] : value;
  const token = String(raw || "").trim().toLowerCase();
  return token === "1" || token === "true" || token === "yes" || token === "on";
}

type PageProps = {
  params: Promise<{ userId: string }>;
  searchParams?: Promise<Record<string, string | string[] | undefined>>;
};

export default async function AssessmentChatPage(props: PageProps) {
  const { userId } = await props.params;
  const resolvedSearchParams = (await props.searchParams) || {};
  const leadFlow = isTruthyToken(resolvedSearchParams.lead);
  const status = await getUserStatus(userId);
  const prefs = status.coaching_preferences || {};
  const user = status.user || {};
  const textScale = prefs.text_scale ? Number.parseFloat(prefs.text_scale) : undefined;
  const promptState = (status.prompt_state_override || "").toLowerCase();
  const promptBadge =
    promptState && promptState !== "live"
      ? `${promptState.charAt(0).toUpperCase()}${promptState.slice(1)} mode`
      : "";
  const displayName = user.display_name || user.first_name || "User";
  const displayFirstName = displayName.split(" ")[0];

  return (
    <PageShell>
      <TextScale defaultScale={textScale} />
      {!leadFlow ? <AppNav userId={userId} promptBadge={promptBadge} /> : null}
      <SectionHeader
        brandMark={
          <a href={`/assessment/${userId}/chat`} className="inline-flex items-center gap-2" aria-label="HealthSense">
            <img src="/healthsense-logo.svg" alt="HealthSense" className="h-8 w-auto" />
          </a>
        }
        eyebrow="Coach Chat"
        title="My Coach Gia"
        subtitle={
          leadFlow
            ? `${displayFirstName} · Let’s complete your assessment now`
            : `${displayFirstName} · Chat with Gia directly in the app`
        }
      />

      <section className="grid gap-6">
        <Card className="shadow-[0_20px_70px_-50px_rgba(30,27,22,0.35)]">
          <p className="text-sm text-[#6b6257]">
            This chat runs in-app with Gia and starts with your assessment flow.
          </p>
          <div className="mt-5">
            <AssessmentChatBox userId={userId} />
          </div>
        </Card>
      </section>
    </PageShell>
  );
}
