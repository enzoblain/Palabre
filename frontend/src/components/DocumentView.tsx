import { useId, useRef, useState } from "react";
import { ApiError, type Decision, type Room, api } from "../api";
import { useI18n } from "../i18n";
import { formatAgo, formatTime, usePolling } from "../util";
import { Markdown } from "./Markdown";
import type { ProjectState } from "./TeamPanel";

const POLL_MS = 8000;
const TASK_STATUSES = ["todo", "in_progress", "review", "changes_requested", "done", "cancelled"] as const;

type Question = { id: number; question: string; asked_by: string; answer: string | null; resolved: boolean };
type Task = { id: number; title: string; status: string; assignee: string | null; pr_url: string | null };
type RoomDocument = {
  room: Pick<Room, "id" | "name" | "objective" | "summary" | "updated_at" | "members">;
  decisions: Decision[];
  questions: Question[];
  tasks: Task[];
};

type SectionKey = "proposed" | "questions" | "tasks" | "objective" | "members" | "past";

/** The shared document of the general room: for a research group, its report. */
export function DocumentView({ project }: { project: ProjectState }) {
  const { t } = useI18n();
  const research = project.detail.kind === "research";
  const room = project.detail.rooms[0];
  const [doc, setDoc] = useState<RoomDocument | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [opened, setOpened] = useState<Set<SectionKey>>(new Set());
  const idPrefix = useId();
  const sectionRefs = useRef<Partial<Record<SectionKey, HTMLElement | null>>>({});

  const load = () => api.roomDocument<RoomDocument>(room.id).then(setDoc);
  usePolling(room ? load : null, POLL_MS, [room?.id]);

  const toggle = (key: SectionKey) =>
    setOpened((prev) => {
      const next = new Set(prev);
      if (!next.delete(key)) next.add(key);
      return next;
    });

  // A figure of the summary opens its section and brings it into view
  function jumpTo(key: SectionKey) {
    setOpened((prev) => new Set(prev).add(key));
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    requestAnimationFrame(() => sectionRefs.current[key]?.scrollIntoView({ behavior: reduce ? "auto" : "smooth", block: "start" }));
  }

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
    (TASK_STATUSES as readonly string[]).includes(status) ? t(`task.${status as (typeof TASK_STATUSES)[number]}`) : status.replaceAll("_", " ");
  const byStatus = (status: Decision["status"]) => doc.decisions.filter((d) => d.status === status);
  const proposed = byStatus("proposed");
  const past = doc.decisions.filter((d) => d.status !== "proposed");
  const open = doc.questions.filter((q) => !q.resolved);
  const resolved = doc.questions.filter((q) => q.resolved);
  const active = doc.tasks.filter((task) => task.status === "in_progress");
  const members = doc.room.members;
  const hasSummary = doc.room.summary.trim() !== "";

  const sections: { key: SectionKey; title: string; count: number; total?: number; badge?: boolean; body: React.ReactNode }[] = [
    {
      key: "proposed", title: research ? t("doc.proposedConclusions") : t("doc.proposedDecisions"), count: proposed.length, badge: true,
      body: proposed.map((d) => (
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
      )),
    },
    {
      key: "questions", title: t("doc.openQuestions"), count: open.length, total: doc.questions.length,
      body: (
        <>
          {open.length > 0 && (
            <ul className="questions">
              {open.map((q) => <li key={q.id}>{q.question} <span className="muted">— {q.asked_by}</span></li>)}
            </ul>
          )}
          {resolved.length > 0 && (
            <>
              <h3 className="sub-title">{t("doc.resolved")} ({resolved.length})</h3>
              <ul className="questions">
                {resolved.map((q) => <li key={q.id}>{q.question} <span className="muted">→ {q.answer}</span></li>)}
              </ul>
            </>
          )}
        </>
      ),
    },
  ];
  if (!research) {
    sections.push({
      key: "tasks", title: t("doc.whoDoesWhat"), count: doc.tasks.filter((task) => task.status !== "cancelled").length,
      body: (
        <ul className="questions">
          {doc.tasks.filter((task) => task.status !== "cancelled").map((task) => (
            <li key={task.id}>
              #{task.id} {task.title} <span className="muted">— {task.assignee ?? t("doc.unassigned")}, {taskStatus(task.status)}</span>
            </li>
          ))}
        </ul>
      ),
    });
  }
  sections.push(
    {
      key: "objective", title: research ? t("doc.topic") : t("doc.objective"), count: doc.room.objective ? 1 : 0,
      body: doc.room.objective ? <Markdown content={doc.room.objective} /> : null,
    },
    {
      key: "members", title: t("doc.members"), count: members.length,
      body: (
        <ul className="questions">
          {members.map((m) => <li key={m.id}>{m.name} <span className="muted">— {m.title}</span></li>)}
        </ul>
      ),
    },
    {
      key: "past", title: research ? t("doc.pastConclusions") : t("doc.pastDecisions"), count: past.length,
      body: past.map((d) => (
        <div key={d.id} className={`decision ${d.status}`}>
          <div className="decision-head">
            <strong>{d.status === "validated" ? "✓ " : ""}{d.title}</strong>
            <span className="muted">{d.status === "rejected" ? `${t("doc.rejected")} · ` : ""}{d.proposed_by}</span>
          </div>
          {d.rationale && d.status === "validated" && <Markdown content={d.rationale} />}
        </div>
      )),
    },
  );

  const stats: { key: SectionKey; label: string }[] = [
    { key: "proposed", label: t("doc.statDecisions", { count: proposed.length }) },
    { key: "questions", label: t("doc.statQuestions", { count: open.length }) },
    ...(research ? [] : [{ key: "tasks" as const, label: t("doc.statTasks", { count: active.length }) }]),
  ];

  return (
    <div className="page document">
      <header className="doc-head">
        <h1>{project.detail.name}</h1>
        <p className="muted doc-meta">
          {doc.room.updated_at && t("doc.summaryMeta", { ago: formatAgo(doc.room.updated_at) })}
        </p>
      </header>
      {error && <p className="error" role="alert">{error}</p>}

      <section className="panel summary-card" aria-labelledby={`${idPrefix}-summary`}>
        <h2 id={`${idPrefix}-summary`}>{research ? t("doc.report") : t("doc.summary")}</h2>
        {hasSummary ? (
          <Markdown content={doc.room.summary} />
        ) : (
          <p className="muted">{research ? t("doc.reportEmpty") : t("doc.summaryEmpty")}</p>
        )}
        <ul className="doc-stats" aria-label={t("doc.statsLabel")}>
          {stats.map((st) => (
            <li key={st.key}>
              <button type="button" className="stat-link" onClick={() => jumpTo(st.key)}>{st.label}</button>
            </li>
          ))}
        </ul>
      </section>

      {sections.map((sec) => {
        const isOpen = opened.has(sec.key);
        const headId = `${idPrefix}-${sec.key}-head`;
        const bodyId = `${idPrefix}-${sec.key}-body`;
        return (
          <section key={sec.key} className="accordion" ref={(el) => { sectionRefs.current[sec.key] = el; }}>
            <h2 className="accordion-title">
              <button type="button" id={headId} className="accordion-head" aria-expanded={isOpen} aria-controls={bodyId}
                onClick={() => toggle(sec.key)}>
                <span className="accordion-name">{sec.title}</span>
                <span className={`count-badge${sec.badge && sec.count > 0 ? " attention" : ""}`}
                  aria-label={sec.badge && sec.count > 0 ? `${sec.count} ${t("doc.toValidate")}` : undefined}>
                  {sec.count}
                </span>
                <span className="chevron" aria-hidden="true">▾</span>
              </button>
            </h2>
            <div id={bodyId} role="region" aria-labelledby={headId} className="accordion-body" hidden={!isOpen}>
              {(sec.total ?? sec.count) === 0 ? <p className="muted">{t("doc.nothing")}</p> : sec.body}
            </div>
          </section>
        );
      })}
    </div>
  );
}
