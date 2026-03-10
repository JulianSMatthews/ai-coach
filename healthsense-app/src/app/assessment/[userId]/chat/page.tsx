import { getUserStatus } from "@/lib/api";
import { Card, PageShell, SectionHeader } from "@/components/ui";
import TextScale from "@/components/TextScale";
import AppNav from "@/components/AppNav";
import AssessmentChatBox from "./AssessmentChatBox";

type PageProps = {
  params: Promise<{ userId: string }>;
};

export default async function AssessmentChatPage(props: PageProps) {
  const { userId } = await props.params;
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
      <AppNav userId={userId} promptBadge={promptBadge} />
      <SectionHeader
        eyebrow="Coach Chat"
        title="My Coach Gia"
        subtitle={`${displayFirstName} · Chat with Gia directly in the app`}
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
