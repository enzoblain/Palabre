import { useEffect, useRef } from "react";
import { locale } from "./i18n";

/** Calls `fn` now, then `ms` after each completion, until the deps change. */
export function usePolling(fn: (() => Promise<unknown>) | null, ms: number, deps: unknown[]): void {
  const fnRef = useRef(fn);
  fnRef.current = fn;
  useEffect(() => {
    if (!fnRef.current) return;
    let stopped = false;
    let timer: number | undefined;
    const tick = async () => {
      try {
        await fnRef.current?.();
      } catch {
        // Retried on the next tick
      }
      if (!stopped) timer = window.setTimeout(tick, ms);
    };
    tick();
    return () => {
      stopped = true;
      window.clearTimeout(timer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
}

/** Dates from the server may come without a time zone: they are UTC. */
export function parseDate(value: string): Date {
  return new Date(/[zZ]|[+-]\d\d:?\d\d$/.test(value) ? value : `${value}Z`);
}

export function formatTime(value: string): string {
  const date = parseDate(value);
  const today = new Date().toDateString() === date.toDateString();
  return date.toLocaleString(locale(), today ? { hour: "2-digit", minute: "2-digit" } : { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
}

const AVATAR_HUES = [12, 32, 145, 175, 200, 230, 262, 290, 320, 350];

export function avatarHue(name: string): number {
  let h = 0;
  for (const c of name) h = (h * 31 + c.charCodeAt(0)) >>> 0;
  return AVATAR_HUES[h % AVATAR_HUES.length];
}

/** Event to insert an @mention into the open conversation's composer. */
export const MENTION_EVENT = "palabre:mention";

export function mention(name: string): void {
  window.dispatchEvent(new CustomEvent(MENTION_EVENT, { detail: name }));
}

/** Same spreading as backend/app/accounts.py: custom accounts are kept, the others
 * fill the least loaded account. `members` must be in creation order. */
export function spreadAccounts(members: (number | null | undefined)[], count: number): number[] {
  const n = Math.max(count, 1);
  const load = new Array(n).fill(0);
  const result = members.map((a) => (a && a >= 1 && a <= n ? a : 0));
  result.forEach((a) => a && load[a - 1]++);
  return result.map((a) => {
    if (a) return a;
    const least = load.indexOf(Math.min(...load));
    load[least]++;
    return least + 1;
  });
}
