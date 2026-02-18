"use server";

import { revalidatePath } from "next/cache";
import {
  createPromptTemplate,
  promoteAllPromptTemplates,
  promotePromptTemplate,
  testPromptTemplate,
  updatePromptTemplate,
} from "@/lib/api";

export type TemplateActionState = {
  ok: boolean;
  error?: string | null;
};

export async function saveTemplateAction(_: TemplateActionState, formData: FormData): Promise<TemplateActionState> {
  const id = String(formData.get("id") || "").trim();
  const touchpoint = String(formData.get("touchpoint") || "").trim();
  const state = String(formData.get("state") || "develop").trim();
  const okr_scope = String(formData.get("okr_scope") || "").trim() || undefined;
  const programme_scope = String(formData.get("programme_scope") || "").trim() || undefined;
  const response_format = String(formData.get("response_format") || "").trim() || undefined;
  const model_override = String(formData.get("model_override") || "").trim() || undefined;
  const block_order = String(formData.get("block_order") || "").trim();
  const task_block = String(formData.get("task_block") || "").trim();
  const note = String(formData.get("note") || "").trim();
  const is_active = Boolean(formData.get("is_active"));

  const payload = {
    touchpoint,
    state,
    okr_scope,
    programme_scope,
    response_format,
    model_override,
    block_order,
    include_blocks: block_order,
    task_block,
    note,
    is_active,
  };

  try {
    if (id) {
      await updatePromptTemplate(Number(id), payload);
      revalidatePath(`/admin/prompts/templates/${id}`);
    } else {
      await createPromptTemplate(payload);
    }
    revalidatePath("/admin/prompts/templates");
    return { ok: true };
  } catch (error) {
    return { ok: false, error: error instanceof Error ? error.message : String(error) };
  }
}

export async function promoteTemplateAction(_: TemplateActionState, formData: FormData): Promise<TemplateActionState> {
  const id = Number(formData.get("id") || 0);
  const to_state = String(formData.get("to_state") || "").trim();
  const note = String(formData.get("note") || "").trim() || undefined;
  const touchpoint = String(formData.get("touchpoint") || "").trim() || undefined;
  const from_state = String(formData.get("from_state") || "").trim() || undefined;
  if (!id || !to_state) return { ok: false, error: "Missing template id or state." };
  try {
    await promotePromptTemplate(id, to_state, note, touchpoint, from_state);
    revalidatePath(`/admin/prompts/templates/${id}`);
    revalidatePath("/admin/prompts/templates");
    return { ok: true };
  } catch (error) {
    return { ok: false, error: error instanceof Error ? error.message : String(error) };
  }
}

export async function promoteAllTemplatesAction(_: TemplateActionState, formData: FormData): Promise<TemplateActionState> {
  const from_state = String(formData.get("from_state") || "").trim();
  const to_state = String(formData.get("to_state") || "").trim();
  const note = String(formData.get("note") || "").trim() || undefined;
  if (!from_state || !to_state) return { ok: false, error: "Missing state values." };
  try {
    await promoteAllPromptTemplates(from_state, to_state, note);
    revalidatePath("/admin/prompts/templates");
    return { ok: true };
  } catch (error) {
    return { ok: false, error: error instanceof Error ? error.message : String(error) };
  }
}

export type PreviewActionState = {
  ok: boolean;
  error?: string | null;
  result?: {
    text?: string;
    blocks?: Record<string, string>;
    block_order?: string[];
    llm?: { model?: string | null; duration_ms?: number | null; content?: string | null; error?: string | null };
  };
};

export async function previewTemplateAction(_: PreviewActionState, formData: FormData): Promise<PreviewActionState> {
  const touchpoint = String(formData.get("touchpoint") || "").trim();
  const user_id = String(formData.get("user_id") || "").trim();
  const state = String(formData.get("state") || "develop").trim();
  const test_date = String(formData.get("test_date") || "").trim() || undefined;
  const run_llm = Boolean(formData.get("run_llm"));
  const model_override = String(formData.get("model_override") || "").trim() || undefined;
  if (!touchpoint || !user_id) {
    return { ok: false, error: "Touchpoint and user id are required." };
  }
  try {
    const result = await testPromptTemplate({
      touchpoint,
      user_id,
      state,
      test_date,
      run_llm,
      model_override,
    });
    return { ok: true, result };
  } catch (error) {
    return { ok: false, error: error instanceof Error ? error.message : String(error) };
  }
}
