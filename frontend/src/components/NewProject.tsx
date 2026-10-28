import { useEffect, useState } from "react";
import { ApiError, type MemberIn, type Mode, type Personality, type ProjectDetail, type ProjectKind, type Role, type TeamMember, type TeamPreview, api } from "../api";
import { go } from "../router";
import { spreadAccounts } from "../util";
import { AccountSelect } from "./AccountSelect";
import { Avatar } from "./Avatar";
import { ShuffleIcon } from "./Icons";
import { TeamEditor, teamProblems } from "./TeamEditor";

const GITHUB_URL = /^(https:\/\/github\.com\/|git@github\.com:)[\w.-]+\/[\w.-]+?(\.git)?\/?$/;
const DEFAULT_MODE: Record<ProjectKind, string> = { company: "startup", research: "panel" };

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
  const [kind, setKind] = useState<ProjectKind>("company");
  const [modes, setModes] = useState<Record<string, Mode> | null>(null);
  const [personality, setPersonality] = useState<Personality | null>(null);
  const [name, setName] = useState("");
  const [repoUrl, setRepoUrl] = useState("");
  const [branch, setBranch] = useState("");
  const [topic, setTopic] = useState("");
  const [mode, setMode] = useState(DEFAULT_MODE.company);
  const research = kind === "research";
  const [team, setTeam] = useState<TeamPreview | null>(null);
  // Team built by hand (null: the team drawn at random is used)
  const [custom, setCustom] = useState<MemberIn[] | null>(null);
  const [roles, setRoles] = useState<Record<string, Role> | null>(null);
  const [names, setNames] = useState<string[]>([]);
  // First name → Claude account chosen by hand; the others are spread automatically
  const [accounts, setAccounts] = useState<Record<string, number>>({});
  // Research: the peer who writes the report (null: drawn at random)
  const [rapporteur, setRapporteur] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api.names().then(setNames).catch(() => {});
  }, []);

  // Each kind of project has its own modes, roles and personality axes
  useEffect(() => {
    setModes(null);
    setRoles(null);
    setPersonality(null);
    setCustom(null);
    setMode(DEFAULT_MODE[kind]);
    api.modes(kind).then(setModes).catch((err) => setError(String(err.message ?? err)));
    api.personality(kind).then(setPersonality).catch(() => {});
    api.roles(kind).then(setRoles).catch(() => {});
  }, [kind]);

  // Building by hand starts from an empty team
  function buildByHand() {
    setCustom((current) => current ?? []);
  }

  function draw(forMode: string) {
    setTeam(null);
    setAccounts({});
    setRapporteur(null);
    api.previewTeam(forMode).then(setTeam).catch((err) => setError(String(err.message ?? err)));
  }
  // Only once the modes of the current kind are known (the mode resets with the kind)
  useEffect(() => {
    if (modes && modes[mode]) draw(mode);
  }, [mode, modes]);

  const repoValid = GITHUB_URL.test(repoUrl.trim());
  const sourceValid = research ? topic.trim().length > 0 : repoValid;
  const problems = custom ? teamProblems(custom, !research) : [];
  const effective = team ? spreadAccounts(team.employees.map((m) => accounts[m.name]), claudeAccounts) : [];

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!team || problems.length) return;
    setBusy(true);
    setError(null);
    try {
      const project = await api.createProject({
        name: name.trim(),
        mode,
        ...(research ? { topic: topic.trim(), rapporteur: custom ? null : rapporteur } : { repo_url: repoUrl.trim(), default_branch: branch.trim() }),
        seed: team.seed,
        accounts: custom ? {} : accounts,
        ...(custom ? { employees: custom.map((m) => ({ ...m, name: m.name.trim() })) } : {}),
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

      <div className="kinds">
        <button type="button" className={`kind${!research ? " selected" : ""}`} onClick={() => setKind("company")}>
          <strong>Software company</strong>
          <span className="muted">A team with roles and a hierarchy builds your app on GitHub.</span>
        </button>
        <button type="button" className={`kind${research ? " selected" : ""}`} onClick={() => setKind("research")}>
          <strong>Research group</strong>
          <span className="muted">Peers search the web, debate and write a sourced report on your topic.</span>
        </button>
      </div>

      <section className="panel">
        <h2>{research ? "Research" : "Project"}</h2>
        <label>
          Name
          <input autoFocus required maxLength={200} value={name} onChange={(e) => setName(e.target.value)}
            placeholder={research ? "Nuclear and climate" : "My product"} />
        </label>
        {research ? (
          <label>
            Topic
            <textarea required rows={4} maxLength={10000} value={topic} onChange={(e) => setTopic(e.target.value)}
              placeholder="What should they investigate? The question, what you want to know, what to focus on…" />
          </label>
        ) : (
          <>
            <label>
              GitHub repository
              <input required value={repoUrl} onChange={(e) => setRepoUrl(e.target.value)} spellCheck={false}
                placeholder="https://github.com/you/your-repo" autoCapitalize="off" />
            </label>
            {repoUrl && !repoValid && <p className="error">Expected a GitHub URL, like https://github.com/owner/repo</p>}
            <label className="narrow">
              Default branch
              <input value={branch} onChange={(e) => setBranch(e.target.value)} spellCheck={false} autoCapitalize="off"
                placeholder="The repository's (main, master…)" />
            </label>
          </>
        )}
      </section>

      <section className="panel">
        <div className="team-head">
          <h2>Your team</h2>
          <div className="segmented" role="tablist">
            <button type="button" role="tab" aria-selected={!custom} className={!custom ? "selected" : ""}
              onClick={() => setCustom(null)}>Random</button>
            <button type="button" role="tab" aria-selected={!!custom} className={custom ? "selected" : ""}
              disabled={!roles || !personality} onClick={buildByHand}>Build my own</button>
          </div>
        </div>
        <p className="muted">
          {research
            ? custom
              ? "Peers of equal standing, each with their own angle. Pick them yourself below."
              : "Peers of equal standing, each with their own angle on the topic."
            : custom
              ? "The company size sets the rules before merging (approvals, QA, CI). Pick the agents yourself below."
              : "The bigger the company, the more roles, and the stricter the rules before merging."}
        </p>
        <div className="modes">
          {modes && modes[mode] &&
            Object.entries(modes).map(([key, m]) => (
              <button type="button" key={key} className={`mode${key === mode ? " selected" : ""}`}
                onClick={() => setMode(key)}>
                <strong>{m.label}</strong>
                {!custom && <span className="mode-size">{teamSize(m)} people</span>}
                <span className="mode-rule">{m.rules[0]}</span>
              </button>
            ))}
        </div>

        {custom && roles && personality ? (
          <TeamEditor members={custom} onChange={setCustom} roles={roles} personality={personality} names={names}
            claudeAccounts={claudeAccounts} />
        ) : (
          <>
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
                  <div className="member-title">
                    {member.title}{research && member.name === rapporteur && " + Rapporteur"}
                  </div>
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
        {research && team && (
          <label className="narrow">
            Rapporteur
            <select value={rapporteur ?? ""} onChange={(e) => setRapporteur(e.target.value || null)}>
              <option value="">Drawn at random</option>
              {team.employees.map((m) => <option key={m.name} value={m.name}>{m.name}</option>)}
            </select>
          </label>
        )}
          </>
        )}
        {research && custom && custom.length > 0 && !custom.some((m) => m.roles.includes("rapporteur")) && (
          <p className="muted">Nobody has the Rapporteur role: one of them will be drawn at random to write the report.</p>
        )}
        {problems.map((problem) => <p key={problem} className="error">{problem}</p>)}
      </section>

      {error && <p className="error">{error}</p>}
      <div className="row actions">
        <button type="button" className="btn" onClick={() => go("/")}>Cancel</button>
        <button className="btn btn-primary" disabled={busy || !team || !name.trim() || !sourceValid || problems.length > 0}>
          {busy ? "Creating…" : research ? "Start the research" : "Create project"}
        </button>
      </div>
    </form>
  );
}
