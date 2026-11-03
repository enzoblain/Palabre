import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { ApiError, clearConnection, isSecureServer, normalizeServer, pairDevice, restoreConnection, saveConnection, setUnauthorizedHandler } from "../api";
import { translate } from "../i18n";

/** "loading": reading secure storage; "signedOut": show the sign-in screen; "signedIn": show the app. */
export type SessionStatus = "loading" | "signedOut" | "signedIn";

export type SessionState = {
  status: SessionStatus;
  /** Last server used, kept in memory so that a signed-out user does not retype it. */
  server: string;
  /** True when the sign-out comes from a 401 (revoked or expired device), not from the user. */
  expired: boolean;
};

export type Session = SessionState & {
  /** Pairs the phone and stores the device token; throws an ApiError with a translated message. */
  signIn: (server: string, accessCode: string, deviceName: string) => Promise<void>;
  signOut: () => Promise<void>;
};

const INITIAL_STATE: SessionState = { status: "loading", server: "", expired: false };

/**
 * Pairs with the server then stores the device token. The access code only lives in this call:
 * it is neither stored nor logged, and nothing is stored when the pairing fails.
 */
export async function pairAndStore(server: string, accessCode: string, deviceName: string): Promise<string> {
  const normalized = normalizeServer(server);
  if (!isSecureServer(normalized)) throw new ApiError(0, translate("api.insecureServer"));
  const connection = await pairDevice(normalized, accessCode, deviceName.trim());
  await saveConnection(connection);
  return connection.server;
}

const SessionContext = createContext<Session | null>(null);

export function SessionProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<SessionState>(INITIAL_STATE);

  useEffect(() => {
    setUnauthorizedHandler(() => {
      void clearConnection();
      setState((previous) => ({ ...previous, status: "signedOut", expired: true }));
    });
    void restoreConnection()
      .catch(() => null)
      .then((connection) =>
        setState({ status: connection ? "signedIn" : "signedOut", server: connection?.server ?? "", expired: false }),
      );
  }, []);

  const signIn = useCallback(async (server: string, accessCode: string, deviceName: string) => {
    const pairedServer = await pairAndStore(server, accessCode, deviceName);
    setState({ status: "signedIn", server: pairedServer, expired: false });
  }, []);

  const signOut = useCallback(async () => {
    await clearConnection();
    setState((previous) => ({ ...previous, status: "signedOut", expired: false }));
  }, []);

  const session = useMemo(() => ({ ...state, signIn, signOut }), [state, signIn, signOut]);
  return <SessionContext.Provider value={session}>{children}</SessionContext.Provider>;
}

export function useSession(): Session {
  const session = useContext(SessionContext);
  if (!session) throw new Error("useSession must be used inside SessionProvider");
  return session;
}
