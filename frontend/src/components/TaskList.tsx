import { useCallback, useEffect, useState } from "react";
import { type Task, api } from "../api";
import { useI18n } from "../i18n";
import { type LoadStatus, statusAfterFailure } from "../navigation";
import { taskStatusLabel } from "../taskStatus";
import { usePolling } from "../util";

const TASKS_POLL_MS = 10000;

/** The tasks of a project, newest first; each one opens its detail page. */
export function TaskList({ projectId }: { projectId: number }) {
  const { t } = useI18n();
  const [tasks, setTasks] = useState<Task[]>([]);
  const [status, setStatus] = useState<LoadStatus>("loading");
  const load = useCallback(() => api.listTasks(projectId).then((list) => {
    setTasks([...list].sort((a, b) => b.id - a.id));
    setStatus("ready");
  }).catch(() => setStatus(statusAfterFailure)), [projectId]);
  useEffect(() => setStatus("loading"), [projectId]);
  usePolling(load, TASKS_POLL_MS, [load]);

  return (
    <div className="page">
      <h2 className="section-label">{t("tasks.title")}</h2>
      {status === "loading" && <p className="muted">{t("common.loading")}</p>}
      {status === "error" && (
        <div className="row">
          <p role="alert" className="error">{t("tasks.loadError")}</p>
          <button className="btn btn-small" onClick={() => { setStatus("loading"); void load(); }}>{t("common.retry")}</button>
        </div>
      )}
      {status === "ready" && tasks.length === 0 && <p className="muted">{t("tasks.empty")}</p>}
      {tasks.length > 0 && (
        <ul className="task-list">
          {tasks.map((task) => (
            <li key={task.id}>
              <a href={`#/p/${projectId}/tasks/${task.id}`} className="task-link">
                <span className="task-link-title">{task.title}</span>
                <span className="muted">{taskStatusLabel(task.status, t)}</span>
              </a>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
