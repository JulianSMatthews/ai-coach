import { cookies } from "next/headers";
import ProgressPage from "./progress/[userId]/page";

export default async function Home() {
  const cookieStore = await cookies();
  const cookieUserId = cookieStore.get("hs_user_id")?.value;
  const rawUserId = cookieUserId || process.env.NEXT_PUBLIC_DEFAULT_USER_ID || "1";
  const userId = String(rawUserId).replace(/[^0-9]/g, "") || "1";
  return ProgressPage({
    params: Promise.resolve({ userId }),
    searchParams: Promise.resolve({}),
  });
}
