import Link from "next/link";
import { revalidatePath } from "next/cache";
import AdminNav from "@/components/AdminNav";
import {
  createAdminUser,
  listAdminUsers,
} from "@/lib/api";

type UsersPageProps = {
  searchParams: Promise<{ q?: string }>;
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
  return (
    <main className="min-h-screen bg-[#f7f4ee] px-6 py-10 text-[#1e1b16]">
      <div className="mx-auto w-full max-w-6xl space-y-6">
        <AdminNav title="Users" subtitle="Search users and review account activity and app state." />

        <details className="rounded-3xl border border-[#e7e1d6] bg-white p-6">
          <summary className="cursor-pointer text-lg font-semibold">Add user</summary>
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
        </details>

        <section className="rounded-3xl border border-[#e7e1d6] bg-white p-6">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <h2 className="text-lg font-semibold">Users</h2>
            <form className="flex items-center gap-2" method="get">
              <input
                name="q"
                defaultValue={query}
                placeholder="Search id, name, phone or email"
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
            <table className="w-full min-w-[600px] text-left text-sm">
              <thead className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">
                <tr><th className="py-3 pr-6">User</th><th className="py-3 pr-6">Last app access</th><th className="py-3 pr-6">Joined</th><th className="py-3">Profile</th></tr>
              </thead>
              <tbody className="divide-y divide-[#efe7db]">
                {users.map((u) => <tr key={u.id}>
                  <td className="py-4 pr-6"><Link href={`/admin/users/${u.id}`} className="font-semibold hover:underline">{[u.first_name, u.surname].filter(Boolean).join(" ") || `User #${u.id}`}</Link><p className="mt-1 text-xs text-[#6b6257]">#{u.id}</p></td>
                  <td className="py-4 pr-6 text-[#6b6257]">{u.last_app_access_at ? <>{formatDate(u.last_app_access_at)}<p className="mt-1 text-xs">{u.days_since_last_accessed === 0 ? "Today" : u.days_since_last_accessed != null ? `${u.days_since_last_accessed} days ago` : ""}</p></> : "No recorded access"}</td>
                  <td className="py-4 pr-6 text-[#6b6257]">{formatDate(u.created_on)}</td>
                  <td className="py-4"><Link href={`/admin/users/${u.id}`} className="rounded-full border border-[#efe7db] px-3 py-2 text-xs">View user</Link></td>
                </tr>)}
                {!users.length ? <tr><td className="py-6 text-[#6b6257]" colSpan={4}>No users found. Try a different search.</td></tr> : null}
              </tbody>
            </table>
          </div>
        </section>
      </div>
    </main>
  );
}
