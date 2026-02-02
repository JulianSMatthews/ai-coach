"use client";

import { useActionState } from "react";
import type { TemplateActionState } from "./actions";
import { promoteAllTemplatesAction } from "./actions";

const emptyState: TemplateActionState = { ok: false, error: null };

function Result({ state }: { state: TemplateActionState }) {
  if (!state.error && !state.ok) return null;
  if (state.error) {
    return <p className="mt-2 text-sm text-red-600">{state.error}</p>;
  }
  return <p className="mt-2 text-sm text-[var(--accent)]">Promotion complete.</p>;
}

export default function PromoteAllCard() {
  const [devState, devAction, devPending] = useActionState(promoteAllTemplatesAction, emptyState);
  const [betaState, betaAction, betaPending] = useActionState(promoteAllTemplatesAction, emptyState);

  return (
    <section className="rounded-3xl border border-[#e7e1d6] bg-white p-6">
      <h2 className="text-lg font-semibold">Promote all templates</h2>
      <p className="mt-2 text-sm text-[#6b6257]">
        Create new versions for every template when promoting develop → beta or beta → live.
      </p>
      <form action={devAction} className="mt-4 flex flex-wrap items-center gap-3">
        <input type="hidden" name="from_state" value="develop" />
        <input type="hidden" name="to_state" value="beta" />
        <input
          name="note"
          placeholder="Version note (optional)"
          className="min-w-[220px] rounded-full border border-[#efe7db] px-3 py-2 text-sm"
        />
        <button
          type="submit"
          className="rounded-full border border-[var(--accent)] bg-[var(--accent)] px-4 py-2 text-xs uppercase tracking-[0.2em] text-white"
          disabled={devPending}
        >
          {devPending ? "Promoting…" : "Promote develop → beta"}
        </button>
      </form>
      <Result state={devState} />

      <form action={betaAction} className="mt-4 flex flex-wrap items-center gap-3">
        <input type="hidden" name="from_state" value="beta" />
        <input type="hidden" name="to_state" value="live" />
        <input
          name="note"
          placeholder="Version note (optional)"
          className="min-w-[220px] rounded-full border border-[#efe7db] px-3 py-2 text-sm"
        />
        <button
          type="submit"
          className="rounded-full border border-[#efe7db] px-4 py-2 text-xs uppercase tracking-[0.2em]"
          disabled={betaPending}
        >
          {betaPending ? "Promoting…" : "Promote beta → live"}
        </button>
      </form>
      <Result state={betaState} />
    </section>
  );
}
