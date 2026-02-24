import Link from "next/link";
import AdminNav from "@/components/AdminNav";
import { getPromptHistoryDetail } from "@/lib/api";

type HistoryDetailPageProps = {
  params: Promise<{ logId: string }>;
};

export const dynamic = "force-dynamic";

function formatDate(value?: string | null) {
  if (!value) return "—";
  return String(value).slice(0, 19).replace("T", " ");
}

function BlockCard({ title, content }: { title: string; content?: string | null }) {
  if (!content) return null;
  return (
    <div className="rounded-2xl border border-[#efe7db] bg-[#faf7f1] p-4">
      <h3 className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">{title}</h3>
      <pre className="mt-2 whitespace-pre-wrap text-xs text-[#2f2a21]">{content}</pre>
    </div>
  );
}

export default async function PromptHistoryDetailPage({ params }: HistoryDetailPageProps) {
  const resolved = await params;
  const logId = Number(resolved.logId);
  const detail = await getPromptHistoryDetail(logId);

  const userLabel = detail.user_name || (detail.user_id ? `User #${detail.user_id}` : "Unknown user");
  const metaItems = [
    ["Date", formatDate(detail.created_at)],
    ["Touchpoint", detail.touchpoint || "—"],
    ["User", userLabel],
    ["Duration", detail.duration_ms ? `${detail.duration_ms} ms` : "—"],
    ["Run source", detail.execution_source || "—"],
    ["Worker ID", detail.worker_id || "—"],
    ["Model", detail.model || "—"],
    ["Template", `${detail.template_state || "—"}${detail.template_version ? ` v${detail.template_version}` : ""}`],
  ];

  const extraBlocks = detail.extra_blocks && typeof detail.extra_blocks === "object" ? detail.extra_blocks : {};

  return (
    <main className="min-h-screen bg-[#f7f4ee] px-6 py-10 text-[#1e1b16]">
      <div className="mx-auto w-full max-w-5xl space-y-6">
        <AdminNav title="Prompt history detail" subtitle="Inspect blocks, assembled prompt, and response." />

        <section className="rounded-3xl border border-[#e7e1d6] bg-white p-6">
          <h2 className="text-lg font-semibold">Metadata</h2>
          <div className="mt-4 grid gap-4 md:grid-cols-2">
            {metaItems.map(([label, value]) => (
              <div key={label}>
                <p className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">{label}</p>
                <p className="mt-2 text-sm text-[#1e1b16]">{value}</p>
              </div>
            ))}
          </div>
        </section>

        <section className="rounded-3xl border border-[#e7e1d6] bg-white p-6">
          <h2 className="text-lg font-semibold">Blocks</h2>
          <div className="mt-4 grid gap-4">
            <BlockCard title="System" content={detail.system_block} />
            <BlockCard title="Locale" content={detail.locale_block} />
            <BlockCard title="OKR" content={detail.okr_block} />
            <BlockCard title="Scores" content={detail.scores_block} />
            <BlockCard title="Habit" content={detail.habit_block} />
            <BlockCard title="Task" content={detail.task_block} />
            <BlockCard title="User" content={detail.user_block} />
            {Object.entries(extraBlocks).map(([key, value]) => (
              <BlockCard key={key} title={`Extra · ${key}`} content={String(value || "")} />
            ))}
          </div>
        </section>

        <section className="rounded-3xl border border-[#e7e1d6] bg-white p-6">
          <h2 className="text-lg font-semibold">Assembled prompt</h2>
          <pre className="mt-4 whitespace-pre-wrap text-xs text-[#2f2a21]">{detail.assembled_prompt || "—"}</pre>
        </section>

        <section className="rounded-3xl border border-[#e7e1d6] bg-white p-6">
          <h2 className="text-lg font-semibold">Dialog view</h2>
          <p className="mt-2 text-sm text-[#6b6257]">Prompt and response shown as a simple exchange.</p>
          <div className="mt-4 space-y-3">
            <div className="rounded-2xl border border-[#efe7db] bg-[#faf7f1] p-4">
              <p className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Prompt</p>
              <pre className="mt-2 whitespace-pre-wrap text-xs text-[#2f2a21]">
                {detail.assembled_prompt || "—"}
              </pre>
            </div>
            <div className="rounded-2xl border border-[#dfeae6] bg-[#eef7f4] p-4">
              <p className="text-xs uppercase tracking-[0.2em] text-[#4b6b63]">Response</p>
              <pre className="mt-2 whitespace-pre-wrap text-xs text-[#1f2a27]">
                {detail.response_preview || "—"}
              </pre>
            </div>
          </div>
        </section>

        {detail.audio_url ? (
          <section className="rounded-3xl border border-[#e7e1d6] bg-white p-6">
            <h2 className="text-lg font-semibold">Podcast audio</h2>
            <div className="mt-3">
              <audio controls className="w-full">
                <source src={detail.audio_url} />
              </audio>
            </div>
          </section>
        ) : null}

        <div>
          <Link
            href="/admin/prompts/history"
            className="rounded-full border border-[#efe7db] px-4 py-2 text-xs uppercase tracking-[0.2em]"
          >
            Back to history
          </Link>
        </div>
      </div>
    </main>
  );
}
