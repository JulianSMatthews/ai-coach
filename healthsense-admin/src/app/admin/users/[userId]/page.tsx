import Link from "next/link";
import { notFound } from "next/navigation";
import AdminNav from "@/components/AdminNav";
import AccountTools from "./AccountTools";
import {
  getAdminUserDetails,
  getAdminUserAppState,
  getAdminUserActivity,
  getAdminUserPerformance,
  type AdminUserActivity,
} from "@/lib/api";

export const dynamic = "force-dynamic";
const sections = [
  { key: "overview", label: "Overview" },
  { key: "activity", label: "Activity" },
  { key: "history", label: "Previous week(s)" },
  { key: "account", label: "Account" },
];
const panel = "rounded-3xl border border-[#e7e1d6] bg-white p-6";
const muted = "text-sm text-[#6b6257]";
function dateLabel(value: unknown, withTime = false) {
  if (!value) return "—";
  const raw = String(value);
  const parsed = new Date(
    raw.includes("T") && !/Z$|[+-]\d{2}:\d{2}$/.test(raw) ? `${raw}Z` : raw,
  );
  if (!Number.isFinite(parsed.getTime())) return "—";
  return parsed.toLocaleString("en-GB", {
    day: "numeric",
    month: "short",
    year: "numeric",
    ...(withTime ? { hour: "2-digit", minute: "2-digit" } : {}),
    timeZone: "Europe/London",
  });
}
function shiftWeek(value: string, days: number) {
  const date = new Date(`${value}T12:00:00Z`);
  date.setUTCDate(date.getUTCDate() + days);
  return date.toISOString().slice(0, 10);
}
function label(value?: string | null) {
  return value ? value.replaceAll("_", " ") : "—";
}
function ErrorNotice({ text }: { text: string }) {
  return (
    <p
      role="alert"
      className="rounded-2xl border border-[#e5b8ad] bg-[#fff3ee] p-4 text-sm text-[#92321b]"
    >
      {text}
    </p>
  );
}
function ActivityList({ events }: { events: AdminUserActivity["events"] }) {
  if (!events.length)
    return <p className={muted}>No recorded app activity is available.</p>;
  return (
    <ol className="divide-y divide-[#efe7db]">
      {events.map((event) => (
        <li key={event.id} className="py-4">
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <p className="font-medium">
              {event.label}
              {event.pillar_key ? ` · ${label(event.pillar_key)}` : ""}
            </p>
            <time className={muted}>{dateLabel(event.recorded_at, true)}</time>
          </div>
          <div className="mt-1 flex flex-wrap gap-x-4 gap-y-1 text-sm text-[#6b6257]">
            {event.for_date ? (
              <span>For {dateLabel(event.for_date)}</span>
            ) : null}
            {event.watch_pct != null ? (
              <span>Video progress: {event.watch_pct}%</span>
            ) : null}
            {event.quiz_score_pct != null ? (
              <span>Quiz result: {event.quiz_score_pct}%</span>
            ) : null}
            {event.completion_status ? (
              <span>Status: {label(event.completion_status)}</span>
            ) : null}
          </div>
        </li>
      ))}
    </ol>
  );
}

export default async function UserProfilePage({
  params,
  searchParams,
}: {
  params: Promise<{ userId: string }>;
  searchParams: Promise<{ section?: string; week?: string }>;
}) {
  const { userId: rawId } = await params;
  const query = await searchParams;
  const userId = Number(rawId);
  if (!Number.isInteger(userId) || userId <= 0) notFound();
  const section = sections.some((item) => item.key === query.section)
    ? query.section!
    : "overview";
  const [details, stateResult, activityResult, historyResult] =
    await Promise.all([
      getAdminUserDetails(userId),
      getAdminUserAppState(userId)
        .then((data) => ({ data, error: false }))
        .catch(() => ({ data: null, error: true })),
      getAdminUserActivity(userId)
        .then((data) => ({ data, error: false }))
        .catch(() => ({ data: null, error: true })),
      section === "history"
        ? getAdminUserPerformance(userId, query.week)
            .then((data) => ({ data, error: false }))
            .catch(() => ({ data: null, error: true }))
        : Promise.resolve({ data: null, error: false }),
    ]);
  const user = (details.user || {}) as Record<string, unknown>;
  const onboarding = (details.onboarding || {}) as Record<string, unknown>;
  const state = stateResult.data;
  const events = activityResult.data?.events || [];
  const journey = state?.journey?.daily_recording;
  const pillars = journey?.pillars || [];
  const lesson = state?.education;
  const progress = lesson?.progress;
  const history = historyResult.data;
  const userName = String(
    user.display_name ||
      [user.first_name, user.surname].filter(Boolean).join(" ") ||
      `User #${userId}`,
  );
  const base = `/admin/users/${userId}`;
  const historyStart = history?.week?.start;
  const newer = historyStart ? shiftWeek(historyStart, 7) : null;
  const historyToday = history?.today;
  const nextIsPast =
    newer && historyToday && shiftWeek(newer, 6) < historyToday;
  const latestCheckin = events.find(
    (event) => event.kind === "pillar_tracker_update",
  );
  const dataWarnings =
    state?.errors?.filter((error) =>
      ["tracker", "education", "weekly_objectives"].includes(
        error.section || "",
      ),
    ) || [];
  return (
    <main className="min-h-screen bg-[#f7f4ee] px-4 py-8 text-[#1e1b16] sm:px-6">
      <div className="mx-auto max-w-6xl space-y-5">
        <AdminNav
          title={userName}
          subtitle="Check-ins, learning and recorded app activity."
        />
        <div className="flex flex-wrap items-center justify-between gap-3 px-1 text-sm text-[#6b6257]">
          <span>
            User #{userId} · Joined {dateLabel(user.created_on)}
          </span>
          <Link className="underline" href="/admin/users">
            Back to users
          </Link>
        </div>
        <nav aria-label="User profile" className="flex flex-wrap gap-2">
          {sections.map((item) => (
            <Link
              key={item.key}
              href={`${base}?section=${item.key}`}
              aria-current={section === item.key ? "page" : undefined}
              className={`rounded-full border px-5 py-3 text-sm font-medium ${section === item.key ? "border-[#c54817] bg-[#c54817] text-white" : "border-[#e7e1d6] bg-white"}`}
            >
              {item.label}
            </Link>
          ))}
        </nav>
        {stateResult.error && section === "overview" ? (
          <ErrorNotice text="The app snapshot could not be loaded. Refresh to try again; unavailable data does not mean the user is inactive." />
        ) : null}
        {section === "overview" ? (
          <>
            <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-5">
              {[
                {
                  title: "Last recorded activity",
                  value: activityResult.error
                    ? "Unavailable"
                    : dateLabel(events[0]?.recorded_at, true),
                },
                {
                  title: "Today’s check-ins",
                  value:
                    state && journey
                      ? `${journey.completed_today_count ?? 0}/${journey.total_pillars ?? 0} pillars`
                      : "Unavailable",
                },
                {
                  title: "Yesterday’s check-ins",
                  value:
                    state && journey
                      ? `${journey.completed_yesterday_count ?? 0}/${journey.total_pillars ?? 0} pillars`
                      : "Unavailable",
                },
                {
                  title: "Check-in streak",
                  value: state?.engagement_summary?.current_streak_days == null
                    ? "Unavailable"
                    : `${state.engagement_summary.current_streak_days} ${state.engagement_summary.current_streak_days === 1 ? "day" : "days"}`,
                },
                {
                  title: "Learning streak",
                  value: lesson?.available
                    ? `${lesson.current_streak_days ?? 0} days`
                    : "Not available",
                },
              ].map((card) => (
                <section key={card.title} className={panel}>
                  <h2 className={muted}>{card.title}</h2>
                  <p className="mt-2 text-xl font-semibold">{card.value}</p>
                </section>
              ))}
            </div>
            {dataWarnings.length ? (
              <ErrorNotice
                text={`Some snapshot data is unavailable: ${dataWarnings.map((error) => error.section).join(", ")}.`}
              />
            ) : null}
            <section className={panel}>
              <h2 className="text-lg font-semibold">Check-ins by pillar</h2>
            <p className="mt-2 text-sm text-[#6b6257]">Same as the app: consecutive days of recorded app activity, including check-ins and learning.</p>
            <p className="mt-2 text-sm text-[#6b6257]">
              Pillar setup: {state?.tracker?.app_setup_completed == null ? "Unknown" : state.tracker.app_setup_completed ? "Complete" : "Not completed"}
            </p>
              <p className="mt-1 mb-4 text-sm text-[#6b6257]">
                Recording dates are separate from submission times. Snapshot for{" "}
                {dateLabel(state?.today)}.
              </p>
              {pillars.length ? (
                <div className="overflow-x-auto">
                  <table className="w-full text-left text-sm">
                    <thead>
                      <tr className="border-b">
                        <th className="py-3">Pillar</th>
                        <th className="pr-4">Day before yesterday</th>
                        <th className="pr-4">Yesterday</th>
                        <th>Today</th>
                      </tr>
                    </thead>
                    <tbody>
                      {pillars.map((pillar) => (
                        <tr
                          key={pillar.pillar_key}
                          className="border-b border-[#efe7db]"
                        >
                          <td className="py-3 font-medium">
                            {pillar.label || label(pillar.pillar_key)}
                          </td>
                          <td
                            className={
                              pillar.day_before_yesterday_complete
                                ? "text-[#397224]"
                                : muted
                            }
                          >
                            {pillar.day_before_yesterday_complete == null
                              ? "Unavailable"
                              : pillar.day_before_yesterday_complete
                                ? "Recorded"
                                : "Not recorded"}
                          </td>
                          <td
                            className={
                              pillar.yesterday_complete
                                ? "text-[#397224]"
                                : muted
                            }
                          >
                            {pillar.yesterday_complete
                              ? "Recorded"
                              : "Not recorded"}
                          </td>
                          <td
                            className={
                              pillar.today_complete ? "text-[#397224]" : muted
                            }
                          >
                            {pillar.today_complete
                              ? "Recorded"
                              : "Not recorded"}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <p className={muted}>
                  {state
                    ? "No pillar recording information is available."
                    : "Snapshot unavailable."}
                </p>
              )}
              {latestCheckin ? (
                <p className="mt-4 text-sm text-[#6b6257]">
                  Latest check-in submitted{" "}
                  {dateLabel(latestCheckin.recorded_at, true)}
                  {latestCheckin.for_date
                    ? ` for ${dateLabel(latestCheckin.for_date)}`
                    : ""}
                  .
                </p>
              ) : null}
            </section>
            <div className="grid gap-5 md:grid-cols-2">
              <section className={panel}>
                <h2 className="text-lg font-semibold">Learning</h2>
                <p className={`mt-1 ${muted}`}>Latest recorded lesson activity across programmes.</p>
                {lesson?.available ? (
                  <div className="mt-3 space-y-2 text-sm">
                    <p className="font-medium">
                      {lesson.concept_label ||
                        lesson.programme_name ||
                        "Current lesson"}
                    </p>
                    <p>Lesson date: {dateLabel(progress?.lesson_date)}</p>
                    <p>
                      Video progress:{" "}
                      {progress?.video_completed_at
                        ? `Completed${progress.watch_pct == null ? "" : ` · ${progress.watch_pct}%`}`
                        : progress?.watch_pct == null
                          ? "Not recorded"
                          : `${progress.watch_pct}%`}
                    </p>
                    <p>
                      Quiz:{" "}
                      {progress?.quiz_completed_at
                        ? `Completed · ${progress.quiz_score_pct ?? "—"}%`
                        : "Not completed"}
                    </p>
                    <p>
                      Lesson completion:{" "}
                      {progress?.completed_at
                        ? dateLabel(progress.completed_at, true)
                        : label(progress?.completion_status || "not completed")}
                    </p>
                  </div>
                ) : (
                  <p className={`mt-3 ${muted}`}>
                    No current lesson is available.
                  </p>
                )}
              </section>
              <section className={panel}>
                <h2 className="text-lg font-semibold">Plan & targets</h2>
                <div className="mt-3 space-y-2 text-sm">
                  <p>{state?.daily_plan?.title || "No daily plan available"}</p>
                  <p className={muted}>
                    Plan date: {dateLabel(state?.daily_plan?.plan_date)}
                  </p>
                  <p>
                    Daily plan: {state?.journey?.daily_plan?.label || "Unknown"}
                  </p>
                  <p>
                    Today’s focus:{" "}
                    {state?.journey?.todays_focus?.label || "Unknown"}
                  </p>
                  <p>
                    Coach insight:{" "}
                    {state?.journey?.gia_message?.label || "Unknown"}
                  </p>
                  <p>
                    {state?.weekly_objectives
                      ? `${state.weekly_objectives.configured_count ?? 0} targets configured`
                      : "Target information unavailable"}
                  </p>
                  {state?.weekly_objectives?.sections?.map((item) => (
                    <p key={item.key} className={muted}>
                      {item.label || item.key}: {item.configured_count ?? 0}/
                      {item.total_count ?? 0}
                    </p>
                  ))}
                </div>
              </section>
            </div>
            <section className={panel}>
              <div className="flex items-center justify-between gap-3">
                <h2 className="text-lg font-semibold">Recent activity</h2>
                <Link
                  href={`${base}?section=activity`}
                  className="text-sm underline"
                >
                  View activity
                </Link>
              </div>
              {activityResult.error ? (
                <ErrorNotice text="Activity could not be loaded." />
              ) : (
                <ActivityList events={events.slice(0, 5)} />
              )}
            </section>
          </>
        ) : null}
        {section === "activity" ? (
          <section className={panel}>
            <h2 className="text-lg font-semibold">Recorded app activity</h2>
            <p className={`my-3 ${muted}`}>
              Latest 100 recorded actions, newest first. Times are shown in UK
              time. An opened lesson or insight is not counted as completed.
            </p>
            {activityResult.error ? (
              <ErrorNotice text="Activity could not be loaded. Refresh to try again." />
            ) : (
              <ActivityList events={events} />
            )}
          </section>
        ) : null}
        {section === "history" ? (
          <section className={panel}>
            <h2 className="text-lg font-semibold">Previous week(s)</h2>
            {historyResult.error ? (
              <ErrorNotice text="Weekly scores could not be loaded. Check the selected date or refresh to try again." />
            ) : (
              <>
                <div className="my-4 flex flex-wrap items-center justify-between gap-3">
                  <p className="font-medium">
                    {dateLabel(history?.week?.start)} –{" "}
                    {dateLabel(history?.week?.end)}
                  </p>
                  <div className="flex gap-4 text-sm">
                    {historyStart ? (
                      <Link
                        className="underline"
                        href={`${base}?section=history&week=${shiftWeek(historyStart, -7)}`}
                      >
                        ← Previous week
                      </Link>
                    ) : null}
                    {nextIsPast ? (
                      <Link
                        className="underline"
                        href={`${base}?section=history&week=${newer}`}
                      >
                        Next week →
                      </Link>
                    ) : null}
                  </div>
                </div>
                <p className="mb-4 text-sm text-[#6b6257]">
                  Read-only scores for this week. Missing scores are not zero.
                </p>
                <div className="overflow-x-auto">
                  <table className="w-full text-left text-sm">
                    <thead>
                      <tr className="border-b">
                        <th className="py-3">Pillar</th>
                        <th>Score / 100</th>
                        <th>Completed recording days</th>
                      </tr>
                    </thead>
                    <tbody>
                      {history?.pillars?.map((pillar) => (
                        <tr
                          key={pillar.pillar_key}
                          className="border-b border-[#efe7db]"
                        >
                          <td className="py-3 font-medium">{pillar.label}</td>
                          <td>{pillar.tracker_score ?? "No recorded score"}</td>
                          <td>{pillar.completed_days_count ?? 0}/7</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </>
            )}
          </section>
        ) : null}
        {section === "account" ? (
          <>
            <section className={panel}>
              <h2 className="text-lg font-semibold">Account details</h2>
              <dl className="mt-4 grid gap-4 sm:grid-cols-2">
                {[
                  ["Name", userName],
                  ["Email", user.email],
                  ["Phone", user.phone],
                  [
                    "Consent",
                    user.consent_given === true ? "Given" : "Not given",
                  ],
                  [
                    "Billing",
                    state
                      ? state.billing?.status || "Not configured"
                      : "Unavailable",
                  ],
                  [
                    "First app access",
                    dateLabel(onboarding.first_app_login_at, true),
                  ],
                ].map(([key, value]) => (
                  <div key={String(key)}>
                    <dt className={muted}>{String(key)}</dt>
                    <dd className="mt-1 font-medium">{String(value || "—")}</dd>
                  </div>
                ))}
              </dl>
              <details className="mt-5 border-t pt-4">
                <summary className="cursor-pointer font-medium">
                  Setup details
                </summary>
                <p className={`mt-3 ${muted}`}>
                  Introduction completed:{" "}
                  {dateLabel(onboarding.intro_content_completed_at, true)}
                </p>
                <p className={`mt-2 ${muted}`}>
                  Email verified: {dateLabel(user.email_verified_at, true)}
                </p>
                <p className={`mt-2 ${muted}`}>
                  Phone verified: {dateLabel(user.phone_verified_at, true)}
                </p>
              </details>
            </section>
            <AccountTools
              userId={userId}
              coachingOn={onboarding.coaching_enabled_now === true}
              promptState={String(user.prompt_state_override || "live")}
            />
          </>
        ) : null}
      </div>
    </main>
  );
}
