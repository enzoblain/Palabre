import { useState } from "react";
import { useI18n } from "../i18n";
import { ApiError, type Connection, normalizeServer, pageServer, testConnection } from "../api";

export function Connect({ onConnected }: { onConnected: (conn: Connection) => void }) {
  const { t } = useI18n();
  const [server, setServer] = useState(pageServer ?? "");
  const [token, setToken] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    const conn = { server: normalizeServer(server), token: token.trim() };
    setBusy(true);
    setError(null);
    try {
      await testConnection(conn);
      onConnected(conn);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="connect">
      <form className="connect-card" onSubmit={submit}>
        <div className="brand-mark" aria-hidden="true">P</div>
        <h1>{t("connect.title")}</h1>
        <p className="muted">{t("connect.intro")}</p>
        {!pageServer && (
          <label>
            {t("connect.server")}
            <input autoFocus required value={server} onChange={(e) => setServer(e.target.value)}
              placeholder="http://192.168.1.10:2710" spellCheck={false} autoCapitalize="off" />
          </label>
        )}
        <label>
          {t("connect.token")}
          <input autoFocus={!!pageServer} required type="password" value={token} onChange={(e) => setToken(e.target.value)}
            placeholder={t("connect.tokenPlaceholder")} />
        </label>
        {error && <p className="error">{error}</p>}
        <button className="btn btn-primary" disabled={busy}>{busy ? t("connect.connecting") : t("connect.connect")}</button>
      </form>
    </div>
  );
}
