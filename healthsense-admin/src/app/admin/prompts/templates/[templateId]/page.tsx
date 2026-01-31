import Link from "next/link";
import AdminNav from "@/components/AdminNav";
import { getPromptTemplate, listAdminUsers } from "@/lib/api";
import TemplateForm from "./template-form";

export const dynamic = "force-dynamic";

type TemplatePageProps = {
  params: Promise<{ templateId: string }>;
};

export default async function TemplatePage({ params }: TemplatePageProps) {
  const resolvedParams = await params;
  const isNew = resolvedParams.templateId === "new";
  const template = isNew ? null : await getPromptTemplate(Number(resolvedParams.templateId));
  const users = await listAdminUsers();
  const userOptions = users.map((u) => ({
    id: u.id,
    label: `${u.display_name || u.first_name || "User"} (#${u.id})${u.phone ? ` · ${u.phone}` : ""}`,
  }));

  return (
    <main className="min-h-screen bg-[#f7f4ee] px-6 py-10 text-[#1e1b16]">
      <div className="mx-auto w-full max-w-4xl space-y-6">
        <AdminNav title={isNew ? "Create template" : `Edit template · ${template?.touchpoint || ""}`} />

        <section className="rounded-3xl border border-[#e7e1d6] bg-white p-6">
          <TemplateForm template={template} userOptions={userOptions} />
          <div className="mt-6 flex flex-wrap gap-3">
            <Link
              className="rounded-full border border-[#efe7db] px-4 py-2 text-xs uppercase tracking-[0.2em]"
              href="/admin/prompts/templates"
            >
              Back to list
            </Link>
          </div>
        </section>
      </div>
    </main>
  );
}
