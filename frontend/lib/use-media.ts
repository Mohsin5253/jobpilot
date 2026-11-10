"use client";

import { useSyncExternalStore } from "react";

/** True while the media query matches. Server render and first paint report `false`; layout is CSS-driven, so this only steers behaviour. */
export function useMediaQuery(query: string) {
  return useSyncExternalStore(
    (cb) => {
      const mq = matchMedia(query);
      mq.addEventListener("change", cb);
      return () => mq.removeEventListener("change", cb);
    },
    () => matchMedia(query).matches,
    () => false,
  );
}
