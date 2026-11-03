import { translate } from "../i18n";
import type { ProjectListItem } from "../api";

const MS_PER_DAY = 86_400_000;
const WEEK_DAYS = 7;
const AVATAR_HUES = 360;
const AVATAR_SATURATION = 45;
const AVATAR_LIGHTNESS = 38; // dark enough for white initials at 4.5:1
const MAX_INITIALS = 2;

/** The server sends UTC timestamps without a zone suffix. */
export function parseDate(value: string): Date {
  return new Date(/[zZ]|[+-]\d\d:?\d\d$/.test(value) ? value : `${value}Z`);
}

/** When the conversation last moved: its last message, else the project creation. */
export function lastActivity(item: ProjectListItem): string {
  return item.last_message?.created_at ?? item.created_at;
}

/** Most recent activity first; the input is left untouched. */
export function sortByActivity(items: ProjectListItem[]): ProjectListItem[] {
  return [...items].sort((a, b) => parseDate(lastActivity(b)).getTime() - parseDate(lastActivity(a)).getTime());
}

/** Case-insensitive match on the name and the last message; an empty query keeps everything. */
export function filterConversations(items: ProjectListItem[], query: string): ProjectListItem[] {
  const needle = query.trim().toLowerCase();
  if (!needle) return items;
  return items.filter(
    (item) =>
      item.name.toLowerCase().includes(needle) || (item.last_message?.content.toLowerCase().includes(needle) ?? false),
  );
}

export function initials(name: string): string {
  return name
    .split(/[\s\-_.·]+/)
    .filter(Boolean)
    .slice(0, MAX_INITIALS)
    .map((word) => String.fromCodePoint(word.codePointAt(0)!).toUpperCase())
    .join("");
}

/** A stable color derived from the name, so a conversation keeps its avatar. */
export function avatarColor(name: string): string {
  let hash = 0;
  for (const char of name) hash = (hash * 31 + char.codePointAt(0)!) % AVATAR_HUES;
  return `hsl(${hash}, ${AVATAR_SATURATION}%, ${AVATAR_LIGHTNESS}%)`;
}

function startOfDay(date: Date): number {
  return new Date(date.getFullYear(), date.getMonth(), date.getDate()).getTime();
}

/** iMessage style: the time today, "Yesterday", the weekday this week, else the short date. */
export function formatListTime(iso: string, now: Date = new Date(), locale?: string): string {
  const date = parseDate(iso);
  const days = Math.round((startOfDay(now) - startOfDay(date)) / MS_PER_DAY);
  if (days <= 0) return date.toLocaleTimeString(locale, { hour: "2-digit", minute: "2-digit" });
  if (days === 1) return translate("list.yesterday");
  if (days < WEEK_DAYS) return date.toLocaleDateString(locale, { weekday: "long" });
  return date.toLocaleDateString(locale, { day: "2-digit", month: "2-digit", year: "2-digit" });
}
