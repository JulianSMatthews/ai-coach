import Link from "next/link";
import { revalidatePath } from "next/cache";
import AdminNav from "@/components/AdminNav";
import {
  createAdminUser,
  listAdminUsers,
} from "@/lib/api";

type UsersPageProps = {
  searchParams: Promise<{ q?: string; inbound_window?: string }>;
};

export const dynamic = "force-dynamic";

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

export default async function UsersPage({ searchParams }: UsersPageProps) {
  const resolvedSearchParams = await searchParams;
  const query = (resolvedSearchParams?.q || "").trim();
  const inboundWindowRaw = (resolvedSearchParams?.inbound_window || "").trim().toLowerCase();
  const inboundWindow: "all" | "outside_24h" | "inside_24h" =
    inboundWindowRaw === "outside_24h"
      ? "outside_24h"
      : inboundWindowRaw === "inside_24h"
        ? "inside_24h"
        : "all";
  const users = await listAdminUsers(query || undefined, inboundWindow);
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
  const isOutside24h = (value?: string | null) => {
    if (!value) return true;
    try {
      const dt = new Date(value);
      if (Number.isNaN(dt.getTime())) return true;
      return Date.now() - dt.getTime() > 24 * 60 * 60 * 1000;
    } catch {
      return true;
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
              <select
                name="inbound_window"
                defaultValue={inboundWindow}
                className="rounded-full border border-[#efe7db] px-3 py-2 text-sm"
              >
                <option value="all">All users</option>
                <option value="outside_24h">Outside 24h window</option>
                <option value="inside_24h">Inside 24h window</option>
              </select>
              <button
                type="submit"
                className="rounded-full border border-[#efe7db] px-4 py-2 text-xs uppercase tracking-[0.2em]"
              >
                Search
              </button>
            </form>
          </div>

          <div className="mt-4 overflow-x-auto">
            <table className="w-full min-w-[980px] text-left text-sm">
              <thead className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">
                <tr>
                  <th className="sticky left-0 z-20 min-w-[80px] bg-white py-2 pr-6 whitespace-nowrap">ID</th>
                  <th className="sticky left-[80px] z-20 min-w-[160px] bg-white py-2 pr-6 whitespace-nowrap">First name</th>
                  <th className="sticky left-[240px] z-20 min-w-[160px] bg-white py-2 pr-6 whitespace-nowrap">Surname</th>
                  <th className="py-2 pr-6 whitespace-nowrap">Phone</th>
                  <th className="py-2 pr-6 whitespace-nowrap">Consent given</th>
                  <th className="py-2 pr-6 whitespace-nowrap">Last inbound</th>
                  <th className="py-2 pr-6 whitespace-nowrap">First assessment</th>
                  <th className="py-2 pr-6 whitespace-nowrap">Next scheduled</th>
                  <th className="py-2 whitespace-nowrap">Action</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[#efe7db]">
                {users.map((u) => {
                  return (
                    <tr key={u.id}>
                    <td className="sticky left-0 z-10 min-w-[80px] bg-white py-3 pr-6 whitespace-nowrap text-[#6b6257]">#{u.id}</td>
                    <td className="sticky left-[80px] z-10 min-w-[160px] bg-white py-3 pr-6 whitespace-nowrap">{u.first_name || "—"}</td>
                    <td className="sticky left-[240px] z-10 min-w-[160px] bg-white py-3 pr-6 whitespace-nowrap">{u.surname || "—"}</td>
                    <td className="py-3 pr-6 whitespace-nowrap text-[#6b6257]">{u.phone || "—"}</td>
                    <td className="py-3 pr-6 whitespace-nowrap text-[#6b6257]">{u.consent_given ? "Yes" : "No"}</td>
                    <td
                      className={`py-3 pr-6 whitespace-nowrap ${isOutside24h(u.last_inbound_message_at) ? "text-[#b42318] font-semibold" : "text-[#6b6257]"}`}
                    >
                      {formatDateTime(u.last_inbound_message_at)}
                    </td>
                    <td className="py-3 pr-6 whitespace-nowrap text-[#6b6257]">
                      {formatDate(u.first_assessment_completed_at)}
                    </td>
                    <td className="py-3 pr-6 whitespace-nowrap text-[#6b6257]">
                      {formatDateTime(u.next_scheduled_at)}
                    </td>
                    <td className="py-3 whitespace-nowrap">
                      <Link
                        href={`/admin/users/${u.id}/actions`}
                        className="rounded-full border border-[#efe7db] px-3 py-1 text-xs"
                      >
                        action
                      </Link>
                    </td>
                    </tr>
                  );
                })}
                {!users.length ? (
                  <tr>
                    <td className="py-6 text-sm text-[#6b6257]" colSpan={9}>
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
