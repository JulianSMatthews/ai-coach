"use server";

import { revalidatePath } from "next/cache";
import {
  createContentGeneration,
  generateLibraryAppIntroAvatar,
  generateLibraryIntroHelpAvatar,
  generateLibraryIntroAvatar,
  generateLibraryAssessmentIntroAvatar,
  refreshLibraryAppIntroAvatar,
  refreshLibraryIntroHelpAvatar,
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
  result?: Record<string, unknown>;
};

export type AssessmentIntroSaveState = {
  ok: boolean;
  error?: string | null;
  result?: Record<string, unknown>;
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
  const app_intro_avatar_url = String(formData.get("app_intro_avatar_url") || "").trim();
  const app_intro_avatar_title = String(formData.get("app_intro_avatar_title") || "").trim();
  const app_intro_avatar_script = String(formData.get("app_intro_avatar_script") || "").trim();
  const app_intro_avatar_poster_url = String(formData.get("app_intro_avatar_poster_url") || "").trim();
  const app_intro_avatar_character = String(formData.get("app_intro_avatar_character") || "").trim();
  const app_intro_avatar_style = String(formData.get("app_intro_avatar_style") || "").trim();
  const app_intro_avatar_voice = String(formData.get("app_intro_avatar_voice") || "").trim();
  const app_habits_avatar_url = String(formData.get("app_habits_avatar_url") || "").trim();
  const app_habits_avatar_title = String(formData.get("app_habits_avatar_title") || "").trim();
  const app_habits_avatar_script = String(formData.get("app_habits_avatar_script") || "").trim();
  const app_habits_avatar_poster_url = String(formData.get("app_habits_avatar_poster_url") || "").trim();
  const app_habits_avatar_character = String(formData.get("app_habits_avatar_character") || "").trim();
  const app_habits_avatar_style = String(formData.get("app_habits_avatar_style") || "").trim();
  const app_habits_avatar_voice = String(formData.get("app_habits_avatar_voice") || "").trim();
  const app_insight_avatar_url = String(formData.get("app_insight_avatar_url") || "").trim();
  const app_insight_avatar_title = String(formData.get("app_insight_avatar_title") || "").trim();
  const app_insight_avatar_script = String(formData.get("app_insight_avatar_script") || "").trim();
  const app_insight_avatar_poster_url = String(formData.get("app_insight_avatar_poster_url") || "").trim();
  const app_insight_avatar_character = String(formData.get("app_insight_avatar_character") || "").trim();
  const app_insight_avatar_style = String(formData.get("app_insight_avatar_style") || "").trim();
  const app_insight_avatar_voice = String(formData.get("app_insight_avatar_voice") || "").trim();
  const app_ask_avatar_url = String(formData.get("app_ask_avatar_url") || "").trim();
  const app_ask_avatar_title = String(formData.get("app_ask_avatar_title") || "").trim();
  const app_ask_avatar_script = String(formData.get("app_ask_avatar_script") || "").trim();
  const app_ask_avatar_poster_url = String(formData.get("app_ask_avatar_poster_url") || "").trim();
  const app_ask_avatar_character = String(formData.get("app_ask_avatar_character") || "").trim();
  const app_ask_avatar_style = String(formData.get("app_ask_avatar_style") || "").trim();
  const app_ask_avatar_voice = String(formData.get("app_ask_avatar_voice") || "").trim();
  const app_daily_tracking_avatar_url = String(formData.get("app_daily_tracking_avatar_url") || "").trim();
  const app_daily_tracking_avatar_title = String(formData.get("app_daily_tracking_avatar_title") || "").trim();
  const app_daily_tracking_avatar_script = String(formData.get("app_daily_tracking_avatar_script") || "").trim();
  const app_daily_tracking_avatar_poster_url = String(formData.get("app_daily_tracking_avatar_poster_url") || "").trim();
  const app_daily_tracking_avatar_character = String(formData.get("app_daily_tracking_avatar_character") || "").trim();
  const app_daily_tracking_avatar_style = String(formData.get("app_daily_tracking_avatar_style") || "").trim();
  const app_daily_tracking_avatar_voice = String(formData.get("app_daily_tracking_avatar_voice") || "").trim();
  try {
    const result = await updateLibraryIntroSettings({
      active,
      title,
      welcome_message_template,
      body,
      podcast_url,
      podcast_voice,
      app_intro_avatar_url,
      app_intro_avatar_title,
      app_intro_avatar_script,
      app_intro_avatar_poster_url,
      app_intro_avatar_character,
      app_intro_avatar_style,
      app_intro_avatar_voice,
      app_habits_avatar_url,
      app_habits_avatar_title,
      app_habits_avatar_script,
      app_habits_avatar_poster_url,
      app_habits_avatar_character,
      app_habits_avatar_style,
      app_habits_avatar_voice,
      app_insight_avatar_url,
      app_insight_avatar_title,
      app_insight_avatar_script,
      app_insight_avatar_poster_url,
      app_insight_avatar_character,
      app_insight_avatar_style,
      app_insight_avatar_voice,
      app_ask_avatar_url,
      app_ask_avatar_title,
      app_ask_avatar_script,
      app_ask_avatar_poster_url,
      app_ask_avatar_character,
      app_ask_avatar_style,
      app_ask_avatar_voice,
      app_daily_tracking_avatar_url,
      app_daily_tracking_avatar_title,
      app_daily_tracking_avatar_script,
      app_daily_tracking_avatar_poster_url,
      app_daily_tracking_avatar_character,
      app_daily_tracking_avatar_style,
      app_daily_tracking_avatar_voice,
    });
    revalidatePath("/admin/library");
    revalidatePath("/admin/library/intro");
    return { ok: true, result };
  } catch (error) {
    return { ok: false, error: error instanceof Error ? error.message : String(error) };
  }
}

export async function saveCoachingSettingsAction(
  _: IntroSaveState,
  formData: FormData,
): Promise<IntroSaveState> {
  const coach_product_avatar_url = String(formData.get("coach_product_avatar_url") || "").trim();
  const coach_product_avatar_title = String(formData.get("coach_product_avatar_title") || "").trim();
  const coach_product_avatar_script = String(formData.get("coach_product_avatar_script") || "").trim();
  const coach_product_avatar_poster_url = String(formData.get("coach_product_avatar_poster_url") || "").trim();
  const coach_product_avatar_character = String(formData.get("coach_product_avatar_character") || "").trim();
  const coach_product_avatar_style = String(formData.get("coach_product_avatar_style") || "").trim();
  const coach_product_avatar_voice = String(formData.get("coach_product_avatar_voice") || "").trim();
  try {
    const result = await updateLibraryIntroSettings({
      coach_product_avatar_url,
      coach_product_avatar_title,
      coach_product_avatar_script,
      coach_product_avatar_poster_url,
      coach_product_avatar_character,
      coach_product_avatar_style,
      coach_product_avatar_voice,
    });
    revalidatePath("/admin/library");
    revalidatePath("/admin/library/intro");
    return { ok: true, result };
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
    const result = await updateLibraryAssessmentIntroSettings({
      active,
      title,
      assessment_intro_avatar_url,
      assessment_intro_avatar_title,
      assessment_intro_avatar_script,
      assessment_intro_avatar_poster_url,
      assessment_intro_avatar_character,
      assessment_intro_avatar_style,
      assessment_intro_avatar_voice,
    });
    revalidatePath("/admin/library");
    revalidatePath("/admin/library/intro");
    return { ok: true, result };
  } catch (error) {
    return { ok: false, error: error instanceof Error ? error.message : String(error) };
  }
}

export async function generateAppIntroAvatarAction(
  _: IntroAvatarState,
  formData: FormData,
): Promise<IntroAvatarState> {
  const app_intro_avatar_title = String(formData.get("app_intro_avatar_title") || "").trim();
  const app_intro_avatar_script = String(formData.get("app_intro_avatar_script") || "").trim();
  const app_intro_avatar_poster_url = String(formData.get("app_intro_avatar_poster_url") || "").trim();
  const app_intro_avatar_character = String(formData.get("app_intro_avatar_character") || "").trim();
  const app_intro_avatar_style = String(formData.get("app_intro_avatar_style") || "").trim();
  const app_intro_avatar_voice = String(formData.get("app_intro_avatar_voice") || "").trim();
  try {
    const result = await generateLibraryAppIntroAvatar({
      app_intro_avatar_title,
      app_intro_avatar_script,
      app_intro_avatar_poster_url,
      app_intro_avatar_character,
      app_intro_avatar_style,
      app_intro_avatar_voice,
    });
    revalidatePath("/admin/library");
    revalidatePath("/admin/library/intro");
    return { ok: Boolean(result.ok), error: result.error ? String(result.error) : null, result };
  } catch (error) {
    return { ok: false, error: error instanceof Error ? error.message : String(error) };
  }
}

export async function refreshAppIntroAvatarAction(
  _: IntroAvatarState,
  _formData: FormData,
): Promise<IntroAvatarState> {
  void _;
  void _formData;
  try {
    const result = await refreshLibraryAppIntroAvatar();
    revalidatePath("/admin/library");
    revalidatePath("/admin/library/intro");
    return { ok: Boolean(result.ok), error: result.error ? String(result.error) : null, result };
  } catch (error) {
    return { ok: false, error: error instanceof Error ? error.message : String(error) };
  }
}

export async function generateAppHelpAvatarAction(
  _: IntroAvatarState,
  formData: FormData,
): Promise<IntroAvatarState> {
  const slot = String(formData.get("app_help_avatar_slot") || "").trim();
  if (!slot) {
    return { ok: false, error: "Help avatar slot is required." };
  }
  const prefix = `app_${slot}_avatar`;
  const title = String(formData.get(`${prefix}_title`) || "").trim();
  const script = String(formData.get(`${prefix}_script`) || "").trim();
  const poster_url = String(formData.get(`${prefix}_poster_url`) || "").trim();
  const character = String(formData.get(`${prefix}_character`) || "").trim();
  const style = String(formData.get(`${prefix}_style`) || "").trim();
  const voice = String(formData.get(`${prefix}_voice`) || "").trim();
  try {
    const result = await generateLibraryIntroHelpAvatar(slot, {
      title: title || undefined,
      script: script || undefined,
      poster_url: poster_url || undefined,
      character: character || undefined,
      style: style || undefined,
      voice: voice || undefined,
    });
    revalidatePath("/admin/library");
    revalidatePath("/admin/library/intro");
    return { ok: Boolean(result.ok), error: result.error ? String(result.error) : null, result };
  } catch (error) {
    return { ok: false, error: error instanceof Error ? error.message : String(error) };
  }
}

export async function refreshAppHelpAvatarAction(
  _: IntroAvatarState,
  formData: FormData,
): Promise<IntroAvatarState> {
  const slot = String(formData.get("app_help_avatar_slot") || "").trim();
  if (!slot) {
    return { ok: false, error: "Help avatar slot is required." };
  }
  try {
    const result = await refreshLibraryIntroHelpAvatar(slot);
    revalidatePath("/admin/library");
    revalidatePath("/admin/library/intro");
    return { ok: Boolean(result.ok), error: result.error ? String(result.error) : null, result };
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
