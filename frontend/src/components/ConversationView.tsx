import { memo, useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { ApiError, type Conversation, type EmployeeStatus, type Message, type Project, type ProjectDetail, type RequestAnswer, type ResearchPhase, type Room, api } from "../api";
import type { Route } from "../router";
import { MENTION_EVENT, formatTime, usePolling } from "../util";
import { Avatar } from "./Avatar";
import { SendIcon } from "./Icons";
import { Markdown, bossNames, mentionsAny } from "./Markdown";
import { ProjectMenu } from "./TeamPanel";

const POLL_MS = 2000;
const PHASE_POLL_MS = 4000;
const PHASES: { key: ResearchPhase; label: string }[] = [
  { key: "research", label: "Research" },
  { key: "debate", label: "Debate" },
  { key: "conclusion", label: "Conclusion" },
  { key: "report", label: "Report" },
];

/** Where the research question stands: research → debate → conclusion → report. */
function PhaseBar({ phase, projectId }: { phase: ResearchPhase; projectId: number }) {
  const current = phase === "done" ? PHASES.length : PHASES.findIndex((p) => p.key === phase);
  return (
    <div className="phase-bar">
      {PHASES.map((p, i) => (
        <span key={p.key} className={`phase${i < current ? " past" : i === current ? " current" : ""}`}>
          {i < current ? "✓ " : ""}{p.label}
        </span>
      ))}
      {phase === "done" && <a className="phase-done" href={`#/p/${projectId}/report`}>Read the report →</a>}
    </div>
  );
}

const ANSWER_LABEL: Record<RequestAnswer, string> = { validated: "validated", rejected: "rejected", nuanced: "nuanced" };

/** The lead asks the CEO something: Validate / Reject / Nuance, then the answer takes the buttons' place. */
function RequestBox({ message: m, onAnswered }: { message: Message; onAnswered: (m: Message) => void }) {
  const [mode, setMode] = useState<"reject" | "nuance" | null>(null);
  const [comment, setComment] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [announce, setAnnounce] = useState("");
  const areaRef = useRef<HTMLTextAreaElement>(null);
  const triggerRef = useRef<HTMLButtonElement | null>(null);

  useEffect(() => {
    if (mode) areaRef.current?.focus();
  }, [mode]);

  async function answer(answer: RequestAnswer, text = "") {
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      const updated = await api.answerRequest(m.id, answer, text.trim());
      setAnnounce(`You ${ANSWER_LABEL[answer]} the request.`);
      onAnswered(updated);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  function close() {
    setMode(null);
    setComment("");
    triggerRef.current?.focus();
  }

  if (m.request_status && m.request_status !== "pending") {
    return (
      <div className="request">
        <p className="request-answer">
          You {ANSWER_LABEL[m.request_status]}{m.request_comment ? <> : <q>{m.request_comment}</q></> : ""}
          {m.request_answered_at && <time className="muted"> · {formatTime(m.request_answered_at)}</time>}
        </p>
        <span className="sr-only" role="status" aria-live="polite">{announce}</span>
      </div>
    );
  }
  const nuance = mode === "nuance";
  return (
    <div className="request">
      <div className="request-actions" role="group" aria-label="Votre réponse à cette demande">
        <button className="btn btn-primary" disabled={busy} onClick={() => answer("validated")}>Validate</button>
        <button className="btn btn-danger-outline" disabled={busy}
          onClick={(e) => { triggerRef.current = e.currentTarget; setMode("reject"); }}>Reject</button>
        <button className="btn" disabled={busy}
          onClick={(e) => { triggerRef.current = e.currentTarget; setMode("nuance"); }}>Nuance</button>
      </div>
      {mode && (
        <div className="request-form">
          <label className="muted" htmlFor={`request-${m.id}`}>{nuance ? "Your nuance" : "Why? (optional)"}</label>
          <textarea id={`request-${m.id}`} ref={areaRef} value={comment} maxLength={2000}
            onChange={(e) => setComment(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Escape") close();
              if (e.key === "Enter" && (e.ctrlKey || e.metaKey) && (!nuance || comment.trim())) {
                answer(nuance ? "nuanced" : "rejected", comment);
              }
            }} />
          <div className="row">
            <button className="btn btn-primary" disabled={busy || (nuance && !comment.trim())}
              onClick={() => answer(nuance ? "nuanced" : "rejected", comment)}>
              {nuance ? "Send" : "Confirm the rejection"}
            </button>
            <button className="btn" onClick={close}>Cancel</button>
          </div>
        </div>
      )}
      {error && <p className="error" role="alert">{error}</p>}
      <span className="sr-only" role="status" aria-live="polite">{announce}</span>
    </div>
  );
}

/** One message. Memoized: re-parsing every message's Markdown on each render made typing slow. */
const MessageRow = memo(function MessageRow({ message: m, grouped, title, selfNames, forYou, onAnswered }: {
  message: Message;
  onAnswered: (m: Message) => void;
  grouped: boolean;
  title: string | undefined;
  selfNames: string[];
  // Written by the lead in the direction channel: addressed to the CEO
  forYou: boolean;
}) {
  const system = m.is_system;
  const boss = m.employee_id === null && !system;
  const forMe = !boss && !system && mentionsAny(m.content, selfNames);
  return (
    <div className={`message${grouped ? " grouped" : ""}${boss ? " from-boss" : ""}${system ? " from-system" : ""}${forMe ? " mentions-me" : ""}`}>
      <div className="message-avatar">{!grouped && (system
          ? <span className="avatar avatar-system" aria-hidden="true" style={{ width: 34, height: 34 }}>•</span>
          : <Avatar name={m.author_name} boss={boss} size={34} />)}</div>
      <div className="message-main">
        {!grouped && (
          <div className="message-meta">
            <strong>{m.author_name}</strong>
            <span className="muted">{system ? "Platform" : boss ? "CEO" : title}</span>
            <time className="muted">{formatTime(m.created_at)}</time>
            {forYou && <span className="for-you">For you</span>}
          </div>
        )}
        <div className="message-body"><Markdown content={m.content} selfNames={selfNames} /></div>
        {m.request_status && !boss && !system && <RequestBox message={m} onAnswered={onAnswered} />}
      </div>
    </div>
  );
});

/** The message box. It keeps the draft to itself, so typing only re-renders the box. */
function Composer({ placeholder, onSend }: { placeholder: string; onSend: (content: string) => Promise<boolean> }) {
  const [draft, setDraft] = useState("");
  const [sending, setSending] = useState(false);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => inputRef.current?.focus(), []);

  // Click on a teammate in the sidebar → "@Name " in the composer
  useEffect(() => {
    const onMention = (e: Event) => {
      const name = (e as CustomEvent<string>).detail;
      setDraft((d) => `${d}${d && !d.endsWith(" ") ? " " : ""}@${name} `);
      inputRef.current?.focus();
    };
    window.addEventListener(MENTION_EVENT, onMention);
    return () => window.removeEventListener(MENTION_EVENT, onMention);
  }, []);

  async function send() {
    const content = draft.trim();
    if (!content || sending) return;
    setSending(true);
    if (await onSend(content)) setDraft("");
    setSending(false);
    inputRef.current?.focus();
  }

  return (
    <div className="composer">
      <textarea ref={inputRef} rows={1} enterKeyHint={isTouchInput() ? "enter" : "send"} value={draft} placeholder={placeholder}
        onChange={(e) => setDraft(e.target.value)}
        onKeyDown={(e) => {
          // On touch screens Enter inserts a newline; the send button sends
          if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing && !isTouchInput()) {
            e.preventDefault();
            send();
          }
        }} />
      <button className="icon-btn send" onClick={send} disabled={!draft.trim() || sending} aria-label="Envoyer">
        <SendIcon />
      </button>
    </div>
  );
}

/** True when the primary input is a touch screen (media query, not the user agent). */
// The direction room is the boss's own conversation: its title would only repeat the project name
function isDirectionTitle(room: Room, conversation: Conversation): boolean {
  return room.kind === "direction" || conversation.title?.toLowerCase().replace(/^#/, "") === "direction";
}

function isTouchInput(): boolean {
  return window.matchMedia?.("(pointer: coarse)").matches ?? false;
}

/** Restarts the anti-loop window of the conversation, for the CEO who cannot write in a read-only channel. */
function LiftLimitButton({ conversationId }: { conversationId: number }) {
  const [busy, setBusy] = useState(false);
  const [feedback, setFeedback] = useState<{ ok: boolean; text: string } | null>(null);

  async function lift() {
    if (busy) return;
    setBusy(true);
    try {
      await api.liftRateLimit(conversationId);
      setFeedback({ ok: true, text: "Loop limit lifted: the team can be woken up again here." });
    } catch (err) {
      setFeedback({ ok: false, text: err instanceof ApiError ? err.message : String(err) });
    } finally {
      setBusy(false);
    }
  }

  return (
    <span className="lift-limit">
      <button className="btn" disabled={busy} onClick={lift}
        title="Agents stop being woken up here after too many runs in an hour. This restarts the count.">
        Lift loop limit
      </button>
      <span className={`lift-note${feedback?.ok === false ? " error" : ""}`} role="status" aria-live="polite">{feedback?.text}</span>
    </span>
  );
}

export function ConversationView({ conversation, room, project, projects, route, statuses, bossName }: {
  conversation: Conversation;
  room: Room;
  project: ProjectDetail;
  projects: Project[];
  route: Route;
  statuses: EmployeeStatus[];
  bossName: string;
}) {
  const [messages, setMessages] = useState<Message[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const stickToBottom = useRef(true);
  const lastId = useRef<number | undefined>(undefined);
  const currentId = useRef(conversation.id);
  currentId.current = conversation.id;

  const employees = new Map(project.employees.map((e) => [e.id, e]));
  const lead = project.employees.find((e) => e.roles.includes("lead"));
  const research = project.kind === "research";
  const [phase, setPhase] = useState<ResearchPhase | null>(project.research_phase);
  usePolling(research ? async () => setPhase((await api.researchPhase(project.id)).phase) : null, PHASE_POLL_MS, [project.id, research]);
  const myNames = useMemo(() => bossNames(bossName), [bossName]);

  function append(incoming: Message[]) {
    if (!incoming.length) return;
    setMessages((prev) => {
      const seen = new Set((prev ?? []).map((m) => m.id));
      const merged = [...(prev ?? []), ...incoming.filter((m) => !seen.has(m.id))];
      lastId.current = merged[merged.length - 1]?.id;
      return merged;
    });
  }

  useEffect(() => {
    setMessages(null);
    lastId.current = undefined;
    stickToBottom.current = true;
  }, [conversation.id]);

  usePolling(
    async () => {
      const id = conversation.id;
      const batch = await api.listMessages(id, lastId.current);
      if (id !== currentId.current) return; // Answer for a conversation we already left
      if (lastId.current === undefined) {
        lastId.current = batch[batch.length - 1]?.id;
        setMessages(batch);
      } else {
        append(batch);
      }
    },
    POLL_MS,
    [conversation.id],
  );

  useLayoutEffect(() => {
    const el = listRef.current;
    if (el && stickToBottom.current) el.scrollTop = el.scrollHeight;
  }, [messages]);

  function onScroll() {
    const el = listRef.current;
    if (el) stickToBottom.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
  }

  async function send(content: string): Promise<boolean> {
    setError(null);
    try {
      const message = await api.postMessage(conversation.id, content);
      stickToBottom.current = true;
      append([message]);
      return true;
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
      return false;
    }
  }

  const onAnswered = useCallback((answered: Message) => {
    setMessages((prev) => prev && prev.map((m) => (m.id === answered.id ? answered : m)));
  }, []);

  const busyHere = statuses.filter((s) => s.status === "working" && s.conversation_id === conversation.id);
  const empty = messages !== null && messages.length === 0;

  return (
    <div className="conversation">
      <header className="conv-head">
        {/* The boss's conversation carries the project's name; a click on it switches project */}
        {/* Fresh object each render: ProjectMenu only reads it, keep it out of effect deps */}
        <ProjectMenu route={route} projects={projects} project={{ detail: project, conversations: {} }}
          bossName={bossName} asTitle />
        {!isDirectionTitle(room, conversation) && conversation.title && <span className="muted">· {conversation.title}</span>}
        <span className="conv-members muted">{room.members.length} membres</span>
        <LiftLimitButton key={conversation.id} conversationId={conversation.id} />
      </header>
      {research && phase && <PhaseBar phase={phase} projectId={project.id} />}

      <div className="messages" ref={listRef} onScroll={onScroll}>
        {messages === null && <p className="muted center">Loading…</p>}
        {empty && (
          <div className="intro">
            <h2>
              {research
                ? "Give the group your topic"
                : `Tell your team about ${project.name}`}
            </h2>
            <p className="muted">
              {research
                ? "Every member of the group reads your message, searches the web and starts the debate."
                : `What are you building, for whom, and what matters most? ${lead ? `${lead.name} (${lead.title}) will read it and organize the work.` : ""}`}
            </p>
          </div>
        )}
        {messages?.map((m, i) => {
          const prev = messages[i - 1];
          const grouped = !!prev && prev.employee_id === m.employee_id && prev.author_name === m.author_name;
          const title = m.employee_id !== null ? employees.get(m.employee_id)?.title : undefined;
          return <MessageRow key={m.id} message={m} grouped={grouped} title={title} selfNames={myNames} forYou={room.kind === "direction" && m.employee_id !== null && m.employee_id === lead?.id} onAnswered={onAnswered} />;
        })}
      </div>

      <div className="typing muted">
        {busyHere.length > 0 && `${busyHere.map((s) => s.name).join(", ")} ${busyHere.length > 1 ? "are" : "is"} thinking…`}
      </div>
      {error && <p className="error composer-error">{error}</p>}
      <Composer key={conversation.id} onSend={send}
        placeholder={
          research
            ? "Ask the group a question, or @mention someone…"
            : empty ? "Describe the project to your team…" : `Message ${project.name} as ${bossName || "the CEO"}`
        } />
    </div>
  );
}
