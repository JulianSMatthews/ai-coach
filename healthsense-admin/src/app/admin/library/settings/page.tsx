import { revalidatePath } from "next/cache";
import AdminNav from "@/components/AdminNav";
import { getContentPromptSettings, updateContentPromptSettings } from "@/lib/api";

export const dynamic = "force-dynamic";

async function saveSettings(formData: FormData) {
  "use server";
  const system_block = String(formData.get("system_block") || "").trim() || undefined;
  const locale_block = String(formData.get("locale_block") || "").trim() || undefined;
  const default_block_order = String(formData.get("default_block_order") || "").trim() || undefined;
  await updateContentPromptSettings({
    system_block,
    locale_block,
    default_block_order: default_block_order ? default_block_order.split(",").map((v) => v.trim()) : undefined,
  });
  revalidatePath("/admin/library/settings");
}

export default async function ContentPromptSettingsPage() {
  const settings = await getContentPromptSettings();

  return (
    <main className="min-h-screen bg-[#f7f4ee] px-6 py-10 text-[#1e1b16]">
      <div className="mx-auto w-full max-w-4xl space-y-6">
        <AdminNav title="Content prompt settings" subtitle="Defaults applied to library content generation." />

        <section className="rounded-3xl border border-[#e7e1d6] bg-white p-6">
          <form action={saveSettings} className="space-y-4">
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
                placeholder="system, locale, context, task"
              />
            </div>
            <button className="rounded-full border border-[#0f766e] bg-[#0f766e] px-5 py-2 text-xs uppercase tracking-[0.2em] text-white">
              Save settings
            </button>
          </form>
        </section>
      </div>
    </main>
  );
}
