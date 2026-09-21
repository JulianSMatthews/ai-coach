# CoachSense Website

Standalone static website files for `coachsense.ai`.

Live hosting verified on 21 September 2026: `coachsense.ai` is still served by the Next.js app. Its middleware rewrites `/` to `healthsense-app/public/coachsense.html`. Until the static-site migration is complete, website updates must also be applied to that file, and images copied into `healthsense-app/public/assets/`. Preserve the app copy's local support and legal links when updating it. Changes in this standalone folder alone do not update the live website.

Render static site settings:

- Root Directory: `coachsense-website`
- Build Command: leave blank or use `echo "static site"`
- Publish Directory: `.`

`index.html` is the main website entry point. `coachsense.html` is kept as a copy for direct compatibility while the website is moved off the app service.

Do not remove the old copy from `healthsense-app/public` until the new Render Static Site and DNS are live.
