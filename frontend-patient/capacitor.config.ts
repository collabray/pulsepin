import { CapacitorConfig } from "@capacitor/cli";

// This is the SAME React app that runs in the browser (frontend-patient/
// src/), wrapped by Capacitor to produce real, submittable iOS and
// Android app binaries — not a separate rewrite. `npx cap add ios` /
// `npx cap add android` (see package.json scripts) generate the native
// Xcode/Android Studio projects; `npm run build && npx cap sync` copies
// the freshly built web bundle into them.
//
// REQUIRED before any store submission: change `appId` below to your real
// reverse-DNS identifier — "com.example.pulsepin.patient" is a
// placeholder that both Apple and Google reject on submission. See
// PUBLISHING.md Section 3a/4a.
const config: CapacitorConfig = {
  appId: "com.example.pulsepin.patient",
  appName: "PulsePin",
  webDir: "dist",
  server: {
    // During development, point the native shell at your dev server so
    // you get hot reload on a real device. Remove/comment this out for
    // production builds, where the app serves the built `dist/` bundle
    // from webDir instead of a remote URL.
    // url: "http://192.168.1.50:5173",
    // cleartext: true,
    androidScheme: "https",
  },
  plugins: {
    PushNotifications: {
      presentationOptions: ["badge", "sound", "alert"],
    },
  },
};

export default config;
