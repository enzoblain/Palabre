import { useCallback, useEffect, useRef, useState } from "react";
import { api, type Message } from "../api";
import { mergeMessages } from "../format/messages";
import { usePolling } from "./usePolling";

export const MESSAGES_POLL_MS = 2000; // same as the web app

/** A message the boss typed that the server has not confirmed yet. */
export type PendingMessage = { key: string; content: string; createdAt: string; status: "sending" | "failed" };

export type MessagesState = {
  name: string | null; // the project name, once known
  messages: Message[] | null; // null until the first load; kept across errors as a cache
  pending: PendingMessage[];
  failed: boolean;
  reload: () => Promise<void>;
  send: (content: string) => Promise<void>;
  retry: (key: string) => Promise<void>;
};

type Target = { name: string; conversationId: number };

/** The boss talks in the direction room: its first conversation (as on the web). */
async function findTarget(projectId: number): Promise<Target> {
  const project = await api.getProject(projectId);
  const room = project.rooms.find((candidate) => candidate.kind === "direction") ?? project.rooms[0];
  const conversation = room ? (await api.listConversations(room.id))[0] : undefined;
  if (!conversation) throw new Error("no conversation");
  return { name: project.name, conversationId: conversation.id };
}

/** The messages of a project's conversation: polled with since_id, with optimistic sends. */
export function useMessages(projectId: number): MessagesState {
  const [name, setName] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[] | null>(null);
  const [pending, setPending] = useState<PendingMessage[]>([]);
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
    setMessages((known) => {
      const merged = mergeMessages(known ?? [], incoming);
      lastId.current = merged[merged.length - 1]?.id;
      return merged;
    });
  }, []);

  const reload = useCallback(async () => {
    try {
      target.current ??= await findTarget(projectId);
      const batch = await api.listMessages(target.current.conversationId, lastId.current);
      if (!mounted.current) return;
      setName(target.current.name);
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
      if (!item || item.status !== "failed") return;
      setStatus(key, "sending");
      await post(key, item.content);
    },
    [pending, post, setStatus],
  );

  return { name, messages, pending, failed, reload, send, retry };
}
