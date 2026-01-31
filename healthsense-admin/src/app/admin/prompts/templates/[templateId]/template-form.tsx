"use client";

import { useActionState, useMemo, useState } from "react";
import type { PromptTemplateDetail } from "@/lib/api";
import { previewTemplateAction, promoteTemplateAction, saveTemplateAction } from "../actions";

type TemplateFormProps = {
  template: PromptTemplateDetail | null;
  userOptions: { id: number; label: string }[];
};

const emptyState = { ok: false, error: null as string | null };
const emptyPreview = { ok: false, error: null as string | null, result: undefined };

export default function TemplateForm({ template, userOptions }: TemplateFormProps) {
  const [saveState, saveAction, savePending] = useActionState(saveTemplateAction, emptyState);
  const [promoteState, promoteAction, promotePending] = useActionState(promoteTemplateAction, emptyState);
  const [previewState, previewAction, previewPending] = useActionState(previewTemplateAction, emptyPreview);
  const isDevelop = !template || (template.state || "develop") === "develop";
  const canPreview = Boolean(template?.id);
  const blockOrder = previewState.result?.block_order || Object.keys(previewState.result?.blocks || {});
  const [userQuery, setUserQuery] = useState("");
  const filteredUsers = useMemo(() => {
    if (!userOptions.length) return [];
    const q = userQuery.trim().toLowerCase();
    const list = q
      ? userOptions.filter((user) => user.label.toLowerCase().includes(q))
      : userOptions;
    return list.slice(0, 50);
  }, [userOptions, userQuery]);

  return (
    <div className="space-y-6">
      <form action={saveAction} className="space-y-4">
        <input type="hidden" name="id" value={template?.id ?? ""} />
        <input type="hidden" name="state" value={template?.state || "develop"} />
        <div>
          <label className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Touchpoint</label>
          <input
            name="touchpoint"
            defaultValue={template?.touchpoint || ""}
            className="mt-2 w-full rounded-xl border border-[#efe7db] px-3 py-2 text-sm"
            placeholder="podcast_kickoff"
            readOnly={Boolean(template?.id)}
          />
        </div>
        <div className="grid gap-4 md:grid-cols-3">
          <div>
            <label className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">OKR scope</label>
            <select
              name="okr_scope"
              defaultValue={template?.okr_scope || ""}
              className="mt-2 w-full rounded-xl border border-[#efe7db] bg-white px-3 py-2 text-sm"
            >
              <option value="">Select scope</option>
              <option value="all">All OKRs (full programme)</option>
              <option value="pillar">Pillar OKRs (current pillar)</option>
              <option value="week">Weekly focus (current week)</option>
              <option value="single">Single KR (focused)</option>
              {template?.okr_scope &&
              !["all", "pillar", "week", "single"].includes(template.okr_scope) ? (
                <option value={template.okr_scope}>{template.okr_scope} (existing)</option>
              ) : null}
            </select>
            <p className="mt-2 text-xs text-[#6b6257]">
              All = full programme OKRs; Pillar = only current pillar; Week = current week focus; Single = one KR.
            </p>
          </div>
          <div>
            <label className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Programme scope</label>
            <select
              name="programme_scope"
              defaultValue={template?.programme_scope || ""}
              className="mt-2 w-full rounded-xl border border-[#efe7db] bg-white px-3 py-2 text-sm"
            >
              <option value="">Select scope</option>
              <option value="full">Full 12-week programme</option>
              <option value="pillar">Current pillar only</option>
              <option value="none">No programme context</option>
              {template?.programme_scope &&
              !["full", "pillar", "none"].includes(template.programme_scope) ? (
                <option value={template.programme_scope}>{template.programme_scope} (existing)</option>
              ) : null}
            </select>
            <p className="mt-2 text-xs text-[#6b6257]">
              Full = all pillars; Pillar = current block; None = omit programme context.
            </p>
          </div>
          <div>
            <label className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Response format</label>
            <input
              name="response_format"
              defaultValue={template?.response_format || ""}
              className="mt-2 w-full rounded-xl border border-[#efe7db] px-3 py-2 text-sm"
              placeholder="text | json"
            />
          </div>
        </div>
        <div>
          <label className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">
            Blocks (order = include)
          </label>
          <input
            name="block_order"
            defaultValue={(template?.block_order || template?.include_blocks || []).join(", ")}
            className="mt-2 w-full rounded-xl border border-[#efe7db] px-3 py-2 text-sm"
            placeholder="system, locale, context, programme, history, okr, scores, habit, task, user"
          />
        </div>
        <div>
          <label className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Task block</label>
          <textarea
            name="task_block"
            defaultValue={template?.task_block || ""}
            rows={10}
            className="mt-2 w-full rounded-xl border border-[#efe7db] px-3 py-2 text-sm"
          />
        </div>
        <div>
          <label className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Notes</label>
          <textarea
            name="note"
            defaultValue={template?.note || ""}
            rows={3}
            className="mt-2 w-full rounded-xl border border-[#efe7db] px-3 py-2 text-sm"
          />
        </div>
        <label className="flex items-center gap-2 text-sm text-[#6b6257]">
          <input type="checkbox" name="is_active" defaultChecked={template?.is_active ?? true} />
          Active
        </label>
        <button
          type="submit"
          disabled={!isDevelop || savePending}
          className="rounded-full border border-[#0f766e] bg-[#0f766e] px-5 py-2 text-xs uppercase tracking-[0.2em] text-white disabled:cursor-not-allowed disabled:opacity-60"
        >
          {savePending ? "Saving…" : isDevelop ? "Save template" : "Read only (non-develop)"}
        </button>
        {saveState.error ? <p className="text-sm text-red-600">{saveState.error}</p> : null}
        {saveState.ok ? <p className="text-sm text-[#0f766e]">Saved.</p> : null}
      </form>

      {template?.id ? (
        <form action={promoteAction} className="rounded-2xl border border-[#efe7db] p-4">
          <input type="hidden" name="id" value={template.id} />
          <input type="hidden" name="touchpoint" value={template.touchpoint} />
          <input type="hidden" name="from_state" value={template.state || "develop"} />
          <div className="flex flex-wrap items-center gap-3">
            <label className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Promote to</label>
            <select name="to_state" className="rounded-full border border-[#efe7db] px-3 py-2 text-sm">
              <option value="beta">Beta</option>
              <option value="live">Live</option>
            </select>
            <input
              name="note"
              placeholder="Promotion note (optional)"
              className="rounded-full border border-[#efe7db] px-3 py-2 text-sm"
            />
            <button
              type="submit"
              disabled={promotePending}
              className="rounded-full border border-[#efe7db] px-4 py-2 text-xs uppercase tracking-[0.2em]"
            >
              {promotePending ? "Promoting…" : "Promote"}
            </button>
          </div>
          {promoteState.error ? <p className="mt-2 text-sm text-red-600">{promoteState.error}</p> : null}
          {promoteState.ok ? <p className="mt-2 text-sm text-[#0f766e]">Promoted.</p> : null}
        </form>
      ) : null}

      <form action={previewAction} className="rounded-2xl border border-[#efe7db] p-4">
        <input type="hidden" name="touchpoint" value={template?.touchpoint || ""} />
        <input type="hidden" name="state" value={template?.state || "develop"} />
        <h3 className="text-sm font-semibold">Generate prompt</h3>
        <div className="mt-3 grid gap-3 md:grid-cols-2">
          <input
            className="rounded-xl border border-[#efe7db] px-3 py-2 text-sm"
            placeholder="Lookup user (name or phone)"
            value={userQuery}
            onChange={(event) => setUserQuery(event.target.value)}
            disabled={!canPreview}
          />
          <input
            name="user_id"
            className="rounded-xl border border-[#efe7db] px-3 py-2 text-sm"
            placeholder="User id (type to search)"
            list="prompt-user-options"
            disabled={!canPreview}
          />
          <datalist id="prompt-user-options">
            {filteredUsers.map((user) => (
              <option key={user.id} value={String(user.id)}>
                {user.label}
              </option>
            ))}
          </datalist>
          <input
            name="test_date"
            type="date"
            className="rounded-xl border border-[#efe7db] px-3 py-2 text-sm"
            disabled={!canPreview}
          />
          <select
            name="model_override"
            className="rounded-xl border border-[#efe7db] px-3 py-2 text-sm"
            disabled={!canPreview}
          >
            <option value="">Default model</option>
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
          <label className="flex items-center gap-2 text-sm text-[#6b6257]">
            <input type="checkbox" name="run_llm" disabled={!canPreview} />
            Generate LLM response
          </label>
        </div>
        <button
          type="submit"
          disabled={!canPreview || previewPending}
          className="mt-4 rounded-full border border-[#efe7db] px-4 py-2 text-xs uppercase tracking-[0.2em] disabled:cursor-not-allowed disabled:opacity-60"
        >
          {previewPending ? "Generating…" : canPreview ? "Generate prompt" : "Save template to generate"}
        </button>
        {previewState.error ? <p className="mt-2 text-sm text-red-600">{previewState.error}</p> : null}
        {previewState.result?.blocks ? (
          <div className="mt-4 space-y-3">
            <p className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Blocks</p>
            {blockOrder.map((blockKey) => (
              <div key={blockKey} className="rounded-2xl border border-[#efe7db] bg-white p-4">
                <p className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">{blockKey}</p>
                <pre className="mt-2 whitespace-pre-wrap text-xs">{previewState.result?.blocks?.[blockKey] || ""}</pre>
              </div>
            ))}
          </div>
        ) : null}
        {previewState.result?.text ? (
          <div className="mt-4 rounded-2xl border border-[#efe7db] bg-[#f7f4ee] p-4">
            <p className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Assembled prompt</p>
            <pre className="mt-2 whitespace-pre-wrap text-xs">{previewState.result.text}</pre>
          </div>
        ) : null}
        {previewState.result?.llm ? (
          <div className="mt-4 rounded-2xl border border-[#efe7db] bg-white p-4">
            <p className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">LLM response</p>
            {previewState.result.llm.error ? (
              <p className="mt-2 text-sm text-red-600">{previewState.result.llm.error}</p>
            ) : (
              <>
                <p className="mt-2 text-xs text-[#6b6257]">
                  Model: {previewState.result.llm.model || "default"} · {previewState.result.llm.duration_ms || 0}ms
                </p>
                <pre className="mt-2 whitespace-pre-wrap text-xs">{previewState.result.llm.content || ""}</pre>
              </>
            )}
          </div>
        ) : null}
      </form>
    </div>
  );
}
