# Apple Review Notes

Use these notes when submitting the iOS build to App Store Connect.

## App purpose

CoachSense is a wellbeing coaching and habit-support app. It provides an assessment, coaching guidance from Gia,
daily habit tracking, and education.

CoachSense is not a medical diagnosis, treatment, emergency, or clinical decision app.

## Native capabilities

- This v1 iOS build does not request Apple Health, camera, or photo library permissions.
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

The reviewer should be able to test:

- Login
- Assessment/home screen
- Gia message
- Preferences
- Support, privacy, terms, and account deletion

## Subscription/payment explanation

CoachSense is currently free to access in this iOS version. No payment, subscription, external checkout, or support-led
subscription setup is offered in the app.

If a future version charges for digital app features, it will use Apple's In-App Purchase before submission.

## Support and deletion

Support URL: https://app.coachsense.ai/support

Privacy URL: https://app.coachsense.ai/privacy

Account deletion is available inside the app at `/delete-account`. A signed-in user can delete their own account and
related assessment, check-in, lesson, coaching, preference, session, and message records from that page.
