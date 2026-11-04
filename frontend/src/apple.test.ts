// @vitest-environment jsdom
import { describe, expect, it } from "vitest";
import { ApiError, type AppleBuild, type AppleHost } from "./api";
import { isAppleModeOff, isKnownStatus, isSettled, relativeTime, shortSha, sortBySeen } from "./apple";

const host = (id: number, lastSeen: string | null): AppleHost => ({
  id, name: `mac-${id}`, created_at: "2026-01-01T00:00:00Z", expires_at: "2027-01-01T00:00:00Z",
  last_seen_at: lastSeen, revoked_at: null, connected: true,
});
const build = (status: AppleBuild["status"]): AppleBuild => ({
  job_id: 1, status, commit_sha: "a1b2c3d4e5", infra_error: status === "error", summary: "", errors: [], finished_at: null,
});

describe("apple helpers", () => {
  it("treats a 404 as Apple mode off", () => {
    expect(isAppleModeOff(new ApiError(404, "nope"))).toBe(true);
    expect(isAppleModeOff(new ApiError(500, "boom"))).toBe(false);
    expect(isAppleModeOff(new Error("x"))).toBe(false);
  });

  it("sorts the Macs by last seen, never seen last", () => {
    const sorted = sortBySeen([host(1, "2026-01-01T00:00:00Z"), host(2, null), host(3, "2026-02-01T00:00:00Z")]);
    expect(sorted.map((h) => h.id)).toEqual([3, 1, 2]);
  });

  it("picks the largest fitting unit for the relative time", () => {
    const now = new Date("2026-01-01T12:00:00Z");
    expect(relativeTime(new Date("2026-01-01T11:59:48Z"), now, "en")).toBe("12 seconds ago");
    expect(relativeTime(new Date("2026-01-01T09:00:00Z"), now, "en")).toBe("3 hours ago");
  });

  it("shortens the commit and knows the backend statuses only", () => {
    expect(shortSha("a1b2c3d4e5")).toBe("a1b2c3d");
    expect(isKnownStatus("passed")).toBe(true);
    expect(isKnownStatus("cancelled")).toBe(false);
  });

  it("settles a build once the Mac gave its verdict", () => {
    expect(isSettled(null)).toBe(true);
    expect(isSettled(build("queued"))).toBe(false);
    expect(isSettled(build("running"))).toBe(false);
    expect(isSettled(build("failed"))).toBe(true);
  });
});
