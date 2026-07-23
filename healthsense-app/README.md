This is the user-facing HealthSense web app built with Next.js and React.

## Capacitor iOS Shell

This repo now includes a Capacitor iOS wrapper under `ios/`.

Important constraint: the current app is server-rendered Next.js and depends on internal `/api/*` routes, so it is not set up as a fully bundled offline Capacitor app. The iOS project is configured as a hosted shell that loads the deployed web app URL instead.

Default hosted URL:

```bash
https://app.coachsense.ai
```

Override it for a different hosted environment when syncing the native project:

```bash
CAP_SERVER_URL=https://your-hosted-app.example.com npm run cap:sync:ios
```

Useful commands:

```bash
npm run cap:sync:ios
npm run cap:open:ios
npm run cap:run:ios
```

If you need a fully bundled native app later, the app will need a broader migration away from server-only Next.js rendering and internal Next API routes.

Current limitation: external checkout and wearable OAuth flows still return through the hosted web app, so they are not yet wired as native deep-link callbacks. The iOS shell works, but those flows are still web-session-first rather than native-first.

For the v1 App Store submission, biometric integrations are disabled by default. The iOS target does not include
HealthKit entitlement, HealthKit plugin registration, Camera plugin dependency, or camera/photo/HealthKit purpose
strings. The web UI can be re-enabled later with `NEXT_PUBLIC_BIOMETRICS_ENABLED=1`, but a future iOS release should
also restore the native permissions/plugins and updated App Review notes before submitting those features.

## Capacitor Android Shell

The native Android project lives under `android/` and uses the same hosted-shell architecture and application ID as iOS.
It targets Android API 36 with a minimum API level of 24.

Prerequisites:

- Android Studio with the Android 16/API 36 SDK
- Java 21 or the compatible JDK bundled with Android Studio

Useful commands:

```bash
npm run cap:sync:android
npm run cap:open:android
npm run cap:run:android
```

To build from the command line after Java and the Android SDK are configured:

```bash
cd android
./gradlew assembleDebug
./gradlew bundleRelease
```

Release keystores and `local.properties` are intentionally excluded from version control.

## Getting Started

First, run the development server:

```bash
npm run dev
# or
yarn dev
# or
pnpm dev
# or
bun dev
```

Open [http://localhost:3000](http://localhost:3000) with your browser to see the result.

## Learn More

To learn more about Next.js, take a look at the following resources:

- [Next.js Documentation](https://nextjs.org/docs) - learn about Next.js features and API.
- [Learn Next.js](https://nextjs.org/learn) - an interactive Next.js tutorial.

You can check out [the Next.js GitHub repository](https://github.com/vercel/next.js).
