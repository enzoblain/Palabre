import { useCallback, useEffect, useRef, useState } from "react";
import { api, type Employee, type Message, type Room } from "../api";
import { mergeMessages } from "../format/messages";
import { usePolling } from "./usePolling";

export const MESSAGES_POLL_MS = 2000; // same as the web app

/** A message the boss typed that the server has not confirmed yet. */
export type PendingMessage = { key: string; content: string; createdAt: string; status: "sending" | "failed" };

export type MessagesState = {
  name: string | null; // the project name, once known
  info: ConversationInfo | null; // room and lead, once known
  messages: Message[] | null; // null until the first load; kept across errors as a cache
  pending: PendingMessage[];
  failed: boolean;
  reload: () => Promise<void>;
  send: (content: string) => Promise<void>;
  retry: (key: string) => Promise<void>;
};

/** What the conversation info panel and the typing indicator need. */
export type ConversationInfo = {
  room: Room;
  leadName: string | null;
  leadTitle: string | null;
  conversationId: number;
  employees: Employee[]; // their titles label the authors
};

type Target = { name: string; conversationId: number; info: ConversationInfo };

/** The boss talks in the direction room: its first conversation (as on the web). */
async function findTarget(projectId: number): Promise<Target> {
  const project = await api.getProject(projectId);
  const room = project.rooms.find((candidate) => candidate.kind === "direction") ?? project.rooms[0];
  const conversation = room ? (await api.listConversations(room.id))[0] : undefined;
  if (!conversation) throw new Error("no conversation");
  const lead = project.employees.find((employee) => employee.roles.includes("lead"));
  return { name: project.name, conversationId: conversation.id, info: {
      room,
      leadName: lead?.name ?? null,
      leadTitle: lead?.title ?? null,
      conversationId: conversation.id,
      employees: project.employees,
    },
  };
}

/** The messages of a project's conversation: polled with since_id, with optimistic sends. */
export function useMessages(projectId: number): MessagesState {
  const [name, setName] = useState<string | null>(null);
  const [info, setInfo] = useState<ConversationInfo | null>(null);
  const [messages, setMessages] = useState<Message[] | null>(null);
  const [pending, setPending] = useState<PendingMessage[]>([]);
  const retrying = useRef(new Set<string>()); // keys being re-sent: guards a fast double tap
  const [failed, setFailed] = useState(false);

  const target = useRef<Target | null>(null);
  const lastId = useRef<number | undefined>(undefined);
  const counter = useRef(0);
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  const append = useCallback((incoming: Message[]) => {
    setMessages((known) => mergeMessages(known ?? [], incoming));
  }, []);

  const reload = useCallback(async () => {
    try {
      target.current ??= await findTarget(projectId);
      const batch = await api.listMessages(target.current.conversationId, lastId.current);
      if (!mounted.current) return;
      setName(target.current.name);
      setInfo(target.current.info);
      // Only polls move the cursor: a sent message's id can skip ones the team posted meanwhile.
      if (batch.length > 0) lastId.current = Math.max(...batch.map((message) => message.id));
      append(batch);
      setFailed(false);
    } catch {
      if (mounted.current) setFailed(true);
    }
  }, [projectId, append]);

  usePolling(reload, MESSAGES_POLL_MS);

  const setStatus = useCallback((key: string, status: PendingMessage["status"]) => {
    setPending((list) => list.map((item) => (item.key === key ? { ...item, status } : item)));
  }, []);

  const post = useCallback(
    async (key: string, content: string) => {
      try {
        target.current ??= await findTarget(projectId);
        const message = await api.postMessage(target.current.conversationId, content);
        if (!mounted.current) return;
        append([message]);
        setPending((list) => list.filter((item) => item.key !== key));
      } catch {
        if (mounted.current) setStatus(key, "failed");
      }
    },
    [projectId, append, setStatus],
  );

  const send = useCallback(
    async (content: string) => {
      counter.current += 1;
      const key = `p${counter.current}`;
      setPending((list) => [...list, { key, content, createdAt: new Date().toISOString(), status: "sending" }]);
      await post(key, content);
    },
    [post],
  );

  const retry = useCallback(
    async (key: string) => {
      const item = pending.find((candidate) => candidate.key === key);
      if (!item || item.status !== "failed" || retrying.current.has(key)) return;
      retrying.current.add(key);
      setStatus(key, "sending");
      await post(key, item.content);
      retrying.current.delete(key);
    },
    [pending, post, setStatus],
  );

  return { name, info, messages, pending, failed, reload, send, retry };
}
