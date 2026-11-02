import { useEffect, useRef, useState } from "react";
import { ApiError, type MemberIn, type Mode, type Personality, type PersonalityPreset, type ProjectDetail, type CatalogLimits, type ProjectKind, type Role, type TeamPreview, api } from "../api";
import { useI18n } from "../i18n";
import { go } from "../router";
import { autoTeamProblems, teamProblems } from "../jobs";
import { CompanyTeamSection, type CreationMode } from "./CompanyTeamSection";
import { ResearchTeamSection } from "./ResearchTeamSection";
import { mandatoryMember, problemMessages } from "./TeamEditor";

const GITHUB_URL = /^(https:\/\/github\.com\/|git@github\.com:)[\w.-]+\/[\w.-]+?(\.git)?\/?$/;
const DEFAULT_MODE: Record<ProjectKind, string> = { company: "startup", research: "panel" };

export function NewProject({ claudeAccounts, onCreated }: {
  claudeAccounts: number;
  onCreated: (project: ProjectDetail) => void;
}) {
  const { t } = useI18n();
  const [kind, setKind] = useState<ProjectKind>("company");
  const [modes, setModes] = useState<Record<string, Mode> | null>(null);
  const [personality, setPersonality] = useState<Personality | null>(null);
  const [presets, setPresets] = useState<Record<string, PersonalityPreset> | null>(null);
  const [name, setName] = useState("");
  const [repoUrl, setRepoUrl] = useState("");
  const [topic, setTopic] = useState("");
  const [mode, setMode] = useState(DEFAULT_MODE.company);
  // Company: the team is hired from a description (auto) or listed by hand (manual)
  const [creation, setCreation] = useState<CreationMode>("auto");
  const [description, setDescription] = useState("");
  const [employeeCount, setEmployeeCount] = useState<number | null>(null);
  const research = kind === "research";
  const [team, setTeam] = useState<TeamPreview | null>(null);
  // Team built by hand (null: the team drawn at random is used)
  const [custom, setCustom] = useState<MemberIn[] | null>(null);
  const [roles, setRoles] = useState<Record<string, Role> | null>(null);
  const [names, setNames] = useState<string[]>([]);
  const [limits, setLimits] = useState<CatalogLimits | null>(null);
  // First name → Claude account chosen by hand; the others are spread automatically
  const [accounts, setAccounts] = useState<Record<string, number>>({});
  // Research: the peer who writes the report (null: drawn at random)
  const [rapporteur, setRapporteur] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [presetsFailed, setPresetsFailed] = useState(false);
  const [busy, setBusy] = useState(false);
  // Identifies the latest presets request: a late answer from an earlier one is ignored
  const presetsRequest = useRef(0);

  useEffect(() => {
    api.names().then(setNames).catch(() => {});
    api.limits().then(setLimits).catch(() => {});
  }, []);

  // Each kind of project has its own modes, roles and personality axes
  useEffect(() => {
    setModes(null);
    setRoles(null);
    setPersonality(null);
    setPresets(null);
    setCustom(null);
    setMode(DEFAULT_MODE[kind]);
    setCreation("auto");
    api.modes(kind).then(setModes).catch((err) => setError(String(err.message ?? err)));
    api.personality(kind).then(setPersonality).catch(() => {});
    loadPresets(kind);
    api.roles(kind).then(setRoles).catch(() => {});
  }, [kind]);

  // A failure is shown with a retry: the "build my own" tab cannot work without the presets
  function loadPresets(forKind: ProjectKind) {
    const request = ++presetsRequest.current;
    const isLatest = () => request === presetsRequest.current;
    setPresets(null);
    setPresetsFailed(false);
    api.personalities(forKind)
      .then((loaded) => { if (isLatest()) setPresets(loaded); })
      .catch(() => { if (isLatest()) setPresetsFailed(true); });
  }

  // Building by hand starts from an empty team
  function buildByHand() {
    setCustom((current) => current ?? []);
  }

  // Manual company: the team starts with the mandatory member, who cannot be removed
  function chooseCreation(next: CreationMode) {
    setCreation(next);
    if (next === "auto") return setCustom(null);
    if (personality && limits) setCustom((current) => current ?? [mandatoryMember(personality, names, limits.mandatory_role)]);
  }

  function draw(forMode: string) {
    setTeam(null);
    setAccounts({});
    setRapporteur(null);
    api.previewTeam(forMode).then(setTeam).catch((err) => setError(String(err.message ?? err)));
  }
  // Only once the modes of the current kind are known (the mode resets with the kind)
  useEffect(() => {
    if (research && modes && modes[mode]) draw(mode);
  }, [research, mode, modes]);

  const repoValid = GITHUB_URL.test(repoUrl.trim());
  const sourceValid = research ? topic.trim().length > 0 : repoValid;
  const minSize = research ? 1 : limits?.min_team_size ?? 1;
  const maxSize = limits?.max_agents ?? Infinity;
  // A company's automatic head count starts at the minimum the server asks for
  const headCount = employeeCount ?? minSize;
  const problemCodes = custom
    ? teamProblems(custom, research ? null : limits?.mandatory_role ?? null, minSize, maxSize)
    : !research && creation === "auto" ? autoTeamProblems(headCount, minSize, maxSize) : [];
  const problems = problemMessages(problemCodes, minSize, maxSize);
  const teamReady = research ? !!team : !!limits && (creation === "auto" || !!custom);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!teamReady || problems.length) return;
    setBusy(true);
    setError(null);
    try {
      const project = await api.createProject({
        name: name.trim(),
        mode,
        ...(research
          ? { topic: topic.trim(), rapporteur: custom ? null : rapporteur, seed: team?.seed }
          : { repo_url: repoUrl.trim(), creation_mode: creation }),
        ...(!research && creation === "auto" ? { description: description.trim(), employee_count: headCount } : {}),
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
      <h1>{t("new.title")}</h1>

      <div className="kinds">
        <button type="button" className={`kind${!research ? " selected" : ""}`} onClick={() => setKind("company")}>
          <strong>{t("new.company")}</strong>
          <span className="muted">{t("new.companyIntro")}</span>
        </button>
        <button type="button" className={`kind${research ? " selected" : ""}`} onClick={() => setKind("research")}>
          <strong>{t("new.research")}</strong>
          <span className="muted">{t("new.researchIntro")}</span>
        </button>
      </div>

      <section className="panel">
        <h2>{research ? t("new.sectionResearch") : t("new.sectionProject")}</h2>
        <label>
          {t("new.name")}
          <input autoFocus required maxLength={200} value={name} onChange={(e) => setName(e.target.value)}
            placeholder={research ? t("new.namePlaceholderResearch") : t("new.namePlaceholderProject")} />
        </label>
        {research ? (
          <label>
            {t("new.topic")}
            <textarea required rows={4} maxLength={10000} value={topic} onChange={(e) => setTopic(e.target.value)}
              placeholder={t("new.topicPlaceholder")} />
          </label>
        ) : (
          <>
            <label>
              {t("new.repo")}
              <input required value={repoUrl} onChange={(e) => setRepoUrl(e.target.value)} spellCheck={false}
                placeholder="https://github.com/you/your-repo" autoCapitalize="off" />
            </label>
            {repoUrl && !repoValid && <p className="error">{t("new.repoInvalid")}</p>}
          </>
        )}
      </section>

      {!research && (
        <CompanyTeamSection creation={creation} onCreationChange={chooseCreation} description={description}
          onDescriptionChange={setDescription} employeeCount={headCount} onEmployeeCountChange={setEmployeeCount}
          custom={custom} onCustomChange={setCustom} roles={roles} personality={personality} presets={presets}
          limits={limits} names={names} claudeAccounts={claudeAccounts} presetsFailed={presetsFailed}
          onRetryPresets={() => loadPresets(kind)} problems={problems} />
      )}

      {research && (
        <ResearchTeamSection modes={modes} mode={mode} onModeChange={setMode} team={team} onDrawAnother={() => draw(mode)}
          accounts={accounts} onAccountsChange={setAccounts} rapporteur={rapporteur} onRapporteurChange={setRapporteur}
          custom={custom} onCustomChange={setCustom} onBuildByHand={buildByHand} roles={roles} personality={personality}
          presets={presets} limits={limits} names={names} claudeAccounts={claudeAccounts} presetsFailed={presetsFailed}
          onRetryPresets={() => loadPresets(kind)} problems={problems} />
      )}

      {error && <p className="error">{error}</p>}
      <div className="row actions">
        <button type="button" className="btn" onClick={() => go("/")}>{t("common.cancel")}</button>
        <button className="btn btn-primary" disabled={busy || !teamReady || !name.trim() || !sourceValid || (!research && creation === "auto" && !description.trim()) || problems.length > 0}>
          {busy ? t("new.creating") : research ? t("new.startResearch") : t("new.create")}
        </button>
      </div>
    </form>
  );
}
