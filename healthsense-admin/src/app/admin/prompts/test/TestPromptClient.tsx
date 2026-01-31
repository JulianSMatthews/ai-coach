"use client";

import { useActionState } from "react";
import { testPromptAction, type TestState } from "./actions";

const emptyState: TestState = { ok: false, error: null };

export default function TestPromptClient() {
  const [state, action, pending] = useActionState(testPromptAction, emptyState);
  const audioUrl = state.result?.audio_url || "";
  const podcastError = state.result?.podcast_error || "";

  return (
    <div className="space-y-6">
      <form action={action} className="grid gap-4 md:grid-cols-2">
        <div>
          <label className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Touchpoint</label>
          <input
            name="touchpoint"
            className="mt-2 w-full rounded-xl border border-[#efe7db] px-3 py-2 text-sm"
            placeholder="podcast_kickoff"
          />
        </div>
        <div>
          <label className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">User id</label>
          <input
            name="user_id"
            className="mt-2 w-full rounded-xl border border-[#efe7db] px-3 py-2 text-sm"
            placeholder="1"
          />
        </div>
        <div>
          <label className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Template state</label>
          <select name="state" className="mt-2 w-full rounded-xl border border-[#efe7db] px-3 py-2 text-sm">
            <option value="live">Live</option>
            <option value="beta">Beta</option>
            <option value="develop">Develop</option>
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
          className="rounded-full border border-[#0f766e] bg-[#0f766e] px-5 py-2 text-xs uppercase tracking-[0.2em] text-white disabled:cursor-not-allowed disabled:opacity-60"
        >
          {pending ? "Testing…" : "Preview"}
        </button>
      </form>

      {state.error ? <p className="text-sm text-red-600">{state.error}</p> : null}

      {podcastError ? <p className="text-sm text-red-600">{podcastError}</p> : null}
      {audioUrl ? (
        <div className="rounded-2xl border border-[#efe7db] bg-white p-4">
          <h3 className="text-sm font-semibold">Podcast audio</h3>
          <audio controls className="mt-3 w-full">
            <source src={audioUrl} />
          </audio>
        </div>
      ) : null}

      {state.result?.text ? (
        <div className="rounded-2xl border border-[#efe7db] bg-white p-4">
          <h3 className="text-sm font-semibold">Assembled prompt</h3>
          <pre className="mt-3 whitespace-pre-wrap text-xs text-[#2f2a21]">{state.result.text}</pre>
        </div>
      ) : null}

      {state.result?.blocks ? (
        <div className="rounded-2xl border border-[#efe7db] bg-white p-4">
          <h3 className="text-sm font-semibold">Blocks</h3>
          <pre className="mt-3 whitespace-pre-wrap text-xs text-[#2f2a21]">
            {JSON.stringify(state.result.blocks, null, 2)}
          </pre>
        </div>
      ) : null}

      {state.result?.llm ? (
        <div className="rounded-2xl border border-[#efe7db] bg-white p-4">
          <h3 className="text-sm font-semibold">LLM response</h3>
          {state.result.llm.error ? (
            <p className="mt-2 text-sm text-red-600">{state.result.llm.error}</p>
          ) : (
            <>
              <p className="mt-2 text-xs text-[#6b6257]">
                Model: {state.result.llm.model || "default"} · {state.result.llm.duration_ms || 0}ms
              </p>
              <pre className="mt-3 whitespace-pre-wrap text-xs text-[#2f2a21]">
                {state.result.llm.content || ""}
              </pre>
            </>
          )}
        </div>
      ) : null}
    </div>
  );
}
