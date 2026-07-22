# Apple Review Notes

Use these notes when submitting the iOS build to App Store Connect.

## App purpose

CoachSense is a wellbeing coaching and habit-support app. Version 1.1 adds optional Nutrition and Training
pillars to its assessment, coaching guidance, daily habit tracking, and education experience.

CoachSense is not a medical diagnosis, treatment, emergency, or clinical decision app.

## Native capabilities

- This v1.1 iOS build does not request Apple Health, camera, or photo library permissions.
- Biometric trends and urine strip photo screening are disabled for this App Store submission.
- If these features are enabled in a later version, the app will add the relevant native permissions and updated review notes.

## Account access for review

Provide Apple with a live test account before submission:

- Mobile number: +447700900001
- Password: Not required. CoachSense uses SMS code login only.
- Login code: 123456
- Login code instructions: Enter the mobile number above, tap Send login code, then enter 123456.
- User ID: Created automatically when the reviewer requests the code.

Before submission, configure the API service environment variables:

- `APP_REVIEW_DEMO_ENABLED=1`
- `APP_REVIEW_DEMO_PHONE=+447700900001`
- `APP_REVIEW_DEMO_CODE=123456`
- `EXTENDED_PILLARS_PUBLIC_ENABLED=0`

The Apple review demo account is entitled to Nutrition and Training while they remain unavailable to ordinary
production users before approval. This entitlement does not give the demo account administrator permissions.

The reviewer should be able to test:

- Login
- Assessment/home screen
- Gia message
- Preferences
- Nutrition tracking: protein, fruit and vegetables, hydration, and ultra-processed food
- Training tracking: cardio, strength, and mobility
- Support, privacy, terms, and account deletion

Nutrition and Training are enabled automatically when the reviewer signs in. They can also be selected or
deselected from Preferences. Submit version 1.1 using **Manually release this version**. After approval and
before public release, set `EXTENDED_PILLARS_PUBLIC_ENABLED=1`, verify the pillars with an ordinary account,
then release the version in App Store Connect.

## Subscription/payment explanation

CoachSense is currently free to access in this iOS version. No payment, subscription, external checkout, or support-led
subscription setup is offered in the app.

If a future version charges for digital app features, it will use Apple's In-App Purchase before submission.

## Support and deletion

Support URL: https://app.coachsense.ai/support

Privacy URL: https://app.coachsense.ai/privacy

Account deletion is available inside the app at `/delete-account`. A signed-in user can delete their own account and
related assessment, check-in, lesson, coaching, preference, session, and message records from that page.
