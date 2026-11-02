import { useId, useRef, useState } from "react";
import { ApiError, type Decision, type Room, api } from "../api";
import { useI18n } from "../i18n";
import { formatTime, usePolling } from "../util";
import { Markdown } from "./Markdown";
import type { ProjectState } from "./TeamPanel";

const POLL_MS = 8000;

type Question = { id: number; question: string; asked_by: string; answer: string | null; resolved: boolean };
type RoomDocument = {
  room: Pick<Room, "id" | "name" | "objective" | "summary" | "members">;
  decisions: Decision[];
  questions: Question[];
};

type SectionKey = "proposed" | "questions" | "objective" | "members" | "past";

/** The report of a research group: the rapporteur's summary, with the conclusions to validate. */
export function ReportView({ project }: { project: ProjectState }) {
  const { t } = useI18n();
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
  const byStatus = (status: Decision["status"]) => doc.decisions.filter((d) => d.status === status);
  const proposed = byStatus("proposed");
  const past = doc.decisions.filter((d) => d.status !== "proposed");
  const open = doc.questions.filter((q) => !q.resolved);
  const resolved = doc.questions.filter((q) => q.resolved);
  const members = doc.room.members;
  const hasSummary = doc.room.summary.trim() !== "";

  const sections: { key: SectionKey; title: string; count: number; total?: number; badge?: boolean; body: React.ReactNode }[] = [
    {
      key: "proposed", title: t("doc.proposedConclusions"), count: proposed.length, badge: true,
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
    {
      key: "objective", title: t("doc.topic"), count: doc.room.objective ? 1 : 0,
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
      key: "past", title: t("doc.pastConclusions"), count: past.length,
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
  ];

  const stats: { key: SectionKey; label: string }[] = [
    { key: "proposed", label: t("doc.statDecisions", { count: proposed.length }) },
    { key: "questions", label: t(open.length === 1 ? "doc.statQuestion" : "doc.statQuestions", { count: open.length }) },
  ];

  return (
    <div className="page document">
      <header className="doc-head">
        <h1>{project.detail.name}</h1>
      </header>
      {error && <p className="error" role="alert">{error}</p>}

      <section className="panel summary-card" aria-labelledby={`${idPrefix}-summary`}>
        <h2 id={`${idPrefix}-summary`}>{t("doc.report")}</h2>
        {hasSummary ? (
          <Markdown content={doc.room.summary} />
        ) : (
          <p className="muted">{t("doc.reportEmpty")}</p>
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
