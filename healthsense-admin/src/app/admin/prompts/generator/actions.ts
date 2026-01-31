"use server";

import { revalidatePath } from "next/cache";
import { createContentGeneration } from "@/lib/api";

export type GeneratorState = {
  ok: boolean;
  error?: string | null;
  result?: Record<string, unknown>;
};

export async function generateContentAction(
  _: GeneratorState,
  formData: FormData,
): Promise<GeneratorState> {
  const template_id = Number(formData.get("template_id") || 0) || undefined;
  const template_key = String(formData.get("template_key") || "").trim() || undefined;
  const user_id = String(formData.get("user_id") || "").trim();
  const pillar_key = String(formData.get("pillar_key") || "").trim() || undefined;
  const concept_code = String(formData.get("concept_code") || "").trim() || undefined;
  const provider = String(formData.get("provider") || "").trim() || "openai";
  const test_date = String(formData.get("test_date") || "").trim() || undefined;
  const run_llm = Boolean(formData.get("run_llm"));
  const model_override = String(formData.get("model_override") || "").trim() || undefined;
  const generate_podcast = Boolean(formData.get("generate_podcast"));
  const podcast_voice = String(formData.get("podcast_voice") || "").trim() || undefined;
  if (!template_id && !template_key) {
    return { ok: false, error: "Select a content template to generate." };
  }
  if (generate_podcast && !run_llm) {
    return { ok: false, error: "Enable Run LLM to generate podcast audio." };
  }
  try {
    const result = await createContentGeneration({
      template_id,
      template_key,
      user_id: user_id || undefined,
      pillar_key,
      concept_code,
      provider,
      test_date,
      run_llm,
      model_override,
      generate_podcast,
      podcast_voice,
    });
    revalidatePath("/admin/prompts/generator");
    return { ok: true, result };
  } catch (error) {
    return { ok: false, error: error instanceof Error ? error.message : String(error) };
  }
}
