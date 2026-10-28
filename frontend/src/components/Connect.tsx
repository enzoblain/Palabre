import { useState } from "react";
import { ApiError, type Connection, normalizeServer, pageServer, testConnection } from "../api";

export function Connect({ onConnected }: { onConnected: (conn: Connection) => void }) {
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
        <h1>Welcome to Palabre</h1>
        <p className="muted">Connect to the Palabre server running on your NAS.</p>
        {!pageServer && (
          <label>
            Server address
            <input autoFocus required value={server} onChange={(e) => setServer(e.target.value)}
              placeholder="http://192.168.1.10:2710" spellCheck={false} autoCapitalize="off" />
          </label>
        )}
        <label>
          Access token
          <input autoFocus={!!pageServer} required type="password" value={token} onChange={(e) => setToken(e.target.value)}
            placeholder="ADMIN_TOKEN from your .env" />
        </label>
        {error && <p className="error">{error}</p>}
        <button className="btn btn-primary" disabled={busy}>{busy ? "Connecting…" : "Connect"}</button>
      </form>
    </div>
  );
}
