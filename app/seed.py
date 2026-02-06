# app/seed.py
# PATCH (2025-09-03)
# • Seeds pillars (incl. goals), 5 concepts/pillar (20 total).
# • Seeds per-concept primary + alternates (concept_questions).
# • Seeds 2 KB snippets per concept (kb_snippets).
# • Generates deterministic placeholder embeddings (kb_vectors).
# • Seeds demo users.
# • Adds seed_users() shim for legacy import.

from __future__ import annotations

from typing import Dict, List
from datetime import datetime
import os
import hashlib, math, random
import json

from sqlalchemy import select, text as sa_text
from sqlalchemy.orm import Session

from .db import SessionLocal
from .models import (
    User,
    Pillar,
    Concept,
    ConceptQuestion,
    KbSnippet,
    KbVector,
    Club,
    UserPreference,
    PromptTemplate,
    PromptSettings,
    PromptTemplateVersionLog,
    ADMIN_ROLE_MEMBER,
    ADMIN_ROLE_CLUB,
    ADMIN_ROLE_GLOBAL,
)

PILLARS = [
    ("nutrition",  "Nutrition"),
    ("training",   "Training"),
    ("resilience", "Resilience"),
    ("recovery",   "Recovery"),
]

CONCEPTS: Dict[str, Dict[str, str]] = {
    "nutrition": {
        "protein_intake":   "Protein intake",
        "fruit_veg":        "Fruit & vegetables",
        "hydration":        "Hydration",
        "processed_food":   "Processed food",
    },
    "training": {
        "cardio_frequency":     "Cardio frequency",
        "strength_training":    "Strength training",
        "flexibility_mobility": "Flexibility & mobility",
    },
    "resilience": {
        "emotional_regulation":   "Emotional regulation",
        "positive_connection":    "Positive connection & enjoyment",
        "stress_recovery":        "Stress recovery",
        "optimism_perspective":   "Optimism & perspective",
        "support_openness":       "Support & openness",
    },
    "recovery": {
        "sleep_duration":       "Sleep duration",
        "sleep_quality":        "Sleep quality",
        "bedtime_consistency":  "Bedtime consistency",
    },
}

CONCEPT_QUESTIONS = {
    "nutrition": {
        "protein_intake": {
            "primary": "Thinking about the last 7 days, how many protein portions did you usually *eat on average per day*? For reference: 1 portion = palm-sized meat or fish, 2 eggs, 1 handful of nuts, or 1 cup of beans/lentils."
        },
        "fruit_veg": {
            "primary": "In the last 7 days, how many portions of fruit and vegetables did you *eat on average per day*? For reference: 1 portion = 1 apple or banana, 1 fist-sized serving of vegetables, or 1 handful of salad or berries."
        },
        "hydration": {
            "primary": "Thinking about the last 7 days, how much water did you usually *drink per day*? For reference: 1 glass = 250ml, 1 small bottle = 500ml."
        },
        "processed_food": {
            "primary": "In the last 7 days, how many portions of processed food did you *eat on average per day*? Examples: 1 portion = a chocolate bar, 1 can of fizzy drink, 1 handful of sweets, or a pastry."
        },
    },
    "training": {
        "cardio_frequency": {
            "primary": "In the last 7 days, on how many days did you do at least 20 minutes of cardio exercise, such as running, cycling, or swimming?"
        },
        "strength_training": {
            "primary": "In the last 7 days, how many strength training sessions did you do, such as weights, bodyweight exercises, or resistance bands?"
        },
        "flexibility_mobility": {
            "primary": "In the last 7 days, on how many days did you do stretching, yoga, or mobility work for at least 10 minutes?"
        },
    },
    "resilience": {
        "emotional_regulation": {
            "primary": "In the past 7 days, on how many days did you feel calm and in control of your emotions for most of the day?"
        },
        "positive_connection": {
            "primary": "In the past 7 days, on how many days did you do something that made you feel genuinely good — either by taking time for yourself or connecting with someone you enjoy spending time with?"
        },
        "stress_recovery": {
            "primary": "In the past 7 days, on how many days did you take a short break to relax, breathe deeply, or reset when you felt stressed or tired?"
        },
        "optimism_perspective": {
            "primary": "In the past 7 days, on how many days did you feel able to stay positive and keep things in perspective when challenges arose?"
        },
        "support_openness": {
            "primary": "In the past 7 days, on how many days did you actively connect with others to discuss your goals, progress, or challenges?"
        },
    },
    "recovery": {
        "sleep_duration": {
            "primary": "In the last 7 days, on how many nights did you sleep for 7 or more hours?"
        },
        "sleep_quality": {
            "primary": "In the last 7 days, on how many mornings did you wake up feeling rested and refreshed?"
        },
        "bedtime_consistency": {
            "primary": "In the last 7 days, on how many nights did you go to bed at roughly the same time?"
        },
    },
}

# Optional pillar-level preamble questions (can be asked before concept questions)
PILLAR_PREAMBLE_QUESTIONS = {
    "training": "Looking ahead over the next three months, do you have any particular training goal or focus (e.g., marathon prep, strength maintenance, injury recovery)?"
}

KB_SNIPPETS: Dict[str, Dict[str, List[Dict]]] = {
    "nutrition": {
        "protein_intake": [
            {"title": "Portion baseline", "text": "Aim ~3–4 protein portions/day; 1 portion = palm of lean protein, 2 eggs, or 1 cup beans/lentils."},
            {"title": "Scoring cue (0–5/day)", "text": "0–1/day = low, 2–3/day = fair, 3–4/day = good, 5/day = excellent; spread evenly across meals."},
        ],
        "fruit_veg": [
            {"title": "Target & variety", "text": "≥5 portions/day; mix colours for fibre and micronutrients."},
            {"title": "Make it easy", "text": "Front-load fruit/veg into the first two meals; batch-cook to stay consistent."},
        ],
        "hydration": [
            {"title": "Daily target", "text": "Women: 2–3 L/day; Men: 3–4 L/day (more with heat/training). Pale-straw urine ≈ good hydration."},
            {"title": "Scoring cue (0–6 L/day)", "text": "2–4 L/day = strong; spread intake through the day; pair sips with routine cues."},
        ],
        "processed_food": [
            {"title": "Definition & unit", "text": "UPFs include crisps, sweets, pastries, ready meals, sugary drinks; count portions per day."},
            {"title": "Scoring cue (reverse; 0–4+/day)", "text": "0/day = best, 0–1/day = good, 2–3/day = fair, ≥4/day = poor; use an 80/20 approach and reward gradual reduction."},
        ],
    },
    "training": {
        "cardio_frequency": [
            {"title": "Aerobic baseline", "text": "Do ≥20 min most days in Zone 2–3; include 1–2 sessions/week in Zone 4–5 for range."},
            {"title": "Scoring cue (0–5 days/wk)", "text": "0–1 days = low, 2–3 = fair, 4 = good, 5 = excellent; 150–300 min/week moderate (or 75–150 vigorous) is the weekly anchor."},
        ],
        "strength_training": [
            {"title": "Dose & structure", "text": "2–3 full-body sessions/week; cover push, pull, squat, hinge, carry, core."},
            {"title": "Scoring cue (0–4 sessions/wk)", "text": "1 = low, 2 = fair, 3 = good, 4 = excellent if recovery (sleep/energy/soreness) is solid."},
        ],
        "flexibility_mobility": [
            {"title": "Baseline habit", "text": "≥10 minutes on ≥3 days/week; link to a fixed time (post-workout or pre-bed)."},
            {"title": "Scoring cue (0–5 days/wk)", "text": "Consistency beats one-off long sessions; more days at 10–15 min score higher."},
        ],
    },
    "resilience": {
        "emotional_regulation": [
            {"title": "Micro-resets", "text": "Take 5–10 min walks or mindful breaks; use 2–3 presence prompts/day (breath, posture, body scan)."},
            {"title": "Scoring cue (0–7 days/wk)", "text": "Reward intentional regulation efforts and consistency, not the absence of difficult emotion."},
        ],
        "positive_connection": [
            {"title": "Gratitude & contact", "text": "Note 2–3 gratitudes/day; brief check-ins (message/call) count as positive connection."},
            {"title": "Scoring cue (0–7 days/wk)", "text": "Intentional engagement and gratitude both improve scores; more days = higher."},
        ],
        "stress_recovery": [
            {"title": "Active coping", "text": "Use journaling and reach out to supports to reduce overload; short resets beat avoidance."},
            {"title": "Scoring cue (0–7 days/wk)", "text": "Consistent use of a coping strategy scores higher than infrequent, long sessions."},
        ],
        "optimism_perspective": [
            {"title": "Reframe & evidence", "text": "Widen the view: ask what else could be true; track one small win daily."},
            {"title": "Scoring cue (0–7 days/wk)", "text": "Regular practice of reframing/perspective-taking increases the score."},
        ],
        "support_openness": [
            {"title": "Ask early & specifically", "text": "Share goals/challenges before they build; make specific asks or check-ins."},
            {"title": "Scoring cue (0–7 days/wk)", "text": "Willingness to request or accept support earlier and more consistently scores higher."},
        ],
    },
    "recovery": {
        "sleep_duration": [
            {"title": "Hours & anchor", "text": "Most adults benefit from 7–9 h/night; keep a consistent wake time."},
            {"title": "Scoring cue (0–7 nights/wk)", "text": "More nights at ≥7 h score higher; if fatigued, go to bed earlier rather than sleeping in."},
        ],
        "sleep_quality": [
            {"title": "Wind-down routine", "text": "Dim lights, quiet time, breathing/reading; avoid screens ≥60 min before bed."},
            {"title": "Scoring cue (0–7 mornings/wk)", "text": "Improvement = faster sleep onset, deeper rest, fewer night wakes; more mornings feeling refreshed score higher."},
        ],
        "bedtime_consistency": [
            {"title": "Circadian window", "text": "Keep sleep/wake within ±60 min to support circadian rhythm."},
            {"title": "Scoring cue (0–7 nights/wk)", "text": "Reward stabilising a regular schedule over rigid perfection; consistency > total hours for circadian alignment."},
        ],
    },
}
# Clubs to seed (you can change names/slugs as you like)
CLUBS = [
    ("healthsense",   "HealthSense HQ"),
    ("anytime-eden",  "Anytime Fitness – Eden"),
]
DEMO_USERS = [
    {
        "first_name": "Julian",
        "surname": "Matthews",
        "phone": "+447459954324",
        "is_superuser": True,
        "admin_role": ADMIN_ROLE_GLOBAL,
        "club_slug": "healthsense",
    },
    {
        "first_name": "Rhys",
        "surname": "Williams",
        "phone": "+447860362908",
        "is_superuser": True,
        "admin_role": ADMIN_ROLE_CLUB,
        "club_slug": "healthsense",
    },
]

# Touchpoint type definitions for user-facing explanations
TOUCHPOINT_TYPES = [
    {"code": "prime",   "label": "Prime",   "description": "Light pre-period nudge to confirm focus and gather blockers."},
    {"code": "kickoff", "label": "Kickoff", "description": "Sets the plan and 2–3 key actions for the period."},
    {"code": "adjust",  "label": "Adjust",  "description": "Mid-period variance check to course-correct."},
    {"code": "wrap",    "label": "Wrap",    "description": "Retro: wins, misses, and setup for the next period."},
    {"code": "ad_hoc",  "label": "Ad hoc",  "description": "On-demand or triggered interaction outside the cadence."},
]

# Default cadence profiles (can be overridden per user via UserPreference)
CADENCE_PROFILES = [
    {
        "code": "standard_loop",
        "label": "Standard loop",
        "types": ["prime", "kickoff", "adjust", "wrap"],
        "intensity": "medium",
        "description": "Balanced cadence with planning, mid-course check, and wrap."
    },
    {
        "code": "light_loop",
        "label": "Light loop",
        "types": ["kickoff", "wrap"],
        "intensity": "light",
        "description": "Low-touch cadence for users who prefer fewer check-ins."
    },
]

def _seed_admin_role(entry: dict) -> str:
    role = (entry.get("admin_role") or "").strip().lower()
    if role in {ADMIN_ROLE_MEMBER, ADMIN_ROLE_CLUB, ADMIN_ROLE_GLOBAL}:
        return role
    return ADMIN_ROLE_GLOBAL if bool(entry.get("is_superuser")) else ADMIN_ROLE_MEMBER


DEFAULT_PROMPT_TEMPLATES = [
    {
        "touchpoint": 'podcast_kickoff',
        "okr_scope": 'all',
        "programme_scope": 'full',
        "response_format": '',
        "is_active": True,
        "block_order": ['system', 'locale', 'context', 'programme', 'okr', 'scores', 'habit', 'task', 'user'],
        "include_blocks": ['system', 'locale', 'context', 'programme', 'okr', 'scores', 'habit', 'task', 'user'],
        "task_block": """You are delivering the kick-off podcast for the HealthSense programme.
Your role in this moment is to orient, reassure, and motivate the user as they begin.
This podcast should feel like a calm, confident guide explaining how the journey works and why it has been designed this way.
Use the user’s scores and OKRs to briefly acknowledge where they currently are, without judgement or urgency.
Do not dwell on numbers or deficits — frame scores as a useful starting snapshot, not a measure of success or failure.
Introduce the concept of habit creation as the foundation of the programme.
Explain, in simple and human terms, why the programme is structured in focused 21-day blocks:
habits are easier to build when attention is narrowed
consistency matters more than intensity
progress compounds when behaviours are repeated, not rushed
Introduce habit steps as the practical mechanism the programme uses to create sustainable, meaningful behavioural change.
Explain that habit steps are:
small, clear, achievable actions
intentionally selected to move the user toward their OKRs
consistent enough to build momentum even in busy weeks
the place where most progress is actually created
Explain how habit steps will work within the programme:
Every Monday, the coach will offer a short list of habit steps aligned with the user’s main OKR.
The user and coach will mutually agree on which steps feel realistic and helpful for the week ahead.
These steps form the weekly focus and will be the anchor for ongoing support.
Clarify the rhythm of check-ins:
The primary check-ins during the week will focus on these agreed habit steps.
Sunday includes a dedicated habit step reflection, helping the user notice what worked, what felt easy or challenging, and what might need adjusting.
In Week 3, the check-in shifts briefly toward the OKR itself — to understand how the habit work is beginning to translate into meaningful progress.
Reassure the user that OKRs are always in the background, but the emphasis is on the habit steps — because that’s where change actually happens.
When referencing the programme, keep the overview high-level and reassuring.
Emphasise that the user is not expected to work on everything at once and that each block builds naturally on the last.
Maintain a supportive, optimistic tone throughout.
Avoid pressure, deadlines, or any implication that the user must “perform”.
End the podcast by:
reinforcing confidence in the process
reminding the user that momentum comes from small, repeatable actions
encouraging them to simply begin and trust the structure
The desired emotional outcome is that the user feels clear, capable, and quietly motivated to take their first steps.""",
    },
    {
        "touchpoint": 'podcast_weekstart',
        "okr_scope": 'pillar',
        "programme_scope": 'pillar',
        "response_format": '',
        "is_active": True,
        "block_order": ['system', 'locale', 'context', 'programme', 'history', 'okr', 'scores', 'habit', 'task', 'user'],
        "include_blocks": ['system', 'locale', 'context', 'programme', 'history', 'okr', 'scores', 'habit', 'task', 'user'],
        "task_block": """You are delivering the Week Start Podcast for the HealthSense programme.
Keep it to 2–3 minutes (around 300–450 words).
This podcast is sent every Monday and acts as the weekly reset, designed to help the user start the week with clarity, direction, and confidence.

Your role is to:
- reinforce the purpose and power of habit steps
- guide the user through the habit-step options for their current pillar
- help them understand, in real-world terms, how these steps would look in their daily routine
- prepare them for a follow-up message where they will choose the habit steps they want to focus on this week

1. Frame the purpose of this weekly podcast  
Explain that this is a recurring Monday episode, designed to orient the user for the week ahead without being repetitive or overwhelming.  
Make it clear that each episode builds naturally from the previous week based on:
- the user’s progress
- their experience with the previous habit steps
- the stage they are currently in within the 3-week pillar block

2. Explain the importance of habit steps  
Clearly outline why the programme uses habit steps as the main mechanism for behaviour change:
- Habit steps remove complexity and create clarity.
- They transform big goals (OKRs) into small, doable actions.
- They significantly increase follow-through because smaller behaviours fit more easily into real life.
- Habit steps reduce decision fatigue and help the brain automate behaviour more quickly.
- Consistency with small steps reliably outperforms sporadic intensity.

Your tone should be confident, reassuring, and grounded in behavioural science — but still simple and relatable.

3. Explain why this method is more effective  
Briefly describe that people are far more likely to sustain a behaviour when:
- the action is clearly defined
- the step is small enough to be achievable
- the commitment is made in advance
- the step ties directly to something that matters to them (their OKR)

Avoid jargon; stay human and example-led.

4. Walk through each KR in the current pillar  
For the user’s current pillar:
- reference each OKR briefly
- offer several habit-step options for each OKR
- keep options practical, specific, and varied (so the user can choose what fits their week)

Do NOT tell the user which habit steps to choose; present possibilities.

5. Explain how habit steps play out in real life  
After presenting the options, translate them into real-world examples.

Use simple, grounded scenarios such as:
- busy workdays
- mornings with limited time
- training days
- evenings when energy is low
- weekends
- travel or social events

The goal is to help the user visualise success and understand how doable these steps truly are.

6. Reinforce likelihood of success  
Calmly highlight how much more likely they are to succeed because:
- the steps are clear
- the load is small
- the focus is narrow
- they already have a coach supporting them
- progress compounds when behaviours are repeated week after week

Keep the tone optimistic but not hype-driven.

7. Set the expectation for the follow-up message  
Let the user know:
- After this podcast, the coach will send them a message.
- That message will offer the same habit-step options in written form.
- They will choose (together with the coach) which steps feel right for this week.
- The coach will support them through these steps across the week.

8. Clarify how future Mondays will evolve  
Explain briefly that:
- Monday podcasts will adapt based on the user’s progress.
- Some weeks will focus on strengthening the same steps.
- Some weeks will simplify steps if things feel overwhelming.
- Some weeks will expand or progress steps if the user is ready.
- Every Monday builds on the one before — never a copy-and-paste experience.

9. Emotional outcome  
The user should finish the podcast feeling:
- calm
- capable
- clear on how to start the week
- confident that their habits are realistic and achievable
- supported, not judged
- motivated to choose their habit steps in the follow-up message""",
    },
    {
        "touchpoint": 'weekstart_support',
        "okr_scope": 'week',
        "programme_scope": '',
        "response_format": '',
        "is_active": True,
        "block_order": ['system', 'locale', 'context', 'history', 'okr', 'scores', 'habit', 'task', 'user'],
        "include_blocks": ['system', 'locale', 'context', 'okr', 'scores', 'habit', 'history', 'task'],
        "task_block": """You are in a Monday support chat after the user has received their weekly podcast and action options.

Your role in this message is to reinforce clarity, translate intent into action, and reduce friction. Briefly mention that there will be a Sunday check-in to reflect on how each KR has been going.

Briefly recap the key idea from the weekly podcast, focusing on:
- beginning with courage rather than perfection
- working in focused 21-day blocks
- prioritising consistency over intensity

Acknowledge the user’s current OKRs and clearly highlight the key results that matter for this first phase only.
Do not reference future phases or additional pillars.
Frame KRs as behaviours to practise, not targets to hit.

If the user is unsure about the habit steps, offer one small adjustment or a simpler alternative for a KR.
If they confirm or choose options, acknowledge and encourage their choice.

Use simple, encouraging language.
Avoid overwhelm, checklists, or multiple action items.

End the message by inviting the user to ask questions or flag anything that feels unclear or challenging at this stage.
The tone should feel supportive and available, not instructional or evaluative.

The desired outcome is that the user knows exactly what to focus on this week and feels confident taking their first step.""",
    },
    {
        "touchpoint": 'general_support',
        "okr_scope": 'week',
        "programme_scope": '',
        "response_format": '',
        "is_active": True,
        "block_order": ['system', 'locale', 'context', 'history', 'okr', 'scores', 'habit', 'task', 'user'],
        "include_blocks": ['system', 'locale', 'context', 'history', 'okr', 'scores', 'habit', 'task', 'user'],
        "task_block": """You are in a general coaching support chat that can happen after any weekly touchpoint (Monday-Sunday or Kickoff).
Use the context (current week, focus KRs, and any selected habit steps) to keep your response grounded in what they are already working on.

Respond to the user's message with:
- a brief acknowledgement
- one practical, low-pressure suggestion tied to their current habit steps or goals
- and one short follow-up question that keeps the conversation open

Keep it concise (2-4 short sentences), warm, calm, and supportive.
Avoid OKR/KR jargon in the user-facing text; refer to goals or habit steps.
Do not introduce new goals unless the user asks.
The desired outcome is that the user feels supported and clear on a next small step.""",
    },
    {
        "touchpoint": 'tuesday',
        "okr_scope": 'week',
        "programme_scope": '',
        "response_format": '',
        "is_active": True,
        "block_order": ['system', 'locale', 'context', 'history', 'okr', 'scores', 'habit', 'task', 'user'],
        "include_blocks": ['system', 'locale', 'context', 'history', 'okr', 'scores', 'habit', 'task'],
        "task_block": """You are sending a short Tuesday message designed to maintain presence and connection.

Begin with a friendly, positive opening that gently checks in with the user.
Keep this brief and natural.

Offer a reminder that support is available if they need it.
Frame this casually, without implying there is a problem.

Mention a few light examples of what the user could reach out about, such as:
- a quick question
- something that feels unclear
- help making a habit fit their routine

Keep this conversational and optional, not a list or instruction.

End the message with a grounded motivational line.
The line should feel, positive, encouraging & a little inspiring — not intense.

Do not reference OKRs, KRs, progress, or expectations.
Do not introduce actions or next steps.

The tone should feel friendly, supportive, and unobtrusive.

The desired outcome is that the user feels supported and comfortable starting a conversation if they want to.""",
    },
    {
        "touchpoint": 'saturday',
        "okr_scope": 'week',
        "programme_scope": '',
        "response_format": '',
        "is_active": True,
        "block_order": ['system', 'locale', 'context', 'history', 'okr', 'scores', 'habit', 'task', 'user'],
        "include_blocks": ['system', 'locale', 'context', 'history', 'okr', 'scores', 'habit', 'task'],
        "task_block": """You are sending a short Saturday keepalive message to keep the WhatsApp session active.

Keep it light, friendly, and low-pressure.
Ask a single, simple question and do not include example replies.
Offer help if anything feels unclear, but do not introduce new actions or advice.

Avoid referencing OKRs, KRs, scores, or progress.
Do not mention that this is about the WhatsApp window.

Keep it to 1–2 lines.

The desired outcome is a short reply that keeps the conversation open.""",
    },
    {
        "touchpoint": 'weekstart_actions',
        "okr_scope": 'week',
        "programme_scope": '',
        "response_format": '',
        "is_active": True,
        "block_order": ['system', 'locale', 'context', 'history', 'okr', 'scores', 'habit', 'task', 'user'],
        "include_blocks": ['system', 'locale', 'context', 'history', 'okr', 'scores', 'habit', 'task', 'user'],
        "task_block": """Keep this warm, calm, and easy to read.

Start with a brief line acknowledging the podcast and that you’re now turning the OKRs into simple weekly actions.
Then add one short sentence: you’ll share a few small habit-step options per KR so they can choose what feels most realistic this week.

Using the podcast context, create three habit-step options per KR.
Keep them practical, low‑pressure, and easy to start this week.

Use this exact format (no extra bullets or commentary):

KR1: <short KR description>
1A) <habit step option>
1B) <habit step option>
1C) <habit step option>
KR2: <short KR description>
2A) <habit step option>
2B) <habit step option>
2C) <habit step option>
…

If a KR only needs two options, still include an A and B, but prefer three whenever possible.

End with one short line telling them they’ll be asked to choose an option for each KR.

Tone: steady, supportive, unrushed.""",
    },
    {
        "touchpoint": 'midweek',
        "okr_scope": 'week',
        "programme_scope": '',
        "response_format": '',
        "is_active": True,
        "block_order": ['system', 'locale', 'context', 'history', 'okr', 'scores', 'habit', 'task', 'user'],
        "include_blocks": ['system', 'locale', 'context', 'history', 'okr', 'scores', 'habit', 'task', 'user'],
        "task_block": """You are sending a Wednesday check-in message focused on the user's current Habit Steps (These are not KR's).

Begin with a warm, welcoming opening that checks in on how the user is doing.
Keep this friendly and natural, setting an inviting tone.

Check in on how their Habit Steps are going so far this week. 
Ask how things have felt and whether they've noticed anything over the last few days, if anything at all.

Create space for both positive progress and challenges. 
If things have gone well, acknowledge that this is helpful to hear. 
If anything has felt difficult, invite the user to share it and make it clear that support is available to help find a simple, practical solution.

Use clear, everyday language.
Keep the message concise, open, and easy to respond to.

Do not introduce new actions, advice, or expectations.
Do not reference future programme blocks or timelines.

The tone should be conversational and supportive, with the clear intention of starting a dialogue rather than evaluating performance.

The desired outcome is an open, honest response that allows a natural conversation to begin.""",
    },
    {
        "touchpoint": 'sunday_actions',
        "okr_scope": 'week',
        "programme_scope": '',
        "response_format": '',
        "is_active": True,
        "block_order": ['system', 'locale', 'context', 'history', 'okr', 'scores', 'habit', 'task', 'user'],
        "include_blocks": ['system', 'locale', 'context', 'okr', 'scores', 'habit', 'history', 'task'],
        "task_block": """You are sending a Sunday check-in. The review focus depends on review_mode (habit or kr). Follow it.

Keep this very short: 2-3 short sentences, max ~450 characters. Do not list the habit steps or KRs.

If review_mode = habit:
- Ask how the habit steps went overall this week.
- Ask if they want to tweak one step.

If review_mode = kr:
- Ask for numeric updates for each goal in order, numbers only.

End with: \"I'll summarise this and prep Monday's podcast.\"""",
    },
    {
        "touchpoint": 'sunday_support',
        "okr_scope": 'week',
        "programme_scope": '',
        "response_format": '',
        "is_active": True,
        "block_order": ['system', 'locale', 'context', 'history', 'okr', 'scores', 'habit', 'task', 'user'],
        "include_blocks": ['system', 'locale', 'context', 'history', 'okr', 'scores', 'habit', 'task'],
        "task_block": """You are responding to the user's Sunday check-in.
The review focus depends on review_mode (habit or kr). Follow it.

Briefly acknowledge what they shared, then ask one short follow-up that helps you support them.
Keep the response concise, supportive, and conversational. Avoid judgement or advice overload.

If review_mode = habit:
- Ask whether they want to keep the habit steps as-is or tweak one small step.

If review_mode = kr:
- Ask about one key friction point or blocker that affected the numbers.""",
    },
    {
        "touchpoint": 'podcast_thursday',
        "okr_scope": 'week',
        "programme_scope": '',
        "response_format": '',
        "is_active": True,
        "block_order": ['system', 'locale', 'context', 'history', 'okr', 'scores', 'habit', 'task', 'user'],
        "include_blocks": ['system', 'locale', 'context', 'okr', 'history', 'task'],
        "task_block": """You are delivering a short Thursday podcast (2–3 minutes) that speaks directly to the user in a clear, conversational way.

The purpose of this podcast is to share useful insight that helps the user better understand what they are working on and why it matters.

Speak as if you are talking to the user one-to-one.
Use natural, conversational language rather than formal or academic phrasing.

Introduce one or two relevant insights related to the user’s current focus.
These may include:
- simple, well-established research findings
- practical observations from habit or behaviour science
- credible statistics that are easy to grasp

Explain each insight in plain language and relate it directly back to the user’s current habits or KRs.
Help the user see how their actions connect to real change over time.

Keep the pacing light and engaging.
Avoid sounding scripted, instructional, or overly motivational.

Do not introduce new goals or tasks.
Do not pressure the user to do more.

Close the podcast by reinforcing the value of continuing with what they are already doing and encouraging them to keep building momentum.

The desired outcome is that the user finishes the podcast feeling informed, confident, and more committed to their current focus.""",
    },
    {
        "touchpoint": 'podcast_friday',
        "okr_scope": 'week',
        "programme_scope": '',
        "response_format": '',
        "is_active": True,
        "block_order": ['system', 'locale', 'context', 'history', 'okr', 'scores', 'habit', 'task', 'user'],
        "include_blocks": ['system', 'locale', 'context', 'okr', 'history', 'task'],
        "task_block": """You are a warm, concise wellbeing coach creating a short Friday boost podcast (~45–60s). Write a script that: 1) friendly check-in; 2) encourage ONE focus goal in plain language (no OKR/KR terms); 3) give ONE simple, realistic action they can do over the weekend; 4) keep it brief, motivating, and specific; 5) no medical advice.""",
    },
    {
        "touchpoint": 'assessment_scores',
        "okr_scope": '',
        "programme_scope": '',
        "response_format": '',
        "is_active": True,
        "block_order": ['system', 'locale', 'context', 'scores', 'task', 'user'],
        "include_blocks": ['system', 'locale', 'context', 'scores', 'task'],
        "task_block": """You are explaining the user’s current wellbeing scores in a way that feels deeply relatable and personally accurate. 
Your goal is to help the user recognise themselves in the description and feel understood.

Refer directly to the user’s pillar scores and use them to paint a clear, human picture of what their day-to-day experience might be like.

For each pillar:
- Translate the score into lived experiences, common patterns, and subtle signals the user may recognise.
- Explain how people with similar scores often feel, think, or behave — without making assumptions or sounding diagnostic.
- Use grounded, believable examples that make the user think “yes, that’s exactly me”.

When describing what the scores suggest:
- Be empathetic and non-judgemental.
- Avoid negative labelling or anything that implies failure.
- Focus on understanding, not evaluation.

Show how these scores may be influencing:
- energy levels
- mood and stress response
- motivation and follow-through
- sleep quality
- physical performance
- daily habits and routines
- decision-making
- confidence or self-belief

Keep your language specific and relatable. 
Do not use generic advice, clichés, or vague statements.

Explain that the scores are simply a snapshot — not a verdict. 
They help reveal patterns and highlight where support can make the biggest difference.

Connect the dots between the pillars where relevant:
- how low nutrition consistency may be affecting energy or mood  
- how recovery affects resilience  
- how training habits influence sleep, confidence, or mental clarity  

Use phrases that help the user feel understood, such as “you may notice”, “you might often find”, or “many people with similar patterns experience…”.

Close by reinforcing that recognising these patterns is a powerful first step — and now that the picture is clear, the programme will help them move forward with confidence and structure.

The tone should be warm, insightful, and human — like a coach who truly understands how these scores show up in real life.
maximum words 200""",
    },
    {
        "touchpoint": 'assessment_okr',
        "okr_scope": '',
        "programme_scope": '',
        "response_format": '',
        "is_active": True,
        "block_order": ['system', 'locale', 'context', 'okr', 'task', 'user'],
        "include_blocks": ['system', 'locale', 'context', 'okr', 'task', 'user'],
        "task_block": """You are giving the user a short, conversational summary of what their OKRs mean and what they can expect from the coaching around them. 
Do not restate their OKRs or scores — they can already see those. 
Your role is to help them understand the purpose behind these targets and how the coaching will support them week by week.

Write as a coach who has reviewed their results and wants to explain things simply and clearly. 
Keep this light, personal, and easy to digest.

Explain that their OKRs highlight the few areas that will make the biggest difference for them right now. 
These aren’t random targets — they’re chosen to give the user clarity, momentum, and quick early wins without overwhelming them.

Briefly reassure them that they won’t be left to figure this out alone. 
Let them know that for each KR, the coach will offer a small set of simple, realistic actions they can choose from each week, so they always know exactly what to do next. 
This keeps progress achievable and personalised, and ensures the user builds habits in a way that feels manageable.

Keep the messaging relaxed, warm, and confident. 
End with one short line reinforcing that these OKRs were designed specifically for them and that they’ll be guided step-by-step through how to bring them to life.""",
    },
    {
        "touchpoint": 'assessment_approach',
        "okr_scope": '',
        "programme_scope": '',
        "response_format": '',
        "is_active": True,
        "block_order": ['system', 'locale', 'context', 'habit', 'task', 'user'],
        "include_blocks": ['system', 'locale', 'context', 'habit', 'task', 'user'],
        "task_block": """You are explaining the user’s Habit Readiness Profile in a concise, relatable way.

Keep the explanation short, clear, and personal. Do not over-explain and do not write long paragraphs.

Refer directly to the user’s Habit Readiness Profile and summarise what it suggests about:
- how they typically start habits
- how consistently they follow through
- how confident they feel when trying to make changes
- how much structure or support helps them stay on track

Use simple, relatable examples that help the user recognise themselves (“you may notice…”, “you might often feel…”, “many people with this pattern find…”). Keep these examples brief.

Explain how the coach will adapt to their readiness level:
- the pace of habit building,
- how much structure or clarity they’ll receive,
- how habits will be shaped to fit their routine,
- how support will increase when things feel difficult.

Keep the tone positive and reassuring. Avoid judgement or long detail.

End with one short sentence explaining that their Habit Readiness Profile helps the programme personalise the experience so habits feel achievable and sustainable.

The explanation should feel insightful but concise.""",
    },
    {
        "touchpoint": 'assessor_system',
        "okr_scope": '',
        "programme_scope": '',
        "response_format": 'json',
        "is_active": True,
        "block_order": ['system', 'locale', 'context', 'assessor', 'task', 'user'],
        "include_blocks": ['system', 'locale', 'context', 'assessor', 'task'],
        "task_block": """You are a concise WhatsApp assessor. Ask a main question (<=300 chars) or a clarifier (<=320 chars) when the user's answer is vague. If the reply contains a NUMBER or strongly implies a count/timeframe, you may treat it as sufficient and finish with a score. Only finish once you can assign a 0–100 score. Return JSON only with fields: {action:ask|finish, question, level:Low|Moderate|High, confidence:float, rationale, scores:{}, status:scorable|needs_clarifier|insufficient, why, missing:[], parsed_value:{value,unit,timeframe_ok}}. Use polarity inference and bounds when provided; map habitual phrases to counts; prefer clarifiers if uncertain.""",
    }
]


def _hash_floats(text: str, dim: int = 256) -> list[float]:
    if not text:
        text = " "
    seed = int(hashlib.sha256(text.encode("utf-8")).hexdigest(), 16) % (2**31 - 1)
    rng = random.Random(seed)
    vec = []
    for _ in range(dim):
        h = hashlib.sha256(f"{text}|{rng.randint(0,1_000_000)}".encode("utf-8")).hexdigest()
        v = int(h[:8], 16) / 0xFFFFFFFF
        vec.append(v)
    norm = math.sqrt(sum(v*v for v in vec)) or 1.0
    return [v / norm for v in vec]


def _ensure_user_pref(session: Session, user_id: int, key: str, value: str, meta=None) -> bool:
    row = session.execute(
        select(UserPreference).where(UserPreference.user_id == user_id, UserPreference.key == key)
    ).scalar_one_or_none()
    if row:
        return False
    session.add(UserPreference(user_id=user_id, key=key, value=value, meta=meta))
    return True

CONCEPT_SCORE_BOUNDS = {
    "nutrition": {
        "protein_intake": {"zero_score": 0, "max_score": 5},
        "fruit_veg":      {"zero_score": 0, "max_score": 5},
        "hydration":      {"zero_score": 0, "max_score": 6},
        "processed_food": {"zero_score": 4, "max_score": 0},  # days/week; reverse (7 days bad=0, 0 days best=100)
    },
    "training": {
        "cardio_frequency":     {"zero_score": 0, "max_score": 3},
        "strength_training":    {"zero_score": 0, "max_score": 4},
        "flexibility_mobility": {"zero_score": 0, "max_score": 4},
    },
    "resilience": {
        "emotional_regulation":   {"zero_score": 0, "max_score": 7},
        "positive_connection":    {"zero_score": 0, "max_score": 7},
        "stress_recovery":        {"zero_score": 0, "max_score": 7},
        "optimism_perspective":   {"zero_score": 0, "max_score": 7},
        "support_openness":       {"zero_score": 0, "max_score": 7},
    },
    "recovery": {
        "sleep_duration":      {"zero_score": 0, "max_score": 7},
        "sleep_quality":       {"zero_score": 0, "max_score": 7},
        "bedtime_consistency": {"zero_score": 0, "max_score": 7},
    },
}

def upsert_pillars(session: Session) -> int:
    created = 0
    for key, name in PILLARS:
        row = session.execute(select(Pillar).where(Pillar.key == key)).scalar_one_or_none()
        if not row:
            session.add(Pillar(key=key, name=name, created_at=datetime.utcnow())); created += 1
    session.commit(); return created

def upsert_concepts(session: Session) -> int:
    created = 0
    for pillar_key, mapping in CONCEPTS.items():
        for code, name in mapping.items():
            row = session.execute(
                select(Concept).where(Concept.pillar_key == pillar_key, Concept.code == code)
            ).scalar_one_or_none()
            bounds = (CONCEPT_SCORE_BOUNDS.get(pillar_key, {}) or {}).get(code)
            if not row:
                session.add(Concept(
                    pillar_key=pillar_key,
                    code=code,
                    name=name,
                    description=None,
                    created_at=datetime.utcnow(),
                    zero_score=(bounds or {}).get("zero_score"),
                    max_score=(bounds or {}).get("max_score"),
                ))
                created += 1
            else:
                if bounds:
                    row.zero_score = bounds.get("zero_score")
                    row.max_score  = bounds.get("max_score")
    session.commit(); return created

def upsert_concept_questions(session: Session) -> int:
    created = 0
    for pillar_key, concepts in CONCEPT_QUESTIONS.items():
        for code, bundle in concepts.items():
            concept = session.execute(
                select(Concept).where(Concept.pillar_key == pillar_key, Concept.code == code)
            ).scalar_one_or_none()
            if not concept:
                continue
            # primary
            primary = (bundle.get("primary") or "").strip()
            if primary:
                exists = session.execute(
                    select(ConceptQuestion).where(
                        ConceptQuestion.concept_id == concept.id,
                        ConceptQuestion.text == primary
                    )
                ).scalar_one_or_none()
                if not exists:
                    session.add(ConceptQuestion(concept_id=concept.id, text=primary, is_primary=True)); created += 1
            # alternates
            for alt in bundle.get("alts", []):
                t = (alt or "").strip()
                if not t: continue
                exists = session.execute(
                    select(ConceptQuestion).where(
                        ConceptQuestion.concept_id == concept.id,
                        ConceptQuestion.text == t
                    )
                ).scalar_one_or_none()
                if not exists:
                    session.add(ConceptQuestion(concept_id=concept.id, text=t, is_primary=False)); created += 1
    session.commit(); return created


def seed_prompt_templates(session: Session) -> int:
    """Seed baseline prompt templates with default OKR scopes."""
    try:
        PromptTemplate.__table__.create(bind=session.bind, checkfirst=True)
    except Exception:
        pass
    try:
        session.execute(sa_text("ALTER TABLE prompt_templates ADD COLUMN IF NOT EXISTS programme_scope varchar(32);"))
        session.execute(sa_text("ALTER TABLE prompt_templates ADD COLUMN IF NOT EXISTS response_format varchar(32);"))
        session.execute(sa_text("ALTER TABLE prompt_templates ADD COLUMN IF NOT EXISTS state varchar(32) DEFAULT 'develop';"))
        session.execute(sa_text("ALTER TABLE prompt_templates ADD COLUMN IF NOT EXISTS version integer DEFAULT 1;"))
        session.execute(sa_text("ALTER TABLE prompt_templates ADD COLUMN IF NOT EXISTS note text;"))
        session.execute(sa_text("ALTER TABLE prompt_templates ADD COLUMN IF NOT EXISTS parent_id integer;"))
        try:
            session.execute(sa_text("ALTER TABLE prompt_templates DROP CONSTRAINT IF EXISTS prompt_templates_touchpoint_key;"))
        except Exception:
            pass
        try:
            session.execute(sa_text("DROP INDEX IF EXISTS prompt_templates_touchpoint_key;"))
        except Exception:
            pass
        try:
            session.execute(sa_text("DROP INDEX IF EXISTS uq_prompt_templates_touchpoint;"))
        except Exception:
            pass
        session.execute(sa_text("CREATE UNIQUE INDEX IF NOT EXISTS uq_prompt_templates_touchpoint_state_version ON prompt_templates(touchpoint,state,version);"))
        session.execute(sa_text("UPDATE prompt_templates SET state='beta' WHERE state='stage';"))
        session.execute(sa_text("UPDATE prompt_templates SET state='live' WHERE state='production';"))
        session.execute(sa_text("UPDATE prompt_templates SET version=1 WHERE version IS NULL;"))
    except Exception:
        pass
    try:
        PromptSettings.__table__.create(bind=session.bind, checkfirst=True)
    except Exception:
        pass
    try:
        session.execute(sa_text("ALTER TABLE prompt_settings ADD COLUMN IF NOT EXISTS worker_mode_override boolean;"))
        session.execute(sa_text("ALTER TABLE prompt_settings ADD COLUMN IF NOT EXISTS podcast_worker_mode_override boolean;"))
    except Exception:
        pass
    try:
        PromptTemplateVersionLog.__table__.create(bind=session.bind, checkfirst=True)
    except Exception:
        pass
    # Ensure a singleton settings row exists with defaults
    settings = session.execute(select(PromptSettings)).scalar_one_or_none()
    if not settings:
        session.add(
            PromptSettings(
                system_block="Tone: supportive, conversational; speak directly to the user as their coach. Do not mention background music or sound effects. Do not read out section headers or labels; speak naturally as a flowing message. Do not read or say emoji names; ignore emoji.",
                locale_block="Use British English: UK spelling (favour, programme, behaviour), light British phrasing (have a think, check in, crack on), warm, calm, supportive tone; avoid Americanisms (vacation, sidewalk, awesome, mom); no US cultural refs.",
                default_block_order=DEFAULT_PROMPT_TEMPLATES[0].get("block_order"),
            )
        )
    created = 0
    TARGET_STATES = ["develop", "beta", "live"]
    for tpl in DEFAULT_PROMPT_TEMPLATES:
        base = dict(tpl)
        base_state = base.pop("state", None)  # legacy; ignored for multi-state seeding
        base_version = base.pop("version", 1)
        for st in TARGET_STATES:
            target_state = st
            version_val = base_version or 1
            row = (
                session.execute(
                    select(PromptTemplate).where(
                        PromptTemplate.touchpoint == base["touchpoint"],
                        PromptTemplate.state == target_state,
                        PromptTemplate.version == version_val,
                    )
                ).scalar_one_or_none()
            )
            if row:
                row.okr_scope = base.get("okr_scope")
                row.programme_scope = base.get("programme_scope")
                row.response_format = base.get("response_format")
                row.is_active = base.get("is_active", True)
                row.block_order = base.get("block_order") or row.block_order
                row.include_blocks = base.get("include_blocks") or row.include_blocks
                row.task_block = base.get("task_block") or row.task_block
                row.state = target_state
                row.version = row.version or version_val
            else:
                session.add(PromptTemplate(state=target_state, version=version_val, **base))
                created += 1
    session.commit()
    return created

def upsert_kb_snippets(session: Session) -> int:
    created = 0
    for pillar_key, concepts in KB_SNIPPETS.items():
        for concept_code, items in concepts.items():
            for item in items:
                title = item.get("title") or None
                text  = (item.get("text") or "").strip()
                if not text: continue
                existing = session.execute(
                    select(KbSnippet).where(
                        KbSnippet.pillar_key == pillar_key,
                        KbSnippet.concept_code == concept_code,
                        KbSnippet.title == title,
                        KbSnippet.text == text
                    )
                ).scalar_one_or_none()
                if existing: continue
                session.add(KbSnippet(
                    pillar_key=pillar_key, concept_code=concept_code,
                    title=title, text=text, tags=None, created_at=datetime.utcnow()
                )); created += 1
    session.commit(); return created

def ensure_vectors_for_snippets(session: Session, dim: int | None = None) -> int:
    if dim is None:
        try:
            dim = int(os.getenv("KB_EMBED_DIM", "1536"))
        except Exception:
            dim = 1536
    new_vectors = 0
    snippets = session.execute(select(KbSnippet)).scalars().all()
    for sn in snippets:
        exists = session.execute(select(KbVector).where(KbVector.snippet_id == sn.id)).scalar_one_or_none()
        if exists: continue
        emb = _hash_floats(f"{sn.title or ''} | {sn.text}", dim=dim)
        session.add(KbVector(snippet_id=sn.id, embedding=emb, created_at=datetime.utcnow()))
        new_vectors += 1
    session.commit(); return new_vectors


def upsert_clubs(session: Session) -> int:
    created = 0
    for slug, name in CLUBS:
        row = session.execute(select(Club).where(Club.slug == slug)).scalar_one_or_none()
        if not row:
            session.add(Club(slug=slug, name=name, is_active=True))
            created += 1
    session.commit()
    return created

def get_club_by_slug(session: Session, slug: str) -> Club | None:
    return session.execute(select(Club).where(Club.slug == slug, Club.is_active == True)).scalar_one_or_none()

def upsert_demo_users(session: Session) -> int:
    now = datetime.utcnow()
    created = 0
    for u in DEMO_USERS:
        phone = u.get("phone")
        if not phone:
            continue
        club_slug = (u.get("club_slug") or "healthsense").strip()
        club = get_club_by_slug(session, club_slug)

        if not club:
            # If a referenced club wasn't pre-seeded, create it on the fly
            club = Club(
                slug=club_slug,
                name=club_slug.replace("-", " ").title(),
                is_active=True
            )
            session.add(club)
            session.flush()  # get club.id without committing the whole transaction

        # Always proceed to user upsert (regardless of whether club existed)
        row = session.execute(select(User).where(User.phone == phone)).scalar_one_or_none()
        if not row:
            session.add(User(
                club_id=club.id,
                first_name=u.get("first_name"),
                surname=u.get("surname"),
                phone=phone,
                is_superuser=bool(u.get("is_superuser")),
                admin_role=_seed_admin_role(u),
                **(
                    {"created_on": now, "updated_on": now}
                    if "created_on" in User.__table__.columns and "updated_on" in User.__table__.columns
                    else {}
                ),
            ))
            created += 1
        else:
            updated = False
            # Ensure club is set; if missing, set it (do not overwrite if different)
            if getattr(row, "club_id", None) is None:
                row.club_id = club.id
                updated = True
            # Keep superuser flag in sync (promote to True if seed says so)
            if bool(u.get("is_superuser")) and not getattr(row, "is_superuser", False):
                row.is_superuser = True
                updated = True
            target_role = _seed_admin_role(u)
            if getattr(row, "admin_role", None) != target_role:
                row.admin_role = target_role
                updated = True
            # Ensure first_name/surname are set / corrected
            fn = u.get("first_name")
            sn = u.get("surname")
            if fn is not None and getattr(row, "first_name", None) != fn:
                row.first_name = fn
                updated = True
            if sn is not None and getattr(row, "surname", None) != sn:
                row.surname = sn
                updated = True
            if updated and "updated_on" in User.__table__.columns.keys():
                row.updated_on = now

    session.commit()
    return created


def run_seed() -> None:
    """
    Full seed entrypoint. Safely seeds in the right order and won't crash
    if a helper is missing (it will just skip that step).
    """
    with SessionLocal() as s:
        try:
            # 1) Clubs first (so users.club_id NOT NULL can be satisfied)
            cl = upsert_clubs(s) if 'upsert_clubs' in globals() else 0

            # 2) Pillars / Concepts / Questions
            p  = upsert_pillars(s) if 'upsert_pillars' in globals() else 0
            c  = upsert_concepts(s) if 'upsert_concepts' in globals() else 0
            cq = upsert_concept_questions(s) if 'upsert_concept_questions' in globals() else 0

            # 3) KB snippets / vectors
            keep_kb = os.getenv("KEEP_KB_SNIPPETS_ON_RESET") == "1"
            if keep_kb:
                try:
                    existing_kb = s.execute(sa_text("SELECT 1 FROM kb_snippets LIMIT 1")).first()
                except Exception:
                    existing_kb = None
                if existing_kb:
                    sn = 0
                    kv = 0
                    kb_dim = int(os.getenv("KB_EMBED_DIM", "1536") or 1536)
                    print("[seed] Skipping KB seed (KEEP_KB_SNIPPETS_ON_RESET=1).")
                else:
                    sn = upsert_kb_snippets(s) if 'upsert_kb_snippets' in globals() else 0
                    try:
                        kb_dim = int(os.getenv("KB_EMBED_DIM", "1536"))
                    except Exception:
                        kb_dim = 1536
                    kv = ensure_vectors_for_snippets(s, dim=kb_dim) if 'ensure_vectors_for_snippets' in globals() else 0
            else:
                sn = upsert_kb_snippets(s) if 'upsert_kb_snippets' in globals() else 0
                try:
                    kb_dim = int(os.getenv("KB_EMBED_DIM", "1536"))
                except Exception:
                    kb_dim = 1536
                kv = ensure_vectors_for_snippets(s, dim=kb_dim) if 'ensure_vectors_for_snippets' in globals() else 0

            # 4) Users last (requires clubs)
            u  = upsert_demo_users(s) if 'upsert_demo_users' in globals() else 0
            tp = upsert_touchpoint_defaults(s) if 'upsert_touchpoint_defaults' in globals() else {"created_prefs": 0, "created_defs": 0}

            # 5) Prompt templates
            keep_templates = os.getenv("KEEP_PROMPT_TEMPLATES_ON_RESET") == "1"
            if keep_templates:
                pt = seed_prompt_templates(s)
                print("[seed] Prompt templates kept; upserted missing/updated entries.")
            else:
                pt = seed_prompt_templates(s)

            # Commit once at the end
            s.commit()

            total_concepts = sum(len(v) for v in CONCEPTS.values()) if 'CONCEPTS' in globals() else 'n/a'
            print(f"[seed] Clubs seed complete. new_clubs={cl}")
            print(f"[seed] KB upsert complete. new_snippets={sn}")
            print(f"[seed] Concepts seed complete. pillars={len(PILLARS) if 'PILLARS' in globals() else 'n/a'} "
                  f"concepts={total_concepts} new_concepts={c}")
            print(f"[seed] Concept questions upsert complete. new_questions={cq}")
            print(f"[seed] KB vectors complete. new_vectors={kv} (dim={kb_dim})")
            print(f"[seed] Users seed complete. Created {u} new user(s).")
            print(f"[seed] Touchpoint defaults complete. new_prefs={tp['created_prefs']} new_defs={tp['created_defs']}")
            print(f"[seed] Prompt templates complete. new_templates={pt}")

        except Exception as e:
            s.rollback()
            print(f"[seed] ERROR during seeding: {e}")
            raise
