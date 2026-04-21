import LegalPage from "@/components/LegalPage";

export default function PrivacyPage() {
  return (
    <LegalPage
      eyebrow="Privacy"
      title="Privacy policy"
      subtitle="Effective 21 April 2026. This explains the data HealthSense uses to provide coaching and wellbeing support."
    >
      <section className="space-y-2">
        <h2 className="text-xl text-[var(--text-primary)]">What we collect</h2>
        <p>
          We collect the information needed to run your account, including your name, mobile number, email address,
          login/session details, assessment answers, coaching preferences, app activity, and support requests.
        </p>
        <p>
          If you choose to use biometrics, HealthSense may read selected Apple Health metrics such as resting heart
          rate, heart rate variability, step count, and exercise minutes. If you choose to use urine testing, we process
          the photo and derived marker results needed to show your screening history.
        </p>
      </section>

      <section className="space-y-2">
        <h2 className="text-xl text-[var(--text-primary)]">How we use it</h2>
        <p>
          We use your data to provide the assessment, generate your plan, show progress, tailor Gia coaching messages,
          support biomarker and habit trends, keep the app secure, and respond to support or account requests.
        </p>
        <p>
          Health data is used only for wellbeing coaching and app features. It is not used for advertising and is not
          sold.
        </p>
      </section>

      <section className="space-y-2">
        <h2 className="text-xl text-[var(--text-primary)]">Service providers</h2>
        <p>
          We use trusted providers for hosting, authentication, messaging, payments, analytics, AI generation, and media
          processing. They process data only as needed to provide HealthSense services.
        </p>
      </section>

      <section className="space-y-2">
        <h2 className="text-xl text-[var(--text-primary)]">Your choices</h2>
        <p>
          Apple Health access, photo access, camera access, and notifications are optional and controlled by your device
          settings. You can update coaching preferences in the app and request account deletion from the Delete account
          page.
        </p>
      </section>

      <section className="space-y-2">
        <h2 className="text-xl text-[var(--text-primary)]">Contact</h2>
        <p>
          For privacy, support, or deletion requests, contact{" "}
          <a className="text-[var(--accent)] underline" href="mailto:support@healthsense.coach">
            support@healthsense.coach
          </a>
          .
        </p>
      </section>
    </LegalPage>
  );
}
