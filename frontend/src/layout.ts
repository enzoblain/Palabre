import { useSyncExternalStore } from "react";

/** From this width up, the app shows projects and conversation side by side. Keep in step with the 900px rules of styles.css. */
export const DESKTOP_MIN_WIDTH_PX = 901;

const DESKTOP_QUERY = `(min-width: ${DESKTOP_MIN_WIDTH_PX}px)`;

function subscribe(onChange: () => void): () => void {
  const query = window.matchMedia(DESKTOP_QUERY);
  query.addEventListener("change", onChange);
  return () => query.removeEventListener("change", onChange);
}

/** True on large screens (two-column layout), false on phones and small tablets. */
export function useIsDesktop(): boolean {
  return useSyncExternalStore(subscribe, () => window.matchMedia(DESKTOP_QUERY).matches);
}
