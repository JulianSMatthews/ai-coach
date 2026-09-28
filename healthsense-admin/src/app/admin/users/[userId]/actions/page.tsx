import { redirect } from "next/navigation";
export default async function UserActionsPage({
  params,
}: {
  params: Promise<{ userId: string }>;
}) {
  const { userId } = await params;
  redirect(`/admin/users/${encodeURIComponent(userId)}?section=account`);
}
