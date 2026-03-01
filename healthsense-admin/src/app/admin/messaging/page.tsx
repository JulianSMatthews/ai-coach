import AdminNav from "@/components/AdminNav";
import ConfirmDeleteButton from "@/components/ConfirmDeleteButton";
import {
  getGlobalPromptSchedule,
  getMessagingSettings,
  getTwilioTemplates,
  deleteTwilioTemplate,
  syncTwilioTemplates,
  updateGlobalPromptSchedule,
  updateMessagingSettings,
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

async function saveMessagingSettingsAction(formData: FormData) {
  "use server";
  const enabled = Boolean(formData.get("out_of_session_enabled"));
  const message = String(formData.get("out_of_session_message") || "").trim();
  await updateMessagingSettings({
    out_of_session_enabled: enabled,
    out_of_session_message: message || null,
  });
  revalidatePath("/admin/messaging");
}

export default async function MessagingPage() {
  const [templateData, scheduleData] = await Promise.all([
    getTwilioTemplates(),
    getGlobalPromptSchedule(),
  ]);
  const settingsData = await getMessagingSettings();
  const templates = templateData.templates || [];
  const outOfSessionTemplates = templates.filter((tpl) => isOutOfSessionTemplate(tpl));
  const dailyPromptReawakeTemplate = outOfSessionTemplates.find((tpl) => isDailyPromptReawakeTemplate(tpl)) || null;
  const general24hTemplate =
    outOfSessionTemplates.find((tpl) => !isDailyPromptReawakeTemplate(tpl)) ||
    outOfSessionTemplates.find((tpl) => tpl.id !== dailyPromptReawakeTemplate?.id) ||
    null;
  const primaryOutOfSessionTemplate =
    outOfSessionTemplates.find((tpl) => String(tpl.template_type || "").trim().toLowerCase() === "session-reopen") ||
    general24hTemplate ||
    outOfSessionTemplates[0] ||
    null;
  const schedule = scheduleData.items || [];
  const templateIds = templates.map((t) => t.id).join(",");
  const scheduleDays = schedule.map((s) => s.day_key).join(",");
  const deleteFormId = "delete-template-form";
  const previewBody =
    (primaryOutOfSessionTemplate?.preview_body || "").trim() ||
    "Hi from HealthSense. I'm ready to continue your coaching. Please tap the button below to continue your wellbeing journey.";
  const previewButton = (primaryOutOfSessionTemplate?.preview_button || "").trim() || "Continue coaching";
  const templateHasVariables = previewBody.includes("{{");

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
                        {tpl.template_type === "session-reopen" ? "Session reopen" : "Quick reply"}
                        {tpl.button_count ? ` · ${tpl.button_count} buttons` : ""}
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
            <p className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Out-of-session template</p>
            <h2 className="mt-2 text-xl">24h+ messaging</h2>
            <p className="mt-2 text-sm text-[#6b6257]">
              Sends a WhatsApp template message when a member has been inactive for more than 24 hours.
            </p>
          </div>
          <div className="mt-6 space-y-4">
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Status</span>
              <span
                className={`rounded-full border px-3 py-1 text-xs uppercase tracking-[0.2em] ${
                  settingsData?.out_of_session_enabled
                    ? "border-[#16824a] bg-[#edf8f1] text-[#16824a]"
                    : "border-[#b56e0a] bg-[#fff7ea] text-[#b56e0a]"
                }`}
              >
                {settingsData?.out_of_session_enabled ? "Enabled" : "Disabled"}
              </span>
              {outOfSessionTemplates.some((tpl) => Boolean((tpl.sid || "").trim())) ? (
                <span className="rounded-full border border-[#efe7db] bg-[#fdfaf4] px-3 py-1 text-xs uppercase tracking-[0.2em] text-[#6b6257]">
                  Template SID set
                </span>
              ) : (
                <span className="rounded-full border border-[#c43e1c] bg-[#fff5f2] px-3 py-1 text-xs uppercase tracking-[0.2em] text-[#c43e1c]">
                  Template SID missing
                </span>
              )}
              <span
                className={`rounded-full border px-3 py-1 text-xs uppercase tracking-[0.2em] ${approvalBadgeClass(
                  primaryOutOfSessionTemplate?.approval_status,
                )}`}
              >
                WhatsApp approval: {approvalLabel(primaryOutOfSessionTemplate?.approval_status)}
              </span>
            </div>
            {primaryOutOfSessionTemplate?.approval_detail ? (
              <p className="text-xs text-[#6b6257]">{primaryOutOfSessionTemplate.approval_detail}</p>
            ) : null}
            {(primaryOutOfSessionTemplate?.approval_source || primaryOutOfSessionTemplate?.approval_checked_at) ? (
              <p className="text-xs text-[#8a8176]">
                Source: {primaryOutOfSessionTemplate?.approval_source || "—"}
                {primaryOutOfSessionTemplate?.approval_checked_at
                  ? ` · checked ${primaryOutOfSessionTemplate.approval_checked_at}`
                  : ""}
              </p>
            ) : null}
            <div className="rounded-2xl border border-[#efe7db] bg-[#faf7f1] p-4">
              <p className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Twilio template details (24h+)</p>
              {outOfSessionTemplates.length ? (
                <div className="mt-2 space-y-3">
                  {[
                    {
                      key: "general",
                      title: "General +24 hour message sent when the user exceeds the 24 hour period",
                      template: general24hTemplate,
                    },
                    {
                      key: "daily-reawake",
                      title: "24+ hour message to reawake user to receive daily prompt",
                      template: dailyPromptReawakeTemplate,
                    },
                  ].map((slot) => (
                    <div key={slot.key} className="rounded-xl border border-[#efe7db] bg-white p-3">
                      <p className="text-xs uppercase tracking-[0.18em] text-[#6b6257]">{slot.title}</p>
                      <dl className="mt-2 grid gap-2 text-sm md:grid-cols-2 lg:grid-cols-4">
                        <div>
                          <dt className="text-xs uppercase tracking-[0.15em] text-[#8a8176]">Template name</dt>
                          <dd className="mt-1 font-medium">{slot.template?.friendly_name || "Not configured"}</dd>
                        </div>
                        <div>
                          <dt className="text-xs uppercase tracking-[0.15em] text-[#8a8176]">Template type</dt>
                          <dd className="mt-1 font-medium">{slot.template?.template_type || "—"}</dd>
                        </div>
                        <div>
                          <dt className="text-xs uppercase tracking-[0.15em] text-[#8a8176]">Template SID</dt>
                          <dd className="mt-1 font-mono text-xs break-all">{slot.template?.sid || "—"}</dd>
                        </div>
                        <div>
                          <dt className="text-xs uppercase tracking-[0.15em] text-[#8a8176]">WhatsApp approval</dt>
                          <dd className="mt-1 font-medium">{approvalLabel(slot.template?.approval_status)}</dd>
                        </div>
                      </dl>
                    </div>
                  ))}
                </div>
              ) : (
                <p className="mt-2 text-sm text-[#6b6257]">No 24h template rows found.</p>
              )}
            </div>
            <div className="rounded-2xl border border-[#efe7db] bg-[#faf7f1] p-4">
              <p className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Message body preview</p>
              <p className="mt-2 text-sm text-[#1e1b16]">{previewBody}</p>
              <p className="mt-4 text-xs uppercase tracking-[0.2em] text-[#6b6257]">Reply button</p>
              <span className="mt-2 inline-flex rounded-full border border-[#efe7db] bg-white px-3 py-1 text-xs font-medium">
                {previewButton}
              </span>
              <div className="mt-3 rounded-xl border border-[#efe7db] bg-white px-3 py-2 text-xs text-[#6b6257]">
                <p className="font-semibold uppercase tracking-[0.15em] text-[#6b6257]">Where this runs</p>
                <p className="mt-1">
                  1) At scheduled coaching time, if user is outside 24h: this template is sent and that day’s coaching message is deferred.
                </p>
                <p className="mt-1">
                  2) Periodic inactivity check: this template is sent to coaching users outside 24h.
                </p>
                <p className="mt-1">After user replies, the deferred day message is sent.</p>
              </div>
            </div>
            <form action={saveMessagingSettingsAction} className="rounded-2xl border border-[#efe7db] bg-[#faf7f1] p-4">
              <p className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Message configuration</p>
              <label className="mt-3 flex items-center gap-2 text-sm text-[#6b6257]">
                <input
                  type="checkbox"
                  name="out_of_session_enabled"
                  defaultChecked={Boolean(settingsData?.out_of_session_enabled)}
                />
                Enable 24h+ template messaging
              </label>
              <div className="mt-3">
                <label className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Template sentence</label>
                <textarea
                  name="out_of_session_message"
                  defaultValue={settingsData?.out_of_session_message || ""}
                  rows={4}
                  className="mt-2 w-full rounded-xl border border-[#efe7db] bg-white px-3 py-2 text-sm"
                  placeholder="Please tap below to continue your wellbeing journey."
                />
                <p className="mt-2 text-xs text-[#8a8176]">
                  This is the sentence inserted into the approved Twilio template. Supported placeholders:{" "}
                  <code>{"{day}"}</code>, <code>{"{first_name}"}</code>, <code>{"{coach_name}"}</code>.
                </p>
                <p className="mt-1 text-xs text-[#8a8176]">
                  Example: <code>{"Hi {first_name}, {coach_name} here. Your {day} message is ready."}</code>
                </p>
              </div>
              <div
                className={`mt-3 rounded-xl border px-3 py-2 text-xs ${
                  templateHasVariables
                    ? "border-[#16824a] bg-[#edf8f1] text-[#16824a]"
                    : "border-[#b56e0a] bg-[#fff7ea] text-[#8a5a00]"
                }`}
              >
                {templateHasVariables ? (
                  <p>
                    Variable template detected in Twilio preview. The sentence and placeholders above will be applied in live sends.
                  </p>
                ) : (
                  <p>
                    Static template detected in Twilio preview. Editing the sentence above will not change the final WhatsApp body
                    until the Twilio template is updated to include variables and approved.
                  </p>
                )}
              </div>
              <button
                type="submit"
                className="mt-4 rounded-full border border-[var(--accent)] bg-[var(--accent)] px-5 py-2 text-xs uppercase tracking-[0.2em] text-white"
              >
                Save messaging settings
              </button>
            </form>
            <p className="text-xs text-[#6b6257]">
              Preview source: Twilio template content for the primary 24h template.
            </p>
          </div>
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
