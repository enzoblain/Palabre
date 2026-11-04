import { useCallback, useEffect, useRef, useState } from "react";
import { api, type AppSettings } from "../api";

export type AppSettingsState = {
  settings: AppSettings | null; // null until the first load
  failed: boolean;
  reload: () => Promise<void>;
  /** Saves a change and keeps the answer; rejects with the ApiError so the caller can show it. */
  save: (changes: { boss_name?: string; language?: string }) => Promise<void>;
};

/** The server settings (boss name, team language, number of Claude accounts), read once. */
export function useAppSettings(): AppSettingsState {
  const [settings, setSettings] = useState<AppSettings | null>(null);
  const [failed, setFailed] = useState(false);
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    api
      .getSettings()
      .then((loaded) => {
        if (!mounted.current) return;
        setSettings(loaded);
        setFailed(false);
      })
      .catch(() => mounted.current && setFailed(true));
  }, [attempt]);
  const reload = useCallback(async () => setAttempt((count) => count + 1), []);

  const save = useCallback(async (changes: { boss_name?: string; language?: string }) => {
    const saved = await api.saveSettings(changes);
    if (mounted.current) setSettings(saved);
  }, []);

  return { settings, failed, reload, save };
}
