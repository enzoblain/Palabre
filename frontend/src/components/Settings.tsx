import { useEffect, useState } from "react";
import {
  ApiError, type AccountQuota, type AppSettings, type QuotaWindow, type Project, type ProjectDetail, type Usage, type UsageEntry, type UsagePeriod,
  type UsageTotals, api,   getConnection,
} from "../api";
import { locale, translate, useI18n } from "../i18n";
import { parseDate, spreadAccounts } from "../util";
import { AccountSelect } from "./AccountSelect";
import { Avatar } from "./Avatar";

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
      <UsageSection />
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
              {p.name} <span className="muted">· {p.kind === "research" ? t("settings.research") : p.mode}</span>
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

const PERIODS = ["day", "week", "total"] as const satisfies readonly UsagePeriod[];

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

function UsageSection() {
  const { t } = useI18n();
  const [usage, setUsage] = useState<Usage | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [period, setPeriod] = useState<UsagePeriod>("week");
  useEffect(() => {
    api.getUsage().then(setUsage).catch((err) => setError(err instanceof ApiError ? err.message : String(err)));
  }, []);

  return (
    <section className="panel">
      <h2>{t("usage.title")}</h2>
      <p className="muted">
        {t("usage.intro")}
      </p>
      <div className="row" role="group" aria-label={t("usage.period")}>
        {PERIODS.map((p) => (
          <button key={p} className={`btn btn-small${p === period ? " btn-primary" : ""}`}
            aria-pressed={p === period} onClick={() => setPeriod(p)}>{t(`usage.${p}`)}</button>
        ))}
      </div>
      {error && <p className="error">{error}</p>}
      {!usage && !error && <p className="muted">{t("common.loading")}</p>}
      {usage && usage.total.runs === 0 && <p className="muted">{t("usage.empty")}</p>}
      {usage && usage.total.runs > 0 && (
        <>
          <UsageTable title={t("usage.byAccount")} what={t("usage.account")} period={period} entries={usage.accounts}
            label={(e) => (e.id === null ? t("usage.unknown") : t("account.n", { account: e.id }))} />
          <UsageTable title={t("usage.byEmployee")} what={t("usage.employee")} period={period} entries={usage.employees}
            label={(e) => e.name ?? t("usage.employeeN", { id: e.id ?? "" })} />
          <UsageTable title={t("usage.byProject")} what={t("usage.project")} period={period} entries={usage.projects}
            label={(e) => e.name ?? t("usage.projectN", { id: e.id ?? "" })} />
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
      {translate("usage.missing", { tokens: totals.runs_without_tokens, runs: totals.runs, cost: totals.runs_without_cost })}
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
  const { t } = useI18n();
  const rows = entries.filter((e) => e[period].runs > 0);
  const number = new Intl.NumberFormat(locale());
  return (
    <div className="usage-block">
      <h3>{title}</h3>
      {rows.length === 0 ? <p className="muted">{t("usage.noRun")}</p> : (
        <table className="usage-table">
          <thead>
            <tr>
              <th scope="col">{what}</th>
              <th scope="col" className="num">{t("usage.runs")}</th>
              <th scope="col" className="num">{t("usage.input")}</th>
              <th scope="col" className="num">{t("usage.output")}</th>
              <th scope="col" className="num">{t("usage.cache")}</th>
              <th scope="col" className="num">{t("usage.cost")}</th>
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
