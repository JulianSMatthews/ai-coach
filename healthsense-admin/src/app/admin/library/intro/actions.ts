"use server";

import { revalidatePath } from "next/cache";
import {
  createContentGeneration,
  generateLibraryIntroAvatar,
  generateLibraryAssessmentIntroAvatar,
  refreshLibraryIntroAvatar,
  refreshLibraryAssessmentIntroAvatar,
  updateLibraryAssessmentIntroSettings,
  updateLibraryIntroSettings,
} from "@/lib/api";

export type IntroGenerationState = {
  ok: boolean;
  error?: string | null;
  result?: Record<string, unknown>;
};

export type IntroSaveState = {
  ok: boolean;
  error?: string | null;
};

export type AssessmentIntroSaveState = {
  ok: boolean;
  error?: string | null;
};

export type IntroAvatarState = {
  ok: boolean;
  error?: string | null;
  result?: Record<string, unknown>;
};

export async function generateIntroDraftAction(
  _: IntroGenerationState,
  formData: FormData,
): Promise<IntroGenerationState> {
  const template_id = Number(formData.get("template_id") || 0) || undefined;
  const template_key = String(formData.get("template_key") || "").trim() || undefined;
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
  const coach_product_avatar_url = String(formData.get("coach_product_avatar_url") || "").trim();
  const coach_product_avatar_title = String(formData.get("coach_product_avatar_title") || "").trim();
  const coach_product_avatar_script = String(formData.get("coach_product_avatar_script") || "").trim();
  const coach_product_avatar_poster_url = String(formData.get("coach_product_avatar_poster_url") || "").trim();
  const coach_product_avatar_character = String(formData.get("coach_product_avatar_character") || "").trim();
  const coach_product_avatar_style = String(formData.get("coach_product_avatar_style") || "").trim();
  const coach_product_avatar_voice = String(formData.get("coach_product_avatar_voice") || "").trim();
  try {
    await updateLibraryIntroSettings({
      active,
      title: title || undefined,
      welcome_message_template: welcome_message_template || undefined,
      body: body || undefined,
      podcast_url: podcast_url || undefined,
      podcast_voice: podcast_voice || undefined,
      coach_product_avatar_url: coach_product_avatar_url || undefined,
      coach_product_avatar_title: coach_product_avatar_title || undefined,
      coach_product_avatar_script: coach_product_avatar_script || undefined,
      coach_product_avatar_poster_url: coach_product_avatar_poster_url || undefined,
      coach_product_avatar_character: coach_product_avatar_character || undefined,
      coach_product_avatar_style: coach_product_avatar_style || undefined,
      coach_product_avatar_voice: coach_product_avatar_voice || undefined,
    });
    revalidatePath("/admin/library");
    revalidatePath("/admin/library/intro");
    return { ok: true };
  } catch (error) {
    return { ok: false, error: error instanceof Error ? error.message : String(error) };
  }
}

export async function saveAssessmentIntroSettingsAction(
  _: AssessmentIntroSaveState,
  formData: FormData,
): Promise<AssessmentIntroSaveState> {
  const active = Boolean(formData.get("assessment_intro_active"));
  const title = String(formData.get("assessment_intro_title") || "").trim();
  const assessment_intro_avatar_url = String(formData.get("assessment_intro_avatar_url") || "").trim();
  const assessment_intro_avatar_title = String(formData.get("assessment_intro_avatar_title") || "").trim();
  const assessment_intro_avatar_script = String(formData.get("assessment_intro_avatar_script") || "").trim();
  const assessment_intro_avatar_poster_url = String(formData.get("assessment_intro_avatar_poster_url") || "").trim();
  const assessment_intro_avatar_character = String(formData.get("assessment_intro_avatar_character") || "").trim();
  const assessment_intro_avatar_style = String(formData.get("assessment_intro_avatar_style") || "").trim();
  const assessment_intro_avatar_voice = String(formData.get("assessment_intro_avatar_voice") || "").trim();
  try {
    await updateLibraryAssessmentIntroSettings({
      active,
      title: title || undefined,
      assessment_intro_avatar_url: assessment_intro_avatar_url || undefined,
      assessment_intro_avatar_title: assessment_intro_avatar_title || undefined,
      assessment_intro_avatar_script: assessment_intro_avatar_script || undefined,
      assessment_intro_avatar_poster_url: assessment_intro_avatar_poster_url || undefined,
      assessment_intro_avatar_character: assessment_intro_avatar_character || undefined,
      assessment_intro_avatar_style: assessment_intro_avatar_style || undefined,
      assessment_intro_avatar_voice: assessment_intro_avatar_voice || undefined,
    });
    revalidatePath("/admin/library");
    revalidatePath("/admin/library/intro");
    return { ok: true };
  } catch (error) {
    return { ok: false, error: error instanceof Error ? error.message : String(error) };
  }
}

export async function generateIntroAvatarAction(
  _: IntroAvatarState,
  formData: FormData,
): Promise<IntroAvatarState> {
  const coach_product_avatar_title = String(formData.get("coach_product_avatar_title") || "").trim();
  const coach_product_avatar_script = String(formData.get("coach_product_avatar_script") || "").trim();
  const coach_product_avatar_poster_url = String(formData.get("coach_product_avatar_poster_url") || "").trim();
  const coach_product_avatar_character = String(formData.get("coach_product_avatar_character") || "").trim();
  const coach_product_avatar_style = String(formData.get("coach_product_avatar_style") || "").trim();
  const coach_product_avatar_voice = String(formData.get("coach_product_avatar_voice") || "").trim();
  try {
    const result = await generateLibraryIntroAvatar({
      coach_product_avatar_title: coach_product_avatar_title || undefined,
      coach_product_avatar_script: coach_product_avatar_script || undefined,
      coach_product_avatar_poster_url: coach_product_avatar_poster_url || undefined,
      coach_product_avatar_character: coach_product_avatar_character || undefined,
      coach_product_avatar_style: coach_product_avatar_style || undefined,
      coach_product_avatar_voice: coach_product_avatar_voice || undefined,
    });
    revalidatePath("/admin/library");
    revalidatePath("/admin/library/intro");
    return { ok: Boolean(result.ok), error: result.error ? String(result.error) : null, result };
  } catch (error) {
    return { ok: false, error: error instanceof Error ? error.message : String(error) };
  }
}

export async function refreshIntroAvatarAction(
  _: IntroAvatarState,
  _formData: FormData,
): Promise<IntroAvatarState> {
  void _;
  void _formData;
  try {
    const result = await refreshLibraryIntroAvatar();
    revalidatePath("/admin/library");
    revalidatePath("/admin/library/intro");
    return { ok: Boolean(result.ok), error: result.error ? String(result.error) : null, result };
  } catch (error) {
    return { ok: false, error: error instanceof Error ? error.message : String(error) };
  }
}

export async function generateAssessmentIntroAvatarAction(
  _: IntroAvatarState,
  formData: FormData,
): Promise<IntroAvatarState> {
  const assessment_intro_avatar_title = String(formData.get("assessment_intro_avatar_title") || "").trim();
  const assessment_intro_avatar_script = String(formData.get("assessment_intro_avatar_script") || "").trim();
  const assessment_intro_avatar_poster_url = String(formData.get("assessment_intro_avatar_poster_url") || "").trim();
  const assessment_intro_avatar_character = String(formData.get("assessment_intro_avatar_character") || "").trim();
  const assessment_intro_avatar_style = String(formData.get("assessment_intro_avatar_style") || "").trim();
  const assessment_intro_avatar_voice = String(formData.get("assessment_intro_avatar_voice") || "").trim();
  try {
    const result = await generateLibraryAssessmentIntroAvatar({
      assessment_intro_avatar_title: assessment_intro_avatar_title || undefined,
      assessment_intro_avatar_script: assessment_intro_avatar_script || undefined,
      assessment_intro_avatar_poster_url: assessment_intro_avatar_poster_url || undefined,
      assessment_intro_avatar_character: assessment_intro_avatar_character || undefined,
      assessment_intro_avatar_style: assessment_intro_avatar_style || undefined,
      assessment_intro_avatar_voice: assessment_intro_avatar_voice || undefined,
    });
    revalidatePath("/admin/library");
    revalidatePath("/admin/library/intro");
    return { ok: Boolean(result.ok), error: result.error ? String(result.error) : null, result };
  } catch (error) {
    return { ok: false, error: error instanceof Error ? error.message : String(error) };
  }
}

export async function refreshAssessmentIntroAvatarAction(
  _: IntroAvatarState,
  _formData: FormData,
): Promise<IntroAvatarState> {
  void _;
  void _formData;
  try {
    const result = await refreshLibraryAssessmentIntroAvatar();
    revalidatePath("/admin/library");
    revalidatePath("/admin/library/intro");
    return { ok: Boolean(result.ok), error: result.error ? String(result.error) : null, result };
  } catch (error) {
    return { ok: false, error: error instanceof Error ? error.message : String(error) };
  }
}
