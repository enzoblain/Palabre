import type { Key } from "./i18n";

/** The one table from a task status (as the backend sends it) to its translation key. */
const STATUS_KEYS: Record<string, Key> = {
  todo: "task.todo",
  in_progress: "task.in_progress",
  review: "task.review",
  changes_requested: "task.changes_requested",
  done: "task.done",
  cancelled: "task.cancelled",
};

/** The label of a task status; an unknown status is shown as the server sent it. */
export function taskStatusLabel(status: string, t: (key: Key) => string): string {
  const key = STATUS_KEYS[status];
  return key ? t(key) : status;
}
