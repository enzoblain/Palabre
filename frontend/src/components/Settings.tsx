import { useEffect, useState } from "react";
import { ApiError, api, getConnection } from "../api";

export function Settings({ bossName, onSaved, onDisconnect }: {
  bossName: string;
  onSaved: (name: string) => void;
  onDisconnect: () => void;
}) {
  const [name, setName] = useState(bossName);
  const [status, setStatus] = useState<{ ok: boolean; text: string } | null>(null);
  useEffect(() => setName(bossName), [bossName]);

  async function save(e: React.FormEvent) {
    e.preventDefault();
    try {
      const saved = await api.saveSettings(name);
      onSaved(saved.boss_name);
      setStatus({ ok: true, text: "Saved. Your team now knows you by this name." });
    } catch (err) {
      setStatus({ ok: false, text: err instanceof ApiError ? err.message : String(err) });
    }
  }

  return (
    <div className="page">
      <h1>Settings</h1>
      <form className="panel" onSubmit={save}>
        <h2>You</h2>
        <p className="muted">You are the CEO of every project. Your team addresses you by this name.</p>
        {!bossName && <p className="hint">Tell your team what to call you before you start.</p>}
        <label>
          Your name
          <input autoFocus required maxLength={100} value={name} onChange={(e) => setName(e.target.value)}
            placeholder="Your first name" />
        </label>
        <div className="row">
          <button className="btn btn-primary" disabled={!name.trim() || name.trim() === bossName}>Save</button>
          {status && <span className={status.ok ? "success" : "error"}>{status.text}</span>}
        </div>
      </form>
      <section className="panel">
        <h2>Server</h2>
        <p className="muted">Connected to <code>{getConnection()?.server}</code></p>
        <div className="row">
          <button className="btn" onClick={onDisconnect}>Disconnect</button>
        </div>
      </section>
    </div>
  );
}
