import AdminNav from "@/components/AdminNav";
import ConfirmDeleteButton from "@/components/ConfirmDeleteButton";
import {
  getGlobalPromptSchedule,
  getTwilioTemplates,
  deleteTwilioTemplate,
  syncTwilioTemplates,
  updateGlobalPromptSchedule,
  updateTwilioTemplates,
} from "@/lib/api";
import { revalidatePath } from "next/cache";

export const dynamic = "force-dynamic";

function isOutOfSessionTemplate(template: {
  template_type?: string | null;
  friendly_name?: string | null;
  payload?: Record<string, unknown> | null;
}): boolean {
  const templateType = String(template.template_type || "").trim().toLowerCase();
  if (
    [
      "session-reopen",
      "session_reopen",
      "out_of_session",
      "out-of-session",
      "day-reopen",
      "day_reopen",
      "session-reopen-day",
      "session_reopen_day",
    ].includes(templateType)
  ) {
    return true;
  }
  const purpose = String((template.payload && template.payload["purpose"]) || "")
    .trim()
    .toLowerCase();
  if (
    [
      "session-reopen",
      "session_reopen",
      "out_of_session",
      "out-of-session",
      "day-reopen",
      "day_reopen",
      "session-reopen-day",
      "session_reopen_day",
    ].includes(purpose)
  ) {
    return true;
  }
  const friendlyName = String(template.friendly_name || "").trim().toLowerCase();
  return friendlyName.includes("reopen");
}

function isDailyPromptReawakeTemplate(template: {
  template_type?: string | null;
  friendly_name?: string | null;
  payload?: Record<string, unknown> | null;
}): boolean {
  const templateType = String(template.template_type || "").trim().toLowerCase();
  const purpose = String((template.payload && template.payload["purpose"]) || "")
    .trim()
    .toLowerCase();
  const friendlyName = String(template.friendly_name || "").trim().toLowerCase();
  return (
    templateType.includes("day") ||
    purpose.includes("day") ||
    friendlyName.includes("day") ||
    templateType.includes("daily") ||
    purpose.includes("daily") ||
    friendlyName.includes("daily")
  );
}

function twilioTemplateHeading(template: {
  template_type?: string | null;
  button_count?: number | null;
  friendly_name?: string | null;
  payload?: Record<string, unknown> | null;
}): string {
  if (isOutOfSessionTemplate(template)) {
    return isDailyPromptReawakeTemplate(template)
      ? "24+ hour message to reawake user to receive daily prompt"
      : "General +24 hour message";
  }
  if (String(template.template_type || "").trim().toLowerCase() === "quick-reply") {
    return `Quick reply${template.button_count ? ` · ${template.button_count} buttons` : ""}`;
  }
  return String(template.template_type || "Template").trim() || "Template";
}

function approvalBadgeClass(status?: string | null): string {
  const key = String(status || "").toLowerCase();
  if (key === "approved") return "border-[#16824a] bg-[#edf8f1] text-[#16824a]";
  if (key === "pending") return "border-[#b56e0a] bg-[#fff7ea] text-[#b56e0a]";
  if (key === "rejected") return "border-[#c43e1c] bg-[#fff5f2] text-[#c43e1c]";
  if (key === "not_submitted" || key === "missing_sid") return "border-[#c43e1c] bg-[#fff5f2] text-[#c43e1c]";
  return "border-[#efe7db] bg-[#fdfaf4] text-[#6b6257]";
}

function approvalLabel(status?: string | null): string {
  const key = String(status || "").trim().toLowerCase();
  if (!key) return "Unknown";
  if (key === "not_submitted") return "Not submitted";
  if (key === "missing_sid") return "Missing SID";
  return key.replaceAll("_", " ");
}

async function syncTemplatesAction() {
  "use server";
  await syncTwilioTemplates();
  revalidatePath("/admin/messaging");
}

async function deleteTemplateAction(formData: FormData) {
  "use server";
  const id = Number(formData.get("template_delete_id") || 0);
  if (!id) {
    return;
  }
  await deleteTwilioTemplate(id, true);
  revalidatePath("/admin/messaging");
}

async function saveTemplatesAction(formData: FormData) {
  "use server";
  const idListRaw = String(formData.get("template_ids") || "").trim();
  const ids = idListRaw ? idListRaw.split(",").map((v) => Number(v)).filter((v) => Number.isFinite(v) && v > 0) : [];
  const templates = ids.map((id) => ({
    id,
    template_type: String(formData.get(`template_type_${id}`) || ""),
    button_count: Number(formData.get(`button_count_${id}`) || 0) || null,
    friendly_name: String(formData.get(`friendly_name_${id}`) || "").trim() || null,
    sid: String(formData.get(`sid_${id}`) || "").trim() || null,
    status: String(formData.get(`status_${id}`) || "").trim() || null,
  }));
  if (templates.length) {
    await updateTwilioTemplates(templates);
  }
  revalidatePath("/admin/messaging");
}

async function saveScheduleAction(formData: FormData) {
  "use server";
  const dayListRaw = String(formData.get("schedule_days") || "").trim();
  const days = dayListRaw ? dayListRaw.split(",").map((v) => v.trim()).filter(Boolean) : [];
  const items = days.map((day) => ({
    day_key: day,
    time_local: String(formData.get(`time_${day}`) || "").trim() || null,
    enabled: Boolean(formData.get(`enabled_${day}`)),
  }));
  if (items.length) {
    await updateGlobalPromptSchedule(items);
  }
  revalidatePath("/admin/messaging");
}

export default async function MessagingPage() {
  const [templateData, scheduleData] = await Promise.all([
    getTwilioTemplates(),
    getGlobalPromptSchedule(),
  ]);
  const templates = templateData.templates || [];
  const schedule = scheduleData.items || [];
  const templateIds = templates.map((t) => t.id).join(",");
  const scheduleDays = schedule.map((s) => s.day_key).join(",");
  const deleteFormId = "delete-template-form";

  return (
    <main className="min-h-screen bg-[#f7f4ee] px-6 py-10 text-[#1e1b16]">
      <div className="mx-auto w-full max-w-5xl space-y-6">
        <AdminNav title="Messaging" subtitle="Manage Twilio templates and global prompt schedule." />

        <section className="rounded-3xl border border-[#e7e1d6] bg-white p-6">
          <div className="flex flex-wrap items-center justify-between gap-4">
            <div>
              <p className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Twilio templates</p>
              <h2 className="mt-2 text-xl">Quick replies & session reopen</h2>
              <p className="mt-2 text-sm text-[#6b6257]">
                Quick‑reply templates are reused across all messages. The session‑reopen template is used when a member has
                been inactive for more than 24 hours.
              </p>
            </div>
            <form action={syncTemplatesAction}>
              <button
                type="submit"
                className="rounded-full border border-[var(--accent)] bg-[var(--accent)] px-5 py-2 text-xs uppercase tracking-[0.2em] text-white"
              >
                Sync from Twilio
              </button>
            </form>
          </div>

          <form id={deleteFormId} action={deleteTemplateAction} />
          <form action={saveTemplatesAction} className="mt-6 space-y-4">
            <input type="hidden" name="template_ids" value={templateIds} />
            <div className="grid gap-4">
              {templates.map((tpl) => (
                <div key={tpl.id} className="rounded-2xl border border-[#efe7db] p-4">
                  <input type="hidden" name={`template_type_${tpl.id}`} value={tpl.template_type || ""} />
                  <input type="hidden" name={`button_count_${tpl.id}`} value={tpl.button_count ?? ""} />
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div>
                      <p className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">
                        {twilioTemplateHeading(tpl)}
                      </p>
                      <p className="mt-1 text-sm text-[#6b6257]">
                        Last synced: {tpl.last_synced_at ? tpl.last_synced_at : "—"}
                      </p>
                      {tpl.content_types && tpl.content_types.length ? (
                        <p className="mt-1 text-xs text-[#6b6257]">
                          Content types: {tpl.content_types.join(", ")}
                        </p>
                      ) : null}
                    </div>
                    <span className="rounded-full border border-[#efe7db] bg-[#fdfaf4] px-3 py-1 text-xs uppercase tracking-[0.2em] text-[#6b6257]">
                      {tpl.status || "unknown"}
                    </span>
                  </div>
                  {isOutOfSessionTemplate(tpl) ? (
                    <div className="mt-3 space-y-2 rounded-xl border border-[#efe7db] bg-[#faf7f1] p-3">
                      <div className="flex flex-wrap items-center gap-2">
                        <span
                          className={`rounded-full border px-3 py-1 text-xs uppercase tracking-[0.2em] ${approvalBadgeClass(
                            tpl.approval_status,
                          )}`}
                        >
                          WhatsApp approval: {approvalLabel(tpl.approval_status)}
                        </span>
                      </div>
                      {tpl.approval_detail ? <p className="text-xs text-[#6b6257]">{tpl.approval_detail}</p> : null}
                      {(tpl.approval_source || tpl.approval_checked_at) ? (
                        <p className="text-xs text-[#8a8176]">
                          Source: {tpl.approval_source || "—"}
                          {tpl.approval_checked_at ? ` · checked ${tpl.approval_checked_at}` : ""}
                        </p>
                      ) : null}
                      <div>
                        <p className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Twilio message preview</p>
                        <p className="mt-1 text-sm text-[#1e1b16]">
                          {(tpl.preview_body || "").trim() || "No Twilio message body preview available."}
                        </p>
                      </div>
                      <div>
                        <p className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Reply button</p>
                        <span className="mt-1 inline-flex rounded-full border border-[#efe7db] bg-white px-3 py-1 text-xs font-medium">
                          {(tpl.preview_button || "").trim() || "—"}
                        </span>
                      </div>
                    </div>
                  ) : null}
                  <div className="mt-4 grid gap-3 md:grid-cols-3">
                    <div>
                      <label className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Friendly name</label>
                      <input
                        name={`friendly_name_${tpl.id}`}
                        defaultValue={tpl.friendly_name || ""}
                        className="mt-2 w-full rounded-xl border border-[#efe7db] px-3 py-2 text-sm"
                      />
                    </div>
                    <div className="md:col-span-2">
                      <label className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Twilio SID</label>
                      <input
                        name={`sid_${tpl.id}`}
                        defaultValue={tpl.sid || ""}
                        placeholder="HXXXXXXXXXXXXXXXXXXXXXXXXXXXX"
                        className="mt-2 w-full rounded-xl border border-[#efe7db] px-3 py-2 text-sm"
                      />
                    </div>
                  </div>
                  <div className="mt-3">
                    <label className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Status</label>
                    <select
                      name={`status_${tpl.id}`}
                      defaultValue={tpl.status || "active"}
                      className="mt-2 w-full rounded-xl border border-[#efe7db] bg-white px-3 py-2 text-sm"
                    >
                      <option value="active">active</option>
                      <option value="missing">missing</option>
                      <option value="error">error</option>
                      <option value="disabled">disabled</option>
                    </select>
                  </div>
                  <div className="mt-4 flex flex-wrap items-center gap-3">
                    <ConfirmDeleteButton formId={deleteFormId} templateId={tpl.id} />
                  </div>
                </div>
              ))}
            </div>
          </form>
        </section>

        <section className="rounded-3xl border border-[#e7e1d6] bg-white p-6">
          <div>
            <p className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Global schedule</p>
            <h2 className="mt-2 text-xl">Default prompt times</h2>
            <p className="mt-2 text-sm text-[#6b6257]">
              Applies to all users who do not have a personal schedule override.
            </p>
          </div>
          <form action={saveScheduleAction} className="mt-6 space-y-4">
            <input type="hidden" name="schedule_days" value={scheduleDays} />
            <div className="grid gap-3">
              {schedule.map((row) => {
                const day = row.day_key || "";
                return (
                  <div key={row.id || day} className="flex flex-wrap items-center gap-4">
                    <div className="w-28 text-sm capitalize">{day || "day"}</div>
                    <input
                      name={`time_${day}`}
                      defaultValue={row.time_local || ""}
                      placeholder="08:00"
                      className="w-28 rounded-xl border border-[#efe7db] px-3 py-2 text-sm"
                    />
                    <label className="flex items-center gap-2 text-sm text-[#6b6257]">
                      <input type="checkbox" name={`enabled_${day}`} defaultChecked={Boolean(row.enabled)} />
                      Enabled
                    </label>
                  </div>
                );
              })}
            </div>
            <button
              type="submit"
              className="rounded-full border border-[var(--accent)] bg-[var(--accent)] px-5 py-2 text-xs uppercase tracking-[0.2em] text-white"
            >
              Save schedule
            </button>
          </form>
        </section>
      </div>
    </main>
  );
}
