import AdminNav from "@/components/AdminNav";
import Link from "next/link";
import ContentEditorForm from "../ContentEditorForm";
import { createManualLibraryContentAction } from "@/app/admin/library/actions";

export const dynamic = "force-dynamic";

export default function NewLibraryContentPage() {
  return (
    <main className="min-h-screen bg-[#f7f4ee] px-6 py-10 text-[#1e1b16]">
      <div className="mx-auto w-full max-w-4xl space-y-6">
        <AdminNav title="New library content" subtitle="Add external or manual content to the library." />
        <section className="rounded-3xl border border-[#e7e1d6] bg-white p-6">
          <ContentEditorForm action={createManualLibraryContentAction} submitLabel="Create content" />
          <div className="mt-6 flex flex-wrap gap-3">
            <Link
              className="rounded-full border border-[#efe7db] px-4 py-2 text-xs uppercase tracking-[0.2em]"
              href="/admin/library"
            >
              Back to library
            </Link>
          </div>
        </section>
      </div>
    </main>
  );
}
