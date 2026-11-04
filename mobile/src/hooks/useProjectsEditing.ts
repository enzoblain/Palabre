import { useCallback, useState } from "react";
import { ApiError, api, type ProjectListItem } from "../api";
import { translate } from "../i18n";

export type ProjectsEditing = {
  editing: boolean;
  checkedIds: ReadonlySet<number>;
  toggleEditing: () => void;
  toggle: (project: ProjectListItem) => void;
  deleteChecked: () => Promise<void>;
  deleting: boolean;
  error: string | null;
};

/** Edit mode of the conversation list: which projects are ticked, and their deletion in one call. */
export function useProjectsEditing(onDeleted: () => void): ProjectsEditing {
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
    setDeleting(true);
    setError(null);
    try {
      await api.deleteProjects([...checkedIds]);
      setEditing(false);
      setCheckedIds(new Set());
      onDeleted();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : translate("list.deleteError"));
    } finally {
      setDeleting(false);
    }
  }, [checkedIds, onDeleted]);

  return { editing, checkedIds, toggleEditing, toggle, deleteChecked, deleting, error };
}
