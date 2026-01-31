"use server";

import { testPromptTemplate } from "@/lib/api";

export type TestState = {
  ok: boolean;
  error?: string | null;
  result?: {
    text?: string;
    blocks?: Record<string, string>;
    block_order?: string[];
    audio_url?: string | null;
    podcast_error?: string | null;
    llm?: {
      model?: string | null;
      duration_ms?: number | null;
      content?: string | null;
      error?: string | null;
    };
  };
};

export async function testPromptAction(_: TestState, formData: FormData): Promise<TestState> {
  const touchpoint = String(formData.get("touchpoint") || "").trim();
  const user_id = String(formData.get("user_id") || "").trim();
  const state = String(formData.get("state") || "live").trim();
  const test_date = String(formData.get("test_date") || "").trim() || undefined;
  const run_llm = Boolean(formData.get("run_llm"));
  const model_override = String(formData.get("model_override") || "").trim() || undefined;
  const generate_podcast = Boolean(formData.get("generate_podcast"));
  const podcast_voice = String(formData.get("podcast_voice") || "").trim() || undefined;
  if (generate_podcast && !run_llm) {
    return { ok: false, error: "Enable Run LLM to generate podcast audio." };
  }
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
      generate_podcast,
      podcast_voice,
    });
    return { ok: true, result };
  } catch (error) {
    return { ok: false, error: error instanceof Error ? error.message : String(error) };
  }
}
