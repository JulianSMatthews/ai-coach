import AdminNav from "@/components/AdminNav";

export const dynamic = "force-dynamic";

function getApiBaseUrl(): string | null {
  const raw = process.env.API_BASE_URL || process.env.NEXT_PUBLIC_API_BASE_URL || "";
  const trimmed = String(raw || "").trim();
  if (!trimmed) return null;
  return trimmed.replace(/\/+$/, "");
}

export default async function EducationPage() {
  const apiBase = getApiBaseUrl();
  const editorUrl = apiBase ? `${apiBase}/admin/education-programmes` : null;
  const createUrl = apiBase ? `${apiBase}/admin/education-programmes/edit` : null;

  return (
    <main className="min-h-screen bg-[#f7f4ee] px-6 py-10 text-[#1e1b16]">
      <div className="mx-auto w-full max-w-7xl space-y-6">
        <AdminNav
          title="Education"
          subtitle="Configure 21-day education programmes, lesson variants, quizzes, and takeaways."
        />

        <section className="rounded-3xl border border-[#e7e1d6] bg-white p-6">
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div className="max-w-3xl">
              <p className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Programme editor</p>
              <h2 className="mt-2 text-xl font-semibold">Education programmes</h2>
              <p className="mt-2 text-sm text-[#6b6257]">
                Build the pillar-level 21-day learning journey, assign levelled video variants, and configure the
                3-question quiz and coach takeaway shown after completion.
              </p>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              {editorUrl ? (
                <a
                  href={editorUrl}
                  target="_blank"
                  rel="noreferrer"
                  className="rounded-full border border-[#efe7db] px-4 py-2 text-xs uppercase tracking-[0.2em]"
                >
                  Open full page
                </a>
              ) : null}
              {createUrl ? (
                <a
                  href={createUrl}
                  target="_blank"
                  rel="noreferrer"
                  className="rounded-full border border-[var(--accent)] bg-[var(--accent)] px-4 py-2 text-xs uppercase tracking-[0.2em] text-white"
                >
                  New programme
                </a>
              ) : null}
            </div>
          </div>
        </section>

        {!editorUrl ? (
          <section className="rounded-3xl border border-[#e7e1d6] bg-white p-6">
            <p className="text-sm text-[#6b6257]">
              `API_BASE_URL` is not configured for HealthSense Admin, so the education editor cannot be loaded here yet.
            </p>
          </section>
        ) : (
          <section className="overflow-hidden rounded-3xl border border-[#e7e1d6] bg-white shadow-[0_20px_60px_-40px_rgba(30,27,22,0.4)]">
            <iframe
              src={editorUrl}
              title="Education programme editor"
              className="h-[calc(100vh-15rem)] min-h-[980px] w-full border-0"
            />
          </section>
        )}
      </div>
    </main>
  );
}
