// Unit tests of src/presets.ts, run with Node's built-in test runner (no extra dependency).
import assert from "node:assert/strict";
import { test } from "node:test";
import { filterPresets } from "../src/presets.ts";

const presets = {
  zen: { key: "zen", label: "Zen", description: "Calm under pressure." },
  determined: { key: "determined", label: "Déterminé", description: "Never gives up on a hard bug." },
  careful: { key: "careful", label: "Careful", description: "Checks twice, ships once." },
};

test("without a query, every preset is listed by name", () => {
  assert.deepEqual(filterPresets(presets, "").map((p) => p.key), ["careful", "determined", "zen"]);
  assert.deepEqual(filterPresets(presets, "   ").map((p) => p.key), ["careful", "determined", "zen"]);
});

test("the search looks at the name and the description, ignoring case and accents", () => {
  assert.deepEqual(filterPresets(presets, "DETERMINE").map((p) => p.key), ["determined"]);
  assert.deepEqual(filterPresets(presets, "pressure").map((p) => p.key), ["zen"]);
});

test("every word of the query must match", () => {
  assert.deepEqual(filterPresets(presets, "checks ships").map((p) => p.key), ["careful"]);
  assert.deepEqual(filterPresets(presets, "checks calm"), []);
});
