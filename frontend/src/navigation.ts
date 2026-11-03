import type { Route } from "./router";

/** Only the two root screens, Projects and Settings, carry the bottom bar; every other screen is full screen. */
export function showsBottomBar(route: Route): boolean {
  return route.name === "home" || route.name === "settings";
}

export type LoadStatus = "loading" | "ready" | "error";

/** A failed load only shows the error before anything loaded: a failed poll keeps the list on screen. */
export function statusAfterFailure(status: LoadStatus): LoadStatus {
  return status === "loading" ? "error" : status;
}

/**
 * Where the back arrow leads: the parent screen, whatever the browser history holds (direct URL, reload).
 * A conversation has no project screen above it (opening a project redirects into a conversation), so it leads to the projects.
 */
export function parentPath(route: Route): string {
  if (route.name === "info") return `/p/${route.projectId}`;
  return "/";
}

/** Above this many projects, the Projects screen offers a search field. */
export const PROJECT_SEARCH_MIN_COUNT = 8;

/** Projects whose name contains the search, case-insensitively. */
export function filterProjects<T extends { name: string }>(projects: T[], search: string): T[] {
  const needle = search.trim().toLowerCase();
  return needle ? projects.filter((p) => p.name.toLowerCase().includes(needle)) : projects;
}

/** The most recently opened project first, the others keep their order. */
export function lastOpenedFirst<T extends { id: number }>(projects: T[], lastOpenedId: number | null): T[] {
  const last = projects.find((p) => p.id === lastOpenedId);
  return last ? [last, ...projects.filter((p) => p !== last)] : projects;
}

const LAST_OPENED_KEY = "palabre.lastOpenedProject";

export function rememberOpenedProject(projectId: number): void {
  localStorage.setItem(LAST_OPENED_KEY, String(projectId));
}

export function readLastOpenedProject(): number | null {
  const raw = localStorage.getItem(LAST_OPENED_KEY);
  return raw && /^\d+$/.test(raw) ? Number(raw) : null;
}
