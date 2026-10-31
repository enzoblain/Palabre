// Unit tests of src/presets.ts, run with Node's built-in test runner (no extra dependency).
import assert from "node:assert/strict";
import { test } from "node:test";
import { applyPreset, formatLevel, leaningAxes, levelBar } from "../src/presets.ts";

const personality = { axes: [{ key: "rigor", label: "Rigor" }, { key: "speed", label: "Speed" }, { key: "risk", label: "Risk" }] };
const preset = {
  key: "perfectionist",
  label: "Perfectionist",
  traits: { rigor: 2, speed: -1 },
  quirks: ["Quotes sources."],
  style: { tone: "formal" },
};

test("applying a preset sets every axis, neutral when the preset leaves it out", () => {
  const applied = applyPreset(preset, personality, { style: { verbosity: "balanced", tone: "casual" } });
  assert.deepEqual(applied.traits, { rigor: 2, speed: -1, risk: 0 });
  assert.equal(applied.personality, "perfectionist");
});

test("the preset style wins and the other style keys are kept", () => {
  const applied = applyPreset(preset, personality, { style: { verbosity: "balanced", tone: "casual" } });
  assert.deepEqual(applied.style, { verbosity: "balanced", tone: "formal" });
});

test("applied quirks are a copy of the preset's", () => {
  const applied = applyPreset(preset, personality, { style: {} });
  applied.quirks.push("Other.");
  assert.deepEqual(preset.quirks, ["Quotes sources."]);
});

test("leaning axes skip neutral ones and put the strongest first", () => {
  assert.deepEqual(leaningAxes({ ...preset, traits: { rigor: -1, speed: 2 } }, personality),
    [{ label: "Speed", level: 2 }, { label: "Rigor", level: -1 }]);
  assert.deepEqual(leaningAxes({ ...preset, traits: {} }, personality), []);
});

test("levels are written with their sign and drawn on five cells", () => {
  assert.deepEqual([2, 0, -1].map(formatLevel), ["+2", "0", "-1"]);
  assert.equal(levelBar(2), "▓▓▓▓▓");
  assert.equal(levelBar(-1), "▓▓░░░");
  assert.equal(levelBar(-2), "▓░░░░");
});
