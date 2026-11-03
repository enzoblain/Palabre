import { useCallback, useState } from "react";
import { ApiError, type ProjectListItem, api } from "../api";
import { useI18n } from "../i18n";

export type ProjectsEditing = {
  editing: boolean;
  checkedIds: ReadonlySet<number>;
  toggleEditing: () => void;
  toggle: (project: ProjectListItem) => void;
  deleteChecked: () => Promise<void>;
  deleting: boolean;
  error: string | null;
};

/** Edit mode of a project list: which projects are ticked, and their deletion in one call. */
export function useProjectsEditing(onDeleted: (ids: number[]) => void): ProjectsEditing {
  const [editing, setEditing] = useState(false);
  const [checkedIds, setCheckedIds] = useState<ReadonlySet<number>>(new Set());
  const [deleting, setDeleting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const toggleEditing = useCallback(() => {
    setEditing((on) => !on);
    setCheckedIds(new Set());
    setError(null);
  }, []);
  const toggle = useCallback((project: ProjectListItem) => {
    setCheckedIds((ids) => {
      const next = new Set(ids);
      if (!next.delete(project.id)) next.add(project.id);
      return next;
    });
  }, []);
  const deleteChecked = useCallback(async () => {
    const ids = [...checkedIds];
    setDeleting(true);
    setError(null);
    try {
      await api.deleteProjects(ids);
      setEditing(false);
      setCheckedIds(new Set());
      onDeleted(ids);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setDeleting(false);
    }
  }, [checkedIds, onDeleted]);

  return { editing, checkedIds, toggleEditing, toggle, deleteChecked, deleting, error };
}

/** The Edit / Done button that switches a project list into edit mode and back. */
export function EditToggle({ state }: { state: ProjectsEditing }) {
  const { t } = useI18n();
  return (
    <button className="btn btn-small edit-toggle" onClick={state.toggleEditing} aria-pressed={state.editing}>
      {state.editing ? t("projects.done") : t("projects.edit")}
    </button>
  );
}

/** Delete bar of the edit mode, rendered only while editing: asks for a confirmation before deleting the ticked projects. */
export function DeleteSelection({ state }: { state: ProjectsEditing }) {
  const { t } = useI18n();
  const [confirming, setConfirming] = useState(false);
  const count = state.checkedIds.size;
  return (
    <div className="delete-selection">
      {state.error && <p className="error" role="alert">{state.error}</p>}
      {confirming && count > 0 ? (
        <div className="row confirm-delete">
          <span className="error">{t("projects.deleteSelectedConfirm", { count })}</span>
          <button className="btn btn-small" onClick={() => setConfirming(false)} disabled={state.deleting}>{t("common.cancel")}</button>
          <button className="btn btn-small btn-danger" disabled={state.deleting}
            onClick={() => state.deleteChecked().finally(() => setConfirming(false))}>
            {state.deleting ? t("info.deleting") : t("info.deleteForGood")}
          </button>
        </div>
      ) : (
        <button className="btn btn-danger" disabled={count === 0} onClick={() => setConfirming(true)}>
          {t("projects.deleteSelected", { count })}
        </button>
      )}
    </div>
  );
}
