import type { AppleBuild, AppleBuildStatus, AppleHost } from "./api";
import { ApiError } from "./api";

const SHORT_SHA_LENGTH = 7;
const NOT_FOUND = 404;
const KNOWN_STATUSES: readonly AppleBuildStatus[] = ["queued", "running", "passed", "failed", "error"];
// Largest unit first: the relative time uses the first one that fits
const RELATIVE_UNITS: [Intl.RelativeTimeFormatUnit, number][] = [["day", 86400], ["hour", 3600], ["minute", 60], ["second", 1]];

/** The Apple endpoints answer 404 while the mode is off on the server. */
export function isAppleModeOff(err: unknown): boolean {
  return err instanceof ApiError && err.status === NOT_FOUND;
}

/** Most recently seen Mac first; a Mac never seen goes last. */
export function sortBySeen(hosts: AppleHost[]): AppleHost[] {
  const seen = (host: AppleHost): number => (host.last_seen_at ? Date.parse(host.last_seen_at) : 0);
  return [...hosts].sort((a, b) => seen(b) - seen(a));
}

/** "12 seconds ago", "3 hours ago": the unit is the largest one that fits. */
export function relativeTime(date: Date, now: Date, locale: string): string {
  const seconds = Math.round((date.getTime() - now.getTime()) / 1000);
  const [unit, size] = RELATIVE_UNITS.find(([, size]) => Math.abs(seconds) >= size) ?? RELATIVE_UNITS[RELATIVE_UNITS.length - 1];
  return new Intl.RelativeTimeFormat(locale, { numeric: "auto" }).format(Math.round(seconds / size), unit);
}

export const shortSha = (sha: string): string => sha.slice(0, SHORT_SHA_LENGTH);

/** Narrows a status to the ones the backend defines: anything else must be shown as unknown, never invented. */
export function isKnownStatus(status: string): status is AppleBuildStatus {
  return (KNOWN_STATUSES as readonly string[]).includes(status);
}

/** A finished build (the Mac will not change it): no need to poll it. */
export function isSettled(build: AppleBuild | null): boolean {
  return !build || !(build.status === "queued" || build.status === "running");
}
