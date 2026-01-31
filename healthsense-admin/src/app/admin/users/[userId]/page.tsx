import Link from "next/link";
import AdminNav from "@/components/AdminNav";
import { getAdminUserDetails } from "@/lib/api";

type UserStatusPageProps = {
  params: Promise<{ userId: string }>;
};

export const dynamic = "force-dynamic";

export default async function UserStatusPage({ params }: UserStatusPageProps) {
  const resolvedParams = await params;
  const userId = Number(resolvedParams.userId);
  const detail = await getAdminUserDetails(userId);
  const user = detail.user as Record<string, unknown> | undefined;
  const status = detail.status as string | undefined;
  const latest = detail.latest_run as { id?: number; finished_at?: string } | undefined;
  const fields = user ? Object.entries(user) : [];

  return (
    <main className="min-h-screen bg-[#f7f4ee] px-6 py-10 text-[#1e1b16]">
      <div className="mx-auto w-full max-w-5xl space-y-6">
        <AdminNav
          title={
            typeof user?.display_name === "string"
              ? `Details · ${user.display_name}`
              : `Details · #${userId}`
          }
          subtitle="User profile fields and latest assessment metadata."
        />

        <section className="rounded-3xl border border-[#e7e1d6] bg-white p-6">
          <div className="grid gap-4 md:grid-cols-2">
            <div>
              <p className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Status</p>
              <p className="mt-2 text-lg font-semibold capitalize">{status || "unknown"}</p>
              <p className="mt-1 text-sm text-[#6b6257]">
                Latest run: {latest?.id ? `#${latest.id}` : "—"}
              </p>
            </div>
            <div>
              <p className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Latest run finished</p>
              <p className="mt-2 text-sm text-[#6b6257]">{latest?.finished_at || "—"}</p>
            </div>
          </div>

          <div className="mt-6 overflow-hidden rounded-2xl border border-[#efe7db]">
            <table className="w-full text-left text-sm">
              <thead className="bg-[#faf7f1] text-xs uppercase tracking-[0.2em] text-[#6b6257]">
                <tr>
                  <th className="px-4 py-3">Field</th>
                  <th className="px-4 py-3">Value</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[#efe7db]">
                {fields.map(([key, value]) => (
                  <tr key={key}>
                    <td className="px-4 py-3 font-medium">{key}</td>
                    <td className="px-4 py-3 text-[#6b6257]">
                      {value === null || value === undefined ? "—" : String(value)}
                    </td>
                  </tr>
                ))}
                {!fields.length ? (
                  <tr>
                    <td className="px-4 py-6 text-[#6b6257]" colSpan={2}>
                      No user fields available.
                    </td>
                  </tr>
                ) : null}
              </tbody>
            </table>
          </div>

          <div className="mt-6">
            <Link
              className="rounded-full border border-[#efe7db] px-4 py-2 text-xs uppercase tracking-[0.2em]"
              href="/admin/users"
            >
              Back to users
            </Link>
          </div>
        </section>
      </div>
    </main>
  );
}
