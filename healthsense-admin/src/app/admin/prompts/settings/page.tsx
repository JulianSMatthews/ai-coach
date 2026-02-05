import AdminNav from "@/components/AdminNav";
import { getPromptSettings, updatePromptSettings } from "@/lib/api";
import { revalidatePath } from "next/cache";

export const dynamic = "force-dynamic";

async function saveSettingsAction(formData: FormData) {
  "use server";
  const system_block = String(formData.get("system_block") || "").trim() || null;
  const locale_block = String(formData.get("locale_block") || "").trim() || null;
  const default_block_order = String(formData.get("default_block_order") || "").trim();
  const worker_mode_override = String(formData.get("worker_mode_override") || "").trim();
  const podcast_worker_mode_override = String(formData.get("podcast_worker_mode_override") || "").trim();

  const parseOverride = (value: string) => {
    if (!value) return null;
    if (value === "on") return true;
    if (value === "off") return false;
    return null;
  };
  const payload = {
    system_block,
    locale_block,
    default_block_order: default_block_order ? default_block_order.split(",").map((b) => b.trim()) : null,
    worker_mode_override: parseOverride(worker_mode_override),
    podcast_worker_mode_override: parseOverride(podcast_worker_mode_override),
  };
  await updatePromptSettings(payload);
  revalidatePath("/admin/prompts/settings");
}

export default async function PromptSettingsPage() {
  const settings = await getPromptSettings();
  const workerDefault =
    settings.worker_mode_override === true ? "on" : settings.worker_mode_override === false ? "off" : "";
  const podcastDefault =
    settings.podcast_worker_mode_override === true ? "on" : settings.podcast_worker_mode_override === false ? "off" : "";

  return (
    <main className="min-h-screen bg-[#f7f4ee] px-6 py-10 text-[#1e1b16]">
      <div className="mx-auto w-full max-w-4xl space-y-6">
        <AdminNav title="Prompt settings" subtitle="Global system/locale blocks and default order." />
        <section className="rounded-3xl border border-[#e7e1d6] bg-white p-6">
          <form action={saveSettingsAction} className="space-y-4">
            <div>
              <label className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">System block</label>
              <textarea
                name="system_block"
                defaultValue={settings.system_block || ""}
                rows={6}
                className="mt-2 w-full rounded-xl border border-[#efe7db] px-3 py-2 text-sm"
              />
            </div>
            <div>
              <label className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Locale block</label>
              <textarea
                name="locale_block"
                defaultValue={settings.locale_block || ""}
                rows={4}
                className="mt-2 w-full rounded-xl border border-[#efe7db] px-3 py-2 text-sm"
              />
            </div>
            <div>
              <label className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Default block order</label>
              <input
                name="default_block_order"
                defaultValue={(settings.default_block_order || []).join(", ")}
                className="mt-2 w-full rounded-xl border border-[#efe7db] px-3 py-2 text-sm"
                placeholder="system, locale, context, programme, history, okr, scores, habit, task, user"
              />
            </div>
            <div>
              <label className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Worker mode override</label>
              <select
                name="worker_mode_override"
                defaultValue={workerDefault}
                className="mt-2 w-full rounded-xl border border-[#efe7db] bg-white px-3 py-2 text-sm"
              >
                <option value="">Use env</option>
                <option value="on">Force on</option>
                <option value="off">Force off</option>
              </select>
              <p className="mt-2 text-xs text-[#6b6257]">Controls whether prompts are queued to the worker service.</p>
            </div>
            <div>
              <label className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Podcast worker override</label>
              <select
                name="podcast_worker_mode_override"
                defaultValue={podcastDefault}
                className="mt-2 w-full rounded-xl border border-[#efe7db] bg-white px-3 py-2 text-sm"
              >
                <option value="">Use env</option>
                <option value="on">Force on</option>
                <option value="off">Force off</option>
              </select>
              <p className="mt-2 text-xs text-[#6b6257]">
                Controls whether podcast/voice jobs are handled by the worker.
              </p>
            </div>
            <button
              type="submit"
              className="rounded-full border border-[var(--accent)] bg-[var(--accent)] px-5 py-2 text-xs uppercase tracking-[0.2em] text-white"
            >
              Save settings
            </button>
          </form>
        </section>
      </div>
    </main>
  );
}
