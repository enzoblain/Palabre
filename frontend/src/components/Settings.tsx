import { useEffect, useState } from "react";
import {
  ApiError, type AppSettings, type Project, type ProjectDetail, api, getConnection,
} from "../api";
import { useI18n } from "../i18n";
import { spreadAccounts } from "../util";
import { AccountSelect } from "./AccountSelect";
import { Avatar } from "./Avatar";
import { ConnectedDevices } from "./ConnectedDevices";

export function Settings({ settings, projects, onSaved, onDisconnect }: {
  settings: AppSettings;
  projects: Project[];
  onSaved: (settings: AppSettings) => void;
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
      <ConnectedDevices />
      <ClaudeAccounts count={settings.claude_accounts} projects={projects} />
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
