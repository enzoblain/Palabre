import type { Device } from "../api";
import { currentLanguage } from "../i18n";
import { parseDate } from "./conversations";

/** The list without the revoked device. */
export function withoutDevice(devices: Device[], id: number): Device[] {
  return devices.filter((device) => device.id !== id);
}

/** The backend sets `last_used_at` to `created_at` when pairing: a device never used still has them equal. */
export function neverUsed(device: Device): boolean {
  return device.last_used_at === device.created_at;
}

/** Long date and short time in the phone's language. */
export function formatDateTime(value: string): string {
  return parseDate(value).toLocaleString(currentLanguage(), { dateStyle: "long", timeStyle: "short" });
}

/**
 * Same spreading as backend/app/accounts.py: pinned accounts are kept, the others fill the least loaded
 * account. `members` must be in creation order.
 */
export function spreadAccounts(members: (number | null | undefined)[], count: number): number[] {
  const accountCount = Math.max(count, 1);
  const load: number[] = new Array(accountCount).fill(0);
  const pinned = members.map((account) => (account && account >= 1 && account <= accountCount ? account : 0));
  pinned.forEach((account) => account && load[account - 1]++);
  return pinned.map((account) => {
    if (account) return account;
    const least = load.indexOf(Math.min(...load));
    load[least]++;
    return least + 1;
  });
}
