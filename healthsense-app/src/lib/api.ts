// Render sync marker: force fresh HealthSense app build/deploy from latest commit.
type FetchOptions = RequestInit & { query?: Record<string, string | number | undefined> };

export type AssessmentResponse = {
  user?: { id?: number; first_name?: string; surname?: string; display_name?: string };
  run?: { id?: number; finished_at?: string; combined_overall?: number };
  scores?: {
    combined?: number;
    rows?: Array<{ label?: string; value?: number; bucket?: string }>;
    by_pillar?: Record<string, number>;
  };
  pillars?: Array<{
    pillar_key?: string;
    pillar_name?: string;
    score?: number;
    bucket?: string;
    concept_scores?: Record<string, number>;
    concept_labels?: Record<string, string>;
    qa_samples?: Array<{ question?: string; answer?: string }>;
    focus_note?: string;
  }>;
  okrs?: Array<{
    pillar_key?: string;
    pillar_name?: string;
    score?: number;
    objective?: string;
    key_results?: string[];
    focus_note?: string;
  }>;
  narratives?: {
    score_html?: string;
    okr_html?: string;
    coaching_html?: string;
    score_audio_url?: string;
    okr_audio_url?: string;
    coaching_audio_url?: string;
  };
  readiness?: { score?: number; label?: string; note?: string } | null;
  readiness_breakdown?: Array<{ key?: string; label?: string; value?: number }>;
  readiness_responses?: Array<{ key?: string; question?: string; answer?: number | string }>;
  meta?: {
    reported_at?: string;
    narratives_cached?: boolean;
    narratives_source?: string;
    habit_narrative_pending?: boolean;
  };
  reports?: {
    assessment_html?: string;
    assessment_pdf?: string;
    assessment_image?: string;
  };
};

export type ProgressResponse = {
  user?: { id?: number; first_name?: string; surname?: string; display_name?: string };
  meta?: { anchor_date?: string; anchor_label?: string; is_virtual_date?: boolean; reported_at?: string };
  status_counts?: Record<string, number>;
  total_krs?: number;
  engagement?: {
    daily_streak?: number;
    active_today?: boolean;
    last_interaction_date?: string | null;
    recent_window_days?: number;
    recent_active_dates?: string[];
    source?: string;
  };
  focus?: { kr_ids?: number[]; kr_titles?: string[] };
  week_window?: { start?: string | null; end?: string | null; is_current?: boolean };
  readiness?: { score?: number; label?: string; note?: string } | null;
  programme?: {
    blocks?: Array<{
      pillar_key?: string;
      pillar_label?: string;
      label?: string;
      week_label?: string;
      week_start?: number;
      week_end?: number;
      start?: string | null;
      end?: string | null;
      bridge_days?: number;
    }>;
  };
  rows?: Array<{
    pillar?: string;
    cycle_label?: string;
    cycle_start?: string;
    cycle_end?: string;
    objective?: string;
    krs?: Array<{
      id?: number;
      description?: string;
      baseline?: number | null;
      actual?: number | null;
      target?: number | null;
      unit?: string | null;
      metric_label?: string | null;
      habit_steps?: Array<{
        id?: number;
        text?: string;
        status?: string;
        week_no?: number | null;
      }>;
    }>;
  }>;
  reports?: { progress_html?: string };
};

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

export type CoachingHistoryResponse = {
  user?: { id?: number; display_name?: string };
  items?: Array<{
    id?: number;
    ts?: string;
    type?: "podcast" | "prompt" | "dialog";
    title?: string;
    preview?: string;
    full_text?: string;
    is_truncated?: boolean;
    audio_url?: string;
    channel?: string;
    direction?: string;
    touchpoint_type?: string;
    week_no?: number | null;
  }>;
};

export type LibraryContentResponse = {
  user_id?: number;
  items?: Record<
    string,
    Array<{
      id?: number;
      pillar_key?: string;
      concept_code?: string | null;
      title?: string;
      body?: string;
      created_at?: string | null;
      podcast_url?: string | null;
      podcast_voice?: string | null;
    }>
  >;
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

export async function getAssessment(userId: string | number, runId?: string | number): Promise<AssessmentResponse> {
  return apiGet<AssessmentResponse>(`/api/v1/users/${userId}/assessment`, {
    query: { run_id: runId },
  });
}

export async function getProgress(userId: string | number, anchorDate?: string): Promise<ProgressResponse> {
  return apiGet<ProgressResponse>(`/api/v1/users/${userId}/progress`, {
    query: { anchor_date: anchorDate },
  });
}

export async function getUserStatus(userId: string | number): Promise<UserStatusResponse> {
  return apiGet<UserStatusResponse>(`/api/v1/users/${userId}/status`);
}

export async function getCoachingHistory(
  userId: string | number,
  limit?: number,
): Promise<CoachingHistoryResponse> {
  return apiGet<CoachingHistoryResponse>(`/api/v1/users/${userId}/coaching-history`, {
    query: { limit },
  });
}

export async function getLibraryContent(userId: string | number): Promise<LibraryContentResponse> {
  return apiGet<LibraryContentResponse>(`/api/v1/users/${userId}/library`);
}

export async function getBillingPlans(): Promise<BillingPlansResponse> {
  return apiGet<BillingPlansResponse>("/api/v1/billing/plans");
}
