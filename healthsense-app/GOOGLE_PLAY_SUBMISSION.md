# CoachSense Google Play submission

Prepared for Android 1.0, version code 1, package `ai.coachsense.app`. Confirm the highest
version code already uploaded in Play Console before signing; every new upload needs an
unused, appropriately increasing code. The owner confirmed no Play app, prior build or
existing upload key on 21 September 2026. This document prepares a submission; it does not
record a production deployment, a configured live account, or a Play Console submission.

## Scope and release sequencing

Submit all six pillars: Resilience, Recovery, Reflection, Purpose, Nutrition and Training.
Google preparation and testing come first. The native shell loads `https://app.coachsense.ai`,
so the deployed web app and API are part of the release, not just the Android bundle.

Keep `EXTENDED_PILLARS_PUBLIC_ENABLED=0` while reviewing. Store-review accounts receive
both additional pillars through their account entitlement. Disclose this explicitly below.
The public flag currently enables the pillars for Android, iOS and web together. Before
public release, either coordinate Apple approval and shared activation, or implement and
validate separate rollout controls. A Google-first submission does not require switching
on unreviewed functionality for existing iOS users.

Start with Internal testing and complete any closed-testing/production-access requirements
shown for the developer account. Internal testing is not production approval. Check the
available first-release publishing controls before sending the production release for review;
do not rely on managed publishing or staged rollout being available for the first release.

## Dedicated review account setup

Deploy the API change supporting these environment variables, then configure them privately:

```dotenv
GOOGLE_PLAY_REVIEW_DEMO_ENABLED=1
GOOGLE_PLAY_REVIEW_DEMO_PHONE=<dedicated test number in international format>
GOOGLE_PLAY_REVIEW_DEMO_CODE=<private six-digit reusable code>
EXTENDED_PILLARS_PUBLIC_ENABLED=0
```

Use a distinct phone from `APP_REVIEW_DEMO_PHONE`, unrelated to any real user's account.
Private proposed values have been generated in `../.android-release/google-play-review.env`.
They have not been deployed or used to verify a production login. Confirm the chosen test
number is unused in production before configuring it.
Keep the actual credentials in the API environment and Play Console App access fields,
not this document. Google credentials have no default code. Existing Apple configuration
remains independent. No changes to Apple submission details are needed for Google testing.

The review account is created on the first login-code request with the name Google Reviewer.
The request creates a normal expiring login challenge using the configured reusable code
without sending an SMS. If the challenge expires, request a new one and use the same code.
The account gets Nutrition and Training access, not administrator access. Login enables
both pillars again; preference persistence tests should restart the app without signing out.
Account deletion removes its data; a new login request recreates the review account.

Validate the production login, assessment and all six pillars from the installed Android
app before entering credentials in Play Console. Use only synthetic assessment/check-in
data. Keep the credentials usable throughout review and subsequent store checks.

## App access text

Paste after replacing the placeholders with the verified private values:

> CoachSense requires sign-in. Mobile number: [REVIEW PHONE]. No password is required.
> Select mobile/SMS login, enter that number, tap Send login code, and enter [REVIEW CODE].
> This dedicated review account uses a reusable code; you do not need access to a phone,
> SMS inbox, email account or an external service. If the code request expires, request
> it again and use the same code. No payment is required for this version.
>
> Complete the guided assessment if shown, then explore the home screen, daily check-ins,
> Gia coaching, learning and Preferences. All six pillars are available: Resilience,
> Recovery, Reflection, Purpose, Nutrition and Training. Nutrition covers protein,
> fruit and vegetables, hydration and ultra-processed food. Training covers cardio,
> strength and mobility. Pillars can be selected or deselected in Preferences.
>
> Nutrition and Training are enabled for this review account while the public release
> is being prepared. They are included in the submitted release and will be enabled for
> ordinary users at public launch. The account uses the same features as ordinary users
> and has no administrator permissions. Support, privacy, terms and account deletion are
> available in the app. Account deletion can be tested; requesting another login code
> recreates the test account, after which the assessment may need to be completed again.

## Store listing copy

App name: CoachSense

Short description:

> Daily wellbeing coaching, nutrition and training habits in one place.

Full description:

> Build everyday wellbeing habits with CoachSense, your personal coaching companion.
>
> Explore six pillars: Resilience, Recovery, Reflection, Purpose, Nutrition and Training.
> Start with a guided assessment, choose the areas you want to work on, and use daily
> check-ins, personalised coaching and practical learning to support your progress.
>
> NUTRITION
> Record everyday habits around protein, fruit and vegetables, hydration and
> ultra-processed food. Use check-ins and coaching to reflect on your routines.
>
> TRAINING
> Track cardio, strength and mobility habits and build a more consistent activity routine.
>
> COACHING AND LEARNING
> Get personalised guidance from Gia, the AI wellbeing coach. Explore lessons, reflect on
> your progress and choose which pillars appear in your experience through Preferences.
>
> CoachSense is currently free to access. An account and internet connection are required.
> Nutrition and activity entries are provided by you; no wearable or Health Connect access
> is required.
>
> CoachSense is not a medical device and does not diagnose, treat, cure or prevent any
> medical condition. Consult a qualified healthcare professional for medical advice,
> diagnosis or treatment. CoachSense does not provide emergency support.
>
> Support: https://app.coachsense.ai/support
> Privacy: https://app.coachsense.ai/privacy
> Delete your account: https://app.coachsense.ai/delete-account

Release notes:

> Welcome to CoachSense on Android. Explore six wellbeing pillars: Resilience, Recovery,
> Reflection, Purpose, Nutrition and Training. Build daily habits with guided assessments,
> check-ins, personalised coaching and practical learning. Track nutrition habits and
> cardio, strength and mobility, and choose your pillars in Preferences.

## App content and assets

Suggested category: Health & Fitness. Confirm the actual age audience, ads, content rating
and all other declarations in Play Console against the deployed app.

Health declaration: include Activity and Fitness and Nutrition and Weight Management.
Also assess Sleep Management and Stress Management, Relaxation, Mental Acuity against
the existing Recovery and Resilience features. These are declaration category names,
not claims that CoachSense provides weight-loss treatment or medical services.
Do not select “no health features”. Declare any other applicable features after testing.

Data safety requires a production data-flow review. The privacy policy already mentions
nutrition, activity and AI processing, but that alone does not establish the console answers.
Check personal information (name, phone, optional email, user IDs), health and fitness data,
coaching messages and other user content, app interactions, diagnostic/device data, retention,
deletion and encryption. Verify what hosting, messaging, AI and media providers receive,
and apply Google's collection/sharing definitions rather than assuming all provider
processing is either exempt or shared. No Health Connect permissions are declared by the
current Android manifest; this does not remove the need to declare manually entered health data.

Capture screenshots from the release-configured Android app using synthetic data:
home, Nutrition check-in, Training check-in, Gia/learning, progress and Preferences.
Use actual screen content and verify Nutrition and Training appear in the images.
The existing feature graphic at `../output/imagegen/coachsense-google-play-feature.png`
was visually checked: it is 1024 × 500 and uses general wellbeing coaching copy, with no
four-pillar restriction. It can accompany the expanded scope. Device screenshots still
need to be captured and checked.

## Build and submission gates

Local validation completed on 21 September 2026:

- 13 Python unit tests passed, including independent store credentials and ordinary-login isolation.
- Python compilation and the Next.js production build passed.
- Android `bundleRelease lintRelease` passed using JDK 21 and the new upload key.
- JAR signature verification passed; the upload certificate is self-signed. The verifier also
  emitted archive entry-order/JarInputStream warnings for the Gradle-produced AAB. Play-side
  bundle acceptance has not been tested.
- Packaged app ID, production URL, Android version user-agent and offline error asset checked.
- Signed export: `../output/google-play/coachsense-1.0-1.aab` (3,196,261 bytes).
- SHA-256: `e738a7b082804dcac40f91dbbe4e7f027e23f22ba58f74cc87e4e34eba129b52`.
- No Android device was attached; live login and device flows remain unverified.

Follow ANDROID_RELEASE_CHECKLIST.md for build commands. `bundleRelease` produces
an unsigned bundle unless an upload-key signing configuration is supplied. Never upload
an unsigned bundle or a debug APK as the production release. Sign using the app's existing
upload key if it already has one; do not replace an existing key or create a new app identity.

A new upload key and signing properties were generated locally in `../.android-release/`,
which is excluded from Git and restricted to the local user. Back up the keystore and its
password securely before the first upload; future updates need this upload identity.
The public certificate is `coachsense-upload-certificate.pem` in that directory.
Use Play App Signing for the distribution signing key.

Rebuild the signed bundle from `healthsense-app/android`:

```bash
JAVA_HOME=/opt/homebrew/opt/openjdk@21/libexec/openjdk.jdk/Contents/Home \
COACHSENSE_ANDROID_SIGNING_PROPERTIES="$PWD/../../.android-release/keystore.properties" \
./gradlew bundleRelease lintRelease
```

The local build uses JDK 21; the installed Android Studio JDK 25 is incompatible with
this Gradle wrapper. The output is `android/app/build/outputs/bundle/release/app-release.aab`.

- [x] Confirm no existing app/build/key; generate first upload key and signed version 1 bundle.
- [ ] Back up the private upload key and password securely.
- [ ] Create Play Console app and confirm developer-account production eligibility.
- [ ] Deploy API change and configure private Google review credentials.
- [ ] Verify reusable login on production, including logout/login and expired challenges.
- [ ] Test onboarding and all six pillars on an Android device; verify changes persist.
- [ ] Test selected/deselected pillars, Gia, learning, progress, support and deletion.
- [ ] Confirm non-admin access and ordinary-user behavior under release configuration.
- [ ] Sign the AAB and install via the Play internal-testing opt-in link.
- [ ] Capture and review six-pillar screenshots and feature graphic.
- [ ] Complete Health apps, Data safety, age/content rating, ads and App access declarations.
- [ ] Resolve the shared public flag/Apple release dependency before public Google launch.
- [ ] Submit the correct track in Play Console and record its actual review status.

## Official references

- [Reusable reviewer access](https://support.google.com/googleplay/android-developer/answer/15748846?hl=en)
- [Health declaration categories](https://support.google.com/googleplay/android-developer/answer/14738291?hl=en)
- [Health content policy and description disclaimer](https://support.google.com/googleplay/android-developer/answer/16679511?hl=en-GB)
- [App signing](https://support.google.com/googleplay/android-developer/answer/9842756?hl=en)
