import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";
import {
  createAdminUserAppSession,
  deleteAdminUser,
  setAdminUserPromptState,
} from "@/lib/api";

function normalizeHsAppBase(raw: string | null | undefined): string | null {
  const nodeEnv = (process.env.NODE_ENV || "").toLowerCase();
  const isDev = nodeEnv === "development";
  const isHosted =
    (process.env.ENV || "").toLowerCase() === "production" ||
    (process.env.RENDER || "").toLowerCase() === "true" ||
    Boolean((process.env.RENDER_EXTERNAL_URL || "").trim());
  const allowLocalInDev =
    isDev &&
    !isHosted &&
    (process.env.HSAPP_ALLOW_LOCALHOST_URLS || "").trim() === "1";
  const input = String(raw || "").trim();
  if (!input) return null;
  try {
    const parsed = new URL(
      input.startsWith("http://") || input.startsWith("https://")
        ? input
        : `https://${input}`,
    );
    const host = parsed.hostname.toLowerCase();
    const isLocalHost =
      host === "localhost" ||
      host === "127.0.0.1" ||
      host === "0.0.0.0" ||
      host.endsWith(".local");
    if (isLocalHost && (!allowLocalInDev || isHosted)) return null;
    if (!isDev && parsed.protocol !== "https:") return null;
    return parsed.origin;
  } catch {
    return null;
  }
}

function resolveHsAppBase(): string {
  const rawCandidates = [
    process.env.NEXT_PUBLIC_HSAPP_BASE_URL,
    process.env.NEXT_PUBLIC_APP_BASE_URL,
    process.env.HSAPP_PUBLIC_URL,
    process.env.HSAPP_PUBLIC_DEFAULT_URL,
    process.env.HSAPP_NGROK_DOMAIN,
  ];
  for (const raw of rawCandidates) {
    const normalized = normalizeHsAppBase(raw);
    if (normalized) return normalized;
  }
  return "https://app.coachsense.ai";
}

function formatDateTime(value?: string | null): string {
  if (!value) return "—";
  return String(value).slice(0, 19).replace("T", " ");
}

async function openAppAction(formData: FormData) {
  "use server";
  const userId = Number(formData.get("user_id") || 0);
  if (!userId) return;
  const session = await createAdminUserAppSession(userId);
  const appBase =
    normalizeHsAppBase(session.app_base_url) || resolveHsAppBase();
  const token = String(session.session_token || "").trim();
  if (!token) return;
  const nextPath = `/assessment/${userId}/chat`;
  const url =
    `${appBase}/api/auth/admin-app-login?session_token=${encodeURIComponent(token)}` +
    `&user_id=${encodeURIComponent(String(userId))}` +
    `&next=${encodeURIComponent(nextPath)}`;
  redirect(url);
}

async function setPromptStateAction(formData: FormData) {
  "use server";
  const userId = Number(formData.get("user_id") || 0);
  const state = String(formData.get("state") || "").trim();
  if (!userId || !state) return;
  await setAdminUserPromptState(userId, state);
  revalidatePath(`/admin/users/${userId}`);
  revalidatePath("/admin/users");
}

async function deleteUserAction(formData: FormData) {
  "use server";
  const userId = Number(formData.get("user_id") || 0);
  const confirm = String(formData.get("confirm") || "")
    .trim()
    .toLowerCase();
  if (!userId || confirm !== "delete") return;
  await deleteAdminUser(userId);
  revalidatePath("/admin/users");
  redirect("/admin/users");
}

export default function AccountTools({
  userId,
  coachingOn,
  promptState,
}: {
  userId: number;
  coachingOn: boolean;
  promptState: string;
}) {
  const input = <input type="hidden" name="user_id" value={userId} />;
  const button =
    "rounded-full border border-[#d9cebe] px-4 py-2 text-sm font-medium";
  return (
    <div className="space-y-5">
      <section className="rounded-2xl border border-[#efe7db] p-5">
        <h2 className="text-lg font-semibold">Preview user app</h2>
        <p className="my-3 text-sm text-[#6b6257]">
          Open a read-only admin preview of the user’s app.
        </p>
        <form action={openAppAction}>
          {input}
          <button className={button}>Open app preview</button>
        </form>
      </section>
      <details className="rounded-2xl border border-[#efe7db] p-5">
        <summary className="cursor-pointer font-semibold">
          Advanced settings
        </summary>
        <div className="mt-4 space-y-5">
          <form
            action={setPromptStateAction}
            className="flex flex-wrap items-center gap-3"
          >
            {input}
            <label htmlFor="prompt-state">Prompt version</label>
            <select
              id="prompt-state"
              name="state"
              defaultValue={promptState}
              className="rounded-lg border p-2"
            >
              <option value="live">Live</option>
              <option value="beta">Beta</option>
            </select>
            <button className={button}>Save prompt version</button>
          </form>
          <div>
            <p className="font-medium">
              Legacy coaching: {coachingOn ? "enabled" : "disabled"}
            </p>
            <p className="my-2 text-sm text-[#6b6257]">
              Read-only compatibility state for the introduction flow. Scheduling
              and messaging controls have been retired.
            </p>
          </div>
        </div>
      </details>
      <details className="rounded-2xl border border-[#e5b8ad] p-5">
        <summary className="cursor-pointer font-semibold text-[#92321b]">
          Delete user
        </summary>
        <p className="my-3 text-sm">
          Permanently remove this account and its data. Type DELETE to confirm.
        </p>
        <form action={deleteUserAction} className="flex flex-wrap gap-3">
          {input}
          <input
            name="confirm"
            aria-label="Type DELETE to confirm"
            required
            pattern="DELETE"
            className="rounded-lg border px-3 py-2"
            autoComplete="off"
          />
          <button className={button}>Delete user</button>
        </form>
      </details>
    </div>
  );
}
