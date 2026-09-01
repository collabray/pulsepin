import { useCallback, useEffect, useRef, useState } from "react";
import { Capacitor } from "@capacitor/core";
import { Geolocation } from "@capacitor/geolocation";

/**
 * Cross-platform location permission flow. On native iOS/Android builds
 * (via Capacitor), uses @capacitor/geolocation, which requests the real
 * platform permission dialog (Info.plist NSLocationWhenInUseUsageDescription
 * on iOS, ACCESS_FINE_LOCATION on Android — see README "Mobile builds" for
 * the manifest/plist entries this requires) and returns actual device GPS,
 * generally more accurate than a browser's geolocation in a WebView. On
 * the web build, falls back to the standard browser Geolocation API. The
 * calling code (Hospitals.jsx, DispatchTracking.jsx) doesn't need to know
 * which platform it's running on — same interface everywhere.
 */
export function useGeolocation() {
  const [status, setStatus] = useState("idle");
  const [position, setPosition] = useState(null);
  const [error, setError] = useState(null);
  const watchIdRef = useRef(null);
  const isNative = Capacitor.isNativePlatform();

  const isSupported = isNative || (typeof navigator !== "undefined" && !!navigator.geolocation);

  const requestOnce = useCallback(async () => {
    if (!isSupported) {
      setStatus("unavailable");
      setError("This platform does not support location services.");
      return;
    }
    setStatus("requesting");

    if (isNative) {
      try {
        const perm = await Geolocation.requestPermissions();
        if (perm.location !== "granted" && perm.coarseLocation !== "granted") {
          setStatus("denied");
          setError("Location permission denied.");
          return;
        }
        const pos = await Geolocation.getCurrentPosition({ enableHighAccuracy: true, timeout: 12000 });
        setPosition({
          latitude: pos.coords.latitude,
          longitude: pos.coords.longitude,
          accuracy: pos.coords.accuracy,
        });
        setStatus("granted");
        setError(null);
      } catch (err) {
        setStatus(err.message?.includes("denied") ? "denied" : "unavailable");
        setError(err.message);
      }
      return;
    }

    navigator.geolocation.getCurrentPosition(
      (pos) => {
        setPosition({
          latitude: pos.coords.latitude,
          longitude: pos.coords.longitude,
          accuracy: pos.coords.accuracy,
        });
        setStatus("granted");
        setError(null);
      },
      (err) => {
        setStatus(err.code === 1 ? "denied" : "unavailable");
        setError(err.message);
      },
      { enableHighAccuracy: true, timeout: 12000, maximumAge: 15000 }
    );
  }, [isSupported, isNative]);

  const startWatching = useCallback(
    async (onUpdate) => {
      if (!isSupported) {
        setStatus("unavailable");
        return;
      }
      setStatus("requesting");

      if (isNative) {
        try {
          const perm = await Geolocation.requestPermissions();
          if (perm.location !== "granted" && perm.coarseLocation !== "granted") {
            setStatus("denied");
            return;
          }
          watchIdRef.current = await Geolocation.watchPosition(
            { enableHighAccuracy: true, timeout: 15000 },
            (pos, err) => {
              if (err) {
                setStatus("unavailable");
                setError(err.message);
                return;
              }
              const next = {
                latitude: pos.coords.latitude,
                longitude: pos.coords.longitude,
                accuracy: pos.coords.accuracy,
                heading: pos.coords.heading,
                speed: pos.coords.speed,
              };
              setPosition(next);
              setStatus("granted");
              setError(null);
              onUpdate?.(next);
            }
          );
        } catch (err) {
          setStatus("unavailable");
          setError(err.message);
        }
        return;
      }

      watchIdRef.current = navigator.geolocation.watchPosition(
        (pos) => {
          const next = {
            latitude: pos.coords.latitude,
            longitude: pos.coords.longitude,
            accuracy: pos.coords.accuracy,
            heading: pos.coords.heading,
            speed: pos.coords.speed,
          };
          setPosition(next);
          setStatus("granted");
          setError(null);
          onUpdate?.(next);
        },
        (err) => {
          setStatus(err.code === 1 ? "denied" : "unavailable");
          setError(err.message);
        },
        { enableHighAccuracy: true, maximumAge: 5000, timeout: 15000 }
      );
    },
    [isSupported, isNative]
  );

  const stopWatching = useCallback(() => {
    if (watchIdRef.current === null) return;
    if (isNative) {
      Geolocation.clearWatch({ id: watchIdRef.current });
    } else {
      navigator.geolocation.clearWatch(watchIdRef.current);
    }
    watchIdRef.current = null;
  }, [isNative]);

  useEffect(() => () => stopWatching(), [stopWatching]);

  return { status, position, error, isSupported, isNative, requestOnce, startWatching, stopWatching };
}

