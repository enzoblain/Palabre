import { useEffect, useState } from "react";
import { ApiError, type ProjectDetail, type ProjectState, api } from "../api";
import { useI18n } from "../i18n";
import { goBack } from "../router";
import { BackIcon } from "./Icons";
import { TeamSection } from "./TeamSection";

/** Header of a project screen: back arrow, name, and an optional action on the right. */
export function ProjectBar({ name, onBack, children }: {
  name: string;
  onBack: () => void;
  children?: React.ReactNode;
}) {
  const { t } = useI18n();
  return (
    <header className="project-bar">
      <button className="icon-btn" onClick={onBack} aria-label={t("common.back")}><BackIcon size={22} /></button>
      <h1 className="project-bar-title truncate">{name}</h1>
      <span className="project-bar-end">{children}</span>
    </header>
  );
}

/** Name and main branch of the project, saved together; the backend reports a missing branch. */
function ProjectForm({ detail, onSaved }: { detail: ProjectDetail; onSaved: () => void }) {
  const { t } = useI18n();
  const [name, setName] = useState(detail.name);
  const [branch, setBranch] = useState(detail.default_branch);
  const [saving, setSaving] = useState(false);
  const [status, setStatus] = useState<{ ok: boolean; text: string } | null>(null);
  useEffect(() => setName(detail.name), [detail.name]);
  useEffect(() => setBranch(detail.default_branch), [detail.default_branch]);

  const changed = name.trim() !== detail.name || branch.trim() !== detail.default_branch;

  async function save(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    setStatus(null);
    try {
      const updated = await api.updateProject(detail.id, {
        ...(name.trim() !== detail.name ? { name: name.trim() } : {}),
        ...(branch.trim() !== detail.default_branch ? { main_branch: branch.trim() } : {}),
      });
      setStatus(updated.warning ? { ok: false, text: updated.warning } : { ok: true, text: t("info.saved") });
      onSaved();
    } catch (err) {
      setStatus({ ok: false, text: err instanceof ApiError ? err.message : String(err) });
    } finally {
      setSaving(false);
    }
  }

  return (
    <form className="panel" onSubmit={save}>
      <h2 className="section-label">{t("info.details")}</h2>
      <label>
        {t("info.name")}
        <input required maxLength={100} value={name} onChange={(e) => setName(e.target.value)} />
      </label>
      <label>
        {t("info.branch")}
        <input required value={branch} onChange={(e) => setBranch(e.target.value)} spellCheck={false}
          autoCapitalize="off" aria-describedby="info-branch-hint" />
      </label>
      <p className="muted" id="info-branch-hint">{t("info.branchHint")}</p>
      <div className="row">
        <button className="btn btn-primary" disabled={saving || !changed || !name.trim() || !branch.trim()}>
          {saving ? t("common.saving") : t("common.save")}
        </button>
        {status && <span className={status.ok ? "success" : "error"} role="status">{status.text}</span>}
      </div>
    </form>
  );
}

/** Delete button at the bottom of the page; asks for a confirmation before calling the backend. */
function DeleteProject({ detail, onDeleted }: { detail: ProjectDetail; onDeleted: () => void }) {
  const { t } = useI18n();
  const [confirming, setConfirming] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function remove() {
    setDeleting(true);
    setError(null);
    try {
      await api.deleteProject(detail.id);
      onDeleted();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
      setDeleting(false);
    }
  }

  return (
    <section className="panel danger-zone" aria-labelledby="info-delete">
      <h2 className="section-label" id="info-delete">{t("info.delete")}</h2>
      <p className="muted">{t("info.deleteWarning")}</p>
      {error && <p className="error" role="alert">{error}</p>}
      {confirming ? (
        <div className="row confirm-delete">
          <span className="error">{t("info.deleteConfirm", { name: detail.name })}</span>
          <button className="btn btn-small" onClick={() => setConfirming(false)} disabled={deleting}>{t("common.cancel")}</button>
          <button className="btn btn-small btn-danger" onClick={remove} disabled={deleting}>
            {deleting ? t("info.deleting") : t("info.deleteForGood")}
          </button>
        </div>
      ) : (
        <div className="row">
          <button className="btn btn-danger" onClick={() => setConfirming(true)}>{t("common.delete")}</button>
        </div>
      )}
    </section>
  );
}

/** Own page of a project: editable name and main branch, description, git link, the team, and deletion. */
export function ProjectInfo({ project, onChanged, onDeleted }: {
  project: ProjectState | null;
  /** The project was edited: reload it and the project list */
  onChanged: () => void;
  onDeleted: () => void;
}) {
  const { t } = useI18n();
  if (!project) return <p className="muted center">{t("common.loading")}</p>;
  const { detail } = project;
  // The boss's objective for the project lives on the direction room
  const description = (detail.rooms.find((r) => r.kind === "direction") ?? detail.rooms[0])?.objective.trim();
  return (
    <>
      <ProjectBar name={detail.name} onBack={() => goBack(`/p/${detail.id}`)} />
      <div className="page project-info">
        <ProjectForm detail={detail} onSaved={onChanged} />
        <section aria-labelledby="info-description">
          <h2 className="section-label" id="info-description">{t("info.description")}</h2>
          <p className={description ? "info-description" : "muted"}>{description || t("info.noDescription")}</p>
          <p className="muted">{t("info.descriptionHint")}</p>
        </section>
        <section aria-labelledby="info-git">
          <h2 className="section-label" id="info-git">{t("info.git")}</h2>
          {detail.repo_url ? (
            <a href={detail.repo_url} target="_blank" rel="noopener noreferrer" className="info-link">{detail.repo_url}</a>
          ) : <p className="muted">{t("info.noGit")}</p>}
        </section>
        <TeamSection projectId={detail.id} members={detail.employees} onChanged={onChanged} />
        <DeleteProject detail={detail} onDeleted={onDeleted} />
      </div>
    </>
  );
}
