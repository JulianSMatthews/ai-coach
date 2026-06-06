# CoachSense App Current vs Legacy Report

Last reviewed: 2026-06-06

## Current app surface

- `/` is the current authenticated app home.
- The first screen is the check-in pillar cue surface, with Learn available through the bottom app navigation.
- Current home data comes from pillar tracker state, mainly `/api/v1/users/{user_id}/pillar-tracker` through the frontend `/api/pillar-tracker/summary` proxy.
- Current Learn data comes from `/api/v1/users/{user_id}/education-plan/today` through `/api/education-plan/today`.
- Current supporting areas are preferences, weekly objectives, coach insight, education quiz/video progress, auth, support, privacy, terms, delete account, biometrics preferences, and optional wearable/urine-test capture.

## Legacy or mixed areas

- `/assessment/[userId]/chat` remains a mixed wrapper. It still contains both the old assessment dialog flow and the current check-in/Learn app surface.
- `AssessmentChatBox.tsx` is the main mixed component. It currently includes legacy assessment chat state, lead assessment handling, claim identity, current check-in home, Learn, final coach message, and education quiz UI.
- `/api/assessment/chat/*`, `/api/assessment/report`, `/api/assessment/*avatar*`, and `/ig/start` are assessment/lead-era routes.
- Legacy naming remains in internal code paths, including `assessment`, `Gia`, `HealthSense`, `dashboard`, and KR/OKR wording.
- Historical reporting, seed, and scheduler modules still contain HealthSense/Gia/assessment-era text and should not be treated as current app copy without review.

## Changes made in this cleanup pass

- `/` now calls the app renderer with `forceModernHome: true`.
- The modern home path no longer needs the old assessment-completed flag before rendering the check-in/Learn surface.
- The current home path skips the legacy assessment chat state load, preventing the old dialog textarea from appearing as the default logged-in experience.
- The old `/assessment/[userId]/chat` route remains available for legacy and lead assessment flows.

## Recommended next cleanup

1. Extract check-in home UI from `AssessmentChatBox.tsx` into a dedicated current app component.
2. Extract Learn UI into its own component using the existing education-plan APIs.
3. Leave `AssessmentChatBox.tsx` responsible only for legacy assessment/lead chat.
4. Move current app API proxies into a clearly named current-app grouping where practical.
5. Review remaining visible copy for `HealthSense`, `Gia`, assessment, urine, and Apple Health references before removing backend capabilities.
