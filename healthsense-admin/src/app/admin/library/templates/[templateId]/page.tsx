import Link from "next/link";
import AdminNav from "@/components/AdminNav";
import { getContentPromptTemplate, listConceptOptions } from "@/lib/api";
import ContentTemplateForm from "./template-form";

export const dynamic = "force-dynamic";

type TemplatePageProps = {
  params: Promise<{ templateId: string }>;
};

export default async function ContentTemplatePage({ params }: TemplatePageProps) {
  const resolvedParams = await params;
  const isNew = resolvedParams.templateId === "new";
  const template = isNew ? null : await getContentPromptTemplate(Number(resolvedParams.templateId));
  const conceptRows = await listConceptOptions();
  const conceptsByPillar = conceptRows.reduce<Record<string, { code: string; name: string }[]>>((acc, row) => {
    const pillarKey = row.pillar_key || "other";
    const code = row.code || "";
    const name = row.name || row.code || "";
    if (!code) return acc;
    if (!acc[pillarKey]) acc[pillarKey] = [];
    acc[pillarKey].push({ code, name });
    return acc;
  }, {});

  return (
    <main className="min-h-screen bg-[#f7f4ee] px-6 py-10 text-[#1e1b16]">
      <div className="mx-auto w-full max-w-4xl space-y-6">
        <AdminNav title={isNew ? "Create content template" : `Edit content template · ${template?.template_key || ""}`} />

        <section className="rounded-3xl border border-[#e7e1d6] bg-white p-6">
          <ContentTemplateForm template={template} conceptsByPillar={conceptsByPillar} />
          <div className="mt-6 flex flex-wrap gap-3">
            <Link
              className="rounded-full border border-[#efe7db] px-4 py-2 text-xs uppercase tracking-[0.2em]"
              href="/admin/library/templates"
            >
              Back to list
            </Link>
          </div>
        </section>
      </div>
    </main>
  );
}
