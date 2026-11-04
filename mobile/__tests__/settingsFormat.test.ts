import type { Device } from "../src/api";
import { neverUsed, spreadAccounts, withoutDevice } from "../src/format/settings";

jest.mock("expo-localization", () => ({ getLocales: () => [{ languageCode: "fr" }] }));

const device = (id: number, over: Partial<Device> = {}): Device => ({
  id,
  name: `Phone ${id}`,
  created_at: "2026-01-01T10:00:00",
  last_used_at: "2026-01-02T10:00:00",
  expires_at: "2026-02-01T10:00:00",
  ...over,
});

describe("devices helpers", () => {
  it("removes the revoked device only", () => {
    expect(withoutDevice([device(1), device(2)], 1).map((d) => d.id)).toEqual([2]);
  });

  it("flags a device whose last use equals its creation as never used", () => {
    expect(neverUsed(device(1, { last_used_at: "2026-01-01T10:00:00" }))).toBe(true);
    expect(neverUsed(device(1))).toBe(false);
  });
});

describe("spreadAccounts", () => {
  it("keeps pinned accounts and fills the least loaded one", () => {
    expect(spreadAccounts([2, null, null], 2)).toEqual([2, 1, 1]);
  });

  it("ignores an account beyond the count and works with no account configured", () => {
    expect(spreadAccounts([5, null], 2)).toEqual([1, 2]);
    expect(spreadAccounts([null, null], 0)).toEqual([1, 1]);
  });
});
