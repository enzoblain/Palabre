import { useEffect, useState } from "react";
import {
  ApiError, type AccountQuota, type AppSettings, type QuotaWindow, type Project, type ProjectDetail, api, getConnection,
} from "../api";
import { locale, translate, useI18n } from "../i18n";
import { parseDate, spreadAccounts } from "../util";
import { AccountSelect } from "./AccountSelect";
import { Avatar } from "./Avatar";

const MODE_KEYS = {
  startup: "mode.startup", scaleup: "mode.scaleup", enterprise: "mode.enterprise", multinational: "mode.multinational",
} as const;

/** Company size in the project language; an unknown mode is shown as stored. */
function modeLabel(mode: string, t: (key: (typeof MODE_KEYS)[keyof typeof MODE_KEYS]) => string): string {
  return Object.prototype.hasOwnProperty.call(MODE_KEYS, mode) ? t(MODE_KEYS[mode as keyof typeof MODE_KEYS]) : mode;
}

export function Settings({ settings, projects, onSaved, onProjectsChanged, onDisconnect }: {
  settings: AppSettings;
  projects: Project[];
  onSaved: (settings: AppSettings) => void;
  onProjectsChanged: () => void;
  onDisconnect: () => void;
}) {
  const { t, tr } = useI18n();
  const bossName = settings.boss_name;
  const [name, setName] = useState(bossName);
  const [status, setStatus] = useState<{ ok: boolean; text: string } | null>(null);
  useEffect(() => setName(bossName), [bossName]);

  async function save(e: React.FormEvent) {
    e.preventDefault();
    try {
      onSaved(await api.saveSettings({ boss_name: name }));
      setStatus({ ok: true, text: t("settings.nameSaved") });
    } catch (err) {
      setStatus({ ok: false, text: err instanceof ApiError ? err.message : String(err) });
    }
  }

  return (
    <div className="page">
      <h1>{t("settings.title")}</h1>
      <form className="panel" onSubmit={save}>
        <h2>{t("settings.you")}</h2>
        <p className="muted">{t("settings.youIntro")}</p>
        {!bossName && <p className="hint">{t("settings.nameHint")}</p>}
        <label>
          {t("settings.name")}
          <input autoFocus required maxLength={100} value={name} onChange={(e) => setName(e.target.value)}
            placeholder={t("settings.namePlaceholder")} />
        </label>
        <div className="row">
          <button className="btn btn-primary" disabled={!name.trim() || name.trim() === bossName}>{t("common.save")}</button>
          {status && <span className={status.ok ? "success" : "error"}>{status.text}</span>}
        </div>
      </form>
      <TeamLanguage settings={settings} onSaved={onSaved} />
      <ClaudeAccounts count={settings.claude_accounts} projects={projects} />
      <QuotaSection />
      <Projects projects={projects} onChanged={onProjectsChanged} />
      <section className="panel">
        <h2>{t("settings.server")}</h2>
        <p className="muted">{tr("settings.connectedTo", { server: <code>{getConnection()?.server}</code> })}</p>
        <div className="row">
          <button className="btn" onClick={onDisconnect}>{t("settings.disconnect")}</button>
        </div>
      </section>
    </div>
  );
}

function TeamLanguage({ settings, onSaved }: { settings: AppSettings; onSaved: (settings: AppSettings) => void }) {
  const { t } = useI18n();
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
      <h2>{t("settings.language")}</h2>
      <p className="muted">{t("settings.languageIntro")}</p>
      <div className="row">
        <select value={settings.language} onChange={(e) => change(e.target.value)} aria-label={t("settings.languageAria")}>
          {Object.entries(settings.languages).map(([key, label]) => (
            <option key={key} value={key}>{label}</option>
          ))}
        </select>
        {saved && <span className="success">{t("settings.languageSaved")}</span>}
        {error && <span className="error">{error}</span>}
      </div>
    </section>
  );
}

function ClaudeAccounts({ count, projects }: { count: number; projects: Project[] }) {
  const { t } = useI18n();
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
      <h2>{t("settings.accounts")}</h2>
      <p className="muted">
        {count === 0 && t("settings.accountsNone")}
        {count === 1 && t("settings.accountsOne")}
        {count > 1 && t("settings.accountsMany", { count })}
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
  const { t, tr } = useI18n();
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
      <h2>{t("settings.projects")}</h2>
      <p className="muted">
        {tr("settings.projectsBranch", { dev: <code>dev</code>, main: <code>main</code> })}
      </p>
      <p className="muted">
        {t("settings.projectsDelete")}
      </p>
      {error && <p className="error">{error}</p>}
      {projects.length === 0 && <p className="muted">{t("settings.noProject")}</p>}
      <ul className="project-list">
        {projects.map((p) => (
          <li key={p.id}>
            <span className="project-initial">{p.name.slice(0, 1).toUpperCase()}</span>
            <span className="truncate project-list-name">
              {p.name} <span className="muted">· {p.kind === "research" ? t("settings.research") : modeLabel(p.mode, t)}</span>
            </span>
            {p.kind === "company" && confirming !== p.id && <BranchField project={p} onChanged={onChanged} />}
            {confirming === p.id ? (
              <span className="row confirm-delete">
                <span className="error">{t("settings.confirmDelete")}</span>
                <button className="btn btn-small" onClick={() => setConfirming(null)} disabled={deleting === p.id}>{t("common.cancel")}</button>
                <button className="btn btn-small btn-danger" onClick={() => remove(p)} disabled={deleting === p.id}>
                  {deleting === p.id ? t("settings.deleting") : t("settings.deleteForGood")}
                </button>
              </span>
            ) : (
              <button className="btn btn-small" onClick={() => setConfirming(p.id)}>{t("common.delete")}</button>
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}

function BranchField({ project, onChanged }: { project: Project; onChanged: () => void }) {
  const { t } = useI18n();
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
      <button className="btn btn-small" title={t("settings.branchTitle")}
        onClick={() => { setBranch(project.default_branch); setEditing(true); }}>
        <code>{project.default_branch}</code>
      </button>
    );
  }
  return (
    <form className="row branch-field" onSubmit={save}>
      <input autoFocus required value={branch} onChange={(e) => setBranch(e.target.value)} spellCheck={false}
        autoCapitalize="off" aria-label={t("settings.branchAria")} />
      <button type="button" className="btn btn-small" onClick={() => setEditing(false)} disabled={saving}>{t("common.cancel")}</button>
      <button className="btn btn-small btn-primary" disabled={saving || !branch.trim()}>{saving ? t("common.saving") : t("common.save")}</button>
      {error && <span className="error">{error}</span>}
    </form>
  );
}

function QuotaSection() {
  const { t, tr } = useI18n();
  const [accounts, setAccounts] = useState<AccountQuota[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const refresh = () => {
    setLoading(true);
    api.getQuota()
      .then((q) => { setAccounts(q.accounts); setError(null); })
      .catch((err) => setError(err instanceof ApiError ? err.message : String(err)))
      .finally(() => setLoading(false));
  };
  useEffect(refresh, []);

  return (
    <section className="panel">
      <h2>{t("quota.title")}</h2>
      <p className="muted">{tr("quota.intro", { usage: <code>/usage</code> })}</p>
      <div className="row">
        <button className="btn btn-small" onClick={refresh} disabled={loading}>{loading ? t("common.refreshing") : t("common.refresh")}</button>
      </div>
      {error && <p className="error" role="alert">{error}</p>}
      {!accounts && !error && <p className="muted">{t("common.loading")}</p>}
      {accounts?.length === 0 && <p className="muted">{t("quota.none")}</p>}
      {accounts?.map((a) => (
        <div key={a.account} className="quota-account">
          <h3>{t("quota.account", { account: a.account })}</h3>
          {a.error ? (
            <p className="error" role="alert">{t("quota.unavailable", { error: a.error })}</p>
          ) : (
            <>
              <QuotaBar label={t("quota.session")} window={a.session} />
              <QuotaBar label={t("quota.week")} window={a.week} />
              {a.models.map((m) => <QuotaBar key={m.model} label={t("quota.weekModel", { model: m.model })} window={m} />)}
            </>
          )}
        </div>
      ))}
    </section>
  );
}

function resetText(value: string | null): string {
  if (!value) return "";
  const date = parseDate(value);
  const ms = date.getTime() - Date.now();
  if (ms <= 0) return translate("quota.resetsNow");
  if (ms < 24 * 3600 * 1000) {
    const minutes = Math.round(ms / 60000);
    return minutes < 60
      ? translate("quota.resetsInMinutes", { minutes })
      : translate("quota.resetsInHours", { hours: Math.floor(minutes / 60), minutes: String(minutes % 60).padStart(2, "0") });
  }
  const when = date.toLocaleString(locale(), { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
  return translate("quota.resetsAt", { date: when });
}

function QuotaBar({ label, window }: { label: string; window: QuotaWindow | null }) {
  const { t } = useI18n();
  if (!window) return null;
  const percent = Math.max(0, Math.min(100, Math.round(window.used_percent)));
  return (
    <div className="quota-row">
      <div className="quota-head">
        <span>{label}</span>
        <span className="muted">{t("quota.used", { percent })}{window.resets_at ? ` · ${resetText(window.resets_at)}` : ""}</span>
      </div>
      <div className={`quota-bar${percent >= 90 ? " quota-high" : ""}`} role="progressbar" aria-label={label}
        aria-valuemin={0} aria-valuemax={100} aria-valuenow={percent}>
        <div className="quota-fill" style={{ width: `${percent}%` }} />
      </div>
    </div>
  );
}
