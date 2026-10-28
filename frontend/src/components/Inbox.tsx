import { useState } from "react";
import { ApiError, type Notification, api } from "../api";
import { go } from "../router";
import { formatTime } from "../util";
import { Avatar } from "./Avatar";
import { Markdown } from "./Markdown";
import type { ProjectState } from "./Sidebar";

function title(n: Notification, room: string, research: boolean): string {
  switch (n.type) {
    case "mention":
      return `${n.author ?? "Someone"} mentioned you in #${room}`;
    case "escalation":
      return `${n.author ?? "Someone"} needs you in #${room}`;
    case "decision_proposed":
      return `${n.author ?? "Someone"} proposes a ${research ? "conclusion" : "decision"} in #${room}`;
    case "conversation_throttled":
      return `The team talked too much in #${room}`;
    default:
      return n.type.replace(/_/g, " ");
  }
}

export function Inbox({ project, notifications, bossName, onChanged }: {
  project: ProjectState;
  notifications: Notification[];
  bossName: string;
  onChanged: () => void;
}) {
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<number | null>(null);
  const roomName = (n: Notification) => project.detail.rooms.find((r) => r.id === n.room_id)?.name ?? "?";

  function conversationOf(n: Notification): number | null {
    if (n.conversation_id) return n.conversation_id;
    return n.room_id ? project.conversations[n.room_id]?.[0]?.id ?? null : null;
  }

  async function run(n: Notification, action: () => Promise<unknown>) {
    setBusy(n.id);
    setError(null);
    try {
      await action();
      onChanged();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setBusy(null);
    }
  }

  async function open(n: Notification) {
    const conversation = conversationOf(n);
    // A throttled conversation stays flagged until the boss posts in it
    if (n.type !== "conversation_throttled" && n.type !== "decision_proposed") await api.markRead(n.id).catch(() => {});
    onChanged();
    if (conversation) go(`/p/${project.detail.id}/c/${conversation}`);
  }

  return (
    <div className="page inbox">
      <div className="inbox-head">
        <h1>Inbox</h1>
        {notifications.length > 0 && (
          <button className="btn btn-small" onClick={() => run(notifications[0], () => api.markAllRead({ project_id: project.detail.id }))}>
            Mark all as read
          </button>
        )}
      </div>
      {error && <p className="error">{error}</p>}
      {notifications.length === 0 && (
        <p className="muted">Nothing waiting for you. The team will reach you here when they need you.</p>
      )}
      <ul className="notifications">
        {notifications.map((n) => (
          <li key={n.id} className={`notification notification-${n.type}`}>
            <div className="notification-icon">
              {n.author ? <Avatar name={n.author} size={32} /> : <span className="notification-dot" />}
            </div>
            <div className="notification-main">
              <div className="notification-title">
                <strong>{title(n, roomName(n), project.detail.kind === "research")}</strong>
                <time className="muted">{formatTime(n.created_at)}</time>
              </div>
              {n.excerpt && (
                <div className="notification-excerpt"><Markdown content={n.excerpt} selfNames={["boss", "ceo", bossName]} /></div>
              )}
              {n.type === "conversation_throttled" && (
                <p className="muted">Their chatter is paused there until you post in it. Work on tasks and reviews goes on.</p>
              )}
              {n.decision && (
                <div className="notification-decision">
                  <strong>{n.decision.title}</strong>
                  {n.decision.rationale && <Markdown content={n.decision.rationale} />}
                </div>
              )}
              <div className="row notification-actions">
                {n.decision?.status === "proposed" && (
                  <>
                    <button className="btn btn-small btn-primary" disabled={busy === n.id}
                      onClick={() => run(n, () => api.decide(n.decision!.id, "validated"))}>Validate</button>
                    <button className="btn btn-small" disabled={busy === n.id}
                      onClick={() => run(n, () => api.decide(n.decision!.id, "rejected"))}>Reject</button>
                  </>
                )}
                {conversationOf(n) && (
                  <button className="btn btn-small" onClick={() => open(n)}>Open #{roomName(n)}</button>
                )}
                {n.type !== "conversation_throttled" && n.decision?.status !== "proposed" && (
                  <button className="btn btn-small" disabled={busy === n.id}
                    onClick={() => run(n, () => api.markRead(n.id))}>Mark as read</button>
                )}
              </div>
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}
