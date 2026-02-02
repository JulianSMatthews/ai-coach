import AdminNav from "@/components/AdminNav";
import SubmitButton from "./SubmitButton";
import {
  listAdminUsers,
  listScriptRuns,
  runAssessmentSimulation,
  runCoachingSimulation,
} from "@/lib/api";
import { revalidatePath } from "next/cache";

export const dynamic = "force-dynamic";

async function runSimulationAction(formData: FormData) {
  "use server";
  const scenario = String(formData.get("scenario") || "").trim();
  const batch = formData.get("batch") === "on";
  const preset = String(formData.get("preset") || "").trim();
  const startFrom = String(formData.get("start_from") || "").trim();
  const clubIds = String(formData.get("club_ids") || "").trim();
  const sleep = String(formData.get("sleep") || "").trim();
  const unique = formData.get("unique") === "unique" ? true : formData.get("unique") === "reuse" ? false : undefined;
  const simulateWeeks = String(formData.get("simulate_weeks") || "").trim();
  const julian = String(formData.get("julian") || "").trim();

  try {
    await runAssessmentSimulation({
      scenario,
      batch,
      preset: preset || undefined,
      start_from: startFrom || undefined,
      club_ids: clubIds || undefined,
      sleep: sleep || undefined,
      unique,
      simulate_weeks: simulateWeeks || undefined,
      julian: julian || undefined,
    });
    revalidatePath("/admin/scripts");
  } catch (err) {
    throw err;
  }
}

async function runCoachingAction(formData: FormData) {
  "use server";
  const userIdRaw = String(formData.get("user_id") || "").trim();
  const userIdSelectRaw = String(formData.get("user_id_select") || "").trim();
  const effectiveUserIdRaw = userIdRaw || userIdSelectRaw;
  const userId = Number(effectiveUserIdRaw);
  const mode = String(formData.get("coaching_mode") || "").trim();
  const weekRaw = String(formData.get("week") || "").trim();
  const startWeek = String(formData.get("start_week") || "").trim();
  const sleep = String(formData.get("sleep") || "").trim();

  const payload: Record<string, unknown> = {
    user_id: Number.isFinite(userId) && userId > 0 ? userId : undefined,
    week: mode === "single" ? weekRaw || undefined : undefined,
    simulate_weeks: mode === "week1" ? "week1" : mode === "weeks12" ? "12" : undefined,
    start_week: startWeek || undefined,
    sleep: sleep || undefined,
  };

  try {
    await runCoachingSimulation(payload);
    revalidatePath("/admin/scripts");
  } catch (err) {
    throw err;
  }
}

async function runCombinedAction(formData: FormData) {
  "use server";
  let scenario = String(formData.get("scenario") || "").trim();
  const preset = String(formData.get("preset") || "").trim();
  const simulateWeeks = String(formData.get("simulate_weeks") || "").trim();
  const julian = String(formData.get("julian") || "").trim();
  const unique = formData.get("unique") === "unique" ? true : formData.get("unique") === "reuse" ? false : undefined;

  if (!scenario && !julian && !preset) {
    scenario = "competent_a";
  }

  try {
    await runAssessmentSimulation({
      scenario,
      preset: preset || undefined,
      simulate_weeks: simulateWeeks || undefined,
      julian: julian || undefined,
      unique,
    });
    revalidatePath("/admin/scripts");
  } catch (err) {
    throw err;
  }
}

export default async function ScriptsPage() {
  const runs = await listScriptRuns(12);
  const users = await listAdminUsers();

  return (
    <main className="min-h-screen bg-[#f7f4ee] px-6 py-10 text-[#1e1b16]">
      <div className="mx-auto w-full max-w-5xl space-y-6">
        <AdminNav title="Scripts" subtitle="Run assessment simulations with your preferred options." />

        <section className="rounded-3xl border border-[#e7e1d6] bg-white p-6">
          <h2 className="text-lg font-semibold">Assessment simulation</h2>
          <p className="mt-2 text-sm text-[#6b6257]">
            Use these controls to run the assessment simulation script in the background. Choose a single run (scenario
            or preset) or a batch run.
          </p>

          <form action={runSimulationAction} className="mt-6 space-y-6">
            <div className="grid gap-4 md:grid-cols-[1fr_1fr]">
              <div className="rounded-2xl border border-[#efe7db] bg-[#fffaf0] p-4">
                <p className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Single run</p>
                <label className="mt-3 text-xs uppercase tracking-[0.2em] text-[#6b6257]">Scenario key</label>
                <input
                  name="scenario"
                  className="mt-2 w-full rounded-xl border border-[#efe7db] bg-white px-3 py-2 text-sm"
                  placeholder="competent_a or mix:training=expert,nutrition=competent|b"
                />
                <p className="mt-2 text-xs text-[#6b6257]">
                  Runs one scenario only. Leave blank if you’re using a preset.
                </p>
              </div>
              <div className="rounded-2xl border border-[#efe7db] bg-white p-4">
                <p className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Single run presets</p>
                <label className="mt-3 text-xs uppercase tracking-[0.2em] text-[#6b6257]">Preset level</label>
                <select name="preset" className="mt-2 w-full rounded-xl border border-[#efe7db] bg-white px-3 py-2 text-sm">
                  <option value="">none</option>
                  <option value="min">min (novice)</option>
                  <option value="mid">mid (competent)</option>
                  <option value="max">max (expert)</option>
                  <option value="range">range (min → mid → max)</option>
                </select>
                <p className="mt-2 text-xs text-[#6b6257]">
                  Forces scores to the selected level (range runs three passes).
                </p>
                <label className="mt-4 text-xs uppercase tracking-[0.2em] text-[#6b6257]">Julian presets</label>
                <select name="julian" className="mt-2 w-full rounded-xl border border-[#efe7db] bg-white px-3 py-2 text-sm">
                  <option value="">none</option>
                  <option value="julian">julian (mid)</option>
                  <option value="julianlow">julian low</option>
                  <option value="julianhigh">julian high</option>
                </select>
                <p className="mt-2 text-xs text-[#6b6257]">
                  Overrides scenario/preset to target Julian test cases.
                </p>
              </div>
            </div>

            <div className="grid gap-4 md:grid-cols-[1fr_1fr_1fr]">
              <div className="rounded-2xl border border-[#efe7db] bg-white p-4">
                <p className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Batch run</p>
                <label className="mt-3 text-xs uppercase tracking-[0.2em] text-[#6b6257]">Start from</label>
                <input
                  name="start_from"
                  className="mt-2 w-full rounded-xl border border-[#efe7db] bg-white px-3 py-2 text-sm"
                  placeholder="developing_b"
                />
                <p className="mt-2 text-xs text-[#6b6257]">
                  Batch only. Skips earlier scenarios.
                </p>
                <label className="mt-4 flex items-center gap-2 text-sm text-[#3c332b]">
                  <input type="checkbox" name="batch" />
                  Run batch (all scenarios)
                </label>
                <p className="mt-2 text-xs text-[#6b6257]">
                  Runs every predefined scenario (uniform + mixed pillars).
                </p>
              </div>
              <div className="rounded-2xl border border-[#efe7db] bg-white p-4">
                <label className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Club IDs</label>
                <input
                  name="club_ids"
                  className="mt-2 w-full rounded-xl border border-[#efe7db] bg-white px-3 py-2 text-sm"
                  placeholder="1,2"
                />
                <p className="mt-2 text-xs text-[#6b6257]">
                  Batch only. Cycle users across these club IDs (comma‑separated).
                </p>
              </div>
              <div className="rounded-2xl border border-[#efe7db] bg-white p-4">
                <label className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Sleep between runs</label>
                <input
                  name="sleep"
                  className="mt-2 w-full rounded-xl border border-[#efe7db] bg-white px-3 py-2 text-sm"
                  placeholder="2.0"
                />
                <p className="mt-2 text-xs text-[#6b6257]">
                  Batch only. Pause (seconds) between scenarios.
                </p>
              </div>
            </div>

            <div className="grid gap-4 md:grid-cols-[1fr_1fr_1fr]">
              <div className="rounded-2xl border border-[#efe7db] bg-white p-4">
                <label className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">User reuse</label>
                <select name="unique" className="mt-2 w-full rounded-xl border border-[#efe7db] bg-white px-3 py-2 text-sm">
                  <option value="">default (unique)</option>
                  <option value="unique">unique users</option>
                  <option value="reuse">reuse same user</option>
                </select>
                <p className="mt-2 text-xs text-[#6b6257]">
                  Reuse keeps updating the same user; unique makes new users per run.
                </p>
              </div>
              <div className="rounded-2xl border border-[#efe7db] bg-white p-4">
                <label className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Simulate weeks</label>
                <select name="simulate_weeks" className="mt-2 w-full rounded-xl border border-[#efe7db] bg-white px-3 py-2 text-sm">
                  <option value="">none</option>
                  <option value="week1">week 1 only</option>
                  <option value="12">weeks 1–12</option>
                </select>
                <p className="mt-2 text-xs text-[#6b6257]">
                  Runs post‑assessment touchpoints for the selected period.
                </p>
              </div>
              <div className="rounded-2xl border border-[#efe7db] bg-[#fffaf0] p-4">
                <p className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Notes</p>
                <p className="mt-2 text-sm text-[#3c332b]">
                  Batch ignores scenario/preset inputs. Julian presets override scenario/preset selections.
                </p>
                <p className="mt-2 text-xs text-[#6b6257]">
                  Script runs in the background; watch backend logs for progress.
                </p>
              </div>
            </div>

            <div className="flex items-center gap-3">
              <SubmitButton
                label="Run simulation"
                pendingLabel="Starting…"
                pendingText="Starting assessment simulation… check Recent runs below."
                className="rounded-full border border-[var(--accent)] bg-[var(--accent)] px-5 py-2 text-xs uppercase tracking-[0.2em] text-white disabled:opacity-60"
              />
            </div>
          </form>
        </section>

        <section className="rounded-3xl border border-[#e7e1d6] bg-white p-6">
          <h2 className="text-lg font-semibold">Coaching simulation</h2>
          <p className="mt-2 text-sm text-[#6b6257]">
            Run coaching touchpoints only (no assessment). Choose a single week, week 1, or a 12‑week run for an existing
            user.
          </p>

          <form action={runCoachingAction} className="mt-6 space-y-6">
            <div className="grid gap-4 md:grid-cols-[1fr_1fr_1fr]">
              <div className="rounded-2xl border border-[#efe7db] bg-[#fffaf0] p-4">
                <label className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">User ID</label>
                <input
                  name="user_id"
                  className="mt-2 w-full rounded-xl border border-[#efe7db] bg-white px-3 py-2 text-sm"
                  placeholder="1"
                />
                <label className="mt-4 text-xs uppercase tracking-[0.2em] text-[#6b6257]">Or select user</label>
                <select
                  name="user_id_select"
                  className="mt-2 w-full rounded-xl border border-[#efe7db] bg-white px-3 py-2 text-sm"
                  defaultValue=""
                >
                  <option value="">select user</option>
                  {users.map((u) => (
                    <option key={u.id} value={u.id}>
                      #{u.id} {u.first_name || ""} {u.surname || ""} {u.phone ? `(${u.phone})` : ""}
                    </option>
                  ))}
                </select>
                <p className="mt-2 text-xs text-[#6b6257]">
                  Provide a user id or select a user to run coaching touchpoints.
                </p>
              </div>
              <div className="rounded-2xl border border-[#efe7db] bg-white p-4">
                <label className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Run mode</label>
                <select
                  name="coaching_mode"
                  className="mt-2 w-full rounded-xl border border-[#efe7db] bg-white px-3 py-2 text-sm"
                  defaultValue="single"
                >
                  <option value="single">single week</option>
                  <option value="week1">week 1 only</option>
                  <option value="weeks12">weeks 1–12</option>
                </select>
                <p className="mt-2 text-xs text-[#6b6257]">Pick how much of the program to simulate.</p>
              </div>
              <div className="rounded-2xl border border-[#efe7db] bg-white p-4">
                <label className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Week number (single)</label>
                <input
                  name="week"
                  className="mt-2 w-full rounded-xl border border-[#efe7db] bg-white px-3 py-2 text-sm"
                  placeholder="4"
                />
                <p className="mt-2 text-xs text-[#6b6257]">Only used when mode is “single week”.</p>
              </div>
            </div>

            <div className="grid gap-4 md:grid-cols-[1fr_1fr]">
              <div className="rounded-2xl border border-[#efe7db] bg-white p-4">
                <label className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Start week (12‑week)</label>
                <input
                  name="start_week"
                  className="mt-2 w-full rounded-xl border border-[#efe7db] bg-white px-3 py-2 text-sm"
                  placeholder="1"
                />
                <p className="mt-2 text-xs text-[#6b6257]">
                  Only used when running weeks 1–12. Defaults to week 1.
                </p>
              </div>
              <div className="rounded-2xl border border-[#efe7db] bg-white p-4">
                <label className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Sleep between weeks</label>
                <input
                  name="sleep"
                  className="mt-2 w-full rounded-xl border border-[#efe7db] bg-white px-3 py-2 text-sm"
                  placeholder="2.0"
                />
                <p className="mt-2 text-xs text-[#6b6257]">Seconds to pause between weeks in a 12‑week run.</p>
              </div>
            </div>

            <div className="flex items-center gap-3">
              <SubmitButton
                label="Run coaching"
                pendingLabel="Starting…"
                pendingText="Starting coaching simulation… check Recent runs below."
                className="rounded-full border border-[var(--accent)] bg-[var(--accent)] px-5 py-2 text-xs uppercase tracking-[0.2em] text-white disabled:opacity-60"
              />
            </div>
          </form>
        </section>

        <section className="rounded-3xl border border-[#e7e1d6] bg-white p-6">
          <h2 className="text-lg font-semibold">Combined (assessment + coaching)</h2>
          <p className="mt-2 text-sm text-[#6b6257]">
            Run assessment + follow‑on coaching in one step. Pick a scenario/preset and a coaching duration.
          </p>

          <form action={runCombinedAction} className="mt-6 space-y-6">
            <div className="grid gap-4 md:grid-cols-[1fr_1fr_1fr]">
              <div className="rounded-2xl border border-[#efe7db] bg-[#fffaf0] p-4">
                <label className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Scenario key</label>
                <input
                  name="scenario"
                  className="mt-2 w-full rounded-xl border border-[#efe7db] bg-white px-3 py-2 text-sm"
                  placeholder="competent_a or mix:training=expert,nutrition=competent|b"
                />
                <p className="mt-2 text-xs text-[#6b6257]">Leave blank if you’re using a preset.</p>
              </div>
              <div className="rounded-2xl border border-[#efe7db] bg-white p-4">
                <label className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Preset level</label>
                <select name="preset" className="mt-2 w-full rounded-xl border border-[#efe7db] bg-white px-3 py-2 text-sm">
                  <option value="">none</option>
                  <option value="min">min (novice)</option>
                  <option value="mid">mid (competent)</option>
                  <option value="max">max (expert)</option>
                  <option value="range">range (min → mid → max)</option>
                </select>
                <p className="mt-2 text-xs text-[#6b6257]">
                  Forces scores to the selected level (range runs three passes).
                </p>
              </div>
              <div className="rounded-2xl border border-[#efe7db] bg-white p-4">
                <label className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Julian presets</label>
                <select name="julian" className="mt-2 w-full rounded-xl border border-[#efe7db] bg-white px-3 py-2 text-sm">
                  <option value="">none</option>
                  <option value="julian">julian (mid)</option>
                  <option value="julianlow">julian low</option>
                  <option value="julianhigh">julian high</option>
                </select>
                <p className="mt-2 text-xs text-[#6b6257]">Overrides scenario/preset selections.</p>
              </div>
            </div>

            <div className="grid gap-4 md:grid-cols-[1fr_1fr_1fr]">
              <div className="rounded-2xl border border-[#efe7db] bg-white p-4">
                <label className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Coaching duration</label>
                <select
                  name="simulate_weeks"
                  className="mt-2 w-full rounded-xl border border-[#efe7db] bg-white px-3 py-2 text-sm"
                  defaultValue="week1"
                >
                  <option value="week1">week 1 only</option>
                  <option value="12">weeks 1–12</option>
                </select>
                <p className="mt-2 text-xs text-[#6b6257]">Required to run coaching after assessment.</p>
              </div>
              <div className="rounded-2xl border border-[#efe7db] bg-white p-4">
                <label className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">User reuse</label>
                <select name="unique" className="mt-2 w-full rounded-xl border border-[#efe7db] bg-white px-3 py-2 text-sm">
                  <option value="">default (unique)</option>
                  <option value="unique">unique users</option>
                  <option value="reuse">reuse same user</option>
                </select>
                <p className="mt-2 text-xs text-[#6b6257]">Reuse keeps updating the same user.</p>
              </div>
              <div className="rounded-2xl border border-[#efe7db] bg-[#fffaf0] p-4">
                <p className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Notes</p>
                <p className="mt-2 text-sm text-[#3c332b]">
                  Combined uses the assessment script, then runs coaching touchpoints for the selected period.
                </p>
              </div>
            </div>

            <div className="flex items-center gap-3">
              <SubmitButton
                label="Run combined"
                pendingLabel="Starting…"
                pendingText="Starting combined run… check Recent runs below."
                className="rounded-full border border-[var(--accent)] bg-[var(--accent)] px-5 py-2 text-xs uppercase tracking-[0.2em] text-white disabled:opacity-60"
              />
            </div>
          </form>
        </section>

        <section className="rounded-3xl border border-[#e7e1d6] bg-white p-6">
          <h2 className="text-lg font-semibold">Recent runs</h2>
          <p className="mt-2 text-sm text-[#6b6257]">
            Latest script runs with status and logs. Click a run to view its output.
          </p>

          <div className="mt-4 overflow-x-auto rounded-2xl border border-[#efe7db]">
            <table className="min-w-full text-left text-sm">
              <thead className="bg-[#faf6ef] text-xs uppercase tracking-[0.2em] text-[#6b6257]">
                <tr>
                  <th className="px-4 py-3">Run</th>
                  <th className="px-4 py-3">Type</th>
                  <th className="px-4 py-3">Status</th>
                  <th className="px-4 py-3">Started</th>
                  <th className="px-4 py-3">Finished</th>
                  <th className="px-4 py-3">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[#efe7db]">
                {runs.map((run) => (
                  <tr key={run.id} className="bg-white">
                    <td className="px-4 py-3">#{run.id}</td>
                    <td className="px-4 py-3 capitalize">{run.kind}</td>
                    <td className="px-4 py-3 capitalize">{run.status}</td>
                    <td className="px-4 py-3">{run.started_at || "—"}</td>
                    <td className="px-4 py-3">{run.finished_at || "—"}</td>
                    <td className="px-4 py-3">
                      <a
                        className="rounded-full border border-[var(--accent)] px-3 py-1 text-xs uppercase tracking-[0.2em] text-[var(--accent)]"
                        href={`/admin/scripts/runs/${run.id}`}
                      >
                        Log
                      </a>
                    </td>
                  </tr>
                ))}
                {runs.length === 0 ? (
                  <tr>
                    <td className="px-4 py-6 text-sm text-[#6b6257]" colSpan={6}>
                      No runs yet.
                    </td>
                  </tr>
                ) : null}
              </tbody>
            </table>
          </div>
        </section>
      </div>
    </main>
  );
}
