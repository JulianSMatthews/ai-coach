"use server";

import { revalidatePath } from "next/cache";
import { createKbSnippet, updateKbSnippet } from "@/lib/api";

export type SnippetActionState = {
  ok: boolean;
  error?: string | null;
};

export async function saveKbSnippetAction(
  _: SnippetActionState,
  formData: FormData
): Promise<SnippetActionState> {
  const id = String(formData.get("id") || "").trim();
  const pillar_key = String(formData.get("pillar_key") || "").trim();
  const concept_code = String(formData.get("concept_code") || "").trim();
  const title = String(formData.get("title") || "").trim();
  const tags = String(formData.get("tags") || "").trim();
  const text = String(formData.get("text") || "").trim();

  const payload = {
    pillar_key,
    concept_code,
    title,
    tags,
    text,
  };

  try {
    if (id) {
      await updateKbSnippet(Number(id), payload);
    } else {
      await createKbSnippet(payload);
    }
    revalidatePath("/admin/kb");
    return { ok: true };
  } catch (error) {
    return { ok: false, error: error instanceof Error ? error.message : String(error) };
  }
}
