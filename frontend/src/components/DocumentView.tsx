import { useState } from "react";
import { ApiError, type Decision, api } from "../api";
import { useI18n } from "../i18n";
import { formatTime, usePolling } from "../util";
import { Markdown } from "./Markdown";
import type { ProjectState } from "./TeamPanel";

const POLL_MS = 8000;
const TASK_STATUSES = ["todo", "in_progress", "review", "changes_requested", "done", "cancelled"] as const;

type Question = { id: number; question: string; asked_by: string; answer: string | null; resolved: boolean };
type Task = { id: number; title: string; status: string; assignee: string | null; pr_url: string | null };
type RoomDocument = {
  room: { id: number; name: string; objective: string; summary: string };
  decisions: Decision[];
  questions: Question[];
  tasks: Task[];
};

/** The shared document of the general room: for a research group, its report. */
export function DocumentView({ project }: { project: ProjectState }) {
  const { t } = useI18n();
  const research = project.detail.kind === "research";
  const room = project.detail.rooms[0];
  const [doc, setDoc] = useState<RoomDocument | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = () => api.roomDocument<RoomDocument>(room.id).then(setDoc);
  usePolling(room ? load : null, POLL_MS, [room?.id]);

  async function decide(decision: Decision, status: "validated" | "rejected") {
    setError(null);
    try {
      await api.decide(decision.id, status);
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    }
  }

  if (!doc) return <p className="muted center">{t("common.loading")}</p>;
  const taskStatus = (status: string) =>
    (TASK_STATUSES as readonly string[]).includes(status) ? t(`task.${status as (typeof TASK_STATUSES)[number]}`) : status.replace("_", " ");
  const conclusions = research ? t("doc.conclusions") : t("doc.decisions");
  const byStatus = (status: Decision["status"]) => doc.decisions.filter((d) => d.status === status);
  const open = doc.questions.filter((q) => !q.resolved);
  const resolved = doc.questions.filter((q) => q.resolved);

  return (
    <div className="page document">
      <h1>{research ? t("doc.report") : t("doc.document")}</h1>
      {error && <p className="error">{error}</p>}

      {doc.room.objective && (
        <section className="panel">
          <h2>{research ? t("doc.topic") : t("doc.objective")}</h2>
          <Markdown content={doc.room.objective} />
        </section>
      )}

      <section className="panel">
        <h2>{research ? t("doc.report") : t("doc.summary")}</h2>
        {doc.room.summary ? (
          <Markdown content={doc.room.summary} />
        ) : (
          <p className="muted">
            {research ? t("doc.reportEmpty") : t("doc.summaryEmpty")}
          </p>
        )}
      </section>

      <section className="panel">
        <h2>{conclusions}</h2>
        {doc.decisions.length === 0 && <p className="muted">{t("doc.noneProposed")}</p>}
        {byStatus("proposed").map((d) => (
          <div key={d.id} className="decision proposed">
            <div className="decision-head">
              <strong>{d.title}</strong>
              <span className="muted">{t("doc.proposedBy", { name: d.proposed_by, time: formatTime(d.created_at) })}</span>
            </div>
            {d.rationale && <Markdown content={d.rationale} />}
            <div className="row">
              <button className="btn btn-small btn-primary" onClick={() => decide(d, "validated")}>
                {d.pr_number ? t("doc.mergePr", { number: d.pr_number }) : t("request.validate")}
              </button>
              <button className="btn btn-small" onClick={() => decide(d, "rejected")}>{t("request.reject")}</button>
            </div>
          </div>
        ))}
        {byStatus("validated").map((d) => (
          <div key={d.id} className="decision validated">
            <div className="decision-head"><strong>✓ {d.title}</strong><span className="muted">{d.proposed_by}</span></div>
            {d.rationale && <Markdown content={d.rationale} />}
          </div>
        ))}
        {byStatus("rejected").length > 0 && (
          <details className="rejected-list">
            <summary className="muted">{t("doc.rejectedCount", { count: byStatus("rejected").length })}</summary>
            {byStatus("rejected").map((d) => (
              <div key={d.id} className="decision rejected">
                <div className="decision-head"><strong>{d.title}</strong><span className="muted">{d.proposed_by}</span></div>
              </div>
            ))}
          </details>
        )}
      </section>

      <section className="panel">
        <h2>{t("doc.openQuestions")}</h2>
        {open.length === 0 && <p className="muted">{t("common.none")}</p>}
        <ul className="questions">
          {open.map((q) => <li key={q.id}>{q.question} <span className="muted">— {q.asked_by}</span></li>)}
        </ul>
        {resolved.length > 0 && (
          <details>
            <summary className="muted">{t("doc.resolvedCount", { count: resolved.length })}</summary>
            <ul className="questions">
              {resolved.map((q) => <li key={q.id}>{q.question} <span className="muted">→ {q.answer}</span></li>)}
            </ul>
          </details>
        )}
      </section>

      {!research && doc.tasks.length > 0 && (
        <section className="panel">
          <h2>{t("doc.whoDoesWhat")}</h2>
          <ul className="questions">
            {doc.tasks.map((task) => (
              <li key={task.id}>
                #{task.id} {task.title} <span className="muted">— {task.assignee ?? t("doc.unassigned")}, {taskStatus(task.status)}</span>
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}
