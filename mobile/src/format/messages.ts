import type { Message } from "../api";
import { translate } from "../i18n";
import { parseDate } from "./conversations";

export const TIMESTAMP_GAP_MS = 3_600_000; // iMessage shows a time when the pause exceeds 1 h

export type DeliveryStatus = "sent" | "sending" | "failed";

/** A message as the screen shows it: a server message or one the boss just typed. */
export type DisplayMessage = {
  key: string;
  author: string;
  employeeId: number | null;
  content: string;
  createdAt: string;
  own: boolean; // the boss: bubbles on the right
  system: boolean;
  isRequest: boolean;
  status: DeliveryStatus;
};

export type ChatItem =
  | { kind: "timestamp"; key: string; label: string }
  | { kind: "system"; key: string; message: DisplayMessage }
  | { kind: "bubble"; key: string; message: DisplayMessage; showAuthor: boolean; tail: boolean; firstInSeries: boolean };

/** The boss has no employee behind its messages; platform lines have none either but are flagged. */
export function toDisplayMessage(message: Message): DisplayMessage {
  return {
    key: `m${message.id}`,
    author: message.author_name,
    employeeId: message.employee_id,
    content: message.content,
    createdAt: message.created_at,
    own: message.employee_id === null && !message.is_system,
    system: message.is_system,
    isRequest: message.request_kind !== null,
    status: "sent",
  };
}

/** Adds `incoming` to `known`, skipping ids already there (a poll can overlap a send), ordered by id. */
export function mergeMessages(known: Message[], incoming: Message[]): Message[] {
  const seen = new Set(known.map((message) => message.id));
  const fresh = incoming.filter((message) => !seen.has(message.id));
  return fresh.length === 0 ? known : [...known, ...fresh].sort((a, b) => a.id - b.id);
}

function gapMs(previous: DisplayMessage, next: DisplayMessage): number {
  return parseDate(next.createdAt).getTime() - parseDate(previous.createdAt).getTime();
}

function sameSeries(previous: DisplayMessage | undefined, next: DisplayMessage | undefined): boolean {
  if (!previous || !next || previous.system || next.system) return false;
  return previous.own === next.own && previous.author === next.author && gapMs(previous, next) <= TIMESTAMP_GAP_MS;
}

/** "14:05" today, else the date and the time. */
export function formatBubbleTime(iso: string, now: Date = new Date(), locale?: string): string {
  const date = parseDate(iso);
  const time = date.toLocaleTimeString(locale, { hour: "2-digit", minute: "2-digit" });
  if (date.toDateString() === now.toDateString()) return time;
  return `${date.toLocaleDateString(locale, { day: "numeric", month: "short" })}, ${time}`;
}

/** Full date and time of sending, for the Info action. */
export function formatSentAt(iso: string, locale?: string): string {
  return parseDate(iso).toLocaleString(locale, { dateStyle: "long", timeStyle: "medium" });
}

/** Series of bubbles, a centered time after each pause over 1 h, system lines apart. */
export function buildChatItems(messages: DisplayMessage[], now: Date = new Date(), locale?: string): ChatItem[] {
  const items: ChatItem[] = [];
  messages.forEach((message, index) => {
    const previous = messages[index - 1];
    if (previous && gapMs(previous, message) > TIMESTAMP_GAP_MS) {
      items.push({ kind: "timestamp", key: `t${message.key}`, label: formatBubbleTime(message.createdAt, now, locale) });
    }
    if (message.system) {
      items.push({ kind: "system", key: message.key, message });
      return;
    }
    const continuing = sameSeries(previous, message);
    items.push({
      kind: "bubble",
      key: message.key,
      message,
      firstInSeries: !continuing,
      showAuthor: !continuing && !message.own,
      tail: !sameSeries(message, messages[index + 1]),
    });
  });
  return items;
}

/** What VoiceOver reads for a bubble: who, what, when, and the delivery state. */
export function bubbleLabel(message: DisplayMessage, now: Date = new Date(), locale?: string): string {
  const author = message.own ? translate("conversation.me") : message.author;
  const state =
    message.status === "sending" ? translate("conversation.sending") : message.status === "failed" ? translate("conversation.sendFailed") : "";
  return [author, message.isRequest ? translate("conversation.request") : "", message.content, formatBubbleTime(message.createdAt, now, locale), state]
    .filter(Boolean)
    .join(", ");
}
