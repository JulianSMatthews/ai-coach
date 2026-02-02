"use client";

import { useActionState } from "react";
import Link from "next/link";
import { generateContentAction, type GeneratorState } from "./actions";
import type { ContentPromptTemplateSummary } from "@/lib/api";

type ContentGeneratorClientProps = {
  templates: ContentPromptTemplateSummary[];
};

const emptyState: GeneratorState = { ok: false, error: null };

export default function ContentGeneratorClient({ templates }: ContentGeneratorClientProps) {
  const [state, action, pending] = useActionState(generateContentAction, emptyState);
  const result = state.result || {};
  const resultId = typeof result.id === "number" ? result.id : null;
  const resultPayload = (result.result || {}) as Record<string, unknown>;
  const llm = (resultPayload.llm || {}) as Record<string, unknown>;
  const podcastUrl = String((result as Record<string, unknown>).podcast_url || "");
  const podcastError = String((result as Record<string, unknown>).podcast_error || "");

  return (
    <div className="space-y-6">
      <form action={action} className="grid gap-4 md:grid-cols-2">
        <div>
          <label className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Content template</label>
          <select
            name="template_id"
            className="mt-2 w-full rounded-xl border border-[#efe7db] px-3 py-2 text-sm"
            defaultValue={templates[0]?.id ?? ""}
          >
            <option value="">Select template</option>
            {templates.map((tpl) => (
              <option key={tpl.id} value={tpl.id}>
                {tpl.template_key}
                {tpl.label ? ` · ${tpl.label}` : ""}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">User id</label>
          <input
            name="user_id"
            className="mt-2 w-full rounded-xl border border-[#efe7db] px-3 py-2 text-sm"
            placeholder="optional"
          />
        </div>
        <div>
          <label className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Pillar (optional)</label>
          <input
            name="pillar_key"
            className="mt-2 w-full rounded-xl border border-[#efe7db] px-3 py-2 text-sm"
            placeholder="nutrition"
          />
        </div>
        <div>
          <label className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Concept (optional)</label>
          <input
            name="concept_code"
            className="mt-2 w-full rounded-xl border border-[#efe7db] px-3 py-2 text-sm"
            placeholder="hydration"
          />
        </div>
        <div>
          <label className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Provider</label>
          <select name="provider" className="mt-2 w-full rounded-xl border border-[#efe7db] px-3 py-2 text-sm">
            <option value="openai">OpenAI</option>
            <option value="anthropic">Anthropic</option>
            <option value="google">Google</option>
          </select>
        </div>
        <div>
          <label className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">As of date</label>
          <input
            name="test_date"
            type="date"
            className="mt-2 w-full rounded-xl border border-[#efe7db] px-3 py-2 text-sm"
          />
        </div>
        <div>
          <label className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">LLM model (optional)</label>
          <select name="model_override" className="mt-2 w-full rounded-xl border border-[#efe7db] px-3 py-2 text-sm">
            <option value="">Default</option>
            <option value="gpt-5.1">gpt-5.1</option>
            <option value="gpt-5-mini">gpt-5-mini</option>
            <option value="gpt-5-nano">gpt-5-nano</option>
            <option value="gpt-4.1">gpt-4.1</option>
            <option value="gpt-4.1-mini">gpt-4.1-mini</option>
            <option value="gpt-4.1-nano">gpt-4.1-nano</option>
            <option value="gpt-4o">gpt-4o</option>
            <option value="gpt-4o-mini">gpt-4o-mini</option>
            <option value="o3">o3</option>
            <option value="o4-mini">o4-mini</option>
            <option value="gpt-3.5-turbo">gpt-3.5-turbo</option>
          </select>
        </div>
        <div className="flex items-center gap-2 text-sm text-[#6b6257]">
          <input type="checkbox" name="run_llm" />
          <span>Run LLM (generate response)</span>
        </div>
        <div className="flex items-center gap-2 text-sm text-[#6b6257]">
          <input type="checkbox" name="generate_podcast" />
          <span>Generate podcast audio</span>
        </div>
        <div>
          <label className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Podcast voice</label>
          <select name="podcast_voice" className="mt-2 w-full rounded-xl border border-[#efe7db] px-3 py-2 text-sm">
            <option value="">Default</option>
            <option value="alloy">Alloy</option>
            <option value="breeze">Breeze</option>
            <option value="echo">Echo</option>
            <option value="verse">Verse</option>
            <option value="shimmer">Shimmer</option>
            <option value="onyx">Onyx</option>
            <option value="coral">Coral</option>
            <option value="amber">Amber</option>
          </select>
        </div>
        <button
          type="submit"
          disabled={pending}
          className="rounded-full border border-[var(--accent)] bg-[var(--accent)] px-5 py-2 text-xs uppercase tracking-[0.2em] text-white disabled:cursor-not-allowed disabled:opacity-60"
        >
          {pending ? "Generating…" : "Generate"}
        </button>
      </form>

      {state.error ? <p className="text-sm text-red-600">{state.error}</p> : null}

      {resultId ? (
        <div className="rounded-2xl border border-[#efe7db] bg-white p-4 text-sm">
          <p className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Saved</p>
          <div className="mt-2 flex flex-wrap items-center gap-3">
            <span className="rounded-full border border-[#efe7db] px-3 py-1">Generation #{resultId}</span>
            <Link
              className="rounded-full border border-[#efe7db] px-3 py-1 text-xs uppercase tracking-[0.2em]"
              href={`/admin/prompts/generator/${resultId}`}
            >
              View details
            </Link>
          </div>
          {podcastError ? <p className="mt-3 text-sm text-red-600">{podcastError}</p> : null}
          {podcastUrl ? (
            <div className="mt-3">
              <audio controls className="w-full">
                <source src={podcastUrl} />
              </audio>
            </div>
          ) : null}
        </div>
      ) : null}

      {resultPayload.text ? (
        <div className="rounded-2xl border border-[#efe7db] bg-white p-4">
          <h3 className="text-sm font-semibold">Assembled prompt</h3>
          <pre className="mt-3 whitespace-pre-wrap text-xs text-[#2f2a21]">{String(resultPayload.text)}</pre>
        </div>
      ) : null}

      {resultPayload.blocks ? (
        <div className="rounded-2xl border border-[#efe7db] bg-white p-4">
          <h3 className="text-sm font-semibold">Blocks</h3>
          <pre className="mt-3 whitespace-pre-wrap text-xs text-[#2f2a21]">
            {JSON.stringify(resultPayload.blocks, null, 2)}
          </pre>
        </div>
      ) : null}

      {Object.keys(llm).length ? (
        <div className="rounded-2xl border border-[#efe7db] bg-white p-4">
          <h3 className="text-sm font-semibold">LLM response</h3>
          {llm.error ? (
            <p className="mt-2 text-sm text-red-600">{String(llm.error)}</p>
          ) : (
            <>
              <p className="mt-2 text-xs text-[#6b6257]">
                Model: {String(llm.model || "default")} · {String(llm.duration_ms || 0)}ms
              </p>
              <pre className="mt-3 whitespace-pre-wrap text-xs text-[#2f2a21]">
                {String(llm.content || "")}
              </pre>
            </>
          )}
        </div>
      ) : null}
    </div>
  );
}
