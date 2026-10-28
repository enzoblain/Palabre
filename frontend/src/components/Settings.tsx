import { useEffect, useState } from "react";
import { ApiError, type Project, type ProjectDetail, api, getConnection } from "../api";
import { spreadAccounts } from "../util";
import { AccountSelect } from "./AccountSelect";
import { Avatar } from "./Avatar";

export function Settings({ bossName, claudeAccounts, projects, onSaved, onDisconnect }: {
  bossName: string;
  claudeAccounts: number;
  projects: Project[];
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
      <ClaudeAccounts count={claudeAccounts} projects={projects} />
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

function ClaudeAccounts({ count, projects }: { count: number; projects: Project[] }) {
  const [details, setDetails] = useState<ProjectDetail[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    if (count < 2) return;
    Promise.all(projects.map((p) => api.getProject(p.id)))
      .then(setDetails)
      .catch((err) => setError(String(err.message ?? err)));
  }, [count, projects]);

  async function change(projectId: number, employeeId: number, account: number | null) {
    setError(null);
    try {
      const updated = await api.setAccount(employeeId, account);
      setDetails((ds) => ds && ds.map((d) => d.id !== projectId ? d : {
        ...d, employees: d.employees.map((e) => (e.id === employeeId ? updated : e)),
      }));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    }
  }

  return (
    <section className="panel">
      <h2>Claude accounts</h2>
      <p className="muted">
        {count === 0 && "No account configured: set CLAUDE_CODE_OAUTH_TOKENS in the server's .env."}
        {count === 1 && "One account: every agent runs on it. Add more in CLAUDE_CODE_OAUTH_TOKENS, separated by |."}
        {count > 1 && `${count} accounts. Agents are spread evenly over them; pick an account to pin an agent to it.`}
      </p>
      {error && <p className="error">{error}</p>}
      {count > 1 && details?.map((project) => {
        const effective = spreadAccounts(project.employees.map((e) => e.account), count);
        return (
          <div key={project.id} className="account-project">
            <h3>{project.name}</h3>
            <ul className="account-list">
              {project.employees.map((e, i) => (
                <li key={e.id}>
                  <Avatar name={e.name} size={24} />
                  <span className="account-name truncate">{e.name} <span className="muted">· {e.title}</span></span>
                  <AccountSelect value={e.account} effective={effective[i]} count={count}
                    onChange={(account) => change(project.id, e.id, account)} />
                </li>
              ))}
            </ul>
          </div>
        );
      })}
    </section>
  );
}
