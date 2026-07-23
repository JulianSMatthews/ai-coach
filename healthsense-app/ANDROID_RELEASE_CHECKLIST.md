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

Nutrition and Training remain disabled for ordinary users while
`EXTENDED_PILLARS_PUBLIC_ENABLED=0`. Do not enable that flag for this Android release.

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

Test login, onboarding/assessment, the four released pillars, preferences in light and dark
mode, Gia messaging, support/privacy/terms, logout, and account deletion. Confirm Nutrition
and Training are not visible to an ordinary account.

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
9. Supply Google reviewers with a working ordinary-user test account and login instructions.
   Store reviewer credentials only in Play Console, never in this file.
10. Promote the tested bundle to production and use a managed/staged rollout.

## Suggested store listing

Short description:

> Build resilience, recovery, reflection and purpose through small daily actions.

Release notes:

> Welcome to CoachSense on Android. Build greater self-awareness and consistency through
> guided assessments, daily check-ins, personalised coaching and practical learning across
> Resilience, Recovery, Reflection and Purpose.

Before completing Data safety, verify the declarations against the production services and
privacy policy. The app processes account/contact details, user-entered wellbeing and activity
information, app interactions, and authentication/session data. Do not declare Nutrition or
Training as released functionality in this version.
