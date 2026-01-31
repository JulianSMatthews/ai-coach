import Link from "next/link";
import AdminNav from "@/components/AdminNav";
import { getKbSnippet } from "@/lib/api";
import SnippetForm from "../SnippetForm";

export const dynamic = "force-dynamic";

type SnippetPageProps = {
  params: Promise<{ snippetId: string }>;
};

export default async function SnippetPage({ params }: SnippetPageProps) {
  const resolvedParams = await params;
  const isNew = resolvedParams.snippetId === "new";
  const snippet = isNew ? null : await getKbSnippet(Number(resolvedParams.snippetId));

  return (
    <main className="min-h-screen bg-[#f7f4ee] px-6 py-10 text-[#1e1b16]">
      <div className="mx-auto w-full max-w-4xl space-y-6">
        <AdminNav title={isNew ? "Create snippet" : "Edit snippet"} subtitle={snippet?.title || undefined} />

        <section className="rounded-3xl border border-[#e7e1d6] bg-white p-6">
          <SnippetForm snippet={snippet} />
          <div className="mt-6 flex flex-wrap gap-3">
            <Link
              className="rounded-full border border-[#efe7db] px-4 py-2 text-xs uppercase tracking-[0.2em]"
              href="/admin/kb"
            >
              Back to list
            </Link>
          </div>
        </section>
      </div>
    </main>
  );
}
