import AdminNav from "@/components/AdminNav";
import { getContentGeneration, getLibraryContent } from "@/lib/api";
import { updateLibraryContentAction, updateLibraryContentStatusAction } from "@/app/admin/library/actions";
import ContentEditorForm from "../ContentEditorForm";

type PageProps = {
  params: Promise<{ contentId: string }>;
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

export default async function LibraryContentDetailPage({ params }: PageProps) {
  const { contentId } = await params;
  const content = await getLibraryContent(Number(contentId));
  const generation = content.source_generation_id
    ? await getContentGeneration(Number(content.source_generation_id))
    : null;
  const podcastUrl = generation?.podcast_url || content.podcast_url || "";
  const podcastError = generation?.podcast_error || "";

  return (
    <main className="min-h-screen bg-[#f7f4ee] px-6 py-10 text-[#1e1b16]">
      <div className="mx-auto w-full max-w-5xl space-y-6">
        <AdminNav title={content.title || `Content #${content.id}`} subtitle="Library content detail." />

        <section className="rounded-3xl border border-[#e7e1d6] bg-white p-6">
          <div className="grid gap-4 md:grid-cols-2">
            <div>
              <p className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Metadata</p>
              <p className="mt-2 text-sm text-[#6b6257]">ID: #{content.id}</p>
              <p className="mt-1 text-sm text-[#6b6257]">Status: {content.status || "—"}</p>
              <p className="mt-1 text-sm text-[#6b6257]">Pillar: {content.pillar_key || "—"}</p>
              <p className="mt-1 text-sm text-[#6b6257]">Concept: {content.concept_code || "—"}</p>
            </div>
            <div>
              <p className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Timestamps</p>
              <p className="mt-2 text-sm text-[#6b6257]">Created: {formatDateTime(content.created_at)}</p>
              <p className="mt-1 text-sm text-[#6b6257]">Updated: {formatDateTime(content.updated_at)}</p>
              <p className="mt-1 text-sm text-[#6b6257]">
                Source generation:{" "}
                {content.source_generation_id ? `#${content.source_generation_id}` : "—"}
              </p>
            </div>
          </div>
          <form action={updateLibraryContentStatusAction} className="mt-4 flex flex-wrap items-center gap-3">
            <input type="hidden" name="content_id" value={content.id} />
            <label className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Publish status</label>
            <select
              name="status"
              defaultValue={content.status || "draft"}
              className="rounded-full border border-[#efe7db] px-3 py-2 text-sm"
            >
              <option value="draft">Draft</option>
              <option value="published">Published</option>
            </select>
            <button className="rounded-full border border-[var(--accent)] bg-[var(--accent)] px-4 py-2 text-xs uppercase tracking-[0.2em] text-white">
              Update
            </button>
          </form>
          {content.source_generation_id ? (
            <div className="mt-4">
              <a
                className="rounded-full border border-[#efe7db] px-4 py-2 text-xs uppercase tracking-[0.2em]"
                href={`/admin/library/generations/${content.source_generation_id}`}
              >
                View generation
              </a>
            </div>
          ) : null}
        </section>

        <section className="rounded-3xl border border-[#e7e1d6] bg-white p-6">
          <h2 className="text-lg font-semibold">Content</h2>
          <pre className="mt-4 whitespace-pre-wrap text-sm text-[#2f2a21]">{content.body || "—"}</pre>
        </section>

        <section className="rounded-3xl border border-[#e7e1d6] bg-white p-6">
          <h2 className="text-lg font-semibold">Edit content</h2>
          <div className="mt-4">
            <ContentEditorForm
              content={content}
              action={updateLibraryContentAction.bind(null, content.id)}
              submitLabel="Update content"
            />
          </div>
        </section>

        {(podcastUrl || podcastError) ? (
          <section className="rounded-3xl border border-[#e7e1d6] bg-white p-6">
            <h2 className="text-lg font-semibold">Podcast audio</h2>
            {podcastError ? (
              <p className="mt-3 text-sm text-red-600">{podcastError}</p>
            ) : null}
            {podcastUrl ? (
              <div className="mt-3">
                <audio controls className="w-full">
                  <source src={podcastUrl} />
                </audio>
              </div>
            ) : null}
          </section>
        ) : null}

        <div className="flex flex-wrap gap-2">
          <a
            className="rounded-full border border-[#efe7db] px-4 py-2 text-xs uppercase tracking-[0.2em]"
            href="/admin/library"
          >
            Back to library
          </a>
          {podcastUrl ? (
            <a
              className="rounded-full border border-[var(--accent)] bg-[var(--accent)] px-4 py-2 text-xs uppercase tracking-[0.2em] text-white"
              href={podcastUrl}
              target="_blank"
              rel="noreferrer"
            >
              Open audio
            </a>
          ) : null}
        </div>
      </div>
    </main>
  );
}
