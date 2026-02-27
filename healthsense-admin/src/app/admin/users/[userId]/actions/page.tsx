import Link from "next/link";
import { revalidatePath } from "next/cache";
import { redirect, notFound } from "next/navigation";
import type { ReactNode } from "react";
import AdminNav from "@/components/AdminNav";
import {
  createAdminUserAppSession,
  deleteAdminUser,
  listAdminUsers,
  resetAdminUser,
  sendAdminUser24hTemplate,
  sendAdminUserSms,
  setAdminUserCoaching,
  setAdminUserPromptState,
  startAdminUser,
} from "@/lib/api";

type UserActionsPageProps = {
  params: Promise<{ userId: string }>;
  searchParams: Promise<{ sms?: string; reopen?: string }>;
};

export const dynamic = "force-dynamic";

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
    const parsed = new URL(input.startsWith("http://") || input.startsWith("https://") ? input : `https://${input}`);
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
  return "https://app.healthsense.coach";
}

async function openAppAction(formData: FormData) {
  "use server";
  const userId = Number(formData.get("user_id") || 0);
  if (!userId) return;
  const session = await createAdminUserAppSession(userId);
  const appBase = normalizeHsAppBase(session.app_base_url) || resolveHsAppBase();
  const token = String(session.session_token || "").trim();
  if (!token) return;
  const nextPath = `/progress/${userId}`;
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
  revalidatePath(`/admin/users/${userId}/actions`);
  revalidatePath("/admin/users");
}

async function coachUserAction(formData: FormData) {
  "use server";
  const userId = Number(formData.get("user_id") || 0);
  if (!userId) return;
  await setAdminUserCoaching(userId, true);
  revalidatePath(`/admin/users/${userId}/actions`);
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
  revalidatePath(`/admin/users/${userId}/actions`);
  revalidatePath("/admin/users");
}

async function stopCoachingAction(formData: FormData) {
  "use server";
  const userId = Number(formData.get("user_id") || 0);
  if (!userId) return;
  await setAdminUserCoaching(userId, false);
  revalidatePath(`/admin/users/${userId}/actions`);
  revalidatePath("/admin/users");
}

async function startUserAction(formData: FormData) {
  "use server";
  const userId = Number(formData.get("user_id") || 0);
  if (!userId) return;
  await startAdminUser(userId);
  revalidatePath(`/admin/users/${userId}/actions`);
  revalidatePath("/admin/users");
}

async function resetUserAction(formData: FormData) {
  "use server";
  const userId = Number(formData.get("user_id") || 0);
  const confirm = String(formData.get("confirm") || "").trim().toLowerCase();
  if (!userId || confirm !== "reset") return;
  await resetAdminUser(userId);
  revalidatePath(`/admin/users/${userId}/actions`);
  revalidatePath("/admin/users");
}

async function deleteUserAction(formData: FormData) {
  "use server";
  const userId = Number(formData.get("user_id") || 0);
  const confirm = String(formData.get("confirm") || "").trim().toLowerCase();
  if (!userId || confirm !== "delete") return;
  await deleteAdminUser(userId);
  revalidatePath("/admin/users");
  redirect("/admin/users");
}

async function sendSmsAction(formData: FormData) {
  "use server";
  const userId = Number(formData.get("user_id") || 0);
  const message = String(formData.get("sms_message") || "").trim();
  if (!userId || !message) return;
  let failed = false;
  try {
    await sendAdminUserSms(userId, message);
  } catch {
    failed = true;
  }
  revalidatePath(`/admin/users/${userId}/actions`);
  redirect(`/admin/users/${userId}/actions?sms=${failed ? "failed" : "sent"}`);
}

async function send24hTemplateAction(formData: FormData) {
  "use server";
  const userId = Number(formData.get("user_id") || 0);
  if (!userId) return;
  let failed = false;
  try {
    await sendAdminUser24hTemplate(userId);
  } catch {
    failed = true;
  }
  revalidatePath(`/admin/users/${userId}/actions`);
  redirect(`/admin/users/${userId}/actions?reopen=${failed ? "failed" : "sent"}`);
}

function ActionCard({
  title,
  description,
  children,
}: {
  title: string;
  description: string;
  children: ReactNode;
}) {
  return (
    <section className="rounded-2xl border border-[#efe7db] bg-[#faf8f3] p-4">
      <h2 className="text-sm font-semibold uppercase tracking-[0.2em] text-[#6b6257]">{title}</h2>
      <p className="mt-2 text-sm text-[#6b6257]">{description}</p>
      <div className="mt-3">{children}</div>
    </section>
  );
}

export default async function UserActionsPage({ params, searchParams }: UserActionsPageProps) {
  const resolvedParams = await params;
  const resolvedSearchParams = await searchParams;
  const userId = Number(resolvedParams.userId);
  if (!Number.isFinite(userId) || userId <= 0) notFound();

  const users = await listAdminUsers();
  const user = users.find((u) => Number(u.id) === userId);
  if (!user) notFound();

  const promptState = (user.prompt_state_override || "live").toLowerCase();
  const coachingOn = Boolean(user.coaching_enabled);
  const hasFastMode = typeof user.coaching_fast_minutes === "number" && user.coaching_fast_minutes > 0;
  const fastMinutes: number = hasFastMode ? Number(user.coaching_fast_minutes) : 2;
  const smsStatus = String(resolvedSearchParams?.sms || "").trim().toLowerCase();
  const reopenStatus = String(resolvedSearchParams?.reopen || "").trim().toLowerCase();

  return (
    <main className="min-h-screen bg-[#f7f4ee] px-6 py-10 text-[#1e1b16]">
      <div className="mx-auto w-full max-w-5xl space-y-6">
        <AdminNav
          title={`Action · ${user.first_name || ""} ${user.surname || ""}`.trim() || `Action · #${userId}`}
          subtitle="Run user-specific operations with clear context and controls."
        />

        <section className="flex flex-wrap items-center justify-between gap-2 rounded-2xl border border-[#e7e1d6] bg-white px-4 py-3 text-sm">
          <div className="text-[#6b6257]">
            User #{userId} · {user.phone || "No phone"} · Prompt state: {promptState} · Coaching:{" "}
            {coachingOn ? (hasFastMode ? `On (${fastMinutes}m fast)` : "On") : "Off"}
          </div>
          <div className="flex items-center gap-2">
            <Link href={`/admin/users/${userId}`} className="rounded-full border border-[#efe7db] px-3 py-1 text-xs">
              detail
            </Link>
            <Link href="/admin/users" className="rounded-full border border-[#efe7db] px-3 py-1 text-xs">
              back to users
            </Link>
          </div>
        </section>

        {smsStatus === "sent" ? (
          <section className="rounded-2xl border border-[#b9e2c6] bg-[#ecf8f0] px-4 py-3 text-sm text-[#14532d]">
            SMS sent successfully.
          </section>
        ) : null}
        {smsStatus === "failed" ? (
          <section className="rounded-2xl border border-[#f2c1b5] bg-[#fef1ee] px-4 py-3 text-sm text-[#8c1d1d]">
            SMS failed to send. Please retry and check server logs for the provider error.
          </section>
        ) : null}
        {reopenStatus === "sent" ? (
          <section className="rounded-2xl border border-[#b9e2c6] bg-[#ecf8f0] px-4 py-3 text-sm text-[#14532d]">
            24h+ template sent successfully.
          </section>
        ) : null}
        {reopenStatus === "failed" ? (
          <section className="rounded-2xl border border-[#f2c1b5] bg-[#fef1ee] px-4 py-3 text-sm text-[#8c1d1d]">
            24h+ template failed to send. Please retry and check server logs for details.
          </section>
        ) : null}

        <div className="grid gap-4 md:grid-cols-2">
          <ActionCard
            title="Access app"
            description="Open the member app as this user in a secure admin session. Use this to review exactly what the user sees."
          >
            <form action={openAppAction}>
              <input type="hidden" name="user_id" value={userId} />
              <button
                type="submit"
                className="rounded-full border border-[var(--accent)] bg-[var(--accent)] px-4 py-2 text-xs uppercase tracking-[0.2em] text-white"
              >
                access app
              </button>
            </form>
          </ActionCard>

          <ActionCard
            title="Prompt state"
            description="Set this user to live or beta prompt behavior. Use beta to test changes safely on selected users."
          >
            <form action={setPromptStateAction} className="flex flex-wrap items-center gap-2">
              <input type="hidden" name="user_id" value={userId} />
              <select
                name="state"
                defaultValue={promptState}
                className="rounded-full border border-[#efe7db] bg-white px-3 py-2 text-sm"
              >
                <option value="live">live</option>
                <option value="beta">beta</option>
              </select>
              <button
                type="submit"
                className="rounded-full border border-[#efe7db] px-4 py-2 text-xs uppercase tracking-[0.2em]"
              >
                save
              </button>
            </form>
          </ActionCard>

          <ActionCard
            title="Coaching controls"
            description="Enable or stop coaching, and optionally set fast mode minutes for test cadence."
          >
            <div className="flex flex-wrap items-center gap-2">
              {!coachingOn ? (
                <form action={coachUserAction}>
                  <input type="hidden" name="user_id" value={userId} />
                  <button
                    type="submit"
                    className="rounded-full border border-[var(--accent)] px-4 py-2 text-xs uppercase tracking-[0.2em] text-[var(--accent)]"
                  >
                    set to coaching
                  </button>
                </form>
              ) : (
                <form action={stopCoachingAction}>
                  <input type="hidden" name="user_id" value={userId} />
                  <button
                    type="submit"
                    className="rounded-full border border-[#efe7db] px-4 py-2 text-xs uppercase tracking-[0.2em]"
                  >
                    stop coaching
                  </button>
                </form>
              )}
              <form action={fastCoachUserAction} className="flex flex-wrap items-center gap-2">
                <input type="hidden" name="user_id" value={userId} />
                <input
                  type="number"
                  name="fast_minutes"
                  min={1}
                  max={120}
                  defaultValue={fastMinutes}
                  className="w-24 rounded-full border border-[#efe7db] bg-white px-3 py-2 text-sm"
                />
                <button
                  type="submit"
                  className="rounded-full border border-[var(--accent)] px-4 py-2 text-xs uppercase tracking-[0.2em] text-[var(--accent)]"
                >
                  fast on
                </button>
              </form>
            </div>
          </ActionCard>

          <ActionCard
            title="Assessment controls"
            description="Start or reset the assessment path for this user."
          >
            <div className="flex flex-wrap items-center gap-2">
              <form action={startUserAction}>
                <input type="hidden" name="user_id" value={userId} />
                <button
                  type="submit"
                  className="rounded-full border border-[#efe7db] px-4 py-2 text-xs uppercase tracking-[0.2em]"
                >
                  assess
                </button>
              </form>
              <form action={resetUserAction}>
                <input type="hidden" name="user_id" value={userId} />
                <input type="hidden" name="confirm" value="reset" />
                <button
                  type="submit"
                  className="rounded-full border border-[#efe7db] px-4 py-2 text-xs uppercase tracking-[0.2em]"
                >
                  reset
                </button>
              </form>
            </div>
          </ActionCard>

          <ActionCard
            title="Send SMS"
            description="Send an ad-hoc SMS to this user. Keep it concise; max 500 characters."
          >
            <form action={sendSmsAction} className="space-y-3">
              <input type="hidden" name="user_id" value={userId} />
              <textarea
                name="sms_message"
                rows={6}
                maxLength={500}
                placeholder="Type SMS message to send..."
                className="w-full rounded-xl border border-[#efe7db] bg-white px-3 py-2 text-sm"
              />
              <button
                type="submit"
                className="rounded-full border border-[var(--accent)] px-4 py-2 text-xs uppercase tracking-[0.2em] text-[var(--accent)]"
              >
                send sms
              </button>
            </form>
          </ActionCard>

          <ActionCard
            title="Send 24h template"
            description="Send the out-of-session WhatsApp template now (same template used when user is outside the 24h window)."
          >
            <form action={send24hTemplateAction}>
              <input type="hidden" name="user_id" value={userId} />
              <button
                type="submit"
                className="rounded-full border border-[var(--accent)] px-4 py-2 text-xs uppercase tracking-[0.2em] text-[var(--accent)]"
              >
                send 24h template
              </button>
            </form>
          </ActionCard>

          <ActionCard
            title="Delete user"
            description="Permanently remove this user. Use only when you are sure."
          >
            <form action={deleteUserAction}>
              <input type="hidden" name="user_id" value={userId} />
              <input type="hidden" name="confirm" value="delete" />
              <button
                type="submit"
                className="rounded-full border border-[#c43e1c] px-4 py-2 text-xs uppercase tracking-[0.2em] text-[#c43e1c]"
              >
                delete user
              </button>
            </form>
          </ActionCard>
        </div>
      </div>
    </main>
  );
}
