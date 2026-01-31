import { redirect } from "next/navigation";

type PageProps = {
  params: Promise<{ userId: string }>;
  searchParams: Promise<{ anchor_date?: string }>;
};

export default async function DashboardPage(props: PageProps) {
  const { userId: rawUserId } = await props.params;

  const userId = rawUserId.replace(/[^0-9]/g, "");
  if (!userId) {
    throw new Error(`Invalid user id: ${rawUserId}`);
  }
  redirect(`/progress/${userId}`);
}
