import LegalPage from "@/components/LegalPage";

export default function TermsPage() {
  return (
    <LegalPage
      eyebrow="Terms"
      title="Terms of use"
      subtitle="Effective 21 April 2026. These terms explain how HealthSense should be used."
    >
      <section className="space-y-1.5">
        <h2 className="text-[15px] font-semibold text-[var(--text-primary)]">Coaching, not medical care</h2>
        <p>
          HealthSense provides wellbeing coaching, habit support, education, and trend information. It does not provide
          medical diagnosis, treatment, emergency support, or a replacement for professional medical advice.
        </p>
        <p>
          If you have symptoms, urgent concerns, unexpected biomarker results, or a medical condition, speak to a
          qualified healthcare professional. In an emergency, contact your local emergency services.
        </p>
      </section>

      <section className="space-y-1.5">
        <h2 className="text-[15px] font-semibold text-[var(--text-primary)]">Using health and urine test information</h2>
        <p>
          Biometrics and urine test markers are optional screening and trend signals. They should be interpreted with
          context and repeat checks where appropriate. Do not use them as the sole basis for medical decisions.
        </p>
      </section>

      <section className="space-y-1.5">
        <h2 className="text-[15px] font-semibold text-[var(--text-primary)]">Account responsibility</h2>
        <p>
          Keep your login code, password, and device secure. Only enter accurate information for your own account. You
          can contact support if you believe your account or data is incorrect.
        </p>
      </section>

      <section className="space-y-1.5">
        <h2 className="text-[15px] font-semibold text-[var(--text-primary)]">Subscriptions</h2>
        <p>
          HealthSense subscriptions are for coaching service access and related account support. If your subscription is
          managed directly with HealthSense staff, support can help with billing questions.
        </p>
      </section>

      <section className="space-y-1.5">
        <h2 className="text-[15px] font-semibold text-[var(--text-primary)]">Contact</h2>
        <p>
          For support, billing, privacy, or deletion requests, contact{" "}
          <a className="text-[var(--accent)] underline" href="mailto:support@healthsense.coach">
            support@healthsense.coach
          </a>
          .
        </p>
      </section>
    </LegalPage>
  );
}
