import AdminNav from "@/components/AdminNav";
import { getLibraryIntroSettings, updateLibraryIntroSettings } from "@/lib/api";
import { revalidatePath } from "next/cache";

export const dynamic = "force-dynamic";

async function saveIntroSettingsAction(formData: FormData) {
  "use server";
  const active = Boolean(formData.get("active"));
  const title = String(formData.get("title") || "").trim();
  const welcome_message_template = String(formData.get("welcome_message_template") || "").trim();
  const body = String(formData.get("body") || "").trim();
  const podcast_url = String(formData.get("podcast_url") || "").trim();
  const podcast_voice = String(formData.get("podcast_voice") || "").trim();
  await updateLibraryIntroSettings({
    active,
    title: title || undefined,
    welcome_message_template: welcome_message_template || undefined,
    body: body || undefined,
    podcast_url: podcast_url || undefined,
    podcast_voice: podcast_voice || undefined,
  });
  revalidatePath("/admin/library");
  revalidatePath("/admin/library/intro");
}

export default async function LibraryIntroPage() {
  const intro = await getLibraryIntroSettings();
  return (
    <main className="min-h-screen bg-[#f7f4ee] px-6 py-10 text-[#1e1b16]">
      <div className="mx-auto w-full max-w-4xl space-y-6">
        <AdminNav title="Intro setup" subtitle="Configure the first-login intro experience shown in the app." />

        <section className="rounded-3xl border border-[#e7e1d6] bg-white p-6">
          <form action={saveIntroSettingsAction} className="space-y-4">
            <label className="flex items-center gap-2 text-sm text-[#3c332b]">
              <input type="checkbox" name="active" defaultChecked={Boolean(intro.active)} />
              Intro flow active
            </label>
            <div>
              <label className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Title</label>
              <input
                name="title"
                defaultValue={intro.title || ""}
                className="mt-2 w-full rounded-xl border border-[#efe7db] px-3 py-2 text-sm"
              />
            </div>
            <div>
              <label className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">
                Welcome message template
              </label>
              <input
                name="welcome_message_template"
                defaultValue={intro.welcome_message_template || ""}
                className="mt-2 w-full rounded-xl border border-[#efe7db] px-3 py-2 text-sm"
              />
              <p className="mt-1 text-xs text-[#8a8176]">Supports {"{first_name}"} and {"{display_name}"}.</p>
            </div>
            <div>
              <label className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Read content</label>
              <textarea
                name="body"
                rows={8}
                defaultValue={intro.body || ""}
                className="mt-2 w-full rounded-xl border border-[#efe7db] px-3 py-2 text-sm"
              />
            </div>
            <div className="grid gap-3 md:grid-cols-2">
              <div>
                <label className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Podcast URL</label>
                <input
                  name="podcast_url"
                  defaultValue={intro.podcast_url || ""}
                  className="mt-2 w-full rounded-xl border border-[#efe7db] px-3 py-2 text-sm"
                />
              </div>
              <div>
                <label className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Podcast voice</label>
                <input
                  name="podcast_voice"
                  defaultValue={intro.podcast_voice || ""}
                  className="mt-2 w-full rounded-xl border border-[#efe7db] px-3 py-2 text-sm"
                />
              </div>
            </div>
            <button
              type="submit"
              className="rounded-full border border-[var(--accent)] bg-[var(--accent)] px-5 py-2 text-xs uppercase tracking-[0.2em] text-white"
            >
              Save intro settings
            </button>
          </form>
        </section>
      </div>
    </main>
  );
}
