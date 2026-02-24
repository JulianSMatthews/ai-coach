import Link from "next/link";
import { revalidatePath } from "next/cache";
import AdminNav from "@/components/AdminNav";
import { listAdminUsers, setAdminUserRole, type AdminUserSummary } from "@/lib/api";

export const dynamic = "force-dynamic";

function normalizeRole(user: AdminUserSummary): "member" | "club_admin" | "global_admin" {
  const raw = String(user.admin_role || "").trim().toLowerCase();
  if (raw === "global_admin") return "global_admin";
  if (raw === "club_admin") return "club_admin";
  if (user.is_superuser) return "global_admin";
  return "member";
}

function roleLabel(role: string): string {
  if (role === "global_admin") return "Global admin";
  if (role === "club_admin") return "Club admin";
  return "Member";
}

function roleDescription(role: string): string {
  if (role === "global_admin") {
    return "Full platform access across all clubs, including role management and system settings.";
  }
  if (role === "club_admin") {
    return "Admin access scoped to one club: users, prompts, reporting, and operational tools.";
  }
  return "Standard access with no admin privileges.";
}

async function setRoleAction(formData: FormData) {
  "use server";
  const userId = Number(formData.get("user_id") || 0);
  const role = String(formData.get("admin_role") || "").trim().toLowerCase();
  if (!userId) return;
  if (!["member", "club_admin", "global_admin"].includes(role)) return;
  try {
    await setAdminUserRole(userId, role as "member" | "club_admin" | "global_admin");
  } catch (err) {
    console.error("[team roles] set role failed", { userId, role, err });
  }
  revalidatePath("/admin/team/roles");
}

export default async function TeamRolesPage() {
  const users = await listAdminUsers();

  return (
    <main className="min-h-screen bg-[#f7f4ee] px-6 py-10 text-[#1e1b16]">
      <div className="mx-auto w-full max-w-6xl space-y-6">
        <AdminNav title="Team Roles" subtitle="Set staff access roles for HS Admin." />

        <section className="rounded-3xl border border-[#e7e1d6] bg-white p-6">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <p className="text-sm text-[#6b6257]">
              Role updates require a global admin session. Club admins can view this list.
            </p>
            <Link
              href="/admin/team"
              className="rounded-full border border-[#efe7db] bg-[#fdfaf4] px-4 py-2 text-xs uppercase tracking-[0.2em]"
            >
              Back to team
            </Link>
          </div>

          <div className="mt-4 overflow-x-auto">
            <table className="w-full min-w-[1180px] text-left text-sm">
              <thead className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">
                <tr>
                  <th className="py-2 pr-6">ID</th>
                  <th className="py-2 pr-6">Name</th>
                  <th className="py-2 pr-6">Phone</th>
                  <th className="py-2 pr-6">Club</th>
                  <th className="py-2 pr-6">Current role</th>
                  <th className="py-2 pr-6">Role description</th>
                  <th className="py-2 pr-6">Set role</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[#efe7db]">
                {users.map((u) => {
                  const role = normalizeRole(u);
                  const name =
                    u.display_name ||
                    [u.first_name, u.surname].filter(Boolean).join(" ").trim() ||
                    `User ${u.id}`;
                  return (
                    <tr key={u.id}>
                      <td className="py-3 pr-6">#{u.id}</td>
                      <td className="py-3 pr-6">{name}</td>
                      <td className="py-3 pr-6">{u.phone || "—"}</td>
                      <td className="py-3 pr-6">{u.club_id ?? "—"}</td>
                      <td className="py-3 pr-6">{roleLabel(role)}</td>
                      <td className="py-3 pr-6 text-[#6b6257]">{roleDescription(role)}</td>
                      <td className="py-3 pr-6">
                        <form action={setRoleAction} className="flex items-center gap-2">
                          <input type="hidden" name="user_id" value={u.id} />
                          <select
                            name="admin_role"
                            defaultValue={role}
                            className="rounded-xl border border-[#efe7db] bg-white px-3 py-2 text-sm"
                          >
                            <option value="member">Member</option>
                            <option value="club_admin">Club admin</option>
                            <option value="global_admin">Global admin</option>
                          </select>
                          <button
                            type="submit"
                            className="rounded-full border border-[var(--accent)] bg-[var(--accent)] px-3 py-2 text-xs uppercase tracking-[0.2em] text-white"
                          >
                            Save
                          </button>
                        </form>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </section>
      </div>
    </main>
  );
}
