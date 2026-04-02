type FetchOptions = RequestInit & { query?: Record<string, string | number | undefined> };

export type UserStatusResponse = {
  user?: {
    id?: number;
    first_name?: string;
    surname?: string;
    display_name?: string;
    phone?: string;
    email?: string;
    consent_given?: boolean;
    consent_at?: string;
    billing_status?: string | null;
    billing_provider?: string | null;
    last_inbound_message_at?: string | null;
  };
  active_domain?: string | null;
  latest_run?: { id?: number; finished_at?: string | null; combined_overall?: number };
  status?: "in_progress" | "completed" | "idle";
  prompt_state_override?: string | null;
  coaching_preferences?: {
    auto_prompts?: string;
    note?: string;
    voice?: string;
    schedule?: Record<string, string>;
    text_scale?: string;
    theme?: string;
    training_objective?: string;
    preferred_channel?: string;
    marketing_opt_in?: string;
  };
  onboarding?: {
    assessment_completed_at?: string | null;
    first_app_login_at?: string | null;
    assessment_reviewed_at?: string | null;
    intro_content_presented_at?: string | null;
    intro_content_listened_at?: string | null;
    intro_content_read_at?: string | null;
    intro_content_completed_at?: string | null;
    coaching_auto_enabled_at?: string | null;
  };
  intro?: {
    enabled?: boolean;
    should_show?: boolean;
    coaching_enabled?: boolean;
    content_id?: number | null;
    title?: string | null;
    message?: string | null;
    body?: string | null;
    podcast_url?: string | null;
    podcast_voice?: string | null;
    app_intro_avatar?: {
      url?: string | null;
      title?: string | null;
      script?: string | null;
      poster_url?: string | null;
    } | null;
    assessment_intro_avatar?: {
      url?: string | null;
      title?: string | null;
      script?: string | null;
      poster_url?: string | null;
    } | null;
    welcome_message_template?: string | null;
    onboarding?: {
      assessment_completed_at?: string | null;
      first_app_login_at?: string | null;
      assessment_reviewed_at?: string | null;
      intro_content_presented_at?: string | null;
      intro_content_listened_at?: string | null;
      intro_content_read_at?: string | null;
      intro_content_completed_at?: string | null;
      coaching_auto_enabled_at?: string | null;
    };
  };
  coaching_window?: {
    window_hours?: number | null;
    last_inbound_message_at?: string | null;
    hours_since_last_inbound?: number | null;
    inside_24h?: boolean;
    outside_24h?: boolean;
    continue_command?: string | null;
    continue_whatsapp_url?: string | null;
    whatsapp_number?: string | null;
  };
};

export type WearableProviderState = {
  provider?: string;
  label?: string;
  description?: string;
  availability?: string;
  supports_web_oauth?: boolean;
  partnership_required?: boolean;
  requires_native_app?: boolean;
  connectable?: boolean;
  sync_supported?: boolean;
  connected?: boolean;
  status?: string;
  note?: string | null;
  connection_id?: number | null;
  connected_at?: string | null;
  disconnected_at?: string | null;
  last_sync_at?: string | null;
  last_sync_status?: string | null;
  last_sync_error?: string | null;
  metric_days_count?: number;
  latest_metric_date?: string | null;
};

export type WearablesResponse = {
  user_id?: number;
  connected_count?: number;
  providers?: WearableProviderState[];
};

export type AppleHealthRestingHeartRateResponse = {
  provider?: string;
  connected?: boolean;
  metric_date?: string | null;
  resting_hr_bpm?: number | null;
  steps_today?: number | null;
  steps_metric_date?: string | null;
  baseline_resting_hr_bpm?: number | null;
  delta_bpm?: number | null;
  trend_status?: "optimum" | "normal" | "elevated" | null;
  trend_label?: string | null;
  synced_at?: string | null;
  available?: boolean;
  history?: Array<{
    metric_date?: string | null;
    resting_hr_bpm?: number | null;
    trend_status?: "optimum" | "normal" | "elevated" | null;
    trend_label?: string | null;
  }>;
  steps_history?: Array<{
    metric_date?: string | null;
    steps?: number | null;
  }>;
  ok?: boolean;
  sync?: {
    provider?: string;
    records_synced?: number;
    latest_metric_date?: string | null;
    connected?: boolean;
  };
};

export type PillarTrackerOption = {
  value?: number;
  label?: string;
};

export type PillarTrackerDay = {
  date?: string;
  label?: string;
  is_today?: boolean;
  complete?: boolean;
  score?: number | null;
};

export type PillarTrackerEditableDate = {
  date?: string;
  label?: string;
  is_active?: boolean;
  editable?: boolean;
};

export type PillarTrackerConceptWeekDay = {
  date?: string;
  label?: string;
  is_today?: boolean;
  is_active?: boolean;
  value_label?: string | null;
  score?: number | null;
  target_reached?: boolean | null;
  target_met?: boolean | null;
  daily_status?: "success" | "warning" | "danger" | null;
  daily_positive?: boolean | null;
  okr_on_track?: boolean | null;
};

export type PillarTrackerConcept = {
  concept_key?: string;
  label?: string;
  helper?: string;
  target_label?: string | null;
  target_source?: string | null;
  target_period?: string | null;
  target_unit?: string | null;
  target_value?: number | null;
  options?: PillarTrackerOption[];
  value?: number | null;
  value_label?: string | null;
  score?: number | null;
  target_reached?: boolean | null;
  target_met?: boolean | null;
  daily_status?: "success" | "warning" | "danger" | null;
  daily_positive?: boolean | null;
  okr_on_track?: boolean | null;
  okr_status_label?: string | null;
  okr_status_detail?: string | null;
  streak_days?: number | null;
  week?: PillarTrackerConceptWeekDay[];
};

export type PillarTrackerPillar = {
  pillar_key?: string;
  label?: string;
  score?: number | null;
  tracker_score?: number | null;
  baseline_score?: number | null;
  source?: string | null;
  completed_days_count?: number | null;
  streak_days?: number | null;
  today_complete?: boolean;
  week_start?: string | null;
  week_end?: string | null;
  today?: string | null;
  active_date?: string | null;
  active_label?: string | null;
  current_date?: string | null;
  yesterday_catchup_available?: boolean;
  is_editable?: boolean;
  is_current_week?: boolean;
};

export type PillarTrackerSummaryResponse = {
  week?: {
    anchor_date?: string;
    start?: string;
    end?: string;
  };
  today?: string | null;
  today_complete?: boolean;
  today_completed_pillars_count?: number | null;
  total_pillars?: number | null;
  pillars?: PillarTrackerPillar[];
};

export type PillarTrackerDetailResponse = {
  pillar?: PillarTrackerPillar;
  days?: PillarTrackerDay[];
  concepts?: PillarTrackerConcept[];
  editable_dates?: PillarTrackerEditableDate[];
};

export type WeeklyObjectiveOption = {
  value?: number | string | null;
  label?: string;
};

export type WeeklyObjectiveConcept = {
  concept_key?: string;
  label?: string;
  helper?: string;
  metric_label?: string | null;
  unit?: string | null;
  unit_label?: string | null;
  target_direction?: string | null;
  target_source?: string | null;
  target_label?: string | null;
  selected_value?: number | null;
  options?: WeeklyObjectiveOption[];
};

export type WeeklyObjectivePillarConfig = {
  pillar_key?: string;
  label?: string;
  objective?: string | null;
  concept_count?: number | null;
  configured_count?: number | null;
  concepts?: WeeklyObjectiveConcept[];
};

export type WeeklyObjectiveWellbeingItem = {
  key?: string;
  label?: string;
  helper?: string | null;
  value?: string | null;
  options?: WeeklyObjectiveOption[];
};

export type WeeklyObjectivesResponse = {
  user_id?: number;
  week?: {
    anchor_date?: string | null;
    start?: string | null;
    end?: string | null;
  };
  sections?: Array<{
    key?: string;
    label?: string;
    type?: "pillar" | "wellbeing" | string;
    configured_count?: number | null;
    total_count?: number | null;
  }>;
  pillars?: WeeklyObjectivePillarConfig[];
  wellbeing?: {
    title?: string | null;
    configured_count?: number | null;
    items?: WeeklyObjectiveWellbeingItem[];
  } | null;
  coach_home_refresh?: {
    queued?: boolean;
    execution?: string | null;
    job_id?: number | null;
    created?: boolean;
  } | null;
};

export type DailyHabitPlanItem = {
  id?: string | null;
  moment_key?: string | null;
  moment_label?: string | null;
  title?: string | null;
  detail?: string | null;
  concept_key?: string | null;
  concept_label?: string | null;
  pillar_key?: string | null;
  pillar_label?: string | null;
  selected?: boolean;
};

export type DailyHabitPlanConcept = {
  pillar_key?: string | null;
  pillar_label?: string | null;
  concept_key?: string | null;
  label?: string | null;
  helper?: string | null;
  target_label?: string | null;
  signal?: string | null;
  latest_value?: string | null;
  score?: number | null;
  is_selected?: boolean;
};

export type DailyHabitPlanAskSuggestion = {
  label?: string | null;
  text?: string | null;
};

export type DailyHabitPlanResponse = {
  user_id?: number;
  plan_date?: string | null;
  pillar_key?: string | null;
  pillar_label?: string | null;
  title?: string | null;
  summary?: string | null;
  habits?: DailyHabitPlanItem[];
  options?: DailyHabitPlanItem[];
  ask_suggestions?: DailyHabitPlanAskSuggestion[];
  available_concepts?: DailyHabitPlanConcept[];
  selected_concept_key?: string | null;
  selected_concept_label?: string | null;
  default_habits_view?: "selected_habits" | "suggestions" | null;
  source?: string | null;
  generated_at?: string | null;
};

export type CoachInsightContent = {
  id?: number;
  pillar_key?: string | null;
  concept_code?: string | null;
  title?: string | null;
  body?: string | null;
  podcast_url?: string | null;
  podcast_voice?: string | null;
  avatar?: {
    url?: string | null;
    title?: string | null;
    script?: string | null;
    poster_url?: string | null;
    character?: string | null;
    style?: string | null;
    voice?: string | null;
    status?: string | null;
    job_id?: string | null;
    error?: string | null;
    generated_at?: string | null;
    source?: string | null;
    summary_url?: string | null;
  } | null;
  created_at?: string | null;
};

export type CoachInsightResponse = {
  user_id?: number;
  insight_date?: string | null;
  pillar_key?: string | null;
  pillar_label?: string | null;
  concept_key?: string | null;
  concept_label?: string | null;
  available_concepts?: Array<{
    pillar_key?: string | null;
    pillar_label?: string | null;
    concept_key?: string | null;
    label?: string | null;
    is_selected?: boolean;
  }>;
  matched_by?: string | null;
  content?: CoachInsightContent | null;
};

export type BillingPriceOption = {
  id?: number;
  plan_id?: number;
  currency?: string;
  amount_minor?: number;
  currency_exponent?: number;
  interval?: string;
  interval_count?: number;
  is_default?: boolean;
};

export type BillingPlanOption = {
  id?: number;
  code?: string;
  name?: string;
  description?: string | null;
  prices?: BillingPriceOption[];
};

export type BillingPlansResponse = {
  plans?: BillingPlanOption[];
  default_price_id?: number | null;
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
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 600000);
  const sessionToken = await getSessionToken();
  const headers: Record<string, string> = {
    ...(options.headers || {}),
  } as Record<string, string>;
  if (sessionToken) {
    headers["X-Session-Token"] = sessionToken;
  } else if (process.env.ADMIN_API_TOKEN && process.env.ADMIN_USER_ID) {
    Object.assign(headers, getAdminHeaders());
  }
  const res = await fetch(url, {
    ...options,
    headers,
    cache: "no-store",
    signal: controller.signal,
  }).finally(() => clearTimeout(timeout));
  if (!res.ok) {
    if (
      res.status === 401 &&
      !headers["X-Admin-Token"] &&
      process.env.NODE_ENV !== "production" &&
      process.env.ADMIN_API_TOKEN &&
      process.env.ADMIN_USER_ID
    ) {
      const retryHeaders: Record<string, string> = {
        ...(options.headers || {}),
        ...getAdminHeaders(),
      } as Record<string, string>;
      const retry = await fetch(url, {
        ...options,
        headers: retryHeaders,
        cache: "no-store",
        signal: controller.signal,
      }).finally(() => clearTimeout(timeout));
      if (retry.ok) {
        return retry.json() as Promise<T>;
      }
      const retryText = await retry.text().catch(() => "");
      throw new Error(`API ${retry.status} ${retry.statusText}: ${retryText}`);
    }
    const text = await res.text().catch(() => "");
    throw new Error(`API ${res.status} ${res.statusText}: ${text}`);
  }
  return res.json() as Promise<T>;
}

export async function getUserStatus(userId: string | number): Promise<UserStatusResponse> {
  return apiGet<UserStatusResponse>(`/api/v1/users/${userId}/status`);
}

export async function getWearables(userId: string | number): Promise<WearablesResponse> {
  return apiGet<WearablesResponse>(`/api/v1/users/${userId}/wearables`);
}

export async function getPillarTrackerSummary(
  userId: string | number,
  anchorDate?: string,
): Promise<PillarTrackerSummaryResponse> {
  return apiGet<PillarTrackerSummaryResponse>(`/api/v1/users/${userId}/pillar-tracker`, {
    query: { anchor_date: anchorDate },
  });
}

export async function getCoachInsight(
  userId: string | number,
  anchorDate?: string,
  conceptKey?: string,
): Promise<CoachInsightResponse> {
  return apiGet<CoachInsightResponse>(`/api/v1/users/${userId}/coach-insight`, {
    query: { anchor_date: anchorDate, concept_key: conceptKey },
  });
}

export async function getBillingPlans(): Promise<BillingPlansResponse> {
  return apiGet<BillingPlansResponse>("/api/v1/billing/plans");
}
