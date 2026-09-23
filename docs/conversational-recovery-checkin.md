# Spoken Recovery check-in

Open today's **Recovery** card and choose **Talk to your coach**, then **Start
voice conversation**. Grant microphone permission. The coach speaks each reply,
then listens for an answer. Users can answer several tracker questions together,
correct the summary, and say **save** to confirm. A saved check-in leads into a
spoken reflection. Say **pause**, or use the pause button, to end audio capture.
The transcript and a text fallback remain available.

## Current scope

- Recovery only, including optional concepts configured for the user.
- Today's tracker date, using the existing tracker timezone and allowed values.
- Persistent conversation, corrections before saving, and explicit confirmation.
- Existing tracker saving, goal updates, engagement logging and home refresh.
- Reflection grounded in recorded answers, tracker targets and the current week.
- A new date or changed tracker question configuration starts a fresh draft.
- Lessons, quizzes, other pillars and saved follow-up commitments are later work.

## Implementation

`app/pillar_checkin.py` owns the activity state and stores it under the unique
`recovery_conversation_v1` user preference. The model extracts option values with
quoted evidence; the controller validates them and the user reviews them before
the tracker writes anything. Request IDs deduplicate the last 50 retries and a
preference row lock serializes turns on PostgreSQL. Saving uses the existing
tracker upsert. The tracker write and conversation state use separate database
transactions: a process failure between them may require the same save to be
retried, but does not create a second set of daily tracker entries.

The authenticated `/api/v1/users/{user_id}/pillar-checkin` GET/POST endpoints
load and advance the conversation. The `/voice-session` POST endpoint issues an
expiring Azure Speech token; subscription keys stay server-side. The Next.js
proxy requires a signed-in session and does not fall back to admin credentials.
Admin previews cannot write or start a voice session.

`useCheckinVoice.ts` uses the installed Azure Speech SDK for speech recognition
and synthesis. It alternates one spoken answer with one reply, rather than
listening while the coach speaks. Web Audio is activated on the initiating tap.
Microphone tracks are stopped before reply playback, on pause, when the page is
hidden, and when the component unmounts. Speech credentials refresh before
expiry. Raw recordings are not stored by this implementation; transcripts and
model prompt logs use the app's storage. Speech audio is processed by Azure.

## Configuration and validation

Uses the existing `AZURE_AVATAR_KEY` / `AZURE_SPEECH_KEY` and corresponding
region settings from `app/avatar.py`, plus the configured voice and locale.
It requires a Speech resource supporting recognition and synthesis, and does
not require avatar video or its relay service. Uses the existing coaching model
configuration for answer extraction and reflection.

Microphone access requires a secure context (HTTPS or localhost). iOS microphone
purpose text and Android `RECORD_AUDIO` permission are included. Native builds
must be rebuilt to pick up permission changes.

Automated checks:

```sh
.venv/bin/python -m unittest discover -s tests -p 'test_pillar_checkin.py' -v
cd healthsense-app
node --test tests/checkin-voice.test.cjs
./node_modules/.bin/tsc --noEmit --incremental false
./node_modules/.bin/eslint src/components/RecoveryCheckinChat.tsx src/lib/useCheckinVoice.ts src/app/api/pillar-checkin/route.ts
```

Before release, exercise a real signed-in account and microphone on web, iOS and
Android: grant/deny permission, speak multiple answers, correct a misheard
answer, confirm saving aloud, verify tracker values and scores, pause during
audio and loading, resume, and interrupt the network. Automated voice tests use
simulated audio/SDK responses; they do not establish real-device recognition
accuracy, audio quality or permission behavior.

SDK reference: [Microsoft SpeechRecognizer](https://learn.microsoft.com/javascript/api/microsoft-cognitiveservices-speech-sdk/speechrecognizer).
