import LegalPage from "@/components/LegalPage";

export default function TermsPage() {
  return (
    <LegalPage
      eyebrow="Terms"
      title="Terms of use"
      subtitle="Effective 21 April 2026. These terms explain how CoachSense should be used."
    >
      <section className="space-y-1.5">
        <h2 className="text-[17px] font-semibold text-[var(--text-primary)]">Coaching, not medical care</h2>
        <p>
          CoachSense provides wellbeing coaching, check-ins, habit support, education, and reflection tools. It does
          not provide medical diagnosis, treatment, emergency support, or a replacement for professional medical advice.
        </p>
        <p>
          If you have symptoms, urgent concerns, or a medical condition, speak to a qualified healthcare professional.
          In an emergency, contact your local emergency services.
        </p>
      </section>

      <section className="space-y-1.5">
        <h2 className="text-[17px] font-semibold text-[var(--text-primary)]">How the app works</h2>
        <p>
          You can complete an assessment, choose the pillars you want to use, record check-ins, review habit trends,
          work through lessons, and answer lesson quizzes. CoachSense uses the information you enter to tailor the app
          experience and provide coaching prompts.
        </p>
        <p>
          Coach messages, cue cards, lessons, and weekly objectives are guidance and education. They are not instructions
          that you must follow, and you remain responsible for deciding what is appropriate for your circumstances.
        </p>
      </section>

      <section className="space-y-1.5">
        <h2 className="text-[17px] font-semibold text-[var(--text-primary)]">Preferences and content</h2>
        <p>
          You can update preferences such as theme, selected pillars, and account details in the app. Changing your
          selected pillars changes which check-in and learning areas are shown.
        </p>
        <p>
          Lesson and coaching content may change over time as CoachSense improves the programme, updates the app, or
          adjusts available features.
        </p>
      </section>

      <section className="space-y-1.5">
        <h2 className="text-[17px] font-semibold text-[var(--text-primary)]">Account responsibility</h2>
        <p>
          Keep your login code and device secure. Only enter accurate information for your own account. You
          can contact support if you believe your account or data is incorrect.
        </p>
      </section>

      <section className="space-y-1.5">
        <h2 className="text-[17px] font-semibold text-[var(--text-primary)]">Access</h2>
        <p>
          CoachSense is currently free to access in this app version. If this changes in a future iOS version, any
          digital subscription offered in the app will use Apple In-App Purchase.
        </p>
      </section>

      <section className="space-y-1.5">
        <h2 className="text-[17px] font-semibold text-[var(--text-primary)]">Contact</h2>
        <p>
          For support, privacy, or deletion requests, contact{" "}
          <a className="text-[var(--accent)] underline" href="mailto:support@coachsense.ai">
            support@coachsense.ai
          </a>
          .
        </p>
      </section>
    </LegalPage>
  );
}
