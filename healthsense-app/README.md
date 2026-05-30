This is the user-facing HealthSense web app built with Next.js and React.

## Capacitor iOS Shell

This repo now includes a Capacitor iOS wrapper under `ios/`.

Important constraint: the current app is server-rendered Next.js and depends on internal `/api/*` routes, so it is not set up as a fully bundled offline Capacitor app. The iOS project is configured as a hosted shell that loads the deployed web app URL instead.

Default hosted URL:

```bash
https://app.healthsense.coach
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
