import LegalPage from "@/components/LegalPage";

export default function PrivacyPage() {
  return (
    <LegalPage
      eyebrow="Privacy"
      title="Privacy policy"
      subtitle="Effective 21 April 2026. This explains the data CoachSense uses to provide coaching and wellbeing support."
    >
      <section className="space-y-1.5">
        <h2 className="text-[17px] font-semibold text-[var(--text-primary)]">What we collect</h2>
        <p>
          We collect the information needed to run your account, including your name, mobile number, email address,
          login/session details, assessment answers, coaching preferences, app activity, and support requests.
        </p>
      </section>

      <section className="space-y-1.5">
        <h2 className="text-[17px] font-semibold text-[var(--text-primary)]">How we use it</h2>
        <p>
          We use your data to provide the assessment, generate your plan, show progress, tailor coach messages,
          support habit trends, keep the app secure, and respond to support or account requests.
        </p>
        <p>
          This includes using your check-ins, selected pillars, lesson progress, quiz answers, preferences, and app
          activity to show relevant cue cards, lessons, weekly objectives, and coaching messages.
        </p>
        <p>
          Health data is used only for wellbeing coaching and app features. It is not used for advertising and is not
          sold.
        </p>
      </section>

      <section className="space-y-1.5">
        <h2 className="text-[17px] font-semibold text-[var(--text-primary)]">Service providers</h2>
        <p>
          We use trusted providers for hosting, authentication, messaging, analytics, AI generation, and media
          processing. They process data only as needed to provide CoachSense services.
        </p>
      </section>

      <section className="space-y-1.5">
        <h2 className="text-[17px] font-semibold text-[var(--text-primary)]">Your choices</h2>
        <p>
          Notifications are optional and controlled by your device settings. You can update coaching preferences in the
          app and request account deletion from the Delete account page.
        </p>
      </section>

      <section className="space-y-1.5">
        <h2 className="text-[17px] font-semibold text-[var(--text-primary)]">Contact</h2>
        <p>
          For privacy, support, or deletion requests, contact{" "}
          <a className="text-[var(--accent)] underline" href="mailto:support@coachsense.ai">
            support@coachsense.ai
          </a>
          .
        </p>
      </section>
    </LegalPage>
  );
}
