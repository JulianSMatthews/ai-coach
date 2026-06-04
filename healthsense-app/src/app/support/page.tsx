import LegalPage from "@/components/LegalPage";

export default function SupportPage() {
  return (
    <LegalPage
      eyebrow="Support"
      title="Support"
      subtitle="Get help with access, check-ins, lessons, Gia messages, preferences, or account changes."
    >
      <section className="space-y-1.5">
        <h2 className="text-[17px] font-semibold text-[var(--text-primary)]">Contact CoachSense</h2>
        <p>
          Email{" "}
          <a className="text-[var(--accent)] underline" href="mailto:support@coachsense.ai">
            support@coachsense.ai
          </a>{" "}
          and include your name, mobile number, and a short description of the issue.
        </p>
      </section>

      <section className="space-y-1.5">
        <h2 className="text-[17px] font-semibold text-[var(--text-primary)]">Account deletion</h2>
        <p>
          You can start an account deletion request from the{" "}
          <a className="text-[var(--accent)] underline" href="/delete-account">
            Delete account
          </a>{" "}
          page. We may verify your identity before deleting assessment, check-in, lesson, coaching, and message records.
        </p>
      </section>

      <section className="space-y-1.5">
        <h2 className="text-[17px] font-semibold text-[var(--text-primary)]">Medical or urgent concerns</h2>
        <p>
          CoachSense is not monitored as an emergency service. If you have urgent symptoms or medical concerns, contact
          a qualified healthcare professional or emergency services.
        </p>
      </section>
    </LegalPage>
  );
}
