import { cookies } from "next/headers";
import AssessmentChatPage from "./assessment/[userId]/chat/page";

export default async function Home() {
  const cookieStore = await cookies();
  const cookieUserId = cookieStore.get("hs_user_id")?.value;
  const rawUserId = cookieUserId || process.env.NEXT_PUBLIC_DEFAULT_USER_ID || "1";
  const userId = String(rawUserId).replace(/[^0-9]/g, "") || "1";
  return AssessmentChatPage({
    params: Promise.resolve({ userId }),
    searchParams: Promise.resolve({}),
  });
}
