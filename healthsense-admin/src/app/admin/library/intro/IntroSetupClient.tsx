"use client";

import { useActionState, useEffect, useMemo, useState } from "react";
import type {
  AssessmentIntroLibrarySettings,
  AssessmentIntroAvatarSettings,
  ContentPromptTemplateSummary,
  IntroLibrarySettings,
} from "@/lib/api";
import {
  generateAppIntroAvatarAction,
  generateAppHelpAvatarAction,
  generateAssessmentIntroAvatarAction,
  generateIntroDraftAction,
  generateIntroAvatarAction,
  refreshAppIntroAvatarAction,
  refreshAppHelpAvatarAction,
  refreshAssessmentIntroAvatarAction,
  refreshIntroAvatarAction,
  saveCoachingSettingsAction,
  saveAssessmentIntroSettingsAction,
  saveIntroSettingsAction,
  type AssessmentIntroSaveState,
  type IntroAvatarState,
  type IntroGenerationState,
  type IntroSaveState,
} from "./actions";

type IntroSetupClientProps = {
  appIntro: IntroLibrarySettings;
  assessmentIntro: AssessmentIntroLibrarySettings;
  templates: ContentPromptTemplateSummary[];
};

type IntroSetupTab = "app" | "coaching" | "assessment";
type IntroHelpAvatarSlot = "habits" | "insight" | "ask" | "daily_tracking";
type IntroHelpAvatarFieldState = {
  url: string;
  title: string;
  script: string;
  posterUrl: string;
  character: string;
  style: string;
  voice: string;
  status: string;
  jobId: string;
  error: string;
  generatedAt: string;
  summaryUrl: string;
};
type IntroHelpAvatarStateMap = Record<IntroHelpAvatarSlot, IntroHelpAvatarFieldState>;

const emptyGenerationState: IntroGenerationState = { ok: false, error: null };
const emptySaveState: IntroSaveState = { ok: false, error: null };
const emptyAssessmentSaveState: AssessmentIntroSaveState = { ok: false, error: null };
const emptyAvatarState: IntroAvatarState = { ok: false, error: null };
const INTRO_HELP_AVATAR_CONFIGS: Array<{
  slot: IntroHelpAvatarSlot;
  fieldPrefix: string;
  label: string;
  description: string;
  defaultTitle: string;
}> = [
  {
    slot: "habits",
    fieldPrefix: "app_habits_avatar",
    label: "Habits help video",
    description: "Shown from the HealthSense intro modal when the user wants a quick walkthrough of habits.",
    defaultTitle: "Habits",
  },
  {
    slot: "insight",
    fieldPrefix: "app_insight_avatar",
    label: "Insight help video",
    description: "Shown from the HealthSense intro modal for the Insight area.",
    defaultTitle: "Insight",
  },
  {
    slot: "ask",
    fieldPrefix: "app_ask_avatar",
    label: "Ask help video",
    description: "Shown from the HealthSense intro modal for the Ask coaching area.",
    defaultTitle: "Ask",
  },
  {
    slot: "daily_tracking",
    fieldPrefix: "app_daily_tracking_avatar",
    label: "Daily tracking help video",
    description: "Shown from the HealthSense intro modal for daily pillar tracking.",
    defaultTitle: "Daily tracking",
  },
];

const voiceOptions = [
  { value: "", label: "Default" },
  { value: "alloy", label: "Alloy" },
  { value: "breeze", label: "Breeze" },
  { value: "echo", label: "Echo" },
  { value: "verse", label: "Verse" },
  { value: "shimmer", label: "Shimmer" },
  { value: "onyx", label: "Onyx" },
  { value: "coral", label: "Coral" },
  { value: "amber", label: "Amber" },
];

const modelOptions = [
  "",
  "gpt-5.2-pro",
  "gpt-5.2",
  "gpt-5.1",
  "gpt-5-mini",
  "gpt-5-nano",
  "gpt-4.1",
  "gpt-4.1-mini",
  "gpt-4.1-nano",
  "gpt-4o",
  "gpt-4o-mini",
  "o3",
  "o4-mini",
  "gpt-3.5-turbo",
];

const assessmentAvatarCharacterOptions = [
  { value: "harry", label: "Harry" },
  { value: "jeff", label: "Jeff" },
  { value: "lisa", label: "Lisa" },
  { value: "lori", label: "Lori" },
  { value: "max", label: "Max" },
  { value: "meg", label: "Meg" },
];

const assessmentAvatarStylesByCharacter: Record<string, Array<{ value: string; label: string }>> = {
  harry: [
    { value: "business", label: "Business" },
    { value: "casual", label: "Casual" },
    { value: "youthful", label: "Youthful" },
  ],
  jeff: [
    { value: "business", label: "Business" },
    { value: "formal", label: "Formal" },
  ],
  lisa: [
    { value: "casual-sitting", label: "Casual sitting" },
    { value: "graceful-sitting", label: "Graceful sitting" },
    { value: "graceful-standing", label: "Graceful standing" },
    { value: "technical-sitting", label: "Technical sitting" },
    { value: "technical-standing", label: "Technical standing" },
  ],
  lori: [
    { value: "casual", label: "Casual" },
    { value: "graceful", label: "Graceful" },
    { value: "formal", label: "Formal" },
  ],
  max: [
    { value: "business", label: "Business" },
    { value: "casual", label: "Casual" },
    { value: "formal", label: "Formal" },
  ],
  meg: [
    { value: "business", label: "Business" },
    { value: "casual", label: "Casual" },
    { value: "formal", label: "Formal" },
  ],
};

const assessmentAvatarVoiceOptions = [
  { value: "en-GB-LibbyNeural", label: "Libby · UK English" },
  { value: "en-GB-SoniaNeural", label: "Sonia · UK English" },
  { value: "en-GB-RyanNeural", label: "Ryan · UK English" },
  { value: "en-GB-ThomasNeural", label: "Thomas · UK English" },
  { value: "en-US-AvaNeural", label: "Ava · US English" },
  { value: "en-US-AriaNeural", label: "Aria · US English" },
  { value: "en-US-JennyNeural", label: "Jenny · US English" },
  { value: "en-US-GuyNeural", label: "Guy · US English" },
];

function withCurrentOption(
  options: Array<{ value: string; label: string }>,
  currentValue: string,
): Array<{ value: string; label: string }> {
  const value = String(currentValue || "").trim();
  if (!value) return options;
  if (options.some((option) => option.value === value)) return options;
  return [{ value, label: `${value} (Current)` }, ...options];
}

function introHelpAvatarStateFromSettings(
  settings: AssessmentIntroAvatarSettings | null | undefined,
  fallbackTitle: string,
): IntroHelpAvatarFieldState {
  return {
    url: settings?.url || "",
    title: settings?.title || fallbackTitle,
    script: settings?.script || "",
    posterUrl: settings?.poster_url || "",
    character: settings?.character || "lisa",
    style: settings?.style || "graceful-sitting",
    voice: settings?.voice || "en-GB-SoniaNeural",
    status: settings?.status || "",
    jobId: settings?.job_id || "",
    error: settings?.error || "",
    generatedAt: settings?.generated_at || "",
    summaryUrl: settings?.summary_url || "",
  };
}

function introHelpAvatarMapFromIntro(intro: IntroLibrarySettings): IntroHelpAvatarStateMap {
  return {
    habits: introHelpAvatarStateFromSettings(intro.app_habits_avatar, "Habits"),
    insight: introHelpAvatarStateFromSettings(intro.app_insight_avatar, "Insight"),
    ask: introHelpAvatarStateFromSettings(intro.app_ask_avatar, "Ask"),
    daily_tracking: introHelpAvatarStateFromSettings(intro.app_daily_tracking_avatar, "Daily tracking"),
  };
}

function SectionHeading({
  label,
  description,
}: {
  label: string;
  description: string;
}) {
  return (
    <div>
      <p className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">{label}</p>
      <p className="mt-2 text-sm text-[#6b6257]">{description}</p>
    </div>
  );
}

function TabButton({
  active,
  label,
  onClick,
}: {
  active: boolean;
  label: string;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={[
        "rounded-full border px-4 py-2 text-xs uppercase tracking-[0.2em] transition",
        active
          ? "border-[var(--accent)] bg-[var(--accent)] text-white"
          : "border-[#e7e1d6] bg-white text-[#6b6257]",
      ].join(" ")}
    >
      {label}
    </button>
  );
}

export default function IntroSetupClient({
  appIntro,
  assessmentIntro,
  templates,
}: IntroSetupClientProps) {
  const [generationState, generationAction, generating] = useActionState(
    generateIntroDraftAction,
    emptyGenerationState,
  );
  const [saveState, saveAction, saving] = useActionState(
    saveIntroSettingsAction,
    emptySaveState,
  );
  const [appAvatarGenerationState, appAvatarGenerationAction, generatingAppAvatar] = useActionState(
    generateAppIntroAvatarAction,
    emptyAvatarState,
  );
  const [appAvatarRefreshState, appAvatarRefreshAction, refreshingAppAvatar] = useActionState(
    refreshAppIntroAvatarAction,
    emptyAvatarState,
  );
  const [helpAvatarGenerationState, helpAvatarGenerationAction, generatingHelpAvatar] = useActionState(
    generateAppHelpAvatarAction,
    emptyAvatarState,
  );
  const [helpAvatarRefreshState, helpAvatarRefreshAction, refreshingHelpAvatar] = useActionState(
    refreshAppHelpAvatarAction,
    emptyAvatarState,
  );
  const [coachSaveState, coachSaveAction, savingCoach] = useActionState(
    saveCoachingSettingsAction,
    emptySaveState,
  );
  const [assessmentSaveState, assessmentSaveAction, savingAssessment] = useActionState(
    saveAssessmentIntroSettingsAction,
    emptyAssessmentSaveState,
  );
  const [coachAvatarGenerationState, coachAvatarGenerationAction, generatingCoachAvatar] = useActionState(
    generateIntroAvatarAction,
    emptyAvatarState,
  );
  const [coachAvatarRefreshState, coachAvatarRefreshAction, refreshingCoachAvatar] = useActionState(
    refreshIntroAvatarAction,
    emptyAvatarState,
  );
  const [assessmentAvatarGenerationState, assessmentAvatarGenerationAction, generatingAssessmentAvatar] = useActionState(
    generateAssessmentIntroAvatarAction,
    emptyAvatarState,
  );
  const [assessmentAvatarRefreshState, assessmentAvatarRefreshAction, refreshingAssessmentAvatar] = useActionState(
    refreshAssessmentIntroAvatarAction,
    emptyAvatarState,
  );

  const [active, setActive] = useState(Boolean(appIntro.active));
  const [title, setTitle] = useState(appIntro.title || "Welcome to HealthSense");
  const [welcomeTemplate, setWelcomeTemplate] = useState(
    appIntro.welcome_message_template ||
      "{first_name}, Welcome to HealthSense please listen to our introductory podcast to get started on your journey.",
  );
  const [body, setBody] = useState(appIntro.body || "");
  const [podcastUrl, setPodcastUrl] = useState(appIntro.podcast_url || "");
  const [podcastVoice, setPodcastVoice] = useState(appIntro.podcast_voice || "");
  const [appIntroAvatarUrl, setAppIntroAvatarUrl] = useState(
    appIntro.app_intro_avatar?.url || "",
  );
  const [appIntroAvatarTitle, setAppIntroAvatarTitle] = useState(
    appIntro.app_intro_avatar?.title || "Welcome to HealthSense",
  );
  const [appIntroAvatarScript, setAppIntroAvatarScript] = useState(
    appIntro.app_intro_avatar?.script || "",
  );
  const [appIntroAvatarPosterUrl, setAppIntroAvatarPosterUrl] = useState(
    appIntro.app_intro_avatar?.poster_url || "",
  );
  const [appIntroAvatarCharacter, setAppIntroAvatarCharacter] = useState(
    appIntro.app_intro_avatar?.character || "lisa",
  );
  const [appIntroAvatarStyle, setAppIntroAvatarStyle] = useState(
    appIntro.app_intro_avatar?.style || "graceful-sitting",
  );
  const [appIntroAvatarVoice, setAppIntroAvatarVoice] = useState(
    appIntro.app_intro_avatar?.voice || "en-GB-SoniaNeural",
  );
  const [appIntroAvatarStatus, setAppIntroAvatarStatus] = useState(
    appIntro.app_intro_avatar?.status || "",
  );
  const [appIntroAvatarJobId, setAppIntroAvatarJobId] = useState(
    appIntro.app_intro_avatar?.job_id || "",
  );
  const [appIntroAvatarError, setAppIntroAvatarError] = useState(
    appIntro.app_intro_avatar?.error || "",
  );
  const [appIntroAvatarGeneratedAt, setAppIntroAvatarGeneratedAt] = useState(
    appIntro.app_intro_avatar?.generated_at || "",
  );
  const [appIntroAvatarSummaryUrl, setAppIntroAvatarSummaryUrl] = useState(
    appIntro.app_intro_avatar?.summary_url || "",
  );
  const [helpAvatars, setHelpAvatars] = useState<IntroHelpAvatarStateMap>(() =>
    introHelpAvatarMapFromIntro(appIntro),
  );
  const [activeHelpAvatarSlot, setActiveHelpAvatarSlot] = useState<IntroHelpAvatarSlot | null>(null);
  const [coachProductAvatarUrl, setCoachProductAvatarUrl] = useState(
    appIntro.coach_product_avatar?.url || "",
  );
  const [coachProductAvatarTitle, setCoachProductAvatarTitle] = useState(
    appIntro.coach_product_avatar?.title || "How HealthSense works",
  );
  const [coachProductAvatarScript, setCoachProductAvatarScript] = useState(
    appIntro.coach_product_avatar?.script || "",
  );
  const [coachProductAvatarPosterUrl, setCoachProductAvatarPosterUrl] = useState(
    appIntro.coach_product_avatar?.poster_url || "",
  );
  const [coachProductAvatarCharacter, setCoachProductAvatarCharacter] = useState(
    appIntro.coach_product_avatar?.character || "lisa",
  );
  const [coachProductAvatarStyle, setCoachProductAvatarStyle] = useState(
    appIntro.coach_product_avatar?.style || "graceful-sitting",
  );
  const [coachProductAvatarVoice, setCoachProductAvatarVoice] = useState(
    appIntro.coach_product_avatar?.voice || "en-GB-SoniaNeural",
  );
  const [coachProductAvatarStatus, setCoachProductAvatarStatus] = useState(
    appIntro.coach_product_avatar?.status || "",
  );
  const [coachProductAvatarJobId, setCoachProductAvatarJobId] = useState(
    appIntro.coach_product_avatar?.job_id || "",
  );
  const [coachProductAvatarError, setCoachProductAvatarError] = useState(
    appIntro.coach_product_avatar?.error || "",
  );
  const [coachProductAvatarGeneratedAt, setCoachProductAvatarGeneratedAt] = useState(
    appIntro.coach_product_avatar?.generated_at || "",
  );
  const [coachProductAvatarSummaryUrl, setCoachProductAvatarSummaryUrl] = useState(
    appIntro.coach_product_avatar?.summary_url || "",
  );

  const [assessmentIntroActive, setAssessmentIntroActive] = useState(Boolean(assessmentIntro.active));
  const [assessmentIntroTitle, setAssessmentIntroTitle] = useState(
    assessmentIntro.title || "Assessment intro",
  );
  const [assessmentIntroAvatarUrl, setAssessmentIntroAvatarUrl] = useState(
    assessmentIntro.assessment_intro_avatar?.url || "",
  );
  const [assessmentIntroAvatarTitle, setAssessmentIntroAvatarTitle] = useState(
    assessmentIntro.assessment_intro_avatar?.title || "Assessment introduction",
  );
  const [assessmentIntroAvatarScript, setAssessmentIntroAvatarScript] = useState(
    assessmentIntro.assessment_intro_avatar?.script || "",
  );
  const [assessmentIntroAvatarPosterUrl, setAssessmentIntroAvatarPosterUrl] = useState(
    assessmentIntro.assessment_intro_avatar?.poster_url || "",
  );
  const [assessmentIntroAvatarCharacter, setAssessmentIntroAvatarCharacter] = useState(
    assessmentIntro.assessment_intro_avatar?.character || "lisa",
  );
  const [assessmentIntroAvatarStyle, setAssessmentIntroAvatarStyle] = useState(
    assessmentIntro.assessment_intro_avatar?.style || "graceful-sitting",
  );
  const [assessmentIntroAvatarVoice, setAssessmentIntroAvatarVoice] = useState(
    assessmentIntro.assessment_intro_avatar?.voice || "en-GB-SoniaNeural",
  );
  const [assessmentIntroAvatarStatus, setAssessmentIntroAvatarStatus] = useState(
    assessmentIntro.assessment_intro_avatar?.status || "",
  );
  const [assessmentIntroAvatarJobId, setAssessmentIntroAvatarJobId] = useState(
    assessmentIntro.assessment_intro_avatar?.job_id || "",
  );
  const [assessmentIntroAvatarError, setAssessmentIntroAvatarError] = useState(
    assessmentIntro.assessment_intro_avatar?.error || "",
  );
  const [assessmentIntroAvatarGeneratedAt, setAssessmentIntroAvatarGeneratedAt] = useState(
    assessmentIntro.assessment_intro_avatar?.generated_at || "",
  );
  const [assessmentIntroAvatarSummaryUrl, setAssessmentIntroAvatarSummaryUrl] = useState(
    assessmentIntro.assessment_intro_avatar?.summary_url || "",
  );
  const [activeTab, setActiveTab] = useState<IntroSetupTab>("assessment");

  const generatedPayload = useMemo(
    () => (((generationState.result?.result as Record<string, unknown> | undefined) || {}) as Record<string, unknown>),
    [generationState.result],
  );
  const generatedLlm = useMemo(
    () => ((generatedPayload.llm || {}) as Record<string, unknown>),
    [generatedPayload],
  );
  const generatedText = String(generatedLlm.content || "").trim();
  const generatedPodcastUrl = String(generatedPayload.podcast_url || "").trim();
  const generatedPodcastVoice = String(generatedPayload.podcast_voice || "").trim();
  const assessmentCharacterOptions = useMemo(
    () => withCurrentOption(assessmentAvatarCharacterOptions, assessmentIntroAvatarCharacter),
    [assessmentIntroAvatarCharacter],
  );
  const appCharacterOptions = useMemo(
    () => withCurrentOption(assessmentAvatarCharacterOptions, appIntroAvatarCharacter),
    [appIntroAvatarCharacter],
  );
  const coachCharacterOptions = useMemo(
    () => withCurrentOption(assessmentAvatarCharacterOptions, coachProductAvatarCharacter),
    [coachProductAvatarCharacter],
  );
  const appStyleOptions = useMemo(() => {
    const key = String(appIntroAvatarCharacter || "").trim().toLowerCase();
    const options = assessmentAvatarStylesByCharacter[key] || [];
    return withCurrentOption(options, appIntroAvatarStyle);
  }, [appIntroAvatarCharacter, appIntroAvatarStyle]);
  const assessmentStyleOptions = useMemo(() => {
    const key = String(assessmentIntroAvatarCharacter || "").trim().toLowerCase();
    const options = assessmentAvatarStylesByCharacter[key] || [];
    return withCurrentOption(options, assessmentIntroAvatarStyle);
  }, [assessmentIntroAvatarCharacter, assessmentIntroAvatarStyle]);
  const coachStyleOptions = useMemo(() => {
    const key = String(coachProductAvatarCharacter || "").trim().toLowerCase();
    const options = assessmentAvatarStylesByCharacter[key] || [];
    return withCurrentOption(options, coachProductAvatarStyle);
  }, [coachProductAvatarCharacter, coachProductAvatarStyle]);
  const assessmentVoiceOptions = useMemo(
    () => withCurrentOption(assessmentAvatarVoiceOptions, assessmentIntroAvatarVoice),
    [assessmentIntroAvatarVoice],
  );
  const appVoiceOptions = useMemo(
    () => withCurrentOption(assessmentAvatarVoiceOptions, appIntroAvatarVoice),
    [appIntroAvatarVoice],
  );
  const coachVoiceOptions = useMemo(
    () => withCurrentOption(assessmentAvatarVoiceOptions, coachProductAvatarVoice),
    [coachProductAvatarVoice],
  );
  const helpAvatarConfigBySlot = useMemo(
    () =>
      Object.fromEntries(
        INTRO_HELP_AVATAR_CONFIGS.map((config) => [config.slot, config]),
      ) as Record<IntroHelpAvatarSlot, (typeof INTRO_HELP_AVATAR_CONFIGS)[number]>,
    [],
  );

  const updateHelpAvatarField = (
    slot: IntroHelpAvatarSlot,
    field: keyof IntroHelpAvatarFieldState,
    value: string,
  ) => {
    setHelpAvatars((current) => ({
      ...current,
      [slot]: {
        ...current[slot],
        [field]: value,
      },
    }));
  };

  const updateHelpAvatarCharacter = (slot: IntroHelpAvatarSlot, value: string) => {
    const key = String(value || "").trim().toLowerCase();
    const validStyles = assessmentAvatarStylesByCharacter[key] || [];
    setHelpAvatars((current) => {
      const nextStyle = validStyles.some((option) => option.value === current[slot].style)
        ? current[slot].style
        : validStyles[0]?.value || current[slot].style;
      return {
        ...current,
        [slot]: {
          ...current[slot],
          character: value,
          style: nextStyle,
        },
      };
    });
  };

  /* eslint-disable react-hooks/set-state-in-effect */
  useEffect(() => {
    if (!generationState.ok) return;
    if (generatedText) setBody(generatedText);
    if (generatedPodcastUrl) setPodcastUrl(generatedPodcastUrl);
    if (generatedPodcastVoice) setPodcastVoice(generatedPodcastVoice);
  }, [generationState.ok, generatedText, generatedPodcastUrl, generatedPodcastVoice]);

  useEffect(() => {
    setActive(Boolean(appIntro.active));
    setTitle(appIntro.title || "Welcome to HealthSense");
    setWelcomeTemplate(
      appIntro.welcome_message_template ||
        "{first_name}, Welcome to HealthSense please listen to our introductory podcast to get started on your journey.",
    );
    setBody(appIntro.body || "");
    setPodcastUrl(appIntro.podcast_url || "");
    setPodcastVoice(appIntro.podcast_voice || "");
    setAppIntroAvatarUrl(appIntro.app_intro_avatar?.url || "");
    setAppIntroAvatarTitle(appIntro.app_intro_avatar?.title || "Welcome to HealthSense");
    setAppIntroAvatarScript(appIntro.app_intro_avatar?.script || "");
    setAppIntroAvatarPosterUrl(appIntro.app_intro_avatar?.poster_url || "");
    setAppIntroAvatarCharacter(appIntro.app_intro_avatar?.character || "lisa");
    setAppIntroAvatarStyle(appIntro.app_intro_avatar?.style || "graceful-sitting");
    setAppIntroAvatarVoice(appIntro.app_intro_avatar?.voice || "en-GB-SoniaNeural");
    setAppIntroAvatarStatus(appIntro.app_intro_avatar?.status || "");
    setAppIntroAvatarJobId(appIntro.app_intro_avatar?.job_id || "");
    setAppIntroAvatarError(appIntro.app_intro_avatar?.error || "");
    setAppIntroAvatarGeneratedAt(appIntro.app_intro_avatar?.generated_at || "");
    setAppIntroAvatarSummaryUrl(appIntro.app_intro_avatar?.summary_url || "");
    setHelpAvatars(introHelpAvatarMapFromIntro(appIntro));
    setCoachProductAvatarUrl(appIntro.coach_product_avatar?.url || "");
    setCoachProductAvatarTitle(appIntro.coach_product_avatar?.title || "How HealthSense works");
    setCoachProductAvatarScript(appIntro.coach_product_avatar?.script || "");
    setCoachProductAvatarPosterUrl(appIntro.coach_product_avatar?.poster_url || "");
    setCoachProductAvatarCharacter(appIntro.coach_product_avatar?.character || "lisa");
    setCoachProductAvatarStyle(appIntro.coach_product_avatar?.style || "graceful-sitting");
    setCoachProductAvatarVoice(appIntro.coach_product_avatar?.voice || "en-GB-SoniaNeural");
    setCoachProductAvatarStatus(appIntro.coach_product_avatar?.status || "");
    setCoachProductAvatarJobId(appIntro.coach_product_avatar?.job_id || "");
    setCoachProductAvatarError(appIntro.coach_product_avatar?.error || "");
    setCoachProductAvatarGeneratedAt(appIntro.coach_product_avatar?.generated_at || "");
    setCoachProductAvatarSummaryUrl(appIntro.coach_product_avatar?.summary_url || "");
  }, [appIntro]);

  useEffect(() => {
    setAssessmentIntroActive(Boolean(assessmentIntro.active));
    setAssessmentIntroTitle(assessmentIntro.title || "Assessment intro");
    setAssessmentIntroAvatarUrl(assessmentIntro.assessment_intro_avatar?.url || "");
    setAssessmentIntroAvatarTitle(
      assessmentIntro.assessment_intro_avatar?.title || "Assessment introduction",
    );
    setAssessmentIntroAvatarScript(assessmentIntro.assessment_intro_avatar?.script || "");
    setAssessmentIntroAvatarPosterUrl(assessmentIntro.assessment_intro_avatar?.poster_url || "");
    setAssessmentIntroAvatarCharacter(assessmentIntro.assessment_intro_avatar?.character || "lisa");
    setAssessmentIntroAvatarStyle(
      assessmentIntro.assessment_intro_avatar?.style || "graceful-sitting",
    );
    setAssessmentIntroAvatarVoice(
      assessmentIntro.assessment_intro_avatar?.voice || "en-GB-SoniaNeural",
    );
    setAssessmentIntroAvatarStatus(assessmentIntro.assessment_intro_avatar?.status || "");
    setAssessmentIntroAvatarJobId(assessmentIntro.assessment_intro_avatar?.job_id || "");
    setAssessmentIntroAvatarError(assessmentIntro.assessment_intro_avatar?.error || "");
    setAssessmentIntroAvatarGeneratedAt(
      assessmentIntro.assessment_intro_avatar?.generated_at || "",
    );
    setAssessmentIntroAvatarSummaryUrl(
      assessmentIntro.assessment_intro_avatar?.summary_url || "",
    );
  }, [
    assessmentIntro.active,
    assessmentIntro.assessment_intro_avatar,
    assessmentIntro.title,
    assessmentIntro.updated_at,
  ]);

  useEffect(() => {
    const result =
      saveState.result && typeof saveState.result === "object"
        ? (saveState.result as IntroLibrarySettings)
        : null;
    if (!result) return;
    setActive(Boolean(result.active));
    setTitle(result.title || "Welcome to HealthSense");
    setWelcomeTemplate(
      result.welcome_message_template ||
        "{first_name}, Welcome to HealthSense please listen to our introductory podcast to get started on your journey.",
    );
    setBody(result.body || "");
    setPodcastUrl(result.podcast_url || "");
    setPodcastVoice(result.podcast_voice || "");
    setAppIntroAvatarUrl(result.app_intro_avatar?.url || "");
    setAppIntroAvatarTitle(result.app_intro_avatar?.title || "Welcome to HealthSense");
    setAppIntroAvatarScript(result.app_intro_avatar?.script || "");
    setAppIntroAvatarPosterUrl(result.app_intro_avatar?.poster_url || "");
    setAppIntroAvatarCharacter(result.app_intro_avatar?.character || "lisa");
    setAppIntroAvatarStyle(result.app_intro_avatar?.style || "graceful-sitting");
    setAppIntroAvatarVoice(result.app_intro_avatar?.voice || "en-GB-SoniaNeural");
    setAppIntroAvatarStatus(result.app_intro_avatar?.status || "");
    setAppIntroAvatarJobId(result.app_intro_avatar?.job_id || "");
    setAppIntroAvatarError(result.app_intro_avatar?.error || "");
    setAppIntroAvatarGeneratedAt(result.app_intro_avatar?.generated_at || "");
    setAppIntroAvatarSummaryUrl(result.app_intro_avatar?.summary_url || "");
    setHelpAvatars(introHelpAvatarMapFromIntro(result));
    setCoachProductAvatarUrl(result.coach_product_avatar?.url || "");
    setCoachProductAvatarTitle(result.coach_product_avatar?.title || "How HealthSense works");
    setCoachProductAvatarScript(result.coach_product_avatar?.script || "");
    setCoachProductAvatarPosterUrl(result.coach_product_avatar?.poster_url || "");
    setCoachProductAvatarCharacter(result.coach_product_avatar?.character || "lisa");
    setCoachProductAvatarStyle(result.coach_product_avatar?.style || "graceful-sitting");
    setCoachProductAvatarVoice(result.coach_product_avatar?.voice || "en-GB-SoniaNeural");
    setCoachProductAvatarStatus(result.coach_product_avatar?.status || "");
    setCoachProductAvatarJobId(result.coach_product_avatar?.job_id || "");
    setCoachProductAvatarError(result.coach_product_avatar?.error || "");
    setCoachProductAvatarGeneratedAt(result.coach_product_avatar?.generated_at || "");
    setCoachProductAvatarSummaryUrl(result.coach_product_avatar?.summary_url || "");
  }, [saveState.result]);

  useEffect(() => {
    const result =
      coachSaveState.result && typeof coachSaveState.result === "object"
        ? (coachSaveState.result as IntroLibrarySettings)
        : null;
    if (!result) return;
    setCoachProductAvatarUrl(result.coach_product_avatar?.url || "");
    setCoachProductAvatarTitle(result.coach_product_avatar?.title || "How HealthSense works");
    setCoachProductAvatarScript(result.coach_product_avatar?.script || "");
    setCoachProductAvatarPosterUrl(result.coach_product_avatar?.poster_url || "");
    setCoachProductAvatarCharacter(result.coach_product_avatar?.character || "lisa");
    setCoachProductAvatarStyle(result.coach_product_avatar?.style || "graceful-sitting");
    setCoachProductAvatarVoice(result.coach_product_avatar?.voice || "en-GB-SoniaNeural");
    setCoachProductAvatarStatus(result.coach_product_avatar?.status || "");
    setCoachProductAvatarJobId(result.coach_product_avatar?.job_id || "");
    setCoachProductAvatarError(result.coach_product_avatar?.error || "");
    setCoachProductAvatarGeneratedAt(result.coach_product_avatar?.generated_at || "");
    setCoachProductAvatarSummaryUrl(result.coach_product_avatar?.summary_url || "");
  }, [coachSaveState.result]);

  useEffect(() => {
    const result =
      assessmentSaveState.result && typeof assessmentSaveState.result === "object"
        ? (assessmentSaveState.result as AssessmentIntroLibrarySettings)
        : null;
    if (!result) return;
    setAssessmentIntroActive(Boolean(result.active));
    setAssessmentIntroTitle(result.title || "Assessment intro");
    setAssessmentIntroAvatarUrl(result.assessment_intro_avatar?.url || "");
    setAssessmentIntroAvatarTitle(
      result.assessment_intro_avatar?.title || "Assessment introduction",
    );
    setAssessmentIntroAvatarScript(result.assessment_intro_avatar?.script || "");
    setAssessmentIntroAvatarPosterUrl(result.assessment_intro_avatar?.poster_url || "");
    setAssessmentIntroAvatarCharacter(result.assessment_intro_avatar?.character || "lisa");
    setAssessmentIntroAvatarStyle(result.assessment_intro_avatar?.style || "graceful-sitting");
    setAssessmentIntroAvatarVoice(
      result.assessment_intro_avatar?.voice || "en-GB-SoniaNeural",
    );
    setAssessmentIntroAvatarStatus(result.assessment_intro_avatar?.status || "");
    setAssessmentIntroAvatarJobId(result.assessment_intro_avatar?.job_id || "");
    setAssessmentIntroAvatarError(result.assessment_intro_avatar?.error || "");
    setAssessmentIntroAvatarGeneratedAt(result.assessment_intro_avatar?.generated_at || "");
    setAssessmentIntroAvatarSummaryUrl(result.assessment_intro_avatar?.summary_url || "");
  }, [assessmentSaveState.result]);

  useEffect(() => {
    const result = appAvatarGenerationState.result || appAvatarRefreshState.result;
    const avatar =
      result && typeof result.app_intro_avatar === "object" && result.app_intro_avatar
        ? (result.app_intro_avatar as Record<string, unknown>)
        : null;
    if (!avatar) return;
    setAppIntroAvatarUrl(String(avatar.url || "").trim());
    setAppIntroAvatarTitle(String(avatar.title || "").trim() || "Welcome to HealthSense");
    setAppIntroAvatarScript(String(avatar.script || "").trim());
    setAppIntroAvatarPosterUrl(String(avatar.poster_url || "").trim());
    setAppIntroAvatarCharacter(String(avatar.character || "").trim() || "lisa");
    setAppIntroAvatarStyle(String(avatar.style || "").trim() || "graceful-sitting");
    setAppIntroAvatarVoice(String(avatar.voice || "").trim() || "en-GB-SoniaNeural");
    setAppIntroAvatarStatus(String(avatar.status || "").trim());
    setAppIntroAvatarJobId(String(avatar.job_id || "").trim());
    setAppIntroAvatarError(String(avatar.error || "").trim());
    setAppIntroAvatarGeneratedAt(String(avatar.generated_at || "").trim());
    setAppIntroAvatarSummaryUrl(String(avatar.summary_url || "").trim());
  }, [appAvatarGenerationState.result, appAvatarRefreshState.result]);

  useEffect(() => {
    const result = helpAvatarGenerationState.result || helpAvatarRefreshState.result;
    const rawSlot = String(result?.slot || "").trim() as IntroHelpAvatarSlot;
    const config = rawSlot ? helpAvatarConfigBySlot[rawSlot] : null;
    const avatar =
      result && typeof result.avatar === "object" && result.avatar
        ? (result.avatar as Record<string, unknown>)
        : null;
    if (!config || !avatar) return;
    setHelpAvatars((current) => ({
      ...current,
      [rawSlot]: {
        url: String(avatar.url || "").trim(),
        title: String(avatar.title || "").trim() || config.defaultTitle,
        script: String(avatar.script || "").trim(),
        posterUrl: String(avatar.poster_url || "").trim(),
        character: String(avatar.character || "").trim() || "lisa",
        style: String(avatar.style || "").trim() || "graceful-sitting",
        voice: String(avatar.voice || "").trim() || "en-GB-SoniaNeural",
        status: String(avatar.status || "").trim(),
        jobId: String(avatar.job_id || "").trim(),
        error: String(avatar.error || "").trim(),
        generatedAt: String(avatar.generated_at || "").trim(),
        summaryUrl: String(avatar.summary_url || "").trim(),
      },
    }));
  }, [helpAvatarConfigBySlot, helpAvatarGenerationState.result, helpAvatarRefreshState.result]);

  useEffect(() => {
    const result = coachAvatarGenerationState.result || coachAvatarRefreshState.result;
    const avatar =
      result && typeof result.coach_product_avatar === "object" && result.coach_product_avatar
        ? (result.coach_product_avatar as Record<string, unknown>)
        : null;
    if (!avatar) return;
    setCoachProductAvatarUrl(String(avatar.url || "").trim());
    setCoachProductAvatarTitle(String(avatar.title || "").trim() || "How HealthSense works");
    setCoachProductAvatarScript(String(avatar.script || "").trim());
    setCoachProductAvatarPosterUrl(String(avatar.poster_url || "").trim());
    setCoachProductAvatarCharacter(String(avatar.character || "").trim() || "lisa");
    setCoachProductAvatarStyle(String(avatar.style || "").trim() || "graceful-sitting");
    setCoachProductAvatarVoice(String(avatar.voice || "").trim() || "en-GB-SoniaNeural");
    setCoachProductAvatarStatus(String(avatar.status || "").trim());
    setCoachProductAvatarJobId(String(avatar.job_id || "").trim());
    setCoachProductAvatarError(String(avatar.error || "").trim());
    setCoachProductAvatarGeneratedAt(String(avatar.generated_at || "").trim());
    setCoachProductAvatarSummaryUrl(String(avatar.summary_url || "").trim());
  }, [coachAvatarGenerationState.result, coachAvatarRefreshState.result]);

  useEffect(() => {
    const result = assessmentAvatarGenerationState.result || assessmentAvatarRefreshState.result;
    const avatar =
      result && typeof result.assessment_intro_avatar === "object" && result.assessment_intro_avatar
        ? (result.assessment_intro_avatar as Record<string, unknown>)
        : null;
    if (!avatar) return;
    setAssessmentIntroAvatarUrl(String(avatar.url || "").trim());
    setAssessmentIntroAvatarTitle(String(avatar.title || "").trim() || "Assessment introduction");
    setAssessmentIntroAvatarScript(String(avatar.script || "").trim());
    setAssessmentIntroAvatarPosterUrl(String(avatar.poster_url || "").trim());
    setAssessmentIntroAvatarCharacter(String(avatar.character || "").trim() || "lisa");
    setAssessmentIntroAvatarStyle(String(avatar.style || "").trim() || "graceful-sitting");
    setAssessmentIntroAvatarVoice(String(avatar.voice || "").trim() || "en-GB-SoniaNeural");
    setAssessmentIntroAvatarStatus(String(avatar.status || "").trim());
    setAssessmentIntroAvatarJobId(String(avatar.job_id || "").trim());
    setAssessmentIntroAvatarError(String(avatar.error || "").trim());
    setAssessmentIntroAvatarGeneratedAt(String(avatar.generated_at || "").trim());
    setAssessmentIntroAvatarSummaryUrl(String(avatar.summary_url || "").trim());
  }, [assessmentAvatarGenerationState.result, assessmentAvatarRefreshState.result]);

  useEffect(() => {
    const key = String(appIntroAvatarCharacter || "").trim().toLowerCase();
    const validStyles = assessmentAvatarStylesByCharacter[key] || [];
    if (!validStyles.length) return;
    const currentStyle = String(appIntroAvatarStyle || "").trim();
    if (validStyles.some((option) => option.value === currentStyle)) return;
    setAppIntroAvatarStyle(validStyles[0]?.value || "");
  }, [appIntroAvatarCharacter, appIntroAvatarStyle]);

  useEffect(() => {
    const key = String(coachProductAvatarCharacter || "").trim().toLowerCase();
    const validStyles = assessmentAvatarStylesByCharacter[key] || [];
    if (!validStyles.length) return;
    const currentStyle = String(coachProductAvatarStyle || "").trim();
    if (validStyles.some((option) => option.value === currentStyle)) return;
    setCoachProductAvatarStyle(validStyles[0]?.value || "");
  }, [coachProductAvatarCharacter, coachProductAvatarStyle]);

  useEffect(() => {
    const key = String(assessmentIntroAvatarCharacter || "").trim().toLowerCase();
    const validStyles = assessmentAvatarStylesByCharacter[key] || [];
    if (!validStyles.length) return;
    const currentStyle = String(assessmentIntroAvatarStyle || "").trim();
    if (validStyles.some((option) => option.value === currentStyle)) return;
    setAssessmentIntroAvatarStyle(validStyles[0]?.value || "");
  }, [assessmentIntroAvatarCharacter, assessmentIntroAvatarStyle]);
  /* eslint-enable react-hooks/set-state-in-effect */

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap gap-2">
        <TabButton active={activeTab === "assessment"} label="Assessment Intro" onClick={() => setActiveTab("assessment")} />
        <TabButton active={activeTab === "coaching"} label="Coaching" onClick={() => setActiveTab("coaching")} />
        <TabButton active={activeTab === "app"} label="App Intro" onClick={() => setActiveTab("app")} />
      </div>

      {activeTab === "app" ? (
        <>
          <section className="rounded-2xl border border-[#efe7db] bg-[#fdfaf4] p-4">
            <SectionHeading
              label="Generate app intro draft"
              description="Uses the library content generation flow to draft the onboarding intro copy and optional podcast audio."
            />
            <form action={generationAction} className="mt-4 grid gap-4 md:grid-cols-2">
              <div>
                <label className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">
                  Content template
                </label>
                <select
                  name="template_id"
                  className="mt-2 w-full rounded-xl border border-[#efe7db] bg-white px-3 py-2 text-sm"
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
                <label className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Provider</label>
                <select
                  name="provider"
                  defaultValue="openai"
                  className="mt-2 w-full rounded-xl border border-[#efe7db] bg-white px-3 py-2 text-sm"
                >
                  <option value="openai">OpenAI</option>
                  <option value="anthropic">Anthropic</option>
                  <option value="google">Google</option>
                </select>
              </div>
              <div>
                <label className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">
                  LLM model (optional)
                </label>
                <select
                  name="model_override"
                  className="mt-2 w-full rounded-xl border border-[#efe7db] bg-white px-3 py-2 text-sm"
                >
                  {modelOptions.map((model) => (
                    <option key={model || "default"} value={model}>
                      {model || "Default"}
                    </option>
                  ))}
                </select>
              </div>
              <label className="flex items-center gap-2 text-sm text-[#6b6257]">
                <input type="checkbox" name="run_llm" defaultChecked />
                Run LLM (generate text)
              </label>
              <label className="flex items-center gap-2 text-sm text-[#6b6257]">
                <input type="checkbox" name="generate_podcast" defaultChecked />
                Generate podcast audio
              </label>
              <div>
                <label className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">
                  Podcast voice
                </label>
                <select
                  name="podcast_voice"
                  defaultValue={podcastVoice}
                  className="mt-2 w-full rounded-xl border border-[#efe7db] bg-white px-3 py-2 text-sm"
                >
                  {voiceOptions.map((voice) => (
                    <option key={voice.value || "default"} value={voice.value}>
                      {voice.label}
                    </option>
                  ))}
                </select>
              </div>
              <button
                type="submit"
                disabled={generating}
                className="w-fit rounded-full border border-[var(--accent)] bg-[var(--accent)] px-3 py-1.5 text-[10px] uppercase tracking-[0.12em] text-white disabled:cursor-not-allowed disabled:opacity-60"
              >
                {generating ? "Generating…" : "Generate draft"}
              </button>
            </form>
            {generationState.error ? (
              <p className="mt-3 text-sm text-red-600">{generationState.error}</p>
            ) : null}
            {generatedText ? (
              <p className="mt-3 text-xs text-[#6b6257]">
                Generated text loaded into the app intro read content field below.
              </p>
            ) : null}
          </section>

          <section className="rounded-2xl border border-[#efe7db] bg-white p-4">
            <SectionHeading
              label="HealthSense app intro"
              description="Controls the onboarding intro inside the HealthSense app, including welcome copy and podcast audio."
            />
            <form action={saveAction} className="mt-4 space-y-4">
              <label className="flex items-center gap-2 text-sm text-[#3c332b]">
                <input
                  type="checkbox"
                  name="active"
                  checked={active}
                  onChange={(e) => setActive(e.target.checked)}
                />
                Intro flow active
              </label>
              <div>
                <label className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Title</label>
                <input
                  name="title"
                  value={title}
                  onChange={(e) => setTitle(e.target.value)}
                  className="mt-2 w-full rounded-xl border border-[#efe7db] px-3 py-2 text-sm"
                />
              </div>
              <div>
                <label className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">
                  Welcome message template
                </label>
                <input
                  name="welcome_message_template"
                  value={welcomeTemplate}
                  onChange={(e) => setWelcomeTemplate(e.target.value)}
                  className="mt-2 w-full rounded-xl border border-[#efe7db] px-3 py-2 text-sm"
                />
                <p className="mt-1 text-xs text-[#8a8176]">
                  Supports {"{first_name}"} and {"{display_name}"}.
                </p>
              </div>
              <div>
                <label className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">
                  Read content
                </label>
                <textarea
                  name="body"
                  rows={8}
                  value={body}
                  onChange={(e) => setBody(e.target.value)}
                  className="mt-2 w-full rounded-xl border border-[#efe7db] px-3 py-2 text-sm"
                />
              </div>
              <div className="grid gap-3 md:grid-cols-2">
                <div>
                  <label className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">
                    Podcast URL
                  </label>
                  <input
                    name="podcast_url"
                    value={podcastUrl}
                    onChange={(e) => setPodcastUrl(e.target.value)}
                    className="mt-2 w-full rounded-xl border border-[#efe7db] px-3 py-2 text-sm"
                  />
                </div>
                <div>
                  <label className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">
                    Podcast voice
                  </label>
                  <select
                    name="podcast_voice"
                    value={podcastVoice}
                    onChange={(e) => setPodcastVoice(e.target.value)}
                    className="mt-2 w-full rounded-xl border border-[#efe7db] px-3 py-2 text-sm"
                  >
                    {voiceOptions.map((voice) => (
                      <option key={voice.value || "default"} value={voice.value}>
                        {voice.label}
                      </option>
                    ))}
                  </select>
                </div>
              </div>
              {podcastUrl ? (
                <div className="rounded-xl border border-[#efe7db] bg-[#fdfaf4] p-3">
                  <p className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">
                    Podcast preview
                  </p>
                  <audio
                    key={podcastUrl}
                    controls
                    preload="none"
                    className="mt-2 w-full"
                    src={podcastUrl}
                  />
                  <a
                    href={podcastUrl}
                    target="_blank"
                    rel="noreferrer"
                    className="mt-2 inline-flex text-[11px] uppercase tracking-[0.2em] text-[var(--accent)]"
                  >
                    Open audio
                  </a>
                </div>
              ) : null}
              <div className="space-y-4 rounded-2xl border border-[#efe7db] bg-[#fdfaf4] p-4">
                <div>
                  <p className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">
                    App intro avatar
                  </p>
                  <p className="mt-1 text-sm text-[#6b6257]">
                    Managed video for the first in-app onboarding panel.
                  </p>
                </div>
                <div className="grid gap-3 md:grid-cols-2">
                  <div>
                    <label className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">
                      Video URL
                    </label>
                    <input
                      name="app_intro_avatar_url"
                      value={appIntroAvatarUrl}
                      onChange={(e) => setAppIntroAvatarUrl(e.target.value)}
                      className="mt-2 w-full rounded-xl border border-[#efe7db] px-3 py-2 text-sm"
                    />
                  </div>
                  <div>
                    <label className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">
                      Label
                    </label>
                    <input
                      name="app_intro_avatar_title"
                      value={appIntroAvatarTitle}
                      onChange={(e) => setAppIntroAvatarTitle(e.target.value)}
                      className="mt-2 w-full rounded-xl border border-[#efe7db] px-3 py-2 text-sm"
                    />
                  </div>
                  <div>
                    <label className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">
                      Poster URL
                    </label>
                    <input
                      name="app_intro_avatar_poster_url"
                      value={appIntroAvatarPosterUrl}
                      onChange={(e) => setAppIntroAvatarPosterUrl(e.target.value)}
                      className="mt-2 w-full rounded-xl border border-[#efe7db] px-3 py-2 text-sm"
                    />
                  </div>
                  <div>
                    <label className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">
                      Character
                    </label>
                    <select
                      name="app_intro_avatar_character"
                      value={appIntroAvatarCharacter}
                      onChange={(e) => setAppIntroAvatarCharacter(e.target.value)}
                      className="mt-2 w-full rounded-xl border border-[#efe7db] px-3 py-2 text-sm"
                    >
                      {appCharacterOptions.map((option) => (
                        <option key={option.value} value={option.value}>
                          {option.label}
                        </option>
                      ))}
                    </select>
                  </div>
                  <div>
                    <label className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">
                      Style
                    </label>
                    <select
                      name="app_intro_avatar_style"
                      value={appIntroAvatarStyle}
                      onChange={(e) => setAppIntroAvatarStyle(e.target.value)}
                      className="mt-2 w-full rounded-xl border border-[#efe7db] px-3 py-2 text-sm"
                    >
                      {appStyleOptions.map((option) => (
                        <option key={option.value} value={option.value}>
                          {option.label}
                        </option>
                      ))}
                    </select>
                  </div>
                  <div>
                    <label className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">
                      Voice
                    </label>
                    <select
                      name="app_intro_avatar_voice"
                      value={appIntroAvatarVoice}
                      onChange={(e) => setAppIntroAvatarVoice(e.target.value)}
                      className="mt-2 w-full rounded-xl border border-[#efe7db] px-3 py-2 text-sm"
                    >
                      {appVoiceOptions.map((option) => (
                        <option key={option.value} value={option.value}>
                          {option.label}
                        </option>
                      ))}
                    </select>
                  </div>
                </div>
                <div>
                  <label className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">
                    Avatar script
                  </label>
                  <textarea
                    name="app_intro_avatar_script"
                    rows={8}
                    value={appIntroAvatarScript}
                    onChange={(e) => setAppIntroAvatarScript(e.target.value)}
                    className="mt-2 w-full rounded-xl border border-[#efe7db] px-3 py-2 text-sm"
                  />
                </div>
                <div className="rounded-xl border border-[#efe7db] bg-white p-3 text-sm text-[#6b6257]">
                  <p className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">
                    Azure avatar status
                  </p>
                  <p className="mt-2">Status: {appIntroAvatarStatus || "not generated"}</p>
                  {appIntroAvatarJobId ? (
                    <p className="mt-1 break-all">Job ID: {appIntroAvatarJobId}</p>
                  ) : null}
                  {appIntroAvatarGeneratedAt ? (
                    <p className="mt-1">Generated: {appIntroAvatarGeneratedAt}</p>
                  ) : null}
                  {appIntroAvatarSummaryUrl ? (
                    <a
                      href={appIntroAvatarSummaryUrl}
                      target="_blank"
                      rel="noreferrer"
                      className="mt-2 inline-flex text-[11px] uppercase tracking-[0.2em] text-[var(--accent)]"
                    >
                      Open Azure summary
                    </a>
                  ) : null}
                  {appIntroAvatarError ? (
                    <p className="mt-2 text-red-600">{appIntroAvatarError}</p>
                  ) : null}
                </div>
                <div className="flex flex-wrap gap-2">
                  <button
                    type="submit"
                    formAction={appAvatarGenerationAction}
                    disabled={generatingAppAvatar || refreshingAppAvatar || saving}
                    className="rounded-full border border-[var(--accent)] bg-[var(--accent)] px-5 py-2 text-xs uppercase tracking-[0.2em] text-white disabled:cursor-not-allowed disabled:opacity-60"
                  >
                    {generatingAppAvatar ? "Generating avatar…" : "Generate avatar"}
                  </button>
                  <button
                    type="submit"
                    formAction={appAvatarRefreshAction}
                    disabled={refreshingAppAvatar || generatingAppAvatar || saving}
                    className="rounded-full border border-[#e7e1d6] bg-white px-5 py-2 text-xs uppercase tracking-[0.2em] text-[#3c332b] disabled:cursor-not-allowed disabled:opacity-60"
                  >
                    {refreshingAppAvatar ? "Refreshing…" : "Refresh avatar status"}
                  </button>
                </div>
                {appAvatarGenerationState.error ? (
                  <p className="text-sm text-red-600">{appAvatarGenerationState.error}</p>
                ) : null}
                {appAvatarRefreshState.error ? (
                  <p className="text-sm text-red-600">{appAvatarRefreshState.error}</p>
                ) : null}
                {appIntroAvatarUrl ? (
                  <div className="rounded-xl border border-[#efe7db] bg-white p-3">
                    <p className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">
                      Video preview
                    </p>
                    <video
                      key={appIntroAvatarUrl}
                      controls
                      preload="metadata"
                      playsInline
                      poster={appIntroAvatarPosterUrl || undefined}
                      className="mt-2 w-full rounded-2xl border border-[#efe7db]"
                    >
                      <source src={appIntroAvatarUrl} />
                    </video>
                    <a
                      href={appIntroAvatarUrl}
                      target="_blank"
                      rel="noreferrer"
                      className="mt-2 inline-flex text-[11px] uppercase tracking-[0.2em] text-[var(--accent)]"
                    >
                      Open video
                    </a>
                  </div>
                ) : null}
              </div>
              {INTRO_HELP_AVATAR_CONFIGS.map((config) => {
                const state = helpAvatars[config.slot];
                const characterOptions = withCurrentOption(
                  assessmentAvatarCharacterOptions,
                  state.character,
                );
                const styleOptions = withCurrentOption(
                  assessmentAvatarStylesByCharacter[String(state.character || "").trim().toLowerCase()] || [],
                  state.style,
                );
                const voiceOptionsForSlot = withCurrentOption(
                  assessmentAvatarVoiceOptions,
                  state.voice,
                );
                const showGenerationError =
                  activeHelpAvatarSlot === config.slot ? helpAvatarGenerationState.error : null;
                const showRefreshError =
                  activeHelpAvatarSlot === config.slot ? helpAvatarRefreshState.error : null;
                const isGeneratingThisSlot =
                  generatingHelpAvatar && activeHelpAvatarSlot === config.slot;
                const isRefreshingThisSlot =
                  refreshingHelpAvatar && activeHelpAvatarSlot === config.slot;
                return (
                  <div
                    key={config.slot}
                    className="space-y-4 rounded-2xl border border-[#efe7db] bg-[#fdfaf4] p-4"
                  >
                    <div>
                      <p className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">
                        {config.label}
                      </p>
                      <p className="mt-1 text-sm text-[#6b6257]">{config.description}</p>
                    </div>
                    <div className="grid gap-3 md:grid-cols-2">
                      <div>
                        <label className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">
                          Video URL
                        </label>
                        <input
                          name={`${config.fieldPrefix}_url`}
                          value={state.url}
                          onChange={(e) => updateHelpAvatarField(config.slot, "url", e.target.value)}
                          className="mt-2 w-full rounded-xl border border-[#efe7db] px-3 py-2 text-sm"
                        />
                      </div>
                      <div>
                        <label className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">
                          Label
                        </label>
                        <input
                          name={`${config.fieldPrefix}_title`}
                          value={state.title}
                          onChange={(e) => updateHelpAvatarField(config.slot, "title", e.target.value)}
                          className="mt-2 w-full rounded-xl border border-[#efe7db] px-3 py-2 text-sm"
                        />
                      </div>
                      <div>
                        <label className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">
                          Poster URL
                        </label>
                        <input
                          name={`${config.fieldPrefix}_poster_url`}
                          value={state.posterUrl}
                          onChange={(e) => updateHelpAvatarField(config.slot, "posterUrl", e.target.value)}
                          className="mt-2 w-full rounded-xl border border-[#efe7db] px-3 py-2 text-sm"
                        />
                      </div>
                      <div>
                        <label className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">
                          Character
                        </label>
                        <select
                          name={`${config.fieldPrefix}_character`}
                          value={state.character}
                          onChange={(e) => updateHelpAvatarCharacter(config.slot, e.target.value)}
                          className="mt-2 w-full rounded-xl border border-[#efe7db] px-3 py-2 text-sm"
                        >
                          {characterOptions.map((option) => (
                            <option key={option.value} value={option.value}>
                              {option.label}
                            </option>
                          ))}
                        </select>
                      </div>
                      <div>
                        <label className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">
                          Style
                        </label>
                        <select
                          name={`${config.fieldPrefix}_style`}
                          value={state.style}
                          onChange={(e) => updateHelpAvatarField(config.slot, "style", e.target.value)}
                          className="mt-2 w-full rounded-xl border border-[#efe7db] px-3 py-2 text-sm"
                        >
                          {styleOptions.map((option) => (
                            <option key={option.value} value={option.value}>
                              {option.label}
                            </option>
                          ))}
                        </select>
                      </div>
                      <div>
                        <label className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">
                          Voice
                        </label>
                        <select
                          name={`${config.fieldPrefix}_voice`}
                          value={state.voice}
                          onChange={(e) => updateHelpAvatarField(config.slot, "voice", e.target.value)}
                          className="mt-2 w-full rounded-xl border border-[#efe7db] px-3 py-2 text-sm"
                        >
                          {voiceOptionsForSlot.map((option) => (
                            <option key={option.value} value={option.value}>
                              {option.label}
                            </option>
                          ))}
                        </select>
                      </div>
                    </div>
                    <div>
                      <label className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">
                        Avatar script
                      </label>
                      <textarea
                        name={`${config.fieldPrefix}_script`}
                        rows={6}
                        value={state.script}
                        onChange={(e) => updateHelpAvatarField(config.slot, "script", e.target.value)}
                        className="mt-2 w-full rounded-xl border border-[#efe7db] px-3 py-2 text-sm"
                      />
                    </div>
                    <div className="rounded-xl border border-[#efe7db] bg-white p-3 text-sm text-[#6b6257]">
                      <p className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">
                        Azure avatar status
                      </p>
                      <p className="mt-2">Status: {state.status || "not generated"}</p>
                      {state.jobId ? <p className="mt-1 break-all">Job ID: {state.jobId}</p> : null}
                      {state.generatedAt ? <p className="mt-1">Generated: {state.generatedAt}</p> : null}
                      {state.summaryUrl ? (
                        <a
                          href={state.summaryUrl}
                          target="_blank"
                          rel="noreferrer"
                          className="mt-2 inline-flex text-[11px] uppercase tracking-[0.2em] text-[var(--accent)]"
                        >
                          Open Azure summary
                        </a>
                      ) : null}
                      {state.error ? <p className="mt-2 text-red-600">{state.error}</p> : null}
                    </div>
                    <div className="flex flex-wrap gap-2">
                      <button
                        type="submit"
                        name="app_help_avatar_slot"
                        value={config.slot}
                        formAction={helpAvatarGenerationAction}
                        onClick={() => setActiveHelpAvatarSlot(config.slot)}
                        disabled={generatingHelpAvatar || refreshingHelpAvatar || saving}
                        className="rounded-full border border-[var(--accent)] bg-[var(--accent)] px-5 py-2 text-xs uppercase tracking-[0.2em] text-white disabled:cursor-not-allowed disabled:opacity-60"
                      >
                        {isGeneratingThisSlot ? "Generating avatar…" : "Generate avatar"}
                      </button>
                      <button
                        type="submit"
                        name="app_help_avatar_slot"
                        value={config.slot}
                        formAction={helpAvatarRefreshAction}
                        onClick={() => setActiveHelpAvatarSlot(config.slot)}
                        disabled={refreshingHelpAvatar || generatingHelpAvatar || saving}
                        className="rounded-full border border-[#e7e1d6] bg-white px-5 py-2 text-xs uppercase tracking-[0.2em] text-[#3c332b] disabled:cursor-not-allowed disabled:opacity-60"
                      >
                        {isRefreshingThisSlot ? "Refreshing…" : "Refresh avatar status"}
                      </button>
                    </div>
                    {showGenerationError ? (
                      <p className="text-sm text-red-600">{showGenerationError}</p>
                    ) : null}
                    {showRefreshError ? (
                      <p className="text-sm text-red-600">{showRefreshError}</p>
                    ) : null}
                    {state.url ? (
                      <div className="rounded-xl border border-[#efe7db] bg-white p-3">
                        <p className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">
                          Video preview
                        </p>
                        <video
                          key={`${config.slot}-${state.url}`}
                          controls
                          preload="metadata"
                          playsInline
                          poster={state.posterUrl || undefined}
                          className="mt-2 w-full rounded-2xl border border-[#efe7db]"
                        >
                          <source src={state.url} />
                        </video>
                        <a
                          href={state.url}
                          target="_blank"
                          rel="noreferrer"
                          className="mt-2 inline-flex text-[11px] uppercase tracking-[0.2em] text-[var(--accent)]"
                        >
                          Open video
                        </a>
                      </div>
                    ) : null}
                  </div>
                );
              })}
              <button
                type="submit"
                disabled={
                  saving ||
                  generatingAppAvatar ||
                  refreshingAppAvatar ||
                  generatingHelpAvatar ||
                  refreshingHelpAvatar
                }
                className="rounded-full border border-[var(--accent)] bg-[var(--accent)] px-5 py-2 text-xs uppercase tracking-[0.2em] text-white disabled:cursor-not-allowed disabled:opacity-60"
              >
                {saving ? "Saving…" : "Save app intro"}
              </button>
              {saveState.error ? <p className="text-sm text-red-600">{saveState.error}</p> : null}
              {saveState.ok ? <p className="text-sm text-[var(--accent)]">Saved.</p> : null}
            </form>
          </section>
        </>
      ) : null}

      {activeTab === "coaching" ? (
        <section className="rounded-2xl border border-[#efe7db] bg-white p-4">
          <SectionHeading
            label="HealthSense coaching"
            description="Controls the explainer shown when the user opens their personal coaching plan above the OKRs."
          />
          <form action={coachSaveAction} className="mt-4 space-y-4">
            <div className="grid gap-3 md:grid-cols-2">
              <div>
                <label className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">
                  Video URL
                </label>
                <input
                  name="coach_product_avatar_url"
                  value={coachProductAvatarUrl}
                  onChange={(e) => setCoachProductAvatarUrl(e.target.value)}
                  className="mt-2 w-full rounded-xl border border-[#efe7db] px-3 py-2 text-sm"
                />
              </div>
              <div>
                <label className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">
                  Label
                </label>
                <input
                  name="coach_product_avatar_title"
                  value={coachProductAvatarTitle}
                  onChange={(e) => setCoachProductAvatarTitle(e.target.value)}
                  className="mt-2 w-full rounded-xl border border-[#efe7db] px-3 py-2 text-sm"
                />
              </div>
              <div>
                <label className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">
                  Poster URL
                </label>
                <input
                  name="coach_product_avatar_poster_url"
                  value={coachProductAvatarPosterUrl}
                  onChange={(e) => setCoachProductAvatarPosterUrl(e.target.value)}
                  className="mt-2 w-full rounded-xl border border-[#efe7db] px-3 py-2 text-sm"
                />
              </div>
              <div>
                <label className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">
                  Character
                </label>
                <select
                  name="coach_product_avatar_character"
                  value={coachProductAvatarCharacter}
                  onChange={(e) => setCoachProductAvatarCharacter(e.target.value)}
                  className="mt-2 w-full rounded-xl border border-[#efe7db] px-3 py-2 text-sm"
                >
                  {coachCharacterOptions.map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <label className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">
                  Style
                </label>
                <select
                  name="coach_product_avatar_style"
                  value={coachProductAvatarStyle}
                  onChange={(e) => setCoachProductAvatarStyle(e.target.value)}
                  className="mt-2 w-full rounded-xl border border-[#efe7db] px-3 py-2 text-sm"
                >
                  {coachStyleOptions.map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <label className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">
                  Voice
                </label>
                <select
                  name="coach_product_avatar_voice"
                  value={coachProductAvatarVoice}
                  onChange={(e) => setCoachProductAvatarVoice(e.target.value)}
                  className="mt-2 w-full rounded-xl border border-[#efe7db] px-3 py-2 text-sm"
                >
                  {coachVoiceOptions.map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </select>
              </div>
            </div>
            <div>
              <label className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">
                Avatar script
              </label>
              <textarea
                name="coach_product_avatar_script"
                rows={8}
                value={coachProductAvatarScript}
                onChange={(e) => setCoachProductAvatarScript(e.target.value)}
                className="mt-2 w-full rounded-xl border border-[#efe7db] px-3 py-2 text-sm"
              />
            </div>
            <div className="rounded-xl border border-[#efe7db] bg-[#fdfaf4] p-3 text-sm text-[#6b6257]">
              <p className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">
                Azure avatar status
              </p>
              <p className="mt-2">Status: {coachProductAvatarStatus || "not generated"}</p>
              {coachProductAvatarJobId ? (
                <p className="mt-1 break-all">Job ID: {coachProductAvatarJobId}</p>
              ) : null}
              {coachProductAvatarGeneratedAt ? (
                <p className="mt-1">Generated: {coachProductAvatarGeneratedAt}</p>
              ) : null}
              {coachProductAvatarSummaryUrl ? (
                <a
                  href={coachProductAvatarSummaryUrl}
                  target="_blank"
                  rel="noreferrer"
                  className="mt-2 inline-flex text-[11px] uppercase tracking-[0.2em] text-[var(--accent)]"
                >
                  Open Azure summary
                </a>
              ) : null}
              {coachProductAvatarError ? (
                <p className="mt-2 text-red-600">{coachProductAvatarError}</p>
              ) : null}
            </div>
            <div className="flex flex-wrap gap-2">
              <button
                type="submit"
                formAction={coachAvatarGenerationAction}
                disabled={generatingCoachAvatar || refreshingCoachAvatar || savingCoach}
                className="rounded-full border border-[var(--accent)] bg-[var(--accent)] px-5 py-2 text-xs uppercase tracking-[0.2em] text-white disabled:cursor-not-allowed disabled:opacity-60"
              >
                {generatingCoachAvatar ? "Generating avatar…" : "Generate avatar"}
              </button>
              <button
                type="submit"
                formAction={coachAvatarRefreshAction}
                disabled={refreshingCoachAvatar || generatingCoachAvatar || savingCoach}
                className="rounded-full border border-[#e7e1d6] bg-white px-5 py-2 text-xs uppercase tracking-[0.2em] text-[#3c332b] disabled:cursor-not-allowed disabled:opacity-60"
              >
                {refreshingCoachAvatar ? "Refreshing…" : "Refresh avatar status"}
              </button>
              <button
                type="submit"
                disabled={savingCoach || generatingCoachAvatar || refreshingCoachAvatar}
                className="rounded-full border border-[var(--accent)] bg-[var(--accent)] px-5 py-2 text-xs uppercase tracking-[0.2em] text-white disabled:cursor-not-allowed disabled:opacity-60"
              >
                {savingCoach ? "Saving…" : "Save coaching"}
              </button>
            </div>
            {coachSaveState.error ? <p className="text-sm text-red-600">{coachSaveState.error}</p> : null}
            {coachSaveState.ok ? <p className="text-sm text-[var(--accent)]">Saved.</p> : null}
            {coachAvatarGenerationState.error ? (
              <p className="text-sm text-red-600">{coachAvatarGenerationState.error}</p>
            ) : null}
            {coachAvatarRefreshState.error ? (
              <p className="text-sm text-red-600">{coachAvatarRefreshState.error}</p>
            ) : null}
            {coachProductAvatarUrl ? (
              <div className="rounded-xl border border-[#efe7db] bg-white p-3">
                <p className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">
                  Video preview
                </p>
                <video
                  key={coachProductAvatarUrl}
                  controls
                  preload="metadata"
                  playsInline
                  poster={coachProductAvatarPosterUrl || undefined}
                  className="mt-2 w-full rounded-2xl border border-[#efe7db]"
                >
                  <source src={coachProductAvatarUrl} />
                </video>
                <a
                  href={coachProductAvatarUrl}
                  target="_blank"
                  rel="noreferrer"
                  className="mt-2 inline-flex text-[11px] uppercase tracking-[0.2em] text-[var(--accent)]"
                >
                  Open video
                </a>
              </div>
            ) : null}
          </form>
        </section>
      ) : null}

      {activeTab === "assessment" ? (
        <section className="rounded-2xl border border-[#efe7db] bg-white p-4">
          <SectionHeading
            label="Assessment intro"
            description="Controls the lead assessment landing intro separately from the in-app onboarding intro."
          />
          <form action={assessmentSaveAction} className="mt-4 space-y-4">
          <label className="flex items-center gap-2 text-sm text-[#3c332b]">
            <input
              type="checkbox"
              name="assessment_intro_active"
              checked={assessmentIntroActive}
              onChange={(e) => setAssessmentIntroActive(e.target.checked)}
            />
            Assessment intro active
          </label>
          <div>
            <label className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Title</label>
            <input
              name="assessment_intro_title"
              value={assessmentIntroTitle}
              onChange={(e) => setAssessmentIntroTitle(e.target.value)}
              className="mt-2 w-full rounded-xl border border-[#efe7db] px-3 py-2 text-sm"
            />
          </div>
          <div className="space-y-4 rounded-2xl border border-[#efe7db] bg-[#fdfaf4] p-4">
            <div>
              <p className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">
                Assessment intro avatar
              </p>
              <p className="mt-1 text-sm text-[#6b6257]">
                Managed video for the lead assessment landing page. The frontend on/off
                switch still controls whether it renders.
              </p>
            </div>
            <div className="grid gap-3 md:grid-cols-2">
              <div>
                <label className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">
                  Video URL
                </label>
                <input
                  name="assessment_intro_avatar_url"
                  value={assessmentIntroAvatarUrl}
                  onChange={(e) => setAssessmentIntroAvatarUrl(e.target.value)}
                  className="mt-2 w-full rounded-xl border border-[#efe7db] px-3 py-2 text-sm"
                />
              </div>
              <div>
                <label className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">
                  Label
                </label>
                <input
                  name="assessment_intro_avatar_title"
                  value={assessmentIntroAvatarTitle}
                  onChange={(e) => setAssessmentIntroAvatarTitle(e.target.value)}
                  className="mt-2 w-full rounded-xl border border-[#efe7db] px-3 py-2 text-sm"
                />
              </div>
              <div>
                <label className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">
                  Poster URL
                </label>
                <input
                  name="assessment_intro_avatar_poster_url"
                  value={assessmentIntroAvatarPosterUrl}
                  onChange={(e) => setAssessmentIntroAvatarPosterUrl(e.target.value)}
                  className="mt-2 w-full rounded-xl border border-[#efe7db] px-3 py-2 text-sm"
                />
              </div>
              <div>
                <label className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">
                  Character
                </label>
                <select
                  name="assessment_intro_avatar_character"
                  value={assessmentIntroAvatarCharacter}
                  onChange={(e) => setAssessmentIntroAvatarCharacter(e.target.value)}
                  className="mt-2 w-full rounded-xl border border-[#efe7db] px-3 py-2 text-sm"
                >
                  {assessmentCharacterOptions.map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <label className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">
                  Style
                </label>
                <select
                  name="assessment_intro_avatar_style"
                  value={assessmentIntroAvatarStyle}
                  onChange={(e) => setAssessmentIntroAvatarStyle(e.target.value)}
                  className="mt-2 w-full rounded-xl border border-[#efe7db] px-3 py-2 text-sm"
                >
                  {assessmentStyleOptions.map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <label className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">
                  Voice
                </label>
                <select
                  name="assessment_intro_avatar_voice"
                  value={assessmentIntroAvatarVoice}
                  onChange={(e) => setAssessmentIntroAvatarVoice(e.target.value)}
                  className="mt-2 w-full rounded-xl border border-[#efe7db] px-3 py-2 text-sm"
                >
                  {assessmentVoiceOptions.map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </select>
              </div>
            </div>
            <div>
              <label className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">
                Avatar script
              </label>
              <textarea
                name="assessment_intro_avatar_script"
                rows={8}
                value={assessmentIntroAvatarScript}
                onChange={(e) => setAssessmentIntroAvatarScript(e.target.value)}
                className="mt-2 w-full rounded-xl border border-[#efe7db] px-3 py-2 text-sm"
              />
              <p className="mt-1 text-xs text-[#8a8176]">
                Store the transcript used to create the assessment intro video so it can
                be edited without changing code.
              </p>
            </div>
            <div className="rounded-xl border border-[#efe7db] bg-white p-3 text-sm text-[#6b6257]">
              <p className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">
                Azure avatar status
              </p>
              <p className="mt-2">Status: {assessmentIntroAvatarStatus || "not generated"}</p>
              {assessmentIntroAvatarJobId ? (
                <p className="mt-1 break-all">Job ID: {assessmentIntroAvatarJobId}</p>
              ) : null}
              {assessmentIntroAvatarGeneratedAt ? (
                <p className="mt-1">Generated: {assessmentIntroAvatarGeneratedAt}</p>
              ) : null}
              {assessmentIntroAvatarSummaryUrl ? (
                <a
                  href={assessmentIntroAvatarSummaryUrl}
                  target="_blank"
                  rel="noreferrer"
                  className="mt-2 inline-flex text-[11px] uppercase tracking-[0.2em] text-[var(--accent)]"
                >
                  Open Azure summary
                </a>
              ) : null}
              {assessmentIntroAvatarError ? (
                <p className="mt-2 text-red-600">{assessmentIntroAvatarError}</p>
              ) : null}
            </div>
            <div className="flex flex-wrap gap-2">
              <button
                type="submit"
                formAction={assessmentAvatarGenerationAction}
                disabled={generatingAssessmentAvatar || refreshingAssessmentAvatar}
                className="rounded-full border border-[var(--accent)] bg-[var(--accent)] px-5 py-2 text-xs uppercase tracking-[0.2em] text-white disabled:cursor-not-allowed disabled:opacity-60"
              >
                {generatingAssessmentAvatar ? "Generating avatar…" : "Generate avatar"}
              </button>
              <button
                type="submit"
                formAction={assessmentAvatarRefreshAction}
                disabled={refreshingAssessmentAvatar || generatingAssessmentAvatar}
                className="rounded-full border border-[#e7e1d6] bg-white px-5 py-2 text-xs uppercase tracking-[0.2em] text-[#3c332b] disabled:cursor-not-allowed disabled:opacity-60"
              >
                {refreshingAssessmentAvatar ? "Refreshing…" : "Refresh avatar status"}
              </button>
            </div>
            {assessmentAvatarGenerationState.error ? (
              <p className="text-sm text-red-600">{assessmentAvatarGenerationState.error}</p>
            ) : null}
            {assessmentAvatarRefreshState.error ? (
              <p className="text-sm text-red-600">{assessmentAvatarRefreshState.error}</p>
            ) : null}
            {assessmentIntroAvatarUrl ? (
              <div className="rounded-xl border border-[#efe7db] bg-white p-3">
                <p className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">
                  Video preview
                </p>
                <video
                  key={assessmentIntroAvatarUrl}
                  controls
                  preload="metadata"
                  playsInline
                  poster={assessmentIntroAvatarPosterUrl || undefined}
                  className="mt-2 w-full rounded-2xl border border-[#efe7db]"
                >
                  <source src={assessmentIntroAvatarUrl} />
                </video>
                <a
                  href={assessmentIntroAvatarUrl}
                  target="_blank"
                  rel="noreferrer"
                  className="mt-2 inline-flex text-[11px] uppercase tracking-[0.2em] text-[var(--accent)]"
                >
                  Open video
                </a>
              </div>
            ) : null}
          </div>
          <button
            type="submit"
            disabled={savingAssessment}
            className="rounded-full border border-[var(--accent)] bg-[var(--accent)] px-5 py-2 text-xs uppercase tracking-[0.2em] text-white disabled:cursor-not-allowed disabled:opacity-60"
          >
            {savingAssessment ? "Saving…" : "Save assessment intro"}
          </button>
          {assessmentSaveState.error ? (
            <p className="text-sm text-red-600">{assessmentSaveState.error}</p>
          ) : null}
          {assessmentSaveState.ok ? (
            <p className="text-sm text-[var(--accent)]">Saved.</p>
          ) : null}
          </form>
        </section>
      ) : null}
    </div>
  );
}
