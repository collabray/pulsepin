import { Capacitor } from "@capacitor/core";
import { Preferences } from "@capacitor/preferences";

// Capacitor Preferences persists correctly on native (survives app
// updates, backed by UserDefaults/SharedPreferences); localStorage is the
// right equivalent on web. Used for consent flags that reviewers on both
// platforms will specifically check for during app review — losing this
// on every app restart would mean re-showing (or worse, never showing)
// the disclaimer, either of which is a plausible rejection reason.

export async function getPreference(key) {
  if (Capacitor.isNativePlatform()) {
    const { value } = await Preferences.get({ key });
    return value;
  }
  return localStorage.getItem(key);
}

export async function setPreference(key, value) {
  if (Capacitor.isNativePlatform()) {
    await Preferences.set({ key, value });
  } else {
    localStorage.setItem(key, value);
  }
}
