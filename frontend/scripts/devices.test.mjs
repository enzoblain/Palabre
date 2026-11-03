// Unit tests of src/devices.ts, run with Node's built-in test runner (no extra dependency).
import assert from "node:assert/strict";
import { test } from "node:test";
import { neverUsed, trappedFocusIndex, withoutDevice } from "../src/devices.ts";

const device = (id, lastUsed = "2026-01-02T00:00:00Z") => ({
  id, name: `Phone ${id}`, created_at: "2026-01-01T00:00:00Z", last_used_at: lastUsed, expires_at: "2026-02-01T00:00:00Z",
});

test("a revoked device disappears and the others stay in order", () => {
  assert.deepEqual(withoutDevice([device(1), device(2), device(3)], 2).map((d) => d.id), [1, 3]);
  assert.deepEqual(withoutDevice([device(1)], 9).map((d) => d.id), [1]);
});

test("a device whose last use equals its creation was never used", () => {
  assert.equal(neverUsed(device(1, "2026-01-01T00:00:00Z")), true);
  assert.equal(neverUsed(device(1)), false);
});

test("Tab and Shift+Tab wrap around inside the dialog", () => {
  assert.equal(trappedFocusIndex(2, 1, false), 0);
  assert.equal(trappedFocusIndex(2, 0, true), 1);
  assert.equal(trappedFocusIndex(2, -1, false), 0);
  assert.equal(trappedFocusIndex(0, 0, false), -1);
});
