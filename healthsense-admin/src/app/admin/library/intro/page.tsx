import AdminNav from "@/components/AdminNav";
import IntroSetupClient from "./IntroSetupClient";
import { getLibraryIntroSettings, listContentPromptTemplates } from "@/lib/api";

export const dynamic = "force-dynamic";

export default async function LibraryIntroPage() {
  const [intro, templates] = await Promise.all([getLibraryIntroSettings(), listContentPromptTemplates()]);

  return (
    <main className="min-h-screen bg-[#f7f4ee] px-6 py-10 text-[#1e1b16]">
      <div className="mx-auto w-full max-w-5xl space-y-6">
        <AdminNav title="Intro setup" subtitle="Configure and generate first-login intro podcast + read content." />
        <section className="rounded-3xl border border-[#e7e1d6] bg-white p-6">
          <IntroSetupClient intro={intro} templates={templates} />
        </section>
      </div>
    </main>
  );
}
