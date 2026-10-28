import { useEffect, useState } from "react";
import {
  ApiError, type AppSettings, type Project, type ProjectDetail, type Usage, type UsageEntry, type UsagePeriod,
  type UsageTotals, api,   getConnection,
} from "../api";
import { spreadAccounts } from "../util";
import { AccountSelect } from "./AccountSelect";
import { Avatar } from "./Avatar";

export function Settings({ settings, projects, onSaved, onProjectsChanged, onDisconnect }: {
  settings: AppSettings;
  projects: Project[];
  onSaved: (settings: AppSettings) => void;
  onProjectsChanged: () => void;
  onDisconnect: () => void;
}) {
  const bossName = settings.boss_name;
  const [name, setName] = useState(bossName);
  const [status, setStatus] = useState<{ ok: boolean; text: string } | null>(null);
  useEffect(() => setName(bossName), [bossName]);

  async function save(e: React.FormEvent) {
    e.preventDefault();
    try {
      onSaved(await api.saveSettings({ boss_name: name }));
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
      <TeamLanguage settings={settings} onSaved={onSaved} />
      <ClaudeAccounts count={settings.claude_accounts} projects={projects} />
      <UsageSection />
      <Projects projects={projects} onChanged={onProjectsChanged} />
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

function TeamLanguage({ settings, onSaved }: { settings: AppSettings; onSaved: (settings: AppSettings) => void }) {
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  async function change(language: string) {
    setError(null);
    setSaved(false);
    try {
      onSaved(await api.saveSettings({ language }));
      setSaved(true);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    }
  }

  return (
    <section className="panel">
      <h2>Team language</h2>
      <p className="muted">Your agents speak and write in this language: messages, tasks, reviews and documents.</p>
      <div className="row">
        <select value={settings.language} onChange={(e) => change(e.target.value)} aria-label="Team language">
          {Object.entries(settings.languages).map(([key, label]) => (
            <option key={key} value={key}>{label}</option>
          ))}
        </select>
        {saved && <span className="success">Saved. It applies from their next message.</span>}
        {error && <span className="error">{error}</span>}
      </div>
    </section>
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

function Projects({ projects, onChanged }: { projects: Project[]; onChanged: () => void }) {
  const [confirming, setConfirming] = useState<number | null>(null);
  const [deleting, setDeleting] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function remove(project: Project) {
    setDeleting(project.id);
    setError(null);
    try {
      await api.deleteProject(project.id);
      setConfirming(null);
      onChanged();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setDeleting(null);
    }
  }

  return (
    <section className="panel">
      <h2>Projects</h2>
      <p className="muted">
        The branch is where the team's tasks start from and their PRs are merged: give them a
        <code>dev</code> branch and merge it into <code>main</code> yourself when a step is ready.
        A new branch is created on GitHub from the current one.
      </p>
      <p className="muted">
        Deleting a project removes its agents, conversations, tasks, reports and files on the server.
        A GitHub repository is left as it is.
      </p>
      {error && <p className="error">{error}</p>}
      {projects.length === 0 && <p className="muted">No project.</p>}
      <ul className="project-list">
        {projects.map((p) => (
          <li key={p.id}>
            <span className="project-initial">{p.name.slice(0, 1).toUpperCase()}</span>
            <span className="truncate project-list-name">
              {p.name} <span className="muted">· {p.kind === "research" ? "research" : p.mode}</span>
            </span>
            {p.kind === "company" && confirming !== p.id && <BranchField project={p} onChanged={onChanged} />}
            {confirming === p.id ? (
              <span className="row confirm-delete">
                <span className="error">Delete it and all its data?</span>
                <button className="btn btn-small" onClick={() => setConfirming(null)} disabled={deleting === p.id}>Cancel</button>
                <button className="btn btn-small btn-danger" onClick={() => remove(p)} disabled={deleting === p.id}>
                  {deleting === p.id ? "Deleting…" : "Delete for good"}
                </button>
              </span>
            ) : (
              <button className="btn btn-small" onClick={() => setConfirming(p.id)}>Delete</button>
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}

function BranchField({ project, onChanged }: { project: Project; onChanged: () => void }) {
  const [editing, setEditing] = useState(false);
  const [branch, setBranch] = useState(project.default_branch);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function save(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    setError(null);
    try {
      await api.changeBranch(project.id, branch.trim());
      setEditing(false);
      onChanged();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  }

  if (!editing) {
    return (
      <button className="btn btn-small" title="The branch the team works from and merges into"
        onClick={() => { setBranch(project.default_branch); setEditing(true); }}>
        <code>{project.default_branch}</code>
      </button>
    );
  }
  return (
    <form className="row branch-field" onSubmit={save}>
      <input autoFocus required value={branch} onChange={(e) => setBranch(e.target.value)} spellCheck={false}
        autoCapitalize="off" aria-label="Branch" />
      <button type="button" className="btn btn-small" onClick={() => setEditing(false)} disabled={saving}>Cancel</button>
      <button className="btn btn-small btn-primary" disabled={saving || !branch.trim()}>{saving ? "Saving…" : "Save"}</button>
      {error && <span className="error">{error}</span>}
    </form>
  );
}

const PERIODS: { key: UsagePeriod; label: string }[] = [
  { key: "day", label: "Day" },
  { key: "week", label: "Week" },
  { key: "total", label: "Total" },
];
const number = new Intl.NumberFormat();

function UsageSection() {
  const [usage, setUsage] = useState<Usage | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [period, setPeriod] = useState<UsagePeriod>("week");
  useEffect(() => {
    api.getUsage().then(setUsage).catch((err) => setError(err instanceof ApiError ? err.message : String(err)));
  }, []);

  return (
    <section className="panel">
      <h2>Usage</h2>
      <p className="muted">
        Runs, tokens and estimated cost reported by Claude. Day is today (UTC), week the last 7 days.
      </p>
      <div className="row" role="group" aria-label="Period">
        {PERIODS.map((p) => (
          <button key={p.key} className={`btn btn-small${p.key === period ? " btn-primary" : ""}`}
            aria-pressed={p.key === period} onClick={() => setPeriod(p.key)}>{p.label}</button>
        ))}
      </div>
      {error && <p className="error">{error}</p>}
      {!usage && !error && <p className="muted">Loading…</p>}
      {usage && usage.total.runs === 0 && <p className="muted">No agent run yet: usage will show up here.</p>}
      {usage && usage.total.runs > 0 && (
        <>
          <UsageTable title="By account" what="Account" period={period} entries={usage.accounts}
            label={(e) => (e.id === null ? "Unknown" : `Account ${e.id}`)} />
          <UsageTable title="By employee" what="Employee" period={period} entries={usage.employees}
            label={(e) => e.name ?? `Employee ${e.id}`} />
          <UsageTable title="By project" what="Project" period={period} entries={usage.projects}
            label={(e) => e.name ?? `Project ${e.id}`} />
          <UsageSummary totals={usage[period]} />
        </>
      )}
    </section>
  );
}

function cost(t: UsageTotals) {
  if (t.runs_without_cost >= t.runs) return "–";
  return `${t.runs_without_cost > 0 ? "≥ " : ""}$${t.cost_usd.toFixed(2)}`;
}

function UsageSummary({ totals }: { totals: UsageTotals }) {
  if (totals.runs_without_tokens === 0 && totals.runs_without_cost === 0) return null;
  return (
    <p className="muted">
      {totals.runs_without_tokens} of {totals.runs} runs reported no tokens and {totals.runs_without_cost} no cost:
      they are left out of the sums.
    </p>
  );
}

function UsageTable({ title, what, period, entries, label }: {
  title: string;
  what: string;
  period: UsagePeriod;
  entries: UsageEntry[];
  label: (e: UsageEntry) => string;
}) {
  const rows = entries.filter((e) => e[period].runs > 0);
  return (
    <div className="usage-block">
      <h3>{title}</h3>
      {rows.length === 0 ? <p className="muted">No run over this period.</p> : (
        <table className="usage-table">
          <thead>
            <tr>
              <th scope="col">{what}</th>
              <th scope="col" className="num">Runs</th>
              <th scope="col" className="num">Input</th>
              <th scope="col" className="num">Output</th>
              <th scope="col" className="num">Cache</th>
              <th scope="col" className="num">Cost</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((e) => {
              const t = e[period];
              return (
                <tr key={e.id ?? "none"}>
                  <th scope="row" className="truncate">{label(e)}</th>
                  <td className="num">{number.format(t.runs)}</td>
                  <td className="num">{number.format(t.input_tokens)}</td>
                  <td className="num">{number.format(t.output_tokens)}</td>
                  <td className="num">{number.format(t.cache_creation_tokens + t.cache_read_tokens)}</td>
                  <td className="num">{cost(t)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
    </div>
  );
}
