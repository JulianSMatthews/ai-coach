"use server";

import { revalidatePath } from "next/cache";
import { createContentPromptTemplate, promoteContentPromptTemplate, updateContentPromptTemplate } from "@/lib/api";

export type TemplateActionState = {
  ok: boolean;
  error?: string | null;
};

export async function saveContentTemplateAction(
  _: TemplateActionState,
  formData: FormData,
): Promise<TemplateActionState> {
  const id = String(formData.get("id") || "").trim();
  const template_key = String(formData.get("template_key") || "").trim();
  const label = String(formData.get("label") || "").trim() || undefined;
  const pillar_key = String(formData.get("pillar_key") || "").trim() || undefined;
  const concept_code = String(formData.get("concept_code") || "").trim() || undefined;
  const response_format = String(formData.get("response_format") || "").trim() || undefined;
  const block_order = String(formData.get("block_order") || "").trim();
  const task_block = String(formData.get("task_block") || "").trim();
  const note = String(formData.get("note") || "").trim();
  const is_active = Boolean(formData.get("is_active"));

  const payload = {
    template_key,
    label,
    pillar_key,
    concept_code,
    response_format,
    block_order,
    include_blocks: block_order,
    task_block,
    note,
    is_active,
  };

  try {
    if (id) {
      await updateContentPromptTemplate(Number(id), payload);
    } else {
      await createContentPromptTemplate(payload);
    }
    revalidatePath("/admin/library/templates");
    return { ok: true };
  } catch (error) {
    return { ok: false, error: error instanceof Error ? error.message : String(error) };
  }
}

export async function promoteContentTemplateAction(
  _: TemplateActionState,
  formData: FormData,
): Promise<TemplateActionState> {
  const id = Number(formData.get("id") || 0);
  const to_state = String(formData.get("to_state") || "").trim();
  const note = String(formData.get("note") || "").trim() || undefined;
  if (!id || !to_state) return { ok: false, error: "Missing template id or state." };
  try {
    await promoteContentPromptTemplate({ id, to_state, note });
    revalidatePath("/admin/library/templates");
    return { ok: true };
  } catch (error) {
    return { ok: false, error: error instanceof Error ? error.message : String(error) };
  }
}
