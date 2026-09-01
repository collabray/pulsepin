# Publishing PulsePin to the App Store and Play Store

This is a runbook, in the order you'd actually do the work, from "code
builds" to "submitted for review." Each item says whether it's already
done in the codebase, or a business/legal/account step that no codebase
can complete on your behalf -- and for the latter, exactly what to do.

Skipping items marked **required** is the most common cause of rejection
for this category of app specifically (location + health-adjacent data +
anything that looks like it touches emergency services).

---

## 0. Before you touch Xcode/Android Studio

**Required -- deploy a real backend first.** The app currently has no
backend to talk to unless you deploy one. A reviewer testing your app
against `localhost` will see a broken app and reject it for that alone.
Deploy the backend (`docker-compose.yml --profile prod`, see the main
README) to a real HTTPS domain before building the mobile app for
submission.

**Required -- point the native build at it.**
```bash
cd frontend-patient
cp .env.production.example .env.production
# edit .env.production: VITE_API_BASE_URL=https://api.yourrealdomain.com
npm run build
npx cap sync
```
Already fixed in this codebase: native builds now require
`VITE_API_BASE_URL` (see `src/api/client.js`) instead of silently trying
relative URLs that only work on web -- that specific bug would have caused
every network request to fail on a real device and wasted a review cycle
discovering it.

---

## 1. Legal documents (required, blocks submission at both stores)

Both stores require a **live, publicly reachable** privacy policy URL
before you can even fill out the submission form.

Already in the codebase: `frontend-patient/public/privacy-policy.html`
and `public/terms.html` -- real content describing what this app actually
collects (phone number, location, symptoms, device ID, dispatch records),
not generic boilerplate copied from an unrelated app. **You still must:**

1. Fill in the `[OPERATOR NAME]`, `[CONTACT EMAIL]`, and other bracketed
   placeholders in both files.
2. Have a lawyer in your operating jurisdiction review them -- the
   liability clause in `terms.html` is deliberately left as a placeholder
   because getting that wrong for a health/emergency-adjacent app is a
   real risk, not a template-fill exercise.
3. Make sure the URL is live at the same domain the app is built against
   -- once deployed, it'll be at `https://yourdomain.com/privacy-policy.html`
   (served automatically, it's a static file in the app's own build).
   Set `VITE_PRIVACY_POLICY_URL` / `VITE_TERMS_URL` env vars if you want
   the in-app links to point elsewhere (e.g. a dedicated marketing site).

**Both App Store Connect and Google Play Console have a "Data Safety" /
"App Privacy" form** you fill in that must *match* what your privacy
policy says and what the app actually does. Mismatches between the
declared form and actual behavior are a real, common rejection and
post-launch removal reason. Use the "What we collect" list in
`privacy-policy.html` directly as your answer key for both forms.

---

## 2. The emergency-services disclaimer (required, Apple-specific risk)

Apple's App Review Guideline **1.4.1** (physical harm / regulated
services) and **1.4.3** (apps facilitating emergency response) are
manually checked by a human reviewer for anything that looks like it
touches emergency dispatch -- one of the more scrutinized categories in
review, not a rubber-stamp check.

**Already implemented in this codebase:** a mandatory disclaimer screen
(`src/pages/Disclaimer.jsx`) that every user must explicitly acknowledge
before reaching login -- states plainly that the app is not a replacement
for calling local emergency services, explains in plain language what the
app actually does (triage suggestion, hospital routing, human-verified
dispatch), and links to the privacy policy/terms. It's wired as a hard
gate in `src/App.jsx` (`RequireDisclaimer`), not a dismissible toast.

**What you still need to do:**
- Repeat the same message in your **App Store Connect review notes**
  (the private notes field reviewers read, not the public listing) --
  explicitly tell the reviewer: "this app does not perform automated
  emergency dispatch; all dispatch requests are reviewed and confirmed by
  a human dispatcher before a vehicle is sent" (true, per
  `app/api/routes/dispatch.py`'s reverse-call flow) -- reviewers testing
  emergency-adjacent apps specifically look for this and will often try
  to trigger a "fake" dispatch during review.
- Repeat a shorter version in the **public store listing description**
  itself, since Apple guideline 1.4.1 also cares about how the listing
  *represents* the app to users, not just in-app behavior.
- **Do not** describe the app as "dispatches ambulances" or similar in
  marketing copy while `ENABLE_LIVE_DISPATCH=false` (the shipped
  default -- see `SECURITY.md`). Advertising functionality that's gated
  off is a straightforward rejection and, if it slipped through, grounds
  for removal later.

---

## 3. iOS-specific setup

### 3a. Accounts & identifiers (required, your action)
- Apple Developer Program membership ($99/year).
- A real bundle ID -- `capacitor.config.ts` currently ships
  `com.example.pulsepin.patient`, which Apple will reject as a
  placeholder. Change it to your real reverse-DNS identifier (e.g.
  `com.yourcompany.pulsepin`) and re-run `npx cap sync` after changing it.

### 3b. Permission strings (required -- see `MOBILE_BUILDS.md` for exact XML)
Add `NSLocationWhenInUseUsageDescription` (and
`NSLocationAlwaysAndWhenInUseUsageDescription` if you implement background
tracking) to `ios/App/App/Info.plist`, with an accurate, specific
description -- not "this app needs your location." Apple rejects vague
permission strings.

### 3c. Privacy Manifest (required as of 2024 App Store policy)
Apple now requires a `PrivacyInfo.xcprivacy` file declaring your app's use
of any "required reason" APIs. After `npx cap add ios`, add
`ios/App/App/PrivacyInfo.xcprivacy` declaring:
- **UserDefaults** (`NSPrivacyAccessedAPICategoryUserDefaults`) -- used by
  Capacitor Preferences (this app's consent-flag storage,
  `src/state/preferences.js`) and by localStorage-backed auth tokens.
  Reason code `CA92.1` ("access info from same app, per documented
  entitlement") is typically correct here since nothing is shared across
  apps.
- **Location** -- declare that precise location is collected, and select
  the accurate purpose (e.g. "app functionality").
Apple's own guide: https://developer.apple.com/documentation/bundleresources/privacy_manifest_files
This is a genuine, currently-required step that a codebase-level fix
can't complete for you since it lives in the generated native project,
not the shared React source.

### 3d. Export compliance
This app only uses standard TLS/HTTPS (via `fetch`/`WebSocket` against
your backend) -- no custom cryptography. In App Store Connect's export
compliance questionnaire, this typically qualifies for the standard
encryption exemption, but confirm against Apple's current questionnaire
at submission time; rules here occasionally change and this document
can't stay current with that on your behalf.

### 3e. TestFlight before public submission (strongly recommended)
Submit to TestFlight first, install on a real device, and walk through
the disclaimer -> login (needs a real, working SMS provider -- see below)
-> triage -> hospital search (needs real location permission on a real
device, not a simulator) -> dispatch flow end to end. Catching a broken
flow in TestFlight costs you a day; catching it in App Review costs you a
1-2 week resubmission cycle.

---

## 4. Android-specific setup

### 4a. Accounts & identifiers (required, your action)
- Google Play Console account ($25 one-time).
- Real `appId` in `capacitor.config.ts` (same value works for both
  platforms if you want a matching bundle ID/package name, or use a
  separate one -- either is fine, just not the `com.example.*` placeholder).

### 4b. Permissions (required -- see `MOBILE_BUILDS.md` for exact XML)
`ACCESS_FINE_LOCATION`, `ACCESS_COARSE_LOCATION`, and if you implement
background tracking, `ACCESS_BACKGROUND_LOCATION` -- the last one requires
a separate declaration form in Play Console explaining why, reviewed by a
human, with a similarly high rejection rate to Apple's equivalent if the
justification is vague.

### 4c. Data Safety form (required)
Play Console's Data Safety section asks the same "what do you collect and
why" questions as Apple's Privacy Manifest, in a different format. Same
answer key: `privacy-policy.html`'s "What we collect" list.

### 4d. Health-adjacent content review
Google Play has additional policy scrutiny for apps in medical/health
categories. Since this app suggests possible conditions and urgency
levels, expect Play's automated + manual review to flag it for the
medical content policy -- make sure the in-app disclaimer (already
implemented) and store listing are consistent in stating this is not a
diagnostic medical device, which is both true and the thing that keeps
you inside Play's policy.

### 4e. Internal testing track before production
Same reasoning as TestFlight -- use Play Console's internal testing track
first.

---

## 5. Signing & release builds

Not something this codebase can complete for you -- it requires your own
Apple Distribution certificate / Android signing keystore, generated
through Xcode (Product -> Archive) and Android Studio (Build -> Generate
Signed Bundle), or automated later via Fastlane once you have real
credentials to give it. `MOBILE_BUILDS.md` calls this out as a real
remaining task rather than glossing over it.

---

## 6. Store listing assets (required, your action)

Neither store accepts the placeholder icon generated in
`frontend-patient/public/icons/` (a simple geometric cross) as final
branding -- replace with real designed icons at the required sizes before
submission:
- iOS: 1024x1024 App Store icon + the full icon set Xcode's asset
  catalog requires (Xcode will tell you exactly which sizes are missing).
- Android: adaptive icon (foreground + background layers), 512x512
  Play Store listing icon.

Also required: screenshots (real device sizes, both stores), a short
description, and a full description -- write these to accurately reflect
current functionality (see Section 2's warning about not overclaiming
live dispatch).

---

## 7. Final pre-submission checklist

- [ ] Backend deployed to a real HTTPS domain, not localhost
- [ ] `VITE_API_BASE_URL` set and native build rebuilt/synced against it
- [ ] `SMS_PROVIDER` set to a real provider (not `console`) -- a reviewer
      who can't receive a real OTP can't get past login
- [ ] Bundle ID / package name changed from the `com.example.*` placeholder
- [ ] Privacy policy + terms filled in, legally reviewed, live at a public URL
- [ ] iOS Info.plist location strings added
- [ ] iOS PrivacyInfo.xcprivacy added
- [ ] Android manifest permissions added
- [ ] Both stores' Data Safety / App Privacy forms filled in to match
      `privacy-policy.html` exactly
- [ ] Review notes (iOS) explicitly explain the human-verified dispatch flow
- [ ] Store listing copy doesn't overclaim live automated dispatch while
      `ENABLE_LIVE_DISPATCH=false`
- [ ] Real app icons and screenshots, not the placeholder cross glyph
- [ ] Tested end-to-end on a real device via TestFlight / Play internal
      testing track, not just the simulator/emulator
- [ ] `SECURITY_SIGNOFF_COMPLETED` and `ENABLE_LIVE_DISPATCH` reflect your
      actual legal/security review status (see `SECURITY.md`) -- don't flip
      these to `true` just to make the app "feel more complete" for review
