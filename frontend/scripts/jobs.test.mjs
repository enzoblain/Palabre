// Unit tests of src/jobs.ts, run with Node's built-in test runner (no extra dependency).
import assert from "node:assert/strict";
import { test } from "node:test";
import { autoTeamProblems, groupJobs, teamProblems, teamWarningThreshold } from "../src/jobs.ts";

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

test("search matches the name only, case-insensitively and trimmed", () => {
  assert.deepEqual(groupJobs(roles, "  DEVEL ").flatMap(([, jobs]) => jobs.map((r) => r.key)), ["dev"]);
  assert.deepEqual(groupJobs(roles, "code"), []);
  assert.deepEqual(groupJobs(roles, "lead").flatMap(([, jobs]) => jobs.map((r) => r.key)), ["lead"]);
});

test("empty groups are dropped and no match gives no group", () => {
  assert.deepEqual(groupJobs(roles, "qa").map(([category]) => category), ["quality"]);
  assert.deepEqual(groupJobs(roles, "zzz"), []);
});

test("the warning threshold follows the server limit", () => {
  assert.equal(teamWarningThreshold(30), 24);
  assert.equal(teamWarningThreshold(20), 16);
  assert.ok(teamWarningThreshold(20) < 20);
});

test("historic categories come before the extended ones", () => {
  const mixed = { ...roles, sec: role("sec", "cybersecurity", 0, "Pentester"), ml: role("ml", "artificial_intelligence", 1, "ML engineer") };
  assert.deepEqual(groupJobs(mixed, "").map(([category]) => category),
    ["management", "engineering", "quality", "artificial_intelligence", "cybersecurity"]);
});

const member = (name, ...roles) => ({ name, roles });
const team = (size, ...firstRoles) =>
  Array.from({ length: size }, (_, i) => member(`Member${i}`, ...(i === 0 ? firstRoles : ["dev"])));

test("a company team below four members, lead included, is too small", () => {
  assert.deepEqual(teamProblems(team(3, "lead"), "lead", 4, 30), ["tooSmall"]);
  assert.deepEqual(teamProblems([], "lead", 4, 30), ["none"]);
});

test("a company team needs its lead", () => {
  assert.deepEqual(teamProblems(team(4, "dev"), "lead", 4, 30), ["noLead"]);
  assert.deepEqual(teamProblems(team(4, "dev"), null, 4, 30), []);
});

test("a company team of four with a lead is fine, and the maximum is enforced", () => {
  assert.deepEqual(teamProblems(team(4, "lead"), "lead", 4, 30), []);
  assert.deepEqual(teamProblems(team(31, "lead"), "lead", 4, 30), ["tooBig"]);
});

test("members need distinct valid names and a role", () => {
  assert.deepEqual(teamProblems([member("Ana", "lead"), member("ana", "dev")], "lead", 1, 30), ["duplicate"]);
  assert.deepEqual(teamProblems([member("", "lead")], "lead", 1, 30), ["noName"]);
  assert.deepEqual(teamProblems([member("a b", "lead")], "lead", 1, 30), ["badName"]);
  assert.deepEqual(teamProblems([member("Ana")], null, 1, 30), ["noRole"]);
});

test("an automatic head count is bounded on both sides", () => {
  assert.deepEqual(autoTeamProblems(3, 4, 30), ["tooSmall"]);
  assert.deepEqual(autoTeamProblems(4, 4, 30), []);
  assert.deepEqual(autoTeamProblems(30, 4, 30), []);
  assert.deepEqual(autoTeamProblems(31, 4, 30), ["tooBig"]);
});
