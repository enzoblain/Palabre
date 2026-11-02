import { useEffect, useRef, useState } from "react";
import { ApiError, type MemberIn, type Personality, type PersonalityPreset, type ProjectDetail, type CatalogLimits, type Role, api } from "../api";
import { useI18n } from "../i18n";
import { go } from "../router";
import { autoTeamProblems, teamProblems } from "../jobs";
import { CompanyTeamSection, type CreationMode } from "./CompanyTeamSection";
import { mandatoryMember, problemMessages } from "./TeamEditor";

const GITHUB_URL = /^(https:\/\/github\.com\/|git@github\.com:)[\w.-]+\/[\w.-]+?(\.git)?\/?$/;
const DEFAULT_MODE = "startup";

export function NewProject({ claudeAccounts, onCreated }: {
  claudeAccounts: number;
  onCreated: (project: ProjectDetail) => void;
}) {
  const { t } = useI18n();
  const [personality, setPersonality] = useState<Personality | null>(null);
  const [presets, setPresets] = useState<Record<string, PersonalityPreset> | null>(null);
  const [name, setName] = useState("");
  const [repoUrl, setRepoUrl] = useState("");
  // The team is hired from a description (auto) or listed by hand (manual)
  const [creation, setCreation] = useState<CreationMode>("auto");
  const [description, setDescription] = useState("");
  const [employeeCount, setEmployeeCount] = useState<number | null>(null);
  // Team built by hand (null: the team drawn at random is used)
  const [custom, setCustom] = useState<MemberIn[] | null>(null);
  const [roles, setRoles] = useState<Record<string, Role> | null>(null);
  const [names, setNames] = useState<string[]>([]);
  const [limits, setLimits] = useState<CatalogLimits | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [presetsFailed, setPresetsFailed] = useState(false);
  const [busy, setBusy] = useState(false);
  // Identifies the latest presets request: a late answer from an earlier one is ignored
  const presetsRequest = useRef(0);

  useEffect(() => {
    api.names().then(setNames).catch(() => {});
    api.limits().then(setLimits).catch(() => {});
    api.personality().then(setPersonality).catch(() => {});
    loadPresets();
    api.roles().then(setRoles).catch(() => {});
  }, []);

  // A failure is shown with a retry: the "build my own" tab cannot work without the presets
  function loadPresets() {
    const request = ++presetsRequest.current;
    const isLatest = () => request === presetsRequest.current;
    setPresets(null);
    setPresetsFailed(false);
    api.personalities()
      .then((loaded) => { if (isLatest()) setPresets(loaded); })
      .catch(() => { if (isLatest()) setPresetsFailed(true); });
  }

  // Manual: the team starts with the mandatory member, who cannot be removed
  function chooseCreation(next: CreationMode) {
    setCreation(next);
    if (next === "auto") return setCustom(null);
    if (personality && limits) setCustom((current) => current ?? [mandatoryMember(personality, names, limits.mandatory_role)]);
  }

  const repoValid = GITHUB_URL.test(repoUrl.trim());
  const minSize = limits?.min_team_size ?? 1;
  const maxSize = limits?.max_agents ?? Infinity;
  // The automatic head count starts at the minimum the server asks for
  const headCount = employeeCount ?? minSize;
  const problemCodes = custom
    ? teamProblems(custom, limits?.mandatory_role ?? null, minSize, maxSize)
    : creation === "auto" ? autoTeamProblems(headCount, minSize, maxSize) : [];
  const problems = problemMessages(problemCodes, minSize, maxSize);
  const teamReady = !!limits && (creation === "auto" || !!custom);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!teamReady || problems.length) return;
    setBusy(true);
    setError(null);
    try {
      const project = await api.createProject({
        name: name.trim(),
        mode: DEFAULT_MODE,
        repo_url: repoUrl.trim(),
        creation_mode: creation,
        ...(creation === "auto" ? { description: description.trim(), employee_count: headCount } : {}),
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

      <section className="panel">
        <h2>{t("new.sectionProject")}</h2>
        <label>
          {t("new.name")}
          <input autoFocus required maxLength={200} value={name} onChange={(e) => setName(e.target.value)}
            placeholder={t("new.namePlaceholderProject")} />
        </label>
        <label>
          {t("new.repo")}
          <input required value={repoUrl} onChange={(e) => setRepoUrl(e.target.value)} spellCheck={false}
            placeholder="https://github.com/you/your-repo" autoCapitalize="off" />
        </label>
        {repoUrl && !repoValid && <p className="error">{t("new.repoInvalid")}</p>}
      </section>

      <CompanyTeamSection creation={creation} onCreationChange={chooseCreation} description={description}
        onDescriptionChange={setDescription} employeeCount={headCount} onEmployeeCountChange={setEmployeeCount}
        custom={custom} onCustomChange={setCustom} roles={roles} personality={personality} presets={presets}
        limits={limits} names={names} claudeAccounts={claudeAccounts} presetsFailed={presetsFailed}
        onRetryPresets={loadPresets} problems={problems} />

      {error && <p className="error">{error}</p>}
      <div className="row actions">
        <button type="button" className="btn" onClick={() => go("/")}>{t("common.cancel")}</button>
        <button className="btn btn-primary" disabled={busy || !teamReady || !name.trim() || !repoValid || (creation === "auto" && !description.trim()) || problems.length > 0}>
          {busy ? t("new.creating") : t("new.create")}
        </button>
      </div>
    </form>
  );
}
