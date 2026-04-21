import LegalPage from "@/components/LegalPage";
import DeleteAccountForm from "./DeleteAccountForm";

export default function DeleteAccountPage() {
  return (
    <LegalPage
      eyebrow="Account"
      title="Delete account"
      subtitle="Start a HealthSense account deletion request from inside the app."
    >
      <section className="space-y-2">
        <h2 className="text-xl text-[var(--text-primary)]">What deletion includes</h2>
        <p>
          Account deletion removes or disables your HealthSense user account and related assessment, coaching, biometric
          trend, urine test, preference, session, and message records where we are able to delete them.
        </p>
        <p>
          Some payment, security, legal, or operational records may need to be retained where required by law or for
          legitimate business record keeping.
        </p>
      </section>

      <section className="space-y-3">
        <h2 className="text-xl text-[var(--text-primary)]">Request deletion</h2>
        <DeleteAccountForm />
      </section>
    </LegalPage>
  );
}
