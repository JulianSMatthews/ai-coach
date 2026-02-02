import AdminNav from "@/components/AdminNav";
import { listAdminUsers, listTouchpointHistory } from "@/lib/api";

type TouchpointHistoryPageProps = {
  searchParams: Promise<{ start?: string; end?: string; user_id?: string; touchpoint?: string }>;
};

export const dynamic = "force-dynamic";

function formatDate(value?: string | null) {
  if (!value) return "—";
  return String(value).slice(0, 19).replace("T", " ");
}

export default async function TouchpointHistoryPage({ searchParams }: TouchpointHistoryPageProps) {
  const resolved = await searchParams;
  const start = (resolved?.start || "").trim();
  const end = (resolved?.end || "").trim();
  const touchpoint = (resolved?.touchpoint || "").trim();
  const userRaw = (resolved?.user_id || "").trim();
  const userId = userRaw ? Number(userRaw) : undefined;

  const items = await listTouchpointHistory(100, userId || undefined, touchpoint || undefined, start || undefined, end || undefined);
  const users = await listAdminUsers();

  return (
    <main className="min-h-screen bg-[#f7f4ee] px-6 py-10 text-[#1e1b16]">
      <div className="mx-auto w-full max-w-6xl space-y-6">
        <AdminNav title="Touchpoint history" subtitle="Review coaching dialog across users." />

        <section className="rounded-3xl border border-[#e7e1d6] bg-white p-6">
          <h2 className="text-lg font-semibold">Filters</h2>
          <form className="mt-4 grid gap-3 md:grid-cols-5" method="get">
            <input
              type="date"
              name="start"
              defaultValue={start}
              className="rounded-xl border border-[#efe7db] px-3 py-2 text-sm"
            />
            <input
              type="date"
              name="end"
              defaultValue={end}
              className="rounded-xl border border-[#efe7db] px-3 py-2 text-sm"
            />
            <input
              name="touchpoint"
              defaultValue={touchpoint}
              placeholder="Touchpoint type"
              className="rounded-xl border border-[#efe7db] px-3 py-2 text-sm"
            />
            <input
              name="user_id"
              defaultValue={userRaw}
              placeholder="User ID"
              list="user-options"
              className="rounded-xl border border-[#efe7db] px-3 py-2 text-sm"
            />
            <datalist id="user-options">
              {users.map((u) => (
                <option
                  key={u.id}
                  value={u.id}
                  label={`${u.first_name || ""} ${u.surname || ""} ${u.phone || ""}`.trim()}
                />
              ))}
            </datalist>
            <button
              type="submit"
              className="rounded-full border border-[var(--accent)] bg-[var(--accent)] px-4 py-2 text-xs uppercase tracking-[0.2em] text-white"
            >
              Apply filters
            </button>
          </form>
        </section>

        <section className="rounded-3xl border border-[#e7e1d6] bg-white p-6">
          <h2 className="text-lg font-semibold">Dialog</h2>
          <p className="mt-2 text-sm text-[#6b6257]">
            Showing the most recent 100 touchpoints/messages in the selected filter window.
          </p>
          <div className="mt-4 space-y-4">
            {items.map((item) => {
              const userLabel =
                item.user_name || (item.user_id ? `User #${item.user_id}` : "Unknown user");
              const headline = item.kind === "message"
                ? `${item.direction || "message"}`
                : item.touchpoint_type || "touchpoint";
              const meta = [
                formatDate(item.ts),
                userLabel,
                item.week_no ? `Week ${item.week_no}` : null,
                item.channel || null,
              ]
                .filter(Boolean)
                .join(" · ");
              return (
                <div key={`${item.kind}-${item.id}`} className="rounded-2xl border border-[#efe7db] bg-[#faf7f1] p-4">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div>
                      <p className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">{headline}</p>
                      <p className="mt-1 text-sm text-[#6b6257]">{meta || "—"}</p>
                    </div>
                    {item.audio_url ? (
                      <a
                        href={item.audio_url}
                        target="_blank"
                        rel="noreferrer"
                        className="rounded-full border border-[#efe7db] px-3 py-1 text-xs"
                      >
                        Play
                      </a>
                    ) : null}
                  </div>
                  <p className="mt-3 text-sm text-[#1e1b16]">{item.preview || "—"}</p>
                  {item.is_truncated ? (
                    <details className="mt-3 text-sm text-[#1e1b16]">
                      <summary className="cursor-pointer text-xs uppercase tracking-[0.2em] text-[#6b6257]">
                        Read full
                      </summary>
                      <pre className="mt-2 whitespace-pre-wrap text-xs text-[#2f2a21]">
                        {item.full_text || "—"}
                      </pre>
                    </details>
                  ) : null}
                </div>
              );
            })}
            {!items.length ? (
              <p className="text-sm text-[#6b6257]">No dialog history found for this filter.</p>
            ) : null}
          </div>
        </section>
      </div>
    </main>
  );
}
