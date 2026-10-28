import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { ApiError, type Conversation, type EmployeeStatus, type Message, type Notification, type ProjectDetail, type Room, api } from "../api";
import { MENTION_EVENT, formatTime, usePolling } from "../util";
import { Avatar } from "./Avatar";
import { HashIcon, SendIcon } from "./Icons";
import { Markdown, bossNames, mentionsAny } from "./Markdown";

const POLL_MS = 2000;

export function ConversationView({ conversation, room, project, statuses, bossName, notifications, onNotificationsRead }: {
  conversation: Conversation;
  room: Room;
  project: ProjectDetail;
  statuses: EmployeeStatus[];
  bossName: string;
  // Unread notifications of this conversation
  notifications: Notification[];
  onNotificationsRead: () => void;
}) {
  const [messages, setMessages] = useState<Message[] | null>(null);
  const [draft, setDraft] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [sending, setSending] = useState(false);
  const listRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const stickToBottom = useRef(true);
  const lastId = useRef<number | undefined>(undefined);
  const currentId = useRef(conversation.id);
  currentId.current = conversation.id;

  const employees = new Map(project.employees.map((e) => [e.id, e]));
  const lead = project.employees.find((e) => e.roles.includes("lead"));
  const isGeneral = project.rooms[0]?.id === room.id;
  const myNames = bossNames(bossName);

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
    setDraft("");
    inputRef.current?.focus();
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

  useLayoutEffect(() => {
    const el = listRef.current;
    if (el && stickToBottom.current) el.scrollTop = el.scrollHeight;
  }, [messages]);

  function onScroll() {
    const el = listRef.current;
    if (el) stickToBottom.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
  }

  async function send() {
    const content = draft.trim();
    if (!content || sending) return;
    setSending(true);
    setError(null);
    try {
      const message = await api.postMessage(conversation.id, content);
      stickToBottom.current = true;
      append([message]);
      setDraft("");
      if (throttled) onNotificationsRead(); // Posting lifted the pause
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setSending(false);
      inputRef.current?.focus();
    }
  }

  // Being here means the mentions and escalations of this conversation are read
  const unreadMentions = notifications.filter((n) => n.type === "mention" || n.type === "escalation").length;
  useEffect(() => {
    if (unreadMentions === 0) return;
    api.markAllRead({ conversation_id: conversation.id, types: ["mention", "escalation"] })
      .then(onNotificationsRead)
      .catch(() => {});
  }, [conversation.id, unreadMentions, onNotificationsRead]);
  const throttled = notifications.some((n) => n.type === "conversation_throttled");

  const busyHere = statuses.filter((s) => s.status === "working" && s.conversation_id === conversation.id);
  const empty = messages !== null && messages.length === 0;

  return (
    <div className="conversation">
      <header className="conv-head">
        <HashIcon size={18} />
        <h1>{room.name}</h1>
        {conversation.title && <span className="muted">· {conversation.title}</span>}
        <span className="conv-members muted">{room.members.length} members</span>
      </header>

      <div className="messages" ref={listRef} onScroll={onScroll}>
        {messages === null && <p className="muted center">Loading…</p>}
        {empty && (
          <div className="intro">
            <h2>
              {isGeneral && project.kind === "research"
                ? "Give the group your topic"
                : isGeneral ? `Tell your team about ${project.name}` : `This is the start of #${room.name}`}
            </h2>
            <p className="muted">
              {isGeneral && project.kind === "research"
                ? "Every member of the group reads your message, searches the web and starts the debate."
                : isGeneral
                ? `What are you building, for whom, and what matters most? ${lead ? `${lead.name} (${lead.title}) will read it and organize the work.` : ""}`
                : `Members: ${room.members.map((m) => m.name).join(", ")}.`}
            </p>
          </div>
        )}
        {messages?.map((m, i) => {
          const prev = messages[i - 1];
          const grouped = prev && prev.employee_id === m.employee_id && prev.author_name === m.author_name;
          const author = m.employee_id !== null ? employees.get(m.employee_id) : undefined;
          const boss = m.employee_id === null;
          const forMe = !boss && mentionsAny(m.content, myNames);
          return (
            <div key={m.id} className={`message${grouped ? " grouped" : ""}${boss ? " from-boss" : ""}${forMe ? " mentions-me" : ""}`}>
              <div className="message-avatar">{!grouped && <Avatar name={m.author_name} boss={boss} size={34} />}</div>
              <div className="message-main">
                {!grouped && (
                  <div className="message-meta">
                    <strong>{m.author_name}</strong>
                    <span className="muted">{boss ? "CEO" : author?.title}</span>
                    <time className="muted">{formatTime(m.created_at)}</time>
                  </div>
                )}
                <div className="message-body"><Markdown content={m.content} selfNames={myNames} /></div>
              </div>
            </div>
          );
        })}
      </div>

      {throttled && (
        <div className="banner">
          The team talked too much here: their chatter is paused until you post a message. Work on tasks and reviews goes on.
        </div>
      )}
      <div className="typing muted">
        {busyHere.length > 0 && `${busyHere.map((s) => s.name).join(", ")} ${busyHere.length > 1 ? "are" : "is"} thinking…`}
      </div>
      {error && <p className="error composer-error">{error}</p>}
      <div className="composer">
        <textarea ref={inputRef} rows={1} value={draft}
          placeholder={empty && isGeneral ? "Describe the project to your team…" : `Message #${room.name} as ${bossName || "the CEO"}`}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
              e.preventDefault();
              send();
            }
          }} />
        <button className="icon-btn send" onClick={send} disabled={!draft.trim() || sending} aria-label="Send">
          <SendIcon />
        </button>
      </div>
    </div>
  );
}
