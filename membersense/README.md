# MemberSense

MemberSense is a separate internal gym member-assistance app. It uses Twilio SMS to send members a secure in-app survey link, while keeping its own database tables, configuration, admin routes, and survey logic.

## What It Covers

- New member survey: identifies confidence, barriers, support need, and whether staff should follow up.
- Inactive member check-in: asks why someone is not training and whether a reset plan, class, or trainer check-in would help.
- Exit survey: records why someone is leaving and whether there is a save or win-back opportunity.
- SMS survey links: each survey is completed in a browser from the link sent to the member.
- In-app survey links: each survey link can also be opened manually or emailed when a member has email but no mobile.
- Staff tasks: survey answers are classified into open follow-up tasks when action is useful.
- CSV import: member data can be loaded from a gym system export.

## Run Locally

```bash
python run_membersense.py
```

The admin tool runs at:

```text
http://localhost:8010/admin
```

By default SMS sends are in dry-run mode, so messages are printed rather than sent.

Local configuration is read from:

```text
membersense/.env.local
```

That file is ignored by git, so live Twilio credentials should go there rather than into tracked files.

## Environment

```bash
MEMBERSENSE_DATABASE_URL=sqlite:///./membersense.db
MEMBERSENSE_ADMIN_TOKEN=change-me
MEMBERSENSE_DRY_RUN=1
MEMBERSENSE_DEFAULT_COUNTRY_CODE=44
MEMBERSENSE_GYM_NAME="Anytime Fitness High Wycombe"

MEMBERSENSE_TWILIO_ACCOUNT_SID=...
MEMBERSENSE_TWILIO_AUTH_TOKEN=...
MEMBERSENSE_TWILIO_FROM=+441234567890
MEMBERSENSE_TWILIO_MESSAGING_SERVICE_SID=
MEMBERSENSE_PUBLIC_BASE_URL=https://your-public-url.example

MEMBERSENSE_NGROK=1
MEMBERSENSE_NGROK_DOMAIN=healthsenseapi.ngrok.app
MEMBERSENSE_NGROK_AUTHTOKEN=
MEMBERSENSE_NGROK_RETRY_SECONDS=60
MEMBERSENSE_KILL_NGROK_ON_START=0
```

Set `MEMBERSENSE_DRY_RUN=0` only when Twilio credentials and an SMS-capable sender or Messaging Service SID are ready.
When `MEMBERSENSE_NGROK=1`, `python run_membersense.py` starts an ngrok tunnel before Uvicorn. It uses `MEMBERSENSE_NGROK_AUTHTOKEN`, or falls back to `API_NGROK_AUTHTOKEN` / `NGROK_AUTHTOKEN` from the root env.

## Twilio Webhooks

Point the Twilio SMS inbound webhook to:

```text
https://your-public-url.example/webhooks/twilio
```

The status callback is generated automatically from `MEMBERSENSE_PUBLIC_BASE_URL`:

```text
https://your-public-url.example/webhooks/twilio-status
```

In-app survey links use the same public base URL:

```text
https://your-public-url.example/s/{survey-token}
```

## Render Deployment

MemberSense is defined as its own Python web service in the repo-level `render.yaml`.
It uses a separate Render Postgres database named `membersense-db`.

On first deploy:

1. Open the `membersense` service in Render and confirm it is healthy at `/healthz`.
2. Keep `MEMBERSENSE_DRY_RUN=1` until the SMS sender is configured.
3. Add either an SMS-capable `MEMBERSENSE_TWILIO_FROM` number or `MEMBERSENSE_TWILIO_MESSAGING_SERVICE_SID`.
4. Set the Twilio SMS inbound webhook to `https://your-membersense-url.onrender.com/webhooks/twilio`.
5. Copy `MEMBERSENSE_ADMIN_TOKEN` from the Render environment and open `/admin/setup?token=...` to create the first staff account.
6. After a successful SMS test, change `MEMBERSENSE_DRY_RUN` to `0`.

Render sets `RENDER_EXTERNAL_URL` automatically, and MemberSense uses it for survey links unless `MEMBERSENSE_PUBLIC_BASE_URL` is set manually for a custom domain.

## CSV Columns

Accepted import columns include:

- `phone`, `mobile`, or `phone_e164`
- `first_name`, `last_name`
- `email`
- `status` or `membership_status`
- `join_date`
- `last_visit_date`
- `cancellation_date`

Dates can be `YYYY-MM-DD`, `DD/MM/YYYY`, `DD-MM-YYYY`, or `MM/DD/YYYY`.

The expired-member import only imports rows whose expiry date, or cancellation date fallback, is less than 60 days ago.
