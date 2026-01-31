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
  const settingsData = await getMessagingSettings();
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
                className="rounded-full border border-[#0f766e] bg-[#0f766e] px-5 py-2 text-xs uppercase tracking-[0.2em] text-white"
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
          <form action={saveMessagingSettingsAction} className="mt-6 space-y-4">
            <label className="flex items-center gap-2 text-sm text-[#6b6257]">
              <input
                type="checkbox"
                name="out_of_session_enabled"
                defaultChecked={Boolean(settingsData?.out_of_session_enabled)}
              />
              Enable out-of-session message
            </label>
            <div>
              <label className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Message text</label>
              <textarea
                name="out_of_session_message"
                defaultValue={settingsData?.out_of_session_message || ""}
                placeholder="We have a quick update for you. Reply to continue."
                className="mt-2 w-full rounded-2xl border border-[#efe7db] px-4 py-3 text-sm"
                rows={4}
              />
            </div>
            <button
              type="submit"
              className="rounded-full border border-[#0f766e] bg-[#0f766e] px-5 py-2 text-xs uppercase tracking-[0.2em] text-white"
            >
              Save out-of-session message
            </button>
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
              className="rounded-full border border-[#0f766e] bg-[#0f766e] px-5 py-2 text-xs uppercase tracking-[0.2em] text-white"
            >
              Save schedule
            </button>
          </form>
        </section>
      </div>
    </main>
  );
}
