HealthSense Admin is the staff-facing console for operating the HealthSense user app.

## Current Scope

- User Ops: create/search users, open the user app as a user, review onboarding, coaching, and user app state.
- Monitoring: assessment, coaching, app engagement, and infrastructure health.
- Content & onboarding: app intro, assessment intro, library content, and generated media.
- Prompt QA: template editing, test assembly, promotion, and prompt history.
- Messaging: Twilio templates, 24-hour reopen flow, and global prompt schedule.
- Billing: plan catalog and Stripe sync.
- Reporting: launch URLs, marketing funnel, usage, and cost reporting.

## Development

```bash
npm run dev
npm run lint
npm run build
```

Required server-side environment:

- `API_BASE_URL`
- `ADMIN_API_TOKEN`
- `ADMIN_USER_ID`

Optional user app preview environment:

- `NEXT_PUBLIC_HSAPP_BASE_URL`
- `NEXT_PUBLIC_APP_BASE_URL`
- `HSAPP_PUBLIC_URL`

The scripts area is intentionally hidden from production navigation and should be treated as a development diagnostics surface.
