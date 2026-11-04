import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, type ProjectPlatform, type TaskDetail, api } from "../api";
import { useI18n } from "../i18n";
import { taskStatusLabel } from "../taskStatus";
import { AppleBuild } from "./AppleBuild";

const HTTP_NOT_FOUND = 404;

/** Detail of a task: title, status, assignee, PR link and, on an Apple project, its Swift build. */
export function TaskPage({ projectId, taskId, platform }: { projectId: number; taskId: number; platform: ProjectPlatform }) {
  const { t } = useI18n();
  const [task, setTask] = useState<TaskDetail | null>(null);
  const [failure, setFailure] = useState<"missing" | "error" | null>(null);
  const titleRef = useRef<HTMLHeadingElement>(null);
  const load = useCallback(() => {
    setFailure(null);
    api.getTask(taskId).then(setTask).catch((err: unknown) => {
      setFailure(err instanceof ApiError && err.status === HTTP_NOT_FOUND ? "missing" : "error");
    });
  }, [taskId]);
  useEffect(() => {
    setTask(null);
    load();
  }, [load]);

  useEffect(() => {
    titleRef.current?.focus();
  }, [task?.id]);

  if (failure === "missing") {
    return (
      <div className="page">
        <BackToTasks projectId={projectId} />
        <p className="muted">{t("task.notFound")}</p>
      </div>
    );
  }
  if (failure === "error") {
    return (
      <div className="page row">
        <p role="alert" className="error">{t("task.loadError")}</p>
        <button className="btn btn-small" onClick={load}>{t("common.retry")}</button>
      </div>
    );
  }
  if (!task) return <p role="status" className="muted center">{t("common.loading")}</p>;
  return (
    <div className="page task-page">
      <BackToTasks projectId={projectId} />
      <h1 className="task-title" ref={titleRef} tabIndex={-1}>{task.title}</h1>
      <dl className="task-facts">
        <dt>{t("task.status")}</dt>
        <dd>{taskStatusLabel(task.status, t)}</dd>
        <dt>{t("task.assignee")}</dt>
        <dd>{task.assignee ?? <span className="muted">{t("task.unassigned")}</span>}</dd>
        <dt>{t("task.pr")}</dt>
        <dd>{task.pr_url && isHttpUrl(task.pr_url)
          ? <a href={task.pr_url} target="_blank" rel="noopener noreferrer" aria-label={t("task.openPrLabel")}>{t("task.openPr")}</a>
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

function BackToTasks({ projectId }: { projectId: number }) {
  const { t } = useI18n();
  return <a className="task-back" href={`#/p/${projectId}/tasks`}>{t("task.back")}</a>;
}

/** A PR link comes from the server's data: only http(s) is ever put in an href. */
function isHttpUrl(value: string): boolean {
  return /^https?:\/\//i.test(value);
}
