import type { Device } from "./api";

/** The list without the revoked device. */
export function withoutDevice(devices: Device[], id: number): Device[] {
  return devices.filter((device) => device.id !== id);
}

/** Index of the element focused after Tab (or Shift+Tab) in a modal with `count` focusable elements: it wraps. */
export function trappedFocusIndex(count: number, current: number, backwards: boolean): number {
  if (count <= 0) return -1;
  return (current + (backwards ? -1 : 1) + count) % count;
}

/** The backend sets `last_used_at` to `created_at` when pairing: a device never used still has them equal. */
export function neverUsed(device: Device): boolean {
  return device.last_used_at === device.created_at;
}
