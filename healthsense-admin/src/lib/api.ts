type FetchOptions = {
  query?: Record<string, string | number | boolean | undefined | null>;
  headers?: Record<string, string>;
};

export type AdminProfile = {
  user?: { id?: number; display_name?: string; phone?: string };
};

export type AdminStats = {
  as_of_uk?: string;
  users?: { total?: number; today?: number; week?: number };
  assessments?: { total?: number; today?: number; week?: number };
  interactions?: { total?: number; today?: number; week?: number };
};

export type UsageWeeklySummary = {
  as_of_uk?: string;
  window?: { start_utc?: string; end_utc?: string };
  weekly_flow?: {
    events?: number;
    chars?: number;
    minutes_est?: number;
    cost_est_gbp?: number;
    rate_gbp_per_1m_chars?: number;
    rate_source?: string;
    chars_per_min?: number;
    tag?: string | null;
  };
  total_tts?: {
    events?: number;
    chars?: number;
    minutes_est?: number;
    cost_est_gbp?: number;
    rate_gbp_per_1m_chars?: number;
    rate_source?: string;
    chars_per_min?: number;
    tag?: string | null;
  };
  llm_weekly?: {
    tokens_in?: number;
    tokens_out?: number;
    cost_est_gbp?: number;
    rate_gbp_per_1m_input_tokens?: number;
    rate_gbp_per_1m_output_tokens?: number;
    rate_source?: string;
    tag?: string | null;
  };
  llm_total?: {
    tokens_in?: number;
    tokens_out?: number;
    cost_est_gbp?: number;
    rate_gbp_per_1m_input_tokens?: number;
    rate_gbp_per_1m_output_tokens?: number;
    rate_source?: string;
    tag?: string | null;
  };
  whatsapp_total?: {
    messages?: number;
    cost_est_gbp?: number;
    rate_gbp_per_message?: number;
    rate_source?: string;
    tag?: string | null;
  };
};

export type UsageSummary = {
  as_of_uk?: string;
  window?: { start_utc?: string; end_utc?: string };
  user?: { id?: number; display_name?: string; phone?: string } | null;
  total_tts?: UsageWeeklySummary["total_tts"];
  llm_total?: UsageWeeklySummary["llm_total"];
  whatsapp_total?: UsageWeeklySummary["whatsapp_total"];
  combined_cost_gbp?: number;
};

export type PromptCostRow = {
  prompt_id: number;
  created_at?: string | null;
  user_id?: number | null;
  touchpoint?: string | null;
  model?: string | null;
  prompt_variant?: string | null;
  task_label?: string | null;
  prompt_title?: string | null;
  tokens_in?: number;
  tokens_out?: number;
  rate_in?: number | null;
  rate_out?: number | null;
  rate_source?: string | null;
  cost_est_gbp?: number;
  calc_cost_gbp?: number;
  working?: string | null;
};

export type PromptCostReport = {
  as_of_uk?: string;
  window?: { start_utc?: string; end_utc?: string };
  user?: { id?: number; display_name?: string; phone?: string } | null;
  rows?: PromptCostRow[];
  total_cost_gbp?: number;
  limit?: number;
};

export type UsageSettings = {
  tts_gbp_per_1m_chars?: number | null;
  tts_chars_per_min?: number | null;
  llm_gbp_per_1m_input_tokens?: number | null;
  llm_gbp_per_1m_output_tokens?: number | null;
  wa_gbp_per_message?: number | null;
  wa_gbp_per_media_message?: number | null;
  wa_gbp_per_template_message?: number | null;
  meta?: Record<string, unknown> | string | null;
};

export type PromptTemplateSummary = {
  id: number;
  touchpoint: string;
  state?: string | null;
  version?: number | null;
  is_active?: boolean;
  okr_scope?: string | null;
  programme_scope?: string | null;
  response_format?: string | null;
  note?: string | null;
  updated_at?: string | null;
};

export type PromptTemplateDetail = PromptTemplateSummary & {
  block_order?: string[] | null;
  include_blocks?: string[] | null;
  task_block?: string | null;
};

export type PromptSettingsPayload = {
  system_block?: string | null;
  locale_block?: string | null;
  default_block_order?: string[] | null;
  worker_mode_override?: boolean | null;
  podcast_worker_mode_override?: boolean | null;
  worker_mode_env?: boolean | null;
  podcast_worker_mode_env?: boolean | null;
  worker_mode_effective?: boolean | null;
  podcast_worker_mode_effective?: boolean | null;
  worker_mode_source?: string | null;
  podcast_worker_mode_source?: string | null;
};

export type WorkerStatusPayload = {
  worker_mode_override?: boolean | null;
  podcast_worker_mode_override?: boolean | null;
  worker_mode_env?: boolean | null;
  podcast_worker_mode_env?: boolean | null;
  worker_mode_effective?: boolean | null;
  podcast_worker_mode_effective?: boolean | null;
  worker_mode_source?: string | null;
  podcast_worker_mode_source?: string | null;
};

export type ContentPromptTemplateSummary = {
  id: number;
  template_key: string;
  label?: string | null;
  pillar_key?: string | null;
  concept_code?: string | null;
  state?: string | null;
  version?: number | null;
  is_active?: boolean;
  response_format?: string | null;
  note?: string | null;
  updated_at?: string | null;
};

export type ContentPromptTemplateDetail = ContentPromptTemplateSummary & {
  block_order?: string[] | null;
  include_blocks?: string[] | null;
  task_block?: string | null;
};

export type ContentPromptSettingsPayload = {
  system_block?: string | null;
  locale_block?: string | null;
  default_block_order?: string[] | null;
};

export type ConceptOption = {
  pillar_key?: string | null;
  code?: string | null;
  name?: string | null;
};

export type PromptTestResult = {
  text?: string;
  blocks?: Record<string, string>;
  block_order?: string[];
  llm?: {
    model?: string | null;
    duration_ms?: number | null;
    content?: string | null;
    error?: string | null;
  };
  meta?: Record<string, unknown>;
  audio_url?: string | null;
  podcast_error?: string | null;
};

export type PromptVersionLog = {
  id: number;
  created_at?: string | null;
  version?: number | null;
  from_state?: string | null;
  to_state?: string | null;
  note?: string | null;
};

export type PromptHistoryItem = {
  id: number;
  created_at?: string | null;
  touchpoint?: string | null;
  user_id?: number | null;
  user_name?: string | null;
  first_name?: string | null;
  surname?: string | null;
  phone?: string | null;
  model?: string | null;
  duration_ms?: number | null;
  template_state?: string | null;
  template_version?: number | null;
  response_preview?: string | null;
};

export type PromptHistoryDetail = PromptHistoryItem & {
  prompt_variant?: string | null;
  task_label?: string | null;
  block_order?: string[] | null;
  system_block?: string | null;
  locale_block?: string | null;
  okr_block?: string | null;
  okr_scope?: string | null;
  scores_block?: string | null;
  habit_block?: string | null;
  task_block?: string | null;
  template_state?: string | null;
  template_version?: number | null;
  user_block?: string | null;
  extra_blocks?: Record<string, string> | null;
  assembled_prompt?: string | null;
  context_meta?: Record<string, unknown> | null;
  audio_url?: string | null;
};

export type TouchpointHistoryItem = {
  id: number;
  kind: "touchpoint" | "message";
  ts?: string | null;
  touchpoint_type?: string | null;
  week_no?: number | null;
  channel?: string | null;
  audio_url?: string | null;
  preview?: string | null;
  full_text?: string | null;
  is_truncated?: boolean | null;
  direction?: string | null;
  user_id?: number | null;
  user_name?: string | null;
  phone?: string | null;
};

export type TwilioTemplateItem = {
  id: number;
  provider?: string | null;
  template_type?: string | null;
  button_count?: number | null;
  friendly_name?: string | null;
  sid?: string | null;
  language?: string | null;
  status?: string | null;
  payload?: Record<string, unknown> | null;
  last_synced_at?: string | null;
  content_types?: string[] | null;
};

export type MessagingSettings = {
  out_of_session_enabled?: boolean | null;
  out_of_session_message?: string | null;
  updated_at?: string | null;
};

export type GlobalScheduleItem = {
  id?: number | null;
  day_key?: string | null;
  time_local?: string | null;
  enabled?: boolean | null;
  updated_at?: string | null;
};

export type RecentReportItem = {
  run_id?: number;
  user_id?: number;
  user_name?: string | null;
  finished_at?: string | null;
  combined_overall?: number | null;
  report_html?: string | null;
  report_pdf?: string | null;
  report_image?: string | null;
};

export type ScriptRunSummary = {
  id: number;
  kind: string;
  status: string;
  pid?: number | null;
  command: string;
  log_path?: string | null;
  exit_code?: number | null;
  started_at?: string | null;
  finished_at?: string | null;
  created_by?: number | null;
};

export type KbSnippetSummary = {
  id: number;
  pillar_key?: string | null;
  concept_code?: string | null;
  title?: string | null;
  tags?: string[];
  text_preview?: string | null;
  created_at?: string | null;
};

export type KbSnippetDetail = {
  id: number;
  pillar_key?: string | null;
  concept_code?: string | null;
  title?: string | null;
  text?: string | null;
  tags?: string[];
  created_at?: string | null;
};

export type ContentGenerationSummary = {
  id: number;
  user_id?: number | null;
  user_name?: string | null;
  touchpoint?: string | null;
  prompt_state?: string | null;
  provider?: string | null;
  test_date?: string | null;
  run_llm?: boolean | null;
  model_override?: string | null;
  status?: string | null;
  created_at?: string | null;
};

export type ContentGenerationDetail = ContentGenerationSummary & {
  error?: string | null;
  assembled_prompt?: string | null;
  blocks?: Record<string, string> | null;
  block_order?: string[] | null;
  meta?: Record<string, unknown> | null;
  llm_model?: string | null;
  llm_duration_ms?: number | null;
  llm_content?: string | null;
  llm_error?: string | null;
  podcast_url?: string | null;
  podcast_voice?: string | null;
  podcast_error?: string | null;
};

export type ContentLibrarySummary = {
  id: number;
  pillar_key?: string | null;
  concept_code?: string | null;
  title?: string | null;
  status?: string | null;
  text_preview?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
  source_generation_id?: number | null;
  podcast_url?: string | null;
  podcast_voice?: string | null;
  source_type?: string | null;
  source_url?: string | null;
  license?: string | null;
  published_at?: string | null;
  level?: string | null;
  tags?: string[] | null;
};

export type ContentLibraryDetail = ContentLibrarySummary & {
  body?: string | null;
};

export type AdminUserSummary = {
  id: number;
  first_name?: string | null;
  surname?: string | null;
  display_name?: string | null;
  phone?: string | null;
  created_on?: string | null;
  updated_on?: string | null;
  consent_given?: boolean | null;
  consent_at?: string | null;
  latest_run_id?: number | null;
  latest_run_finished_at?: string | null;
  status?: string | null;
  prompt_state_override?: string | null;
  coaching_enabled?: boolean | null;
};

function getBaseUrl() {
  const base = process.env.API_BASE_URL;
  if (!base) {
    throw new Error("API_BASE_URL is not set");
  }
  return base.replace(/\/+$/, "");
}

function getAdminHeaders() {
  const token = process.env.ADMIN_API_TOKEN;
  const adminUserId = process.env.ADMIN_USER_ID;
  if (!token || !adminUserId) {
    throw new Error("ADMIN_API_TOKEN or ADMIN_USER_ID is not set");
  }
  return {
    "X-Admin-Token": token,
    "X-Admin-User-Id": adminUserId,
  };
}

async function getSessionToken(): Promise<string | null> {
  if (typeof window !== "undefined") return null;
  try {
    const { cookies, headers } = await import("next/headers");
    try {
      const store = await cookies();
      const direct = store.get("hs_session")?.value;
      if (direct) return direct;
    } catch {}
    const hdrs = await headers();
    const cookieHeader = hdrs.get("cookie") || "";
    const match = cookieHeader.match(/(?:^|; )hs_session=([^;]+)/);
    return match ? match[1] : null;
  } catch {
    return null;
  }
}

function withQuery(url: string, query?: FetchOptions["query"]) {
  if (!query) return url;
  const params = new URLSearchParams();
  Object.entries(query).forEach(([k, v]) => {
    if (v === undefined || v === null || v === "") return;
    params.set(k, String(v));
  });
  const qs = params.toString();
  return qs ? `${url}?${qs}` : url;
}

async function apiGet<T>(path: string, options: FetchOptions = {}): Promise<T> {
  const base = getBaseUrl();
  const url = withQuery(`${base}${path}`, options.query);
  const sessionToken = await getSessionToken();
  const headers: Record<string, string> = {
    ...(options.headers || {}),
  } as Record<string, string>;
  if (sessionToken) {
    headers["X-Session-Token"] = sessionToken;
  }
  const res = await fetch(url, {
    headers,
    cache: "no-store",
  });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(`API ${res.status} ${res.statusText}: ${text}`);
  }
  return res.json() as Promise<T>;
}

async function apiAdmin<T>(path: string, options: RequestInit & { query?: FetchOptions["query"] } = {}): Promise<T> {
  const base = getBaseUrl();
  const url = withQuery(`${base}${path}`, options.query);
  const res = await fetch(url, {
    ...options,
    headers: {
      ...(options.headers || {}),
      ...getAdminHeaders(),
    },
    cache: "no-store",
  });
  const text = await res.text();
  if (!res.ok) {
    throw new Error(`API ${res.status} ${res.statusText}: ${text}`);
  }
  return text ? (JSON.parse(text) as T) : ({} as T);
}

export async function getAdminProfile(): Promise<AdminProfile> {
  return apiAdmin<AdminProfile>("/admin/profile");
}

export async function getAdminStats(): Promise<AdminStats> {
  return apiAdmin<AdminStats>("/admin/stats");
}

export async function getAdminUsageWeekly(): Promise<UsageWeeklySummary> {
  return apiAdmin<UsageWeeklySummary>("/admin/usage/weekly");
}

export async function getAdminUsageSummary(params: {
  days?: number;
  start?: string;
  end?: string;
  user_id?: number;
  tag?: string;
} = {}): Promise<UsageSummary> {
  return apiAdmin<UsageSummary>("/admin/usage/summary", {
    query: {
      days: params.days,
      start: params.start,
      end: params.end,
      user_id: params.user_id,
      tag: params.tag,
    },
  });
}

export async function getAdminPromptCosts(params: {
  days?: number;
  start?: string;
  end?: string;
  user_id?: number;
  limit?: number;
} = {}): Promise<PromptCostReport> {
  return apiAdmin<PromptCostReport>("/admin/usage/prompt-costs", {
    query: {
      days: params.days,
      start: params.start,
      end: params.end,
      user_id: params.user_id,
      limit: params.limit,
    },
  });
}

export async function getUsageSettings(): Promise<UsageSettings> {
  return apiAdmin<UsageSettings>("/admin/usage/settings");
}

export async function updateUsageSettings(payload: UsageSettings): Promise<UsageSettings> {
  return apiAdmin<UsageSettings>("/admin/usage/settings", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export async function fetchUsageSettings(): Promise<UsageSettings> {
  return apiAdmin<UsageSettings>("/admin/usage/settings/fetch", {
    method: "POST",
  });
}

export async function listPromptTemplates(state?: string, query?: string) {
  const data = await apiAdmin<{ templates: PromptTemplateSummary[] }>("/admin/prompts/templates", {
    query: { state: state || undefined, q: query || undefined },
  });
  return data.templates || [];
}

export async function getPromptTemplate(id: number) {
  return apiAdmin<PromptTemplateDetail>(`/admin/prompts/templates/${id}`);
}

export async function createPromptTemplate(payload: Record<string, unknown>) {
  return apiAdmin<Record<string, unknown>>("/admin/prompts/templates", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export async function updatePromptTemplate(id: number, payload: Record<string, unknown>) {
  return apiAdmin<Record<string, unknown>>(`/admin/prompts/templates/${id}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export async function promotePromptTemplate(
  id: number,
  to_state: string,
  note?: string,
  touchpoint?: string,
  from_state?: string,
) {
  return apiAdmin<Record<string, unknown>>(`/admin/prompts/templates/${id}/promote`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ to_state, note, touchpoint, from_state }),
  });
}

export async function promoteAllPromptTemplates(from_state: string, to_state: string, note?: string) {
  return apiAdmin<Record<string, unknown>>("/admin/prompts/templates/promote-all", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ from_state, to_state, note }),
  });
}

export async function getPromptSettings() {
  return apiAdmin<PromptSettingsPayload>("/admin/prompts/settings");
}

export async function updatePromptSettings(payload: PromptSettingsPayload) {
  return apiAdmin<Record<string, unknown>>("/admin/prompts/settings", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export async function getWorkerStatus() {
  return apiAdmin<WorkerStatusPayload>("/admin/worker/status");
}

export async function listContentPromptTemplates(
  state?: string,
  q?: string,
  pillar?: string,
  concept?: string,
): Promise<ContentPromptTemplateSummary[]> {
  const data = await apiAdmin<{ templates: ContentPromptTemplateSummary[] }>("/admin/content/templates", {
    query: {
      state: state || undefined,
      q: q || undefined,
      pillar: pillar || undefined,
      concept: concept || undefined,
      limit: 200,
    },
  });
  return data.templates || [];
}

export async function listConceptOptions(pillar?: string): Promise<ConceptOption[]> {
  const data = await apiAdmin<{ items: ConceptOption[] }>("/admin/concepts", {
    query: {
      pillar: pillar || undefined,
    },
  });
  return data.items || [];
}

export async function getContentPromptTemplate(id: number): Promise<ContentPromptTemplateDetail> {
  return apiAdmin<ContentPromptTemplateDetail>(`/admin/content/templates/${id}`);
}

export async function createContentPromptTemplate(payload: {
  template_key: string;
  label?: string;
  pillar_key?: string;
  concept_code?: string;
  state?: string;
  response_format?: string;
  block_order?: string;
  include_blocks?: string;
  task_block?: string;
  note?: string;
  is_active?: boolean;
}) {
  return apiAdmin<Record<string, unknown>>("/admin/content/templates", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export async function updateContentPromptTemplate(id: number, payload: Record<string, unknown>) {
  return apiAdmin<Record<string, unknown>>(`/admin/content/templates/${id}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export async function promoteContentPromptTemplate(payload: { id: number; to_state: string; note?: string }) {
  return apiAdmin<Record<string, unknown>>(`/admin/content/templates/${payload.id}/promote`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ to_state: payload.to_state, note: payload.note }),
  });
}

export async function getContentPromptSettings() {
  return apiAdmin<ContentPromptSettingsPayload>("/admin/content/settings");
}

export async function updateContentPromptSettings(payload: ContentPromptSettingsPayload) {
  return apiAdmin<Record<string, unknown>>("/admin/content/settings", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export async function testPromptTemplate(payload: Record<string, unknown>) {
  return apiAdmin<PromptTestResult>("/admin/prompts/test", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export async function listPromptVersions(limit?: number) {
  const data = await apiAdmin<{ items: PromptVersionLog[] }>("/admin/prompts/versions", {
    query: { limit: limit || undefined },
  });
  return data.items || [];
}

export async function listPromptHistory(
  limit?: number,
  userId?: number,
  touchpoint?: string,
  start?: string,
  end?: string
) {
  const data = await apiAdmin<{ items: PromptHistoryItem[] }>("/admin/prompts/history", {
    query: {
      limit: limit || undefined,
      user_id: userId || undefined,
      touchpoint: touchpoint || undefined,
      start: start || undefined,
      end: end || undefined,
    },
  });
  return data.items || [];
}

export async function getPromptHistoryDetail(logId: number) {
  return apiAdmin<PromptHistoryDetail>(`/admin/prompts/history/${logId}`);
}

export async function listTouchpointHistory(
  limit?: number,
  userId?: number,
  touchpoint?: string,
  start?: string,
  end?: string
) {
  const data = await apiAdmin<{ items: TouchpointHistoryItem[] }>("/admin/touchpoints/history", {
    query: {
      limit: limit || undefined,
      user_id: userId || undefined,
      touchpoint: touchpoint || undefined,
      start: start || undefined,
      end: end || undefined,
    },
  });
  return data.items || [];
}

export async function listRecentReports(limit?: number) {
  const data = await apiAdmin<{ items: RecentReportItem[] }>("/admin/reports/recent", {
    query: { limit: limit || undefined },
  });
  return data.items || [];
}

export async function runAssessmentSimulation(payload: Record<string, unknown>) {
  return apiAdmin<Record<string, unknown>>("/admin/scripts/assessment-simulate", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export async function runCoachingSimulation(payload: Record<string, unknown>) {
  return apiAdmin<Record<string, unknown>>("/admin/scripts/coaching-simulate", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export async function listScriptRuns(limit?: number): Promise<ScriptRunSummary[]> {
  const data = await apiAdmin<{ items: ScriptRunSummary[] }>("/admin/scripts/runs", {
    query: { limit: limit || undefined },
  });
  return data.items || [];
}

export async function getScriptRun(runId: number): Promise<ScriptRunSummary> {
  return apiAdmin<ScriptRunSummary>(`/admin/scripts/runs/${runId}`);
}

export async function getScriptRunLog(runId: number, tail?: number) {
  return apiAdmin<{ log: string; path?: string | null; tail: number }>(
    `/admin/scripts/runs/${runId}/log`,
    {
      query: { tail: tail || undefined },
    }
  );
}

export async function listKbSnippets(query?: {
  q?: string;
  pillar?: string;
  concept?: string;
  limit?: number;
}): Promise<KbSnippetSummary[]> {
  const data = await apiAdmin<{ items: KbSnippetSummary[] }>("/admin/kb/snippets", {
    query: {
      q: query?.q || undefined,
      pillar: query?.pillar || undefined,
      concept: query?.concept || undefined,
      limit: query?.limit || undefined,
    },
  });
  return data.items || [];
}

export async function getKbSnippet(id: number): Promise<KbSnippetDetail> {
  return apiAdmin<KbSnippetDetail>(`/admin/kb/snippets/${id}`);
}

export async function createKbSnippet(payload: Record<string, unknown>) {
  return apiAdmin<Record<string, unknown>>("/admin/kb/snippets", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export async function updateKbSnippet(id: number, payload: Record<string, unknown>) {
  return apiAdmin<Record<string, unknown>>(`/admin/kb/snippets/${id}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export async function listAdminUsers(query?: string): Promise<AdminUserSummary[]> {
  const data = await apiAdmin<{ users: AdminUserSummary[] }>("/admin/users", {
    query: { q: query || undefined },
  });
  return data.users || [];
}

export async function getAdminUserStatus(userId: number): Promise<Record<string, unknown>> {
  return apiAdmin<Record<string, unknown>>(`/admin/users/${userId}/status`);
}

export async function getAdminUserDetails(userId: number): Promise<Record<string, unknown>> {
  return apiAdmin<Record<string, unknown>>(`/admin/users/${userId}`);
}

export async function getAdminUserReport(userId: number): Promise<Record<string, unknown>> {
  return apiAdmin<Record<string, unknown>>(`/admin/users/${userId}/report`);
}

export async function createAdminUser(payload: {
  first_name: string;
  surname: string;
  phone: string;
}): Promise<Record<string, unknown>> {
  return apiAdmin<Record<string, unknown>>("/admin/users", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export async function startAdminUser(userId: number): Promise<Record<string, unknown>> {
  return apiAdmin<Record<string, unknown>>(`/admin/users/${userId}/start`, { method: "POST" });
}

export async function resetAdminUser(userId: number): Promise<Record<string, unknown>> {
  return apiAdmin<Record<string, unknown>>(`/admin/users/${userId}/reset`, { method: "POST" });
}

export async function setAdminUserPromptState(
  userId: number,
  state: string,
): Promise<Record<string, unknown>> {
  return apiAdmin<Record<string, unknown>>(`/admin/users/${userId}/prompt-state`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ state }),
  });
}

export async function setAdminUserCoaching(
  userId: number,
  enabled: boolean,
): Promise<Record<string, unknown>> {
  return apiAdmin<Record<string, unknown>>(`/api/v1/users/${userId}/preferences`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ auto_prompts: enabled ? "on" : "off" }),
  });
}

export async function createContentGeneration(payload: {
  template_id?: number;
  template_key?: string;
  user_id?: string | number;
  state?: string;
  pillar_key?: string;
  concept_code?: string;
  provider?: string;
  test_date?: string;
  run_llm?: boolean;
  model_override?: string;
  generate_podcast?: boolean;
  podcast_voice?: string;
}): Promise<Record<string, unknown>> {
  return apiAdmin<Record<string, unknown>>("/admin/content/generations", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export async function listContentGenerations(query?: {
  user_id?: string | number;
  touchpoint?: string;
  state?: string;
  start?: string;
  end?: string;
  limit?: number;
}): Promise<ContentGenerationSummary[]> {
  const data = await apiAdmin<{ items: ContentGenerationSummary[] }>("/admin/content/generations", {
    query: {
      user_id: query?.user_id || undefined,
      touchpoint: query?.touchpoint || undefined,
      state: query?.state || undefined,
      start: query?.start || undefined,
      end: query?.end || undefined,
      limit: query?.limit || undefined,
    },
  });
  return data.items || [];
}

export async function getContentGeneration(id: number): Promise<ContentGenerationDetail> {
  return apiAdmin<ContentGenerationDetail>(`/admin/content/generations/${id}`);
}

export async function listLibraryContent(query?: {
  q?: string;
  pillar?: string;
  concept?: string;
  status?: string;
  source?: string;
  limit?: number;
}): Promise<ContentLibrarySummary[]> {
  const data = await apiAdmin<{ items: ContentLibrarySummary[] }>("/admin/library/content", {
    query: {
      q: query?.q || undefined,
      pillar: query?.pillar || undefined,
      concept: query?.concept || undefined,
      status: query?.status || undefined,
      source: query?.source || undefined,
      limit: query?.limit || undefined,
    },
  });
  return data.items || [];
}

export async function getLibraryContent(id: number): Promise<ContentLibraryDetail> {
  return apiAdmin<ContentLibraryDetail>(`/admin/library/content/${id}`);
}

export async function createLibraryContent(payload: {
  pillar_key: string;
  concept_code?: string;
  title: string;
  body: string;
  status?: string;
  podcast_url?: string;
  podcast_voice?: string;
  source_type?: string;
  source_url?: string;
  license?: string;
  published_at?: string;
  level?: string;
  tags?: string[] | string;
  source_generation_id?: number;
}): Promise<Record<string, unknown>> {
  return apiAdmin<Record<string, unknown>>("/admin/library/content", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export async function updateLibraryContent(id: number, payload: Record<string, unknown>) {
  return apiAdmin<Record<string, unknown>>(`/admin/library/content/${id}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export async function generateRunReport(runId: number): Promise<Record<string, unknown>> {
  return apiAdmin<Record<string, unknown>>(`/admin/reports/run/${runId}`, { method: "POST" });
}

export async function generateProgressReport(userId: number, anchor?: string): Promise<Record<string, unknown>> {
  return apiAdmin<Record<string, unknown>>(`/admin/reports/progress/${userId}`, {
    method: "POST",
    query: { anchor: anchor || undefined },
  });
}

export async function generateDetailedReport(userId: number): Promise<Record<string, unknown>> {
  return apiAdmin<Record<string, unknown>>(`/admin/reports/detailed/${userId}`, { method: "POST" });
}

export async function generateClubUsersReport(): Promise<Record<string, unknown>> {
  return apiAdmin<Record<string, unknown>>("/admin/reports/club-users", { method: "POST" });
}

export async function generateSummaryReport(start?: string, end?: string): Promise<Record<string, unknown>> {
  return apiAdmin<Record<string, unknown>>("/admin/reports/summary", {
    method: "POST",
    query: { start: start || undefined, end: end || undefined },
  });
}

export async function generateBatchReports(start?: string, end?: string): Promise<Record<string, unknown>> {
  return apiAdmin<Record<string, unknown>>("/admin/reports/batch", {
    method: "POST",
    query: { start: start || undefined, end: end || undefined },
  });
}

export async function generateOkrSummary(start?: string, end?: string, includePrompt?: boolean) {
  return apiAdmin<Record<string, unknown>>("/admin/okr-summary", {
    query: {
      start: start || undefined,
      end: end || undefined,
      include_llm_prompt: includePrompt ? "true" : undefined,
    },
  });
}

export async function getTwilioTemplates(): Promise<{ templates: TwilioTemplateItem[] }> {
  return apiAdmin<{ templates: TwilioTemplateItem[] }>("/admin/messaging/templates");
}

export async function updateTwilioTemplates(templates: Partial<TwilioTemplateItem>[]) {
  return apiAdmin<Record<string, unknown>>("/admin/messaging/templates", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ templates }),
  });
}

export async function syncTwilioTemplates(): Promise<{ templates: TwilioTemplateItem[] }> {
  return apiAdmin<{ templates: TwilioTemplateItem[] }>("/admin/messaging/templates/sync", { method: "POST" });
}

export async function deleteTwilioTemplate(id: number, deleteRemote: boolean = true) {
  return apiAdmin<Record<string, unknown>>("/admin/messaging/templates/delete", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ id, delete_remote: deleteRemote }),
  });
}

export async function getMessagingSettings(): Promise<MessagingSettings> {
  return apiAdmin<MessagingSettings>("/admin/messaging/settings");
}

export async function updateMessagingSettings(payload: MessagingSettings) {
  return apiAdmin<Record<string, unknown>>("/admin/messaging/settings", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export async function getGlobalPromptSchedule(): Promise<{ items: GlobalScheduleItem[] }> {
  return apiAdmin<{ items: GlobalScheduleItem[] }>("/admin/messaging/schedule");
}

export async function updateGlobalPromptSchedule(items: GlobalScheduleItem[]) {
  return apiAdmin<Record<string, unknown>>("/admin/messaging/schedule", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ items }),
  });
}
