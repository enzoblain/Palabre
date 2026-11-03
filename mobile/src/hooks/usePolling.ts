import { useEffect } from "react";
import { AppState } from "react-native";

/**
 * Calls `callback` now, then every `intervalMs` while the app is in the foreground; paused in the
 * background and called again on return. `callback` must be stable (useCallback).
 */
export function usePolling(callback: () => void, intervalMs: number): void {
  useEffect(() => {
    let timer: ReturnType<typeof setInterval> | undefined;
    const start = () => {
      callback();
      timer ??= setInterval(callback, intervalMs);
    };
    const stop = () => {
      clearInterval(timer);
      timer = undefined;
    };
    if (AppState.currentState !== "background") start();
    const subscription = AppState.addEventListener("change", (state) => (state === "active" ? start() : stop()));
    return () => {
      stop();
      subscription.remove();
    };
  }, [callback, intervalMs]);
}
