// Unit tests of src/jobs.ts, run with Node's built-in test runner (no extra dependency).
import assert from "node:assert/strict";
import { test } from "node:test";
import { groupJobs, teamWarningThreshold } from "../src/jobs.ts";

const role = (key, category, order, title = key, description = "") => ({ key, category, order, title, description });
const roles = {
  qa: role("qa", "quality", 3, "QA", "Tests the product"),
  dev: role("dev", "engineering", 2, "Developer", "Writes code"),
  lead: role("lead", "management", 1, "Lead", "Splits the work"),
  arch: role("arch", "engineering", 0, "Architect", "Designs code"),
};

test("groups by category in display order, sorted by order inside a group", () => {
  const groups = groupJobs(roles, "");
  assert.deepEqual(groups.map(([category]) => category), ["management", "engineering", "quality"]);
  assert.deepEqual(groups[1][1].map((r) => r.key), ["arch", "dev"]);
});

test("search matches title and description, case-insensitively and trimmed", () => {
  assert.deepEqual(groupJobs(roles, "  CODE ").flatMap(([, jobs]) => jobs.map((r) => r.key)), ["arch", "dev"]);
  assert.deepEqual(groupJobs(roles, "lead").flatMap(([, jobs]) => jobs.map((r) => r.key)), ["lead"]);
});

test("empty groups are dropped and no match gives no group", () => {
  assert.deepEqual(groupJobs(roles, "tests").map(([category]) => category), ["quality"]);
  assert.deepEqual(groupJobs(roles, "zzz"), []);
});

test("the warning threshold follows the server limit", () => {
  assert.equal(teamWarningThreshold(30), 24);
  assert.equal(teamWarningThreshold(20), 16);
  assert.ok(teamWarningThreshold(20) < 20);
});
