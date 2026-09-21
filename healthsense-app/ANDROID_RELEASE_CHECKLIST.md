# CoachSense Android release checklist

This is the release checklist for the first Google Play release of CoachSense.

## Release configuration

- Application name: `CoachSense`
- Application ID: `ai.coachsense.app`
- Version name: `1.0`
- Version code: `1`
- Minimum Android version: API 24 (Android 7.0)
- Target Android version: API 36
- Production URL: `https://app.coachsense.ai`
- Privacy policy: `https://app.coachsense.ai/privacy`
- Support: `https://app.coachsense.ai/support`
- Account deletion: `https://app.coachsense.ai/delete-account`

This release includes all six pillars: Resilience, Recovery, Reflection, Purpose,
Nutrition, and Training. Use [GOOGLE_PLAY_SUBMISSION.md](GOOGLE_PLAY_SUBMISSION.md)
for listing copy, reviewer setup, declaration guidance, and outstanding submission gates.

Keep `EXTENDED_PILLARS_PUBLIC_ENABLED=0` during review. The dedicated Google review
account can access Nutrition and Training. This flag affects Android, iOS, and web:
Google submission can proceed first, but public activation must be coordinated with
Apple approval or preceded by separately implemented platform/version rollout controls.

## Completed in the project

- Android platform and API 36 configuration
- CoachSense launcher icon, adaptive icon, and light/dark splash assets
- Internet-only Android permission set
- Android application backup disabled because the app handles personal wellbeing data
- Debug APK compilation
- Production dependency update and audit

## Build and local test

From `healthsense-app`:

```bash
npm ci
npm run build
npm run cap:sync:android
cd android
./gradlew clean assembleDebug
```

Install the debug APK on a connected Android device:

```bash
adb install -r app/build/outputs/apk/debug/app-debug.apk
```

Test login, onboarding/assessment, all six pillars, preferences in light and dark
mode, Gia messaging, support/privacy/terms, logout, and account deletion. Test Nutrition
and Training assessment, check-ins, persistence after restarting, coaching, and progress
with the reviewer account. Verify ordinary accounts remain gated during review, then
repeat the six-pillar checks with an ordinary account in a release-configured test environment.

## Google Play Console

1. Create the app in Play Console using package name `ai.coachsense.app`.
2. Enrol in Play App Signing.
3. Create and securely back up the upload keystore. Never commit it to this repository.
4. Add a local Gradle signing configuration or sign the release bundle in Android Studio.
5. Build an Android App Bundle with `./gradlew bundleRelease`.
6. Upload the signed `.aab` to **Internal testing** first.
7. Add testers, install from the Play opt-in link, and complete the device test checklist.
8. Complete App content, Data safety, content rating, target audience, ads, and account
   deletion declarations.
9. Supply Google reviewers with a working non-admin Google review account, access to all six
   pillars, and reusable login instructions from GOOGLE_PLAY_SUBMISSION.md.
   Store reviewer credentials only in Play Console, never in this file.
10. Confirm all submission gates in GOOGLE_PLAY_SUBMISSION.md, including public feature
    availability, before releasing the approved production build. Do not assume managed
    publishing or a staged rollout can hold a first production release; check the controls
    available for this app in Play Console before submitting it to production review.

## Suggested store listing

Short description:

> Daily wellbeing coaching, nutrition and training habits in one place.

Release notes:

> Welcome to CoachSense on Android. Explore six wellbeing pillars: Resilience, Recovery,
> Reflection, Purpose, Nutrition and Training. Build daily habits with guided assessments,
> check-ins, personalised coaching and practical learning. Track nutrition habits and
> cardio, strength and mobility, and choose your pillars in Preferences.

Before completing Data safety, verify the declarations against the production services and
privacy policy. The app processes account/contact details, user-entered wellbeing and activity
information (including nutrition and training), app interactions, and authentication/session
data. Declare the complete six-pillar scope and ensure it is available at public release.
