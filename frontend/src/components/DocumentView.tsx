import { useState } from "react";
import { ApiError, type Decision, api } from "../api";
import { formatTime, usePolling } from "../util";
import { Markdown } from "./Markdown";
import type { ProjectState } from "./Sidebar";

const POLL_MS = 8000;

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

  if (!doc) return <p className="muted center">Loading…</p>;
  const conclusions = research ? "Conclusions" : "Decisions";
  const byStatus = (status: Decision["status"]) => doc.decisions.filter((d) => d.status === status);
  const open = doc.questions.filter((q) => !q.resolved);
  const resolved = doc.questions.filter((q) => q.resolved);

  return (
    <div className="page document">
      <h1>{research ? "Report" : "Document"}</h1>
      {error && <p className="error">{error}</p>}

      {doc.room.objective && (
        <section className="panel">
          <h2>{research ? "Topic" : "Objective"}</h2>
          <Markdown content={doc.room.objective} />
        </section>
      )}

      <section className="panel">
        <h2>{research ? "Report" : "Summary"}</h2>
        {doc.room.summary ? (
          <Markdown content={doc.room.summary} />
        ) : (
          <p className="muted">
            {research
              ? "The rapporteur has not written the report yet. It fills in as the group's research advances."
              : "No summary yet: the scribe writes it as the conversations go."}
          </p>
        )}
      </section>

      <section className="panel">
        <h2>{conclusions}</h2>
        {doc.decisions.length === 0 && <p className="muted">None proposed yet.</p>}
        {byStatus("proposed").map((d) => (
          <div key={d.id} className="decision proposed">
            <div className="decision-head">
              <strong>{d.title}</strong>
              <span className="muted">proposed by {d.proposed_by} · {formatTime(d.created_at)}</span>
            </div>
            {d.rationale && <Markdown content={d.rationale} />}
            <div className="row">
              <button className="btn btn-small btn-primary" onClick={() => decide(d, "validated")}>
                {d.pr_number ? `Merge PR #${d.pr_number}` : "Validate"}
              </button>
              <button className="btn btn-small" onClick={() => decide(d, "rejected")}>Reject</button>
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
            <summary className="muted">{byStatus("rejected").length} rejected</summary>
            {byStatus("rejected").map((d) => (
              <div key={d.id} className="decision rejected">
                <div className="decision-head"><strong>{d.title}</strong><span className="muted">{d.proposed_by}</span></div>
              </div>
            ))}
          </details>
        )}
      </section>

      <section className="panel">
        <h2>Open questions</h2>
        {open.length === 0 && <p className="muted">None.</p>}
        <ul className="questions">
          {open.map((q) => <li key={q.id}>{q.question} <span className="muted">— {q.asked_by}</span></li>)}
        </ul>
        {resolved.length > 0 && (
          <details>
            <summary className="muted">{resolved.length} resolved</summary>
            <ul className="questions">
              {resolved.map((q) => <li key={q.id}>{q.question} <span className="muted">→ {q.answer}</span></li>)}
            </ul>
          </details>
        )}
      </section>

      {!research && doc.tasks.length > 0 && (
        <section className="panel">
          <h2>Who does what</h2>
          <ul className="questions">
            {doc.tasks.map((t) => (
              <li key={t.id}>
                #{t.id} {t.title} <span className="muted">— {t.assignee ?? "unassigned"}, {t.status.replace("_", " ")}</span>
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}
