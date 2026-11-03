import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { ApiError, type Conversation, type Message, type Project, type ProjectDetail, type Room, api } from "../api";
import { useI18n } from "../i18n";
import { useIsDesktop } from "../layout";
import type { Route } from "../router";
import { MENTION_EVENT, usePolling } from "../util";
import { SendIcon, TeamIcon } from "./Icons";
import { ConversationTeam } from "./ConversationTeam";
import { bossNames } from "./Markdown";
import { MessageRow, TypingDots } from "./MessageBubble";
import { ProjectMenu } from "./TeamPanel";

const POLL_MS = 2000;

/** The message box. It keeps the draft to itself, so typing only re-renders the box. */
function Composer({ placeholder, onSend }: { placeholder: string; onSend: (content: string) => Promise<boolean> }) {
  const { t } = useI18n();
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
      <button className="icon-btn send" onClick={send} disabled={!draft.trim() || sending} aria-label={t("common.send")}>
        <SendIcon />
      </button>
    </div>
  );
}

// The direction room is the boss's own conversation: its title would only repeat the project name
function isDirectionTitle(room: Pick<Room, "kind">, conversation: Pick<Conversation, "title">): boolean {
  return room.kind === "direction" || conversation.title?.toLowerCase().replace(/^#/, "") === "direction";
}

/** True when the primary input is a touch screen (media query, not the user agent). */
function isTouchInput(): boolean {
  return window.matchMedia?.("(pointer: coarse)").matches ?? false;
}

/** Restarts the anti-loop window of the conversation, for the CEO who cannot write in a read-only channel. */
function LiftLimitButton({ conversationId }: { conversationId: number }) {
  const { t } = useI18n();
  const [busy, setBusy] = useState(false);
  const [feedback, setFeedback] = useState<{ ok: boolean; text: string } | null>(null);

  async function lift() {
    if (busy) return;
    setBusy(true);
    try {
      await api.liftRateLimit(conversationId);
      setFeedback({ ok: true, text: t("conv.liftLimitDone") });
    } catch (err) {
      setFeedback({ ok: false, text: err instanceof ApiError ? err.message : String(err) });
    } finally {
      setBusy(false);
    }
  }

  return (
    <span className="lift-limit">
      <button className="btn" disabled={busy} onClick={lift}
        title={t("conv.liftLimitTitle")}>
        {t("conv.liftLimit")}
      </button>
      <span className={`lift-note${feedback?.ok === false ? " error" : ""}`} role="status" aria-live="polite">{feedback?.text}</span>
    </span>
  );
}

export function ConversationView({ conversation, room, project, projects, route, bossName, leadWriting, onRead }: {
  conversation: Conversation;
  room: Room;
  project: ProjectDetail;
  projects: Project[];
  route: Route;
  bossName: string;
  // The lead is answering in the direction channel
  leadWriting: boolean;
  // The direction channel was marked as read on the server
  onRead: () => void;
}) {
  const { t } = useI18n();
  const desktop = useIsDesktop();
  const [teamOpen, setTeamOpen] = useState(false);
  const teamButtonRef = useRef<HTMLButtonElement>(null);
  const [messages, setMessages] = useState<Message[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const stickToBottom = useRef(true);
  const lastId = useRef<number | undefined>(undefined);
  const currentId = useRef(conversation.id);
  currentId.current = conversation.id;

  const employees = new Map(project.employees.map((e) => [e.id, e]));
  const lead = project.employees.find((e) => e.roles.includes("lead"));
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

  const typing = room.kind === "direction" && leadWriting;
  useLayoutEffect(() => {
    const el = listRef.current;
    if (el && stickToBottom.current) el.scrollTop = el.scrollHeight;
  }, [messages, typing]);

  // The boss reads direction as soon as it is open, and each new message while it stays open
  const newestId = messages?.[messages.length - 1]?.id;
  useEffect(() => {
    if (room.kind !== "direction" || newestId === undefined) return;
    api.markDirectionRead(project.id).then(onRead).catch(() => {});
  }, [room.kind, project.id, newestId, onRead]);

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

  function closeTeam() {
    setTeamOpen(false);
    teamButtonRef.current?.focus();
  }

  const empty = messages !== null && messages.length === 0;

  return (
    <div className="conversation">
      <header className="conv-head">
        {/* The boss's conversation carries the project's name; a click on it switches project */}
        {/* Fresh object each render: ProjectMenu only reads it, keep it out of effect deps */}
        <ProjectMenu route={route} projects={projects} project={{ detail: project, conversations: {} }} asTitle />
        {!isDirectionTitle(room, conversation) && conversation.title && <span className="muted">· {conversation.title}</span>}
        <span className="conv-members muted">· {t(room.members.length > 1 ? "conv.members" : "conv.member", { count: room.members.length })}</span>
        <span className="conv-head-actions">
          <LiftLimitButton key={conversation.id} conversationId={conversation.id} />
          {desktop && (
            <button ref={teamButtonRef} className="icon-btn" aria-label={t("conv.showTeam")} aria-expanded={teamOpen}
              aria-controls="conv-team" onClick={() => (teamOpen ? closeTeam() : setTeamOpen(true))}>
              <TeamIcon size={20} />
            </button>
          )}
        </span>
      </header>

      <div className="conv-body">
        <div className="conv-main">
        <div className="messages" ref={listRef} onScroll={onScroll}>
          {messages === null && <p className="muted center">{t("common.loading")}</p>}
          {empty && (
            <div className="intro">
              <h2>{t("conv.introTitle", { project: project.name })}</h2>
              <p className="muted">
                {[t("conv.intro"), lead && t("conv.introLead", { name: lead.name, title: lead.title })].filter(Boolean).join(" ")}
              </p>
            </div>
          )}
          {messages?.map((m, i) => {
            const prev = messages[i - 1];
            const grouped = !!prev && prev.employee_id === m.employee_id && prev.author_name === m.author_name;
            const title = m.employee_id !== null ? employees.get(m.employee_id)?.title : undefined;
            return <MessageRow key={m.id} message={m} grouped={grouped} title={title} selfNames={myNames} />;
          })}
          {typing && lead && <TypingDots name={lead.name} />}
        </div>

        {error && <p className="error composer-error">{error}</p>}
        <Composer key={conversation.id} onSend={send}
          placeholder={
            empty ? t("conv.placeholderEmpty") : t("conv.placeholder", { project: project.name, boss: bossName || t("conv.bossFallback") })
          } />
        </div>
        {desktop && teamOpen && <ConversationTeam employees={project.employees} onClose={closeTeam} />}
      </div>
    </div>
  );
}
