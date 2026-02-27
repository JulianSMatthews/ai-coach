import AdminNav from "@/components/AdminNav";
import { listAdminUsers, listTouchpointHistory, listTouchpointHistoryTouchpoints } from "@/lib/api";

type TouchpointHistoryPageProps = {
  searchParams: Promise<{ start?: string; end?: string; user_id?: string; touchpoint?: string; delivery?: string }>;
};

export const dynamic = "force-dynamic";

function formatDate(value?: string | null) {
  if (!value) return "—";
  return String(value).slice(0, 19).replace("T", " ");
}

function messageStatusClass(value?: string | null) {
  const key = String(value || "").toLowerCase();
  if (key === "replied") return "border-[#2f8b55] bg-[#eaf7ef] text-[#14532d]";
  if (key === "read") return "border-[#1f6f8b] bg-[#e8f4f8] text-[#0f4c5f]";
  if (key === "received") return "border-[#2f8b55] bg-[#eaf7ef] text-[#14532d]";
  if (key === "failed") return "border-[#c43d3d] bg-[#fdeaea] text-[#8c1d1d]";
  if (key === "stale_not_received") return "border-[#9f1239] bg-[#fdf2f8] text-[#831843]";
  if (key === "pending") return "border-[#cc9a2f] bg-[#fff6e6] text-[#825b0b]";
  if (key === "inbound") return "border-[#7a6f61] bg-[#f5efe7] text-[#4a433b]";
  return "border-[#d8d1c4] bg-[#f7f4ee] text-[#6b6257]";
}

export default async function TouchpointHistoryPage({ searchParams }: TouchpointHistoryPageProps) {
  const resolved = await searchParams;
  const start = (resolved?.start || "").trim();
  const end = (resolved?.end || "").trim();
  const touchpoint = (resolved?.touchpoint || "").trim();
  const delivery = (resolved?.delivery || "").trim().toLowerCase();
  const userRaw = (resolved?.user_id || "").trim();
  const userId = userRaw ? Number(userRaw) : undefined;

  const items = await listTouchpointHistory(
    100,
    userId || undefined,
    touchpoint || undefined,
    delivery || undefined,
    start || undefined,
    end || undefined
  );
  const users = await listAdminUsers();
  const touchpointOptions = await listTouchpointHistoryTouchpoints(userId || undefined, start || undefined, end || undefined);

  return (
    <main className="min-h-screen bg-[#f7f4ee] px-6 py-10 text-[#1e1b16]">
      <div className="mx-auto w-full max-w-6xl space-y-6">
        <AdminNav title="Touchpoint history" subtitle="Review coaching dialog across users." />

        <section className="rounded-3xl border border-[#e7e1d6] bg-white p-6">
          <h2 className="text-lg font-semibold">Filters</h2>
          <form className="mt-4 grid gap-3 md:grid-cols-6" method="get">
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
              list="touchpoint-options"
              className="rounded-xl border border-[#efe7db] px-3 py-2 text-sm"
            />
            <datalist id="touchpoint-options">
              {touchpointOptions.map((tp) => (
                <option key={tp} value={tp} />
              ))}
            </datalist>
            <input
              name="user_id"
              defaultValue={userRaw}
              placeholder="User ID"
              list="user-options"
              className="rounded-xl border border-[#efe7db] px-3 py-2 text-sm"
            />
            <select
              name="delivery"
              defaultValue={delivery || "all"}
              className="rounded-xl border border-[#efe7db] px-3 py-2 text-sm"
            >
              <option value="all">Delivery: all</option>
              <option value="not_received">Delivery: not received</option>
              <option value="stale_not_received">Delivery: stale not received</option>
              <option value="failed">Delivery: failed</option>
              <option value="pending">Delivery: pending</option>
              <option value="received">Delivery: received</option>
              <option value="read">Delivery: read</option>
              <option value="replied">Delivery: replied</option>
            </select>
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
                    <div className="flex items-center gap-2">
                      {item.kind === "message" ? (
                        <span className={`rounded-full border px-2 py-1 text-[11px] uppercase tracking-[0.18em] ${messageStatusClass(item.engagement_state || item.delivery_state)}`}>
                          {String(item.engagement_state || item.delivery_state || "unknown")}
                        </span>
                      ) : null}
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
                  </div>
                  <p className="mt-3 text-sm text-[#1e1b16]">{item.preview || "—"}</p>
                  {item.kind === "message" ? (
                    <p className="mt-2 text-xs text-[#6b6257]">
                      delivery callback: {item.delivery_status || "—"} · callback time: {formatDate(item.delivery_last_callback_at)}
                      {item.reply_received ? ` · replied at ${formatDate(item.reply_at)}` : ""}
                      {item.delivery_error_code ? ` · error ${item.delivery_error_code}` : ""}
                      {item.delivery_error_description ? ` · ${item.delivery_error_description}` : ""}
                    </p>
                  ) : null}
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
