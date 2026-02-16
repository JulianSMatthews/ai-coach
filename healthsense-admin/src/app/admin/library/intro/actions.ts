"use server";

import { revalidatePath } from "next/cache";
import { createContentGeneration, updateLibraryIntroSettings } from "@/lib/api";

export type IntroGenerationState = {
  ok: boolean;
  error?: string | null;
  result?: Record<string, unknown>;
};

export type IntroSaveState = {
  ok: boolean;
  error?: string | null;
};

export async function generateIntroDraftAction(
  _: IntroGenerationState,
  formData: FormData,
): Promise<IntroGenerationState> {
  const template_id = Number(formData.get("template_id") || 0) || undefined;
  const template_key = String(formData.get("template_key") || "").trim() || undefined;
  const user_id = String(formData.get("user_id") || "").trim() || undefined;
  const provider = String(formData.get("provider") || "").trim() || "openai";
  const model_override = String(formData.get("model_override") || "").trim() || undefined;
  const run_llm = Boolean(formData.get("run_llm"));
  const generate_podcast = Boolean(formData.get("generate_podcast"));
  const podcast_voice = String(formData.get("podcast_voice") || "").trim() || undefined;
  if (!template_id && !template_key) {
    return { ok: false, error: "Select a content template to generate intro content." };
  }
  if (!run_llm) {
    return { ok: false, error: "Run LLM must be enabled to generate intro text." };
  }
  if (generate_podcast && !run_llm) {
    return { ok: false, error: "Enable Run LLM to generate podcast audio." };
  }
  try {
    const result = await createContentGeneration({
      template_id,
      template_key,
      user_id,
      pillar_key: "intro",
      concept_code: "welcome",
      provider,
      run_llm,
      model_override,
      generate_podcast,
      podcast_voice,
    });
    return { ok: true, result };
  } catch (error) {
    return { ok: false, error: error instanceof Error ? error.message : String(error) };
  }
}

export async function saveIntroSettingsAction(
  _: IntroSaveState,
  formData: FormData,
): Promise<IntroSaveState> {
  const active = Boolean(formData.get("active"));
  const title = String(formData.get("title") || "").trim();
  const welcome_message_template = String(formData.get("welcome_message_template") || "").trim();
  const body = String(formData.get("body") || "").trim();
  const podcast_url = String(formData.get("podcast_url") || "").trim();
  const podcast_voice = String(formData.get("podcast_voice") || "").trim();
  try {
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
    return { ok: true };
  } catch (error) {
    return { ok: false, error: error instanceof Error ? error.message : String(error) };
  }
}
