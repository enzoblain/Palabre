// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, type Task, api } from "../api";
import { I18nProvider } from "../i18n";
import { TaskList } from "./TaskList";

vi.mock("../api", async (importOriginal) => {
  const original = await importOriginal<typeof import("../api")>();
  return { ...original, api: { listTasks: vi.fn() } };
});

const listTasks = vi.mocked(api.listTasks);
const task = (id: number, title: string): Task => ({
  id, project_id: 1, room_id: 2, conversation_id: 3, kind: "feature", title, status: "todo", assignee: null,
  severity: null, sensitive: false, marked_sensitive: false, pr_url: null, review_round: 0,
  created_at: "2026-11-04T10:00:00Z", updated_at: "2026-11-04T10:00:00Z",
});
const renderList = () => render(<I18nProvider><TaskList projectId={1} /></I18nProvider>);

afterEach(() => { cleanup(); vi.resetAllMocks(); });

describe("TaskList", () => {
  it("links each task to its page, newest first", async () => {
    listTasks.mockResolvedValue([task(1, "Old"), task(2, "New")]);
    renderList();
    const links = await screen.findAllByRole("link");
    expect(links.map((l) => l.getAttribute("href"))).toEqual(["#/p/1/tasks/2", "#/p/1/tasks/1"]);
  });

  it("shows the translated status", async () => {
    listTasks.mockResolvedValue([{ ...task(1, "A"), status: "changes_requested" }]);
    renderList();
    expect(await screen.findByText("Changes requested")).toBeTruthy();
  });

  it("shows the empty and error states", async () => {
    listTasks.mockResolvedValueOnce([]);
    renderList();
    expect(await screen.findByText("No task yet.")).toBeTruthy();
    cleanup();
    listTasks.mockRejectedValue(new ApiError(500, "boom"));
    renderList();
    expect((await screen.findByRole("alert")).textContent).toBe("Could not load the tasks.");
  });
});
