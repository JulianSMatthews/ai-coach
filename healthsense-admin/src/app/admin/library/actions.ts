"use server";

import { revalidatePath } from "next/cache";
import { createContentGeneration, createLibraryContent, updateLibraryContent } from "@/lib/api";
import { redirect } from "next/navigation";

export type GeneratorState = {
  ok: boolean;
  error?: string | null;
  result?: Record<string, unknown>;
};

export async function generateLibraryContentAction(
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
    revalidatePath("/admin/library");
    return { ok: true, result };
  } catch (error) {
    return { ok: false, error: error instanceof Error ? error.message : String(error) };
  }
}

const parseTags = (value: FormDataEntryValue | null): string[] | undefined => {
  if (!value) return undefined;
  const raw = String(value).trim();
  if (!raw) return undefined;
  return raw.split(",").map((item) => item.trim()).filter(Boolean);
};

const parsePublishedAt = (value: FormDataEntryValue | null): string | undefined => {
  if (!value) return undefined;
  const raw = String(value).trim();
  return raw || undefined;
};

export async function saveLibraryContentAction(
  _: { ok: boolean; error?: string },
  formData: FormData,
): Promise<{ ok: boolean; error?: string }> {
  const pillar_key = String(formData.get("pillar_key") || "").trim();
  const title = String(formData.get("title") || "").trim();
  const body = String(formData.get("body") || "").trim();
  const concept_code = String(formData.get("concept_code") || "").trim() || undefined;
  const status = String(formData.get("status") || "draft").trim() || "draft";
  const podcast_url = String(formData.get("podcast_url") || "").trim() || undefined;
  const podcast_voice = String(formData.get("podcast_voice") || "").trim() || undefined;
  const source_type = String(formData.get("source_type") || "").trim() || undefined;
  const source_url = String(formData.get("source_url") || "").trim() || undefined;
  const license = String(formData.get("license") || "").trim() || undefined;
  const level = String(formData.get("level") || "").trim() || undefined;
  const published_at = parsePublishedAt(formData.get("published_at"));
  const tags = parseTags(formData.get("tags"));
  const source_generation_id = Number(formData.get("source_generation_id") || 0) || undefined;
  if (!pillar_key || !title || !body) {
    return { ok: false, error: "Pillar, title, and body are required." };
  }
  try {
    await createLibraryContent({
      pillar_key,
      concept_code,
      title,
      body,
      status,
      podcast_url,
      podcast_voice,
      source_type,
      source_url,
      license,
      level,
      published_at,
      tags,
      source_generation_id,
    });
    revalidatePath("/admin/library");
    return { ok: true };
  } catch (error) {
    return { ok: false, error: error instanceof Error ? error.message : String(error) };
  }
}

export async function updateLibraryContentStatusAction(formData: FormData) {
  const rawId = Number(formData.get("content_id") || 0);
  const status = String(formData.get("status") || "").trim();
  if (!rawId || !status) {
    redirect("/admin/library");
  }
  await updateLibraryContent(rawId, { status });
  revalidatePath("/admin/library");
  redirect(`/admin/library/content/${rawId}`);
}

export async function createManualLibraryContentAction(_: { ok: boolean; error?: string }, formData: FormData) {
  const pillar_key = String(formData.get("pillar_key") || "").trim();
  const title = String(formData.get("title") || "").trim();
  const body = String(formData.get("body") || "").trim();
  const concept_code = String(formData.get("concept_code") || "").trim() || undefined;
  const status = String(formData.get("status") || "draft").trim() || "draft";
  const podcast_url = String(formData.get("podcast_url") || "").trim() || undefined;
  const podcast_voice = String(formData.get("podcast_voice") || "").trim() || undefined;
  const source_type = String(formData.get("source_type") || "").trim() || undefined;
  const source_url = String(formData.get("source_url") || "").trim() || undefined;
  const license = String(formData.get("license") || "").trim() || undefined;
  const level = String(formData.get("level") || "").trim() || undefined;
  const published_at = parsePublishedAt(formData.get("published_at"));
  const tags = parseTags(formData.get("tags"));
  if (!pillar_key || !title || !body) {
    return { ok: false, error: "Pillar, title, and body are required." };
  }
  try {
    const result = await createLibraryContent({
      pillar_key,
      concept_code,
      title,
      body,
      status,
      podcast_url,
      podcast_voice,
      source_type,
      source_url,
      license,
      level,
      published_at,
      tags,
    });
    const newId = Number((result as Record<string, unknown>).id || 0) || 0;
    revalidatePath("/admin/library");
    if (newId) {
      redirect(`/admin/library/content/${newId}`);
    }
    return { ok: true };
  } catch (error) {
    return { ok: false, error: error instanceof Error ? error.message : String(error) };
  }
}

export async function updateLibraryContentAction(
  contentId: number,
  _: { ok: boolean; error?: string },
  formData: FormData,
): Promise<{ ok: boolean; error?: string }> {
  const title = String(formData.get("title") || "").trim();
  const body = String(formData.get("body") || "").trim();
  const pillar_key = String(formData.get("pillar_key") || "").trim();
  const concept_code = String(formData.get("concept_code") || "").trim() || undefined;
  const status = String(formData.get("status") || "").trim() || undefined;
  const podcast_url = String(formData.get("podcast_url") || "").trim() || undefined;
  const podcast_voice = String(formData.get("podcast_voice") || "").trim() || undefined;
  const source_type = String(formData.get("source_type") || "").trim() || undefined;
  const source_url = String(formData.get("source_url") || "").trim() || undefined;
  const license = String(formData.get("license") || "").trim() || undefined;
  const level = String(formData.get("level") || "").trim() || undefined;
  const published_at = parsePublishedAt(formData.get("published_at"));
  const tags = parseTags(formData.get("tags"));
  if (!pillar_key || !title || !body) {
    return { ok: false, error: "Pillar, title, and body are required." };
  }
  try {
    await updateLibraryContent(contentId, {
      pillar_key,
      concept_code,
      title,
      body,
      status,
      podcast_url,
      podcast_voice,
      source_type,
      source_url,
      license,
      level,
      published_at,
      tags,
    });
    revalidatePath("/admin/library");
    revalidatePath(`/admin/library/content/${contentId}`);
    return { ok: true };
  } catch (error) {
    return { ok: false, error: error instanceof Error ? error.message : String(error) };
  }
}
