import Link from "next/link";
import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";
import AdminNav from "@/components/AdminNav";
import {
  createAdminUserAppSession,
  createAdminUser,
  deleteAdminUser,
  listAdminUsers,
  resetAdminUser,
  setAdminUserCoaching,
  setAdminUserPromptState,
  startAdminUser,
} from "@/lib/api";

type UsersPageProps = {
  searchParams: Promise<{ q?: string }>;
};

export const dynamic = "force-dynamic";

function resolveHsAppBase(): string {
  const allowLocal = (process.env.HSAPP_ALLOW_LOCALHOST_URLS || "").trim() === "1";
  const nodeEnv = (process.env.NODE_ENV || "").toLowerCase();
  const isDev = nodeEnv === "development";
  const isHosted =
    !isDev ||
    (process.env.ENV || "").toLowerCase() === "production" ||
    (process.env.RENDER || "").toLowerCase() === "true" ||
    Boolean((process.env.RENDER_EXTERNAL_URL || "").trim());
  const rawCandidates = [
    process.env.NEXT_PUBLIC_HSAPP_BASE_URL,
    process.env.NEXT_PUBLIC_APP_BASE_URL,
    process.env.HSAPP_PUBLIC_URL,
    process.env.HSAPP_PUBLIC_DEFAULT_URL,
    process.env.HSAPP_NGROK_DOMAIN,
  ];

  const normalized = rawCandidates
    .map((raw) => (raw || "").trim())
    .filter(Boolean)
    .map((raw) => (raw.startsWith("http://") || raw.startsWith("https://") ? raw : `https://${raw}`))
    .map((url) => url.replace(/\/+$/, ""));

  for (const candidate of normalized) {
    try {
      const host = new URL(candidate).hostname.toLowerCase();
      const isLocalHost = host === "localhost" || host === "127.0.0.1" || host === "0.0.0.0" || host.endsWith(".local");
      if (!allowLocal && isLocalHost) continue;
      if (isHosted && isLocalHost) continue;
      return candidate;
    } catch {
      continue;
    }
  }

  return "https://app.healthsense.coach";
}

async function createUserAction(formData: FormData) {
  "use server";
  const first_name = String(formData.get("first_name") || "").trim();
  const surname = String(formData.get("surname") || "").trim();
  const phone = String(formData.get("phone") || "").trim();
  if (!first_name || !surname || !phone) {
    return;
  }
  await createAdminUser({ first_name, surname, phone });
  revalidatePath("/admin/users");
}

async function startUserAction(formData: FormData) {
  "use server";
  const userId = Number(formData.get("user_id") || 0);
  if (!userId) return;
  await startAdminUser(userId);
  revalidatePath("/admin/users");
}

async function setPromptStateAction(formData: FormData) {
  "use server";
  const userId = Number(formData.get("user_id") || 0);
  const state = String(formData.get("state") || "").trim();
  if (!userId || !state) return;
  await setAdminUserPromptState(userId, state);
  revalidatePath("/admin/users");
}

async function resetUserAction(formData: FormData) {
  "use server";
  const userId = Number(formData.get("user_id") || 0);
  const confirm = String(formData.get("confirm") || "").trim().toLowerCase();
  if (!userId || confirm !== "reset") return;
  await resetAdminUser(userId);
  revalidatePath("/admin/users");
}

async function deleteUserAction(formData: FormData) {
  "use server";
  const userId = Number(formData.get("user_id") || 0);
  const confirm = String(formData.get("confirm") || "").trim().toLowerCase();
  if (!userId || confirm !== "delete") return;
  await deleteAdminUser(userId);
  revalidatePath("/admin/users");
}

async function coachUserAction(formData: FormData) {
  "use server";
  const userId = Number(formData.get("user_id") || 0);
  if (!userId) return;
  await setAdminUserCoaching(userId, true);
  revalidatePath("/admin/users");
}

async function fastCoachUserAction(formData: FormData) {
  "use server";
  const userId = Number(formData.get("user_id") || 0);
  const fastMinutesRaw = String(formData.get("fast_minutes") || "").trim();
  const fastMinutesParsed = Number.parseInt(fastMinutesRaw || "2", 10);
  if (!userId || !Number.isFinite(fastMinutesParsed)) return;
  const fastMinutes = Math.max(1, Math.min(120, fastMinutesParsed));
  await setAdminUserCoaching(userId, true, fastMinutes);
  revalidatePath("/admin/users");
}

async function stopCoachingAction(formData: FormData) {
  "use server";
  const userId = Number(formData.get("user_id") || 0);
  if (!userId) return;
  await setAdminUserCoaching(userId, false);
  revalidatePath("/admin/users");
}

async function openAppAction(formData: FormData) {
  "use server";
  const userId = Number(formData.get("user_id") || 0);
  if (!userId) return;
  const appBase = resolveHsAppBase();
  const session = await createAdminUserAppSession(userId);
  const token = String(session.session_token || "").trim();
  if (!token) return;
  const nextPath = `/progress/${userId}`;
  const url =
    `${appBase}/api/auth/admin-app-login?session_token=${encodeURIComponent(token)}` +
    `&user_id=${encodeURIComponent(String(userId))}` +
    `&next=${encodeURIComponent(nextPath)}`;
  redirect(url);
}

export default async function UsersPage({ searchParams }: UsersPageProps) {
  const resolvedSearchParams = await searchParams;
  const query = (resolvedSearchParams?.q || "").trim();
  const users = await listAdminUsers(query || undefined);
  const formatDate = (value?: string | null) => {
    if (!value) return "—";
    try {
      const dt = new Date(value);
      if (Number.isNaN(dt.getTime())) return "—";
      return dt
        .toLocaleString("en-GB", {
          day: "2-digit",
          month: "2-digit",
          year: "2-digit",
          timeZone: "Europe/London",
        })
        .replace(",", "");
    } catch {
      return "—";
    }
  };
  const formatDateTime = (value?: string | null) => {
    if (!value) return "—";
    try {
      const dt = new Date(value);
      if (Number.isNaN(dt.getTime())) return "—";
      return dt
        .toLocaleString("en-GB", {
          day: "2-digit",
          month: "2-digit",
          year: "2-digit",
          hour: "2-digit",
          minute: "2-digit",
          hour12: false,
          timeZone: "Europe/London",
        })
        .replace(",", "");
    } catch {
      return "—";
    }
  };

  return (
    <main className="min-h-screen bg-[#f7f4ee] px-6 py-10 text-[#1e1b16]">
      <div className="mx-auto w-full max-w-6xl space-y-6">
        <AdminNav title="User management" subtitle="Search members, start assessments, and review status." />

        <section className="rounded-3xl border border-[#e7e1d6] bg-white p-6">
          <h2 className="text-lg font-semibold">Create a new user</h2>
          <form action={createUserAction} className="mt-4 grid gap-3 md:grid-cols-[1fr_1fr_1fr_auto]">
            <input
              name="first_name"
              className="rounded-xl border border-[#efe7db] px-3 py-2 text-sm"
              placeholder="First name"
            />
            <input
              name="surname"
              className="rounded-xl border border-[#efe7db] px-3 py-2 text-sm"
              placeholder="Surname"
            />
            <input
              name="phone"
              className="rounded-xl border border-[#efe7db] px-3 py-2 text-sm"
              placeholder="+44 7700 900000"
            />
            <button
              type="submit"
              className="rounded-full border border-[var(--accent)] bg-[var(--accent)] px-4 py-2 text-xs uppercase tracking-[0.2em] text-white"
            >
              Create
            </button>
          </form>
        </section>

        <section className="rounded-3xl border border-[#e7e1d6] bg-white p-6">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <h2 className="text-lg font-semibold">Users</h2>
            <form className="flex items-center gap-2" method="get">
              <input
                name="q"
                defaultValue={query}
                placeholder="Search name or phone"
                className="rounded-full border border-[#efe7db] px-3 py-2 text-sm"
              />
              <button
                type="submit"
                className="rounded-full border border-[#efe7db] px-4 py-2 text-xs uppercase tracking-[0.2em]"
              >
                Search
              </button>
            </form>
          </div>

          <div className="mt-4 overflow-x-auto">
            <table className="w-full min-w-[1100px] text-left text-sm">
              <thead className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">
                <tr>
                  <th className="py-2 pr-6 whitespace-nowrap">ID</th>
                  <th className="py-2 pr-6 whitespace-nowrap">First name</th>
                  <th className="py-2 pr-6 whitespace-nowrap">Surname</th>
                  <th className="py-2 pr-6 whitespace-nowrap">Phone</th>
                  <th className="py-2 pr-6 whitespace-nowrap">Created on</th>
                  <th className="py-2 pr-6 whitespace-nowrap">Updated on</th>
                  <th className="py-2 pr-6 whitespace-nowrap">Consent given</th>
                  <th className="py-2 pr-6 whitespace-nowrap">Consent at</th>
                  <th className="py-2 pr-6 whitespace-nowrap">Last inbound</th>
                  <th className="py-2 pr-6 whitespace-nowrap">Last template sent</th>
                  <th className="py-2 pr-6 whitespace-nowrap">Last assessment</th>
                  <th className="py-2 pr-6 whitespace-nowrap">Prompt state</th>
                  <th className="py-2 pr-6 whitespace-nowrap">Coaching</th>
                  <th className="py-2 whitespace-nowrap">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[#efe7db]">
                {users.map((u) => {
                  const promptState = (u.prompt_state_override || "live").toLowerCase();
                  const coachingOn = Boolean(u.coaching_enabled);
                  const fastMinutes =
                    typeof u.coaching_fast_minutes === "number" && u.coaching_fast_minutes > 0
                      ? u.coaching_fast_minutes
                      : null;
                  return (
                    <tr key={u.id}>
                    <td className="py-3 pr-6 whitespace-nowrap text-[#6b6257]">#{u.id}</td>
                    <td className="py-3 pr-6 whitespace-nowrap">{u.first_name || "—"}</td>
                    <td className="py-3 pr-6 whitespace-nowrap">{u.surname || "—"}</td>
                    <td className="py-3 pr-6 whitespace-nowrap text-[#6b6257]">{u.phone || "—"}</td>
                    <td className="py-3 pr-6 whitespace-nowrap text-[#6b6257]">{formatDate(u.created_on)}</td>
                    <td className="py-3 pr-6 whitespace-nowrap text-[#6b6257]">{formatDate(u.updated_on)}</td>
                    <td className="py-3 pr-6 whitespace-nowrap text-[#6b6257]">{u.consent_given ? "Yes" : "No"}</td>
                    <td className="py-3 pr-6 whitespace-nowrap text-[#6b6257]">{formatDate(u.consent_at)}</td>
                    <td className="py-3 pr-6 whitespace-nowrap text-[#6b6257]">
                      {formatDateTime(u.last_inbound_message_at)}
                    </td>
                    <td className="py-3 pr-6 whitespace-nowrap text-[#6b6257]">
                      {formatDateTime(u.last_template_message_at)}
                    </td>
                    <td className="py-3 pr-6 whitespace-nowrap text-[#6b6257]">
                      {formatDate(u.latest_run_finished_at)}
                    </td>
                    <td className="py-3 pr-6 whitespace-nowrap">
                      <form action={setPromptStateAction} className="flex items-center gap-2">
                        <input type="hidden" name="user_id" value={u.id} />
                        <select
                          name="state"
                          defaultValue={promptState}
                          className="rounded-full border border-[#efe7db] bg-white px-3 py-1 text-xs"
                        >
                          <option value="live">live</option>
                          <option value="beta">beta</option>
                        </select>
                        <button
                          type="submit"
                          className="rounded-full border border-[#efe7db] px-3 py-1 text-xs"
                        >
                          set
                        </button>
                      </form>
                    </td>
                    <td className="py-3 pr-6 whitespace-nowrap text-[#6b6257]">
                      {coachingOn ? (fastMinutes ? `Fast (${fastMinutes}m)` : "On") : "Off"}
                    </td>
                    <td className="py-3 whitespace-nowrap">
                      <div className="flex items-center gap-2 whitespace-nowrap">
                        <form action={openAppAction} target="_blank">
                          <input type="hidden" name="user_id" value={u.id} />
                          <button
                            type="submit"
                            className="rounded-full border border-[#efe7db] px-3 py-1 text-xs"
                          >
                            app
                          </button>
                        </form>
                        <Link
                          href={`/admin/users/${u.id}`}
                          className="rounded-full border border-[#efe7db] px-3 py-1 text-xs"
                        >
                          detail
                        </Link>
                        <form action={startUserAction}>
                          <input type="hidden" name="user_id" value={u.id} />
                          <button
                            type="submit"
                            className="rounded-full border border-[#efe7db] px-3 py-1 text-xs"
                          >
                            assess
                          </button>
                        </form>
                        <form action={resetUserAction}>
                          <input type="hidden" name="user_id" value={u.id} />
                          <input type="hidden" name="confirm" value="reset" />
                          <button
                            type="submit"
                            className="rounded-full border border-[#efe7db] px-3 py-1 text-xs"
                          >
                            reset
                          </button>
                        </form>
                        <form action={fastCoachUserAction} className="flex items-center gap-1">
                          <input type="hidden" name="user_id" value={u.id} />
                          <input
                            type="number"
                            name="fast_minutes"
                            min={1}
                            max={120}
                            defaultValue={fastMinutes || 2}
                            className="w-14 rounded-full border border-[#efe7db] px-2 py-1 text-xs"
                            aria-label={`Fast coaching minutes for user ${u.id}`}
                          />
                          <button
                            type="submit"
                            className="rounded-full border border-[var(--accent)] px-3 py-1 text-xs text-[var(--accent)]"
                          >
                            fast on
                          </button>
                        </form>
                        <form action={deleteUserAction}>
                          <input type="hidden" name="user_id" value={u.id} />
                          <input type="hidden" name="confirm" value="delete" />
                          <button
                            type="submit"
                            className="rounded-full border border-[#c43e1c] px-3 py-1 text-xs text-[#c43e1c]"
                          >
                            delete
                          </button>
                        </form>
                        {!coachingOn ? (
                          <form action={coachUserAction}>
                            <input type="hidden" name="user_id" value={u.id} />
                            <button
                              type="submit"
                              className="rounded-full border border-[var(--accent)] px-3 py-1 text-xs text-[var(--accent)]"
                            >
                              coach
                            </button>
                          </form>
                        ) : (
                          <form action={stopCoachingAction}>
                            <input type="hidden" name="user_id" value={u.id} />
                            <button
                              type="submit"
                              className="rounded-full border border-[#efe7db] px-3 py-1 text-xs"
                            >
                              stop
                            </button>
                          </form>
                        )}
                      </div>
                    </td>
                    </tr>
                  );
                })}
                {!users.length ? (
                  <tr>
                    <td className="py-6 text-sm text-[#6b6257]" colSpan={14}>
                      No users found. Try a different search.
                    </td>
                  </tr>
                ) : null}
              </tbody>
            </table>
          </div>
        </section>
      </div>
    </main>
  );
}
