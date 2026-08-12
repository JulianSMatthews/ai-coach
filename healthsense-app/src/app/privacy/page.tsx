import LegalPage from "@/components/LegalPage";

export default function PrivacyPage() {
  return (
    <LegalPage
      eyebrow="Privacy"
      title="Privacy policy"
      subtitle="Effective 12 August 2026. This explains how CoachSense collects, uses, protects, retains, and deletes personal information."
    >
      <section className="space-y-1.5">
        <h2 className="text-[17px] font-semibold text-[var(--text-primary)]">Who we are</h2>
        <p>
          CoachSense provides educational coaching, wellbeing check-ins, habit support, and progress tracking through
          its Android, iOS, and web applications. References to “CoachSense”, “we”, or “us” in this policy mean the
          provider of the CoachSense app and service.
        </p>
      </section>

      <section className="space-y-1.5">
        <h2 className="text-[17px] font-semibold text-[var(--text-primary)]">What we collect</h2>
        <p>
          We collect the information needed to run your account, including your name, mobile number, email address if
          you choose to provide one, login and session information, device and technical information needed for
          security and troubleshooting, app activity, and support requests.
        </p>
        <p>
          Because CoachSense is a wellbeing service, information you choose to provide may include sensitive wellbeing
          information such as assessment and check-in answers, goals, habits, sleep, recovery, nutrition, activity,
          mood or reflection entries, coaching conversations, lesson progress, and quiz answers.
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
          We may use artificial-intelligence services to generate or personalise educational and coaching content from
          relevant information you provide. CoachSense is a wellbeing and educational service, not a medical device,
          and does not diagnose, treat, cure, or prevent any medical condition.
        </p>
        <p>
          The current Android and iOS apps do not request access to Health Connect, Apple Health, biometrics, camera,
          photo library, contacts, or precise location. If optional integrations are introduced later, we will update
          this policy and explain the data use before requesting permission.
        </p>
      </section>

      <section className="space-y-1.5">
        <h2 className="text-[17px] font-semibold text-[var(--text-primary)]">Sharing and service providers</h2>
        <p>
          We use contracted providers for cloud hosting and databases, authentication, login-code messaging, customer
          support, service monitoring, artificial-intelligence generation, and audio or avatar media processing. They
          receive only the information needed to perform those services and process it under their contractual and
          legal obligations.
        </p>
        <p>
          We do not sell personal information. We may disclose information where required by law, to protect users or
          the service, or as part of a business transfer subject to appropriate safeguards.
        </p>
      </section>

      <section className="space-y-1.5">
        <h2 className="text-[17px] font-semibold text-[var(--text-primary)]">Security and international processing</h2>
        <p>
          We use access controls, encrypted network connections, authentication, monitoring, and other reasonable
          technical and organisational safeguards. No system can guarantee absolute security. Our providers may
          process information in countries outside your own, using contractual or other legally recognised safeguards
          where required.
        </p>
      </section>

      <section className="space-y-1.5">
        <h2 className="text-[17px] font-semibold text-[var(--text-primary)]">Retention and deletion</h2>
        <p>
          We retain account and wellbeing information while your account is active and only for as long as needed to
          provide CoachSense, meet legal obligations, resolve disputes, prevent fraud, and maintain service security.
          Retention periods vary according to the type and purpose of the record.
        </p>
        <p>
          You can request permanent deletion in the app or through the public{" "}
          <a className="text-[var(--accent)] underline" href="/delete-account">
            Delete account
          </a>{" "}
          page. Deletion removes the account and associated personal data, except limited records that must be retained
          for legal, security, fraud-prevention, or regulatory reasons. Residual backup copies are removed through the
          normal backup-retention cycle.
        </p>
      </section>

      <section className="space-y-1.5">
        <h2 className="text-[17px] font-semibold text-[var(--text-primary)]">Your choices and rights</h2>
        <p>
          Notifications are optional and controlled by your device settings. You can update coaching preferences in the
          app. Depending on where you live, you may also have rights to access, correct, export, restrict, object to the
          use of, or delete your personal information. Contact us to exercise these rights.
        </p>
      </section>

      <section className="space-y-1.5">
        <h2 className="text-[17px] font-semibold text-[var(--text-primary)]">Children</h2>
        <p>
          CoachSense is intended for adults and is not directed to children. Please do not create an account or provide
          personal information if you are below the minimum age required to consent to this service in your country.
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
