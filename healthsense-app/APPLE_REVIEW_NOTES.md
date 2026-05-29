# Apple Review Notes

Use these notes when submitting the iOS build to App Store Connect.

## App purpose

CoachSense is a wellbeing coaching and habit-support app. It provides an assessment, coaching guidance from Gia,
daily habit tracking, education, optional biometric trends, and optional urine strip photo screening.

CoachSense is not a medical diagnosis, treatment, emergency, or clinical decision app.

## Native capabilities

- Camera/photo library: used only when the user chooses to capture or upload a urine strip photo.
- Apple Health: optional read access for resting heart rate, heart rate variability, step count, and exercise minutes.
- HealthKit data is used only to show wellbeing and training-readiness trends inside CoachSense.
- HealthKit data is not sold, used for advertising, or shared with third parties for advertising.

## Account access for review

Provide Apple with a live test account before submission:

- Mobile number:
- Password:
- Login code instructions:
- User ID:

The reviewer should be able to test:

- Login
- Assessment/home screen
- Gia message
- Biometrics modal
- Apple Health permission prompt on a real device
- Urine test photo flow
- Preferences
- Support, privacy, terms, and account deletion request

## Subscription/payment explanation

CoachSense is currently free to access in this iOS version. No payment, subscription, external checkout, or support-led
subscription setup is offered in the app.

If a future version charges for digital app features, it will use Apple's In-App Purchase before submission.

## Support and deletion

Support URL: https://app.healthsense.coach/support

Privacy URL: https://app.healthsense.coach/privacy

Account deletion is available inside the app at `/delete-account`. The request is recorded against the signed-in user
and support verifies identity before completing deletion.
