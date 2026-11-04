import { useRouter } from "expo-router";
import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { api, type ExhaustedAccount } from "../api";
import { usePolling } from "./usePolling";

export const CREDITS_POLL_MS = 15000; // same as the web app

type AppShell = { exhausted: ExhaustedAccount[]; claudeAccounts: number };

const AppShellContext = createContext<AppShell>({ exhausted: [], claudeAccounts: 1 });

export function useAppShell(): AppShell {
  return useContext(AppShellContext);
}

async function pollExhausted(setExhausted: (accounts: ExhaustedAccount[]) => void): Promise<void> {
  try {
    setExhausted((await api.orchestratorStatus()).exhausted_accounts);
  } catch {
    // Keep the last known state: the banner is informative, the list shows its own errors
  }
}

/**
 * State shared by the root screens: the Claude accounts out of credits (polled), and the first-run
 * redirect to Settings while the boss has no name yet.
 */
export function AppShellProvider({ children }: { children: ReactNode }) {
  const router = useRouter();
  const [exhausted, setExhausted] = useState<ExhaustedAccount[]>([]);
  const [claudeAccounts, setClaudeAccounts] = useState(1);

  useEffect(() => {
    api
      .getSettings()
      .then((settings) => {
        setClaudeAccounts(settings.claude_accounts);
        if (!settings.boss_name) router.navigate("/settings"); // the team needs a name for its CEO
      })
      .catch(() => {});
  }, [router]);

  usePolling(() => void pollExhausted(setExhausted), CREDITS_POLL_MS);

  return <AppShellContext.Provider value={{ exhausted, claudeAccounts }}>{children}</AppShellContext.Provider>;
}
