import { useEffect, useState } from "react";
import { ApiError, type Mode, type Personality, type ProjectDetail, type TeamMember, type TeamPreview, api } from "../api";
import { go } from "../router";
import { spreadAccounts } from "../util";
import { AccountSelect } from "./AccountSelect";
import { Avatar } from "./Avatar";
import { ShuffleIcon } from "./Icons";

const GITHUB_URL = /^(https:\/\/github\.com\/|git@github\.com:)[\w.-]+\/[\w.-]+?(\.git)?\/?$/;

function teamSize(mode: Mode): number {
  return mode.seats.reduce((n, seat) => n + (seat.count ?? 1), 0);
}

/** The strongest opinions of an employee, e.g. ["bold", "quality"]. */
function traitChips(member: TeamMember, personality: Personality | null): { text: string; strong: boolean }[] {
  if (!personality) return [];
  return personality.axes
    .map((axis) => ({ axis, level: member.traits[axis.key] ?? 0 }))
    .filter(({ level }) => level !== 0)
    .sort((a, b) => Math.abs(b.level) - Math.abs(a.level))
    .slice(0, 3)
    .map(({ axis, level }) => ({
      text: (level > 0 ? axis.high : axis.low).split(" — ")[0],
      strong: Math.abs(level) === 2,
    }));
}

export function NewProject({ claudeAccounts, onCreated }: {
  claudeAccounts: number;
  onCreated: (project: ProjectDetail) => void;
}) {
  const [modes, setModes] = useState<Record<string, Mode> | null>(null);
  const [personality, setPersonality] = useState<Personality | null>(null);
  const [name, setName] = useState("");
  const [repoUrl, setRepoUrl] = useState("");
  const [branch, setBranch] = useState("main");
  const [mode, setMode] = useState("startup");
  const [team, setTeam] = useState<TeamPreview | null>(null);
  // First name → Claude account chosen by hand; the others are spread automatically
  const [accounts, setAccounts] = useState<Record<string, number>>({});
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api.modes().then(setModes).catch((err) => setError(String(err.message ?? err)));
    api.personality().then(setPersonality).catch(() => {});
  }, []);

  function draw(forMode: string) {
    setTeam(null);
    setAccounts({});
    api.previewTeam(forMode).then(setTeam).catch((err) => setError(String(err.message ?? err)));
  }
  useEffect(() => draw(mode), [mode]);

  const repoValid = GITHUB_URL.test(repoUrl.trim());
  const effective = team ? spreadAccounts(team.employees.map((m) => accounts[m.name]), claudeAccounts) : [];

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!team) return;
    setBusy(true);
    setError(null);
    try {
      const project = await api.createProject({
        name: name.trim(),
        repo_url: repoUrl.trim(),
        mode,
        default_branch: branch.trim() || "main",
        seed: team.seed,
        accounts,
      });
      onCreated(project);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
      setBusy(false);
    }
  }

  return (
    <form className="page new-project" onSubmit={submit}>
      <h1>New project</h1>

      <section className="panel">
        <h2>Project</h2>
        <label>
          Name
          <input autoFocus required maxLength={200} value={name} onChange={(e) => setName(e.target.value)}
            placeholder="My product" />
        </label>
        <label>
          GitHub repository
          <input required value={repoUrl} onChange={(e) => setRepoUrl(e.target.value)} spellCheck={false}
            placeholder="https://github.com/you/your-repo" autoCapitalize="off" />
        </label>
        {repoUrl && !repoValid && <p className="error">Expected a GitHub URL, like https://github.com/owner/repo</p>}
        <label className="narrow">
          Default branch
          <input value={branch} onChange={(e) => setBranch(e.target.value)} spellCheck={false} />
        </label>
      </section>

      <section className="panel">
        <h2>Your team</h2>
        <p className="muted">The bigger the company, the more roles, and the stricter the rules before merging.</p>
        <div className="modes">
          {modes &&
            Object.entries(modes).map(([key, m]) => (
              <button type="button" key={key} className={`mode${key === mode ? " selected" : ""}`}
                onClick={() => setMode(key)}>
                <strong>{m.label}</strong>
                <span className="mode-size">{teamSize(m)} people</span>
                <span className="mode-rule">{m.rules[0]}</span>
              </button>
            ))}
        </div>

        <div className="team-head">
          <h3>Drawn at random</h3>
          <button type="button" className="btn btn-small" onClick={() => draw(mode)} disabled={!team}>
            <ShuffleIcon size={14} /> Draw another team
          </button>
        </div>
        {team ? (
          <ul className="team-grid">
            {team.employees.map((member, i) => (
              <li key={member.name} className="member-card">
                <Avatar name={member.name} size={36} />
                <div>
                  <div className="member-name">{member.name} <span className="badge">{member.model}</span></div>
                  <div className="member-title">{member.title}</div>
                  <div className="chips">
                    {traitChips(member, personality).map((chip) => (
                      <span key={chip.text} className={`chip${chip.strong ? " chip-strong" : ""}`}>{chip.text}</span>
                    ))}
                    <span className="chip chip-style">{member.style.tone}</span>
                  </div>
                  {claudeAccounts > 1 && (
                    <AccountSelect value={accounts[member.name] ?? null} effective={effective[i]} count={claudeAccounts}
                      onChange={(account) => setAccounts(({ [member.name]: _, ...rest }) =>
                        account === null ? rest : { ...rest, [member.name]: account })} />
                  )}
                </div>
              </li>
            ))}
          </ul>
        ) : (
          <p className="muted">Drawing a team…</p>
        )}
      </section>

      {error && <p className="error">{error}</p>}
      <div className="row actions">
        <button type="button" className="btn" onClick={() => go("/")}>Cancel</button>
        <button className="btn btn-primary" disabled={busy || !team || !name.trim() || !repoValid}>
          {busy ? "Creating…" : "Create project"}
        </button>
      </div>
    </form>
  );
}
