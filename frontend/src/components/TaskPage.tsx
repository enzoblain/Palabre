import { useCallback, useEffect, useState } from "react";
import { type ProjectPlatform, type TaskDetail, api } from "../api";
import { useI18n } from "../i18n";
import { AppleBuild } from "./AppleBuild";

/** Detail of a task: title, status, assignee, PR link and, on an Apple project, its Swift build. */
export function TaskPage({ taskId, platform }: { taskId: number; platform: ProjectPlatform }) {
  const { t } = useI18n();
  const [task, setTask] = useState<TaskDetail | null>(null);
  const [failed, setFailed] = useState(false);
  const load = useCallback(() => {
    setFailed(false);
    api.getTask(taskId).then(setTask).catch(() => setFailed(true));
  }, [taskId]);
  useEffect(() => {
    setTask(null);
    load();
  }, [load]);

  if (failed) {
    return (
      <div className="page row">
        <p role="alert" className="error">{t("task.loadError")}</p>
        <button className="btn btn-small" onClick={load}>{t("common.retry")}</button>
      </div>
    );
  }
  if (!task) return <p className="muted center">{t("common.loading")}</p>;
  return (
    <div className="page task-page">
      <h2 className="task-title">{task.title}</h2>
      <dl className="task-facts">
        <dt>{t("task.status")}</dt>
        <dd>{task.status}</dd>
        <dt>{t("task.assignee")}</dt>
        <dd>{task.assignee ?? <span className="muted">{t("task.unassigned")}</span>}</dd>
        <dt>{t("task.pr")}</dt>
        <dd>{task.pr_url && isHttpUrl(task.pr_url)
          ? <a href={task.pr_url} target="_blank" rel="noopener noreferrer">{task.pr_url}</a>
          : <span className="muted">{t("task.noPr")}</span>}</dd>
      </dl>
      {task.description && <p className="task-description">{task.description}</p>}
      {task.acceptance_criteria.length > 0 && (
        <section aria-labelledby="task-criteria">
          <h3 className="section-label" id="task-criteria">{t("task.criteria")}</h3>
          <ul>{task.acceptance_criteria.map((criterion, i) => <li key={i}>{criterion}</li>)}</ul>
        </section>
      )}
      {platform === "apple" && <AppleBuild key={task.id} taskId={task.id} />}
    </div>
  );
}

/** A PR link comes from the server's data: only http(s) is ever put in an href. */
function isHttpUrl(value: string): boolean {
  return /^https?:\/\//i.test(value);
}
