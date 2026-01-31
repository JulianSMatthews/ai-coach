import AdminNav from "@/components/AdminNav";
import LibraryContentGeneratorClient from "../LibraryContentGeneratorClient";
import { listContentPromptTemplates } from "@/lib/api";

export const dynamic = "force-dynamic";

export default async function LibraryGeneratorPage() {
  const templates = await listContentPromptTemplates();

  return (
    <main className="min-h-screen bg-[#f7f4ee] px-6 py-10 text-[#1e1b16]">
      <div className="mx-auto w-full max-w-5xl space-y-6">
        <AdminNav title="Generate content" subtitle="Use content templates to generate library items." />

        <section className="rounded-3xl border border-[#e7e1d6] bg-white p-6">
          <LibraryContentGeneratorClient templates={templates} />
        </section>
      </div>
    </main>
  );
}
