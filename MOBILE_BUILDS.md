# Building PulsePin for iOS and Android

The patient app (`frontend-patient/`) is a single React codebase that runs
three ways:

1. **Web** — `npm run build`, served by nginx/Traefik like any static site.
   Also installable as a PWA (Add to Home Screen) via the manifest in
   `vite.config.js`.
2. **iOS** — the same build, wrapped by [Capacitor](https://capacitorjs.com)
   into a real Xcode project, submittable to the App Store.
3. **Android** — same build, wrapped into a real Android Studio project,
   submittable to the Play Store.

This is the standard, production-real way to ship one React codebase to
all three targets — not a simulation of mobile support. The tradeoff
you're accepting versus a fully native (Swift/Kotlin) app: slightly less
native look-and-feel, but a single codebase, and Capacitor plugins give
genuine access to device GPS, push notifications, and platform APIs
(unlike a plain web view).

## First-time setup

```bash
cd frontend-patient
npm install
npm run build
npx cap add ios       # generates ios/ — requires a Mac with Xcode installed
npx cap add android    # generates android/ — requires Android Studio / the Android SDK
npx cap sync
```

`ios/` and `android/` are real native project directories (not checked
into this repo, since they're generated and often 100+ MB) — running the
commands above creates them locally.

## Required native permission entries

Capacitor does not add these for you — you must add them before the app
will pass App Store / Play Store review or even run without crashing on a
permission request.

### iOS — `ios/App/App/Info.plist`

Add these keys (the description strings are what the OS shows the user in
the permission dialog — required to be accurate and non-generic by Apple's
review guidelines):

```xml
<key>NSLocationWhenInUseUsageDescription</key>
<string>PulsePin needs your location to find the nearest hospital that can treat you and to help an ambulance find you.</string>
<key>NSLocationAlwaysAndWhenInUseUsageDescription</key>
<string>PulsePin uses your location during an active emergency dispatch so responders can track your position.</string>
```

If you enable background location updates for the "ambulance still en
route while the app is backgrounded" case, you'll also need the
`location` value in `UIBackgroundModes` and a stronger justification in
your App Store review notes — background location is one of Apple's most
scrutinized permissions, and a rejected review is the normal first
outcome, not a bug in this codebase.

### Android — `android/app/src/main/AndroidManifest.xml`

```xml
<uses-permission android:name="android.permission.ACCESS_FINE_LOCATION" />
<uses-permission android:name="android.permission.ACCESS_COARSE_LOCATION" />
<!-- Only if you implement background tracking during an active dispatch: -->
<uses-permission android:name="android.permission.ACCESS_BACKGROUND_LOCATION" />
<uses-permission android:name="android.permission.INTERNET" />
<uses-permission android:name="android.permission.POST_NOTIFICATIONS" />
```

Android 10+ additionally requires a runtime justification flow for
background location in the Play Console before publishing — same category
of review friction as iOS, not something this codebase can pre-clear for
you.

## What Capacitor gives you that a plain web app can't

- **Real device GPS** via `@capacitor/geolocation` (wired into
  `src/state/useGeolocation.js` — the same hook works on web and native,
  detecting the platform automatically).
- **A stable per-install device identifier** via `@capacitor/device`
  (`Device.getId()`), used for the Dispatch Confidence Engine's device-
  fingerprinting signal — meaningfully harder to reset than a browser
  localStorage value, though still not a hardware IMEI (no modern mobile
  OS exposes that to apps; see LIMITATIONS.md).
- **Push notifications** via `@capacitor/push-notifications` — scaffolded
  as a dependency but not yet wired to a real push provider (APNs/FCM)
  or backend endpoint; that's a real remaining task, not implemented here
  (see LIMITATIONS.md).

## What's explicitly NOT done here

- No app icons beyond the placeholder cross-glyph generated in
  `public/icons/` — replace with real brand assets before submitting to
  either store.
- No App Store / Play Store listing metadata, screenshots, or privacy
  labels — required before submission, out of scope for a codebase.
- No push notification backend wiring (see above).
- No CI pipeline that builds/signs the native binaries automatically —
  `fastlane` is the standard tool for this once you have real signing
  certificates; not set up here since it requires your Apple Developer
  and Google Play accounts to configure.

## Publishing to the stores

See `PUBLISHING.md` for the complete submission runbook — legal documents,
the in-app emergency-services disclaimer (`src/pages/Disclaimer.jsx`,
already implemented), iOS Privacy Manifest requirements, Android Data
Safety form guidance, and a final pre-submission checklist.
