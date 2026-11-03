// Unit tests of src/navigation.ts, run with Node's built-in test runner (no extra dependency).
import assert from "node:assert/strict";
import { test } from "node:test";
import { backFallback, filterProjects, lastOpenedFirst, showsBottomBar } from "../src/navigation.ts";

test("the bottom bar shows on the two root screens only", () => {
  assert.equal(showsBottomBar({ name: "home" }), true);
  assert.equal(showsBottomBar({ name: "settings" }), true);
});

test("the bottom bar is hidden on every full-screen route", () => {
  const routes = [
    { name: "new" },
    { name: "project", projectId: 1, conversationId: null },
    { name: "project", projectId: 1, conversationId: 2 },
    { name: "info", projectId: 1 },
  ];
  for (const route of routes) assert.equal(showsBottomBar(route), false, JSON.stringify(route));
});

test("the info screen falls back to its project, the others to the projects", () => {
  assert.equal(backFallback({ name: "info", projectId: 7 }), "/p/7");
  assert.equal(backFallback({ name: "new" }), "/");
  assert.equal(backFallback({ name: "project", projectId: 7, conversationId: 3 }), "/");
});

test("project search ignores case and surrounding spaces, empty search keeps all", () => {
  const projects = [{ name: "Alpha" }, { name: "beta" }];
  assert.deepEqual(filterProjects(projects, "  AL "), [{ name: "Alpha" }]);
  assert.equal(filterProjects(projects, "  "), projects);
  assert.deepEqual(filterProjects(projects, "zzz"), []);
});

test("the last opened project comes first", () => {
  const projects = [{ id: 1 }, { id: 2 }, { id: 3 }];
  assert.deepEqual(lastOpenedFirst(projects, 3).map((p) => p.id), [3, 1, 2]);
  assert.equal(lastOpenedFirst(projects, 99), projects);
  assert.equal(lastOpenedFirst(projects, null), projects);
});
