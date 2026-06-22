import LegalPage from "@/components/LegalPage";
import DeleteAccountForm from "./DeleteAccountForm";

export default function DeleteAccountPage() {
  return (
    <LegalPage
      eyebrow="Account"
      title="Delete account"
      subtitle="Delete your CoachSense account from inside the app."
    >
      <section className="space-y-1.5">
        <h2 className="text-[17px] font-semibold text-[var(--text-primary)]">What deletion includes</h2>
        <p>
          Account deletion removes or disables your CoachSense user account and related assessment, check-in, lesson,
          quiz, preference, session, coaching, and message records where we are able to delete them.
        </p>
        <p>
          Some security, legal, or operational records may need to be retained where required by law or for
          legitimate business record keeping.
        </p>
      </section>

      <section className="space-y-2.5">
        <h2 className="text-[17px] font-semibold text-[var(--text-primary)]">Confirm deletion</h2>
        <DeleteAccountForm />
      </section>
    </LegalPage>
  );
}
