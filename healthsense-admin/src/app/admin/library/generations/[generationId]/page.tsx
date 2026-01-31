import AdminNav from "@/components/AdminNav";
import { getContentGeneration } from "@/lib/api";

type PageProps = {
  params: Promise<{ generationId: string }>;
};

export const dynamic = "force-dynamic";

const formatDateTime = (value?: string | null) => {
  if (!value) return "—";
  try {
    const dt = new Date(value);
    if (Number.isNaN(dt.getTime())) return "—";
    return dt.toLocaleString("en-GB", {
      day: "2-digit",
      month: "2-digit",
      year: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      timeZone: "Europe/London",
    });
  } catch {
    return "—";
  }
};

export default async function LibraryGenerationDetailPage({ params }: PageProps) {
  const { generationId } = await params;
  const generation = await getContentGeneration(Number(generationId));

  return (
    <main className="min-h-screen bg-[#f7f4ee] px-6 py-10 text-[#1e1b16]">
      <div className="mx-auto w-full max-w-5xl space-y-6">
        <AdminNav title={`Generation #${generation.id}`} subtitle="Content generator output." />

        <section className="rounded-3xl border border-[#e7e1d6] bg-white p-6">
          <div className="grid gap-4 md:grid-cols-2">
            <div>
              <p className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Template</p>
              <p className="mt-2 text-lg">{generation.touchpoint || "—"}</p>
              <p className="mt-2 text-sm text-[#6b6257]">
                User: {generation.user_name || (generation.user_id ? `#${generation.user_id}` : "—")}
              </p>
              <p className="mt-1 text-sm text-[#6b6257]">State: {generation.prompt_state || "—"}</p>
              <p className="mt-1 text-sm text-[#6b6257]">Provider: {generation.provider || "openai"}</p>
            </div>
            <div>
              <p className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Created</p>
              <p className="mt-2 text-sm text-[#6b6257]">{formatDateTime(generation.created_at)}</p>
              <p className="mt-2 text-sm text-[#6b6257]">Status: {generation.status || "—"}</p>
              <p className="mt-1 text-sm text-[#6b6257]">Model: {generation.model_override || "default"}</p>
            </div>
          </div>
        </section>

        {generation.assembled_prompt ? (
          <section className="rounded-3xl border border-[#e7e1d6] bg-white p-6">
            <h2 className="text-lg font-semibold">Assembled prompt</h2>
            <pre className="mt-4 whitespace-pre-wrap text-xs text-[#2f2a21]">
              {generation.assembled_prompt}
            </pre>
          </section>
        ) : null}

        {generation.blocks ? (
          <section className="rounded-3xl border border-[#e7e1d6] bg-white p-6">
            <h2 className="text-lg font-semibold">Blocks</h2>
            <pre className="mt-4 whitespace-pre-wrap text-xs text-[#2f2a21]">
              {JSON.stringify(generation.blocks, null, 2)}
            </pre>
          </section>
        ) : null}

        {(generation.llm_content || generation.llm_error) ? (
          <section className="rounded-3xl border border-[#e7e1d6] bg-white p-6">
            <h2 className="text-lg font-semibold">LLM response</h2>
            {generation.llm_error ? (
              <p className="mt-3 text-sm text-red-600">{generation.llm_error}</p>
            ) : (
              <>
                <p className="mt-3 text-xs text-[#6b6257]">
                  Model: {generation.llm_model || generation.model_override || "default"} ·{" "}
                  {generation.llm_duration_ms || 0}ms
                </p>
                <pre className="mt-4 whitespace-pre-wrap text-xs text-[#2f2a21]">
                  {generation.llm_content || ""}
                </pre>
              </>
            )}
          </section>
        ) : null}

        {(generation.podcast_url || generation.podcast_error) ? (
          <section className="rounded-3xl border border-[#e7e1d6] bg-white p-6">
            <h2 className="text-lg font-semibold">Podcast audio</h2>
            {generation.podcast_error ? (
              <p className="mt-3 text-sm text-red-600">{generation.podcast_error}</p>
            ) : null}
            {generation.podcast_url ? (
              <div className="mt-3">
                <audio controls className="w-full">
                  <source src={generation.podcast_url} />
                </audio>
              </div>
            ) : null}
          </section>
        ) : null}

        <div>
          <a
            className="rounded-full border border-[#efe7db] px-4 py-2 text-xs uppercase tracking-[0.2em]"
            href="/admin/library"
          >
            Back to library
          </a>
        </div>
      </div>
    </main>
  );
}
