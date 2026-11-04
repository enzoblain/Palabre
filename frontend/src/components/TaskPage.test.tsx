// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, type ProjectPlatform, type TaskDetail, api } from "../api";
import { I18nProvider } from "../i18n";
import { TaskPage } from "./TaskPage";

vi.mock("../api", async (importOriginal) => {
  const original = await importOriginal<typeof import("../api")>();
  return { ...original, api: { getTask: vi.fn(), getTaskBuild: vi.fn(), retryAppleBuild: vi.fn() } };
});

const getTask = vi.mocked(api.getTask);
const getTaskBuild = vi.mocked(api.getTaskBuild);

const task = (extra: Partial<TaskDetail> = {}): TaskDetail => ({
  id: 7, project_id: 1, room_id: 2, conversation_id: 3, kind: "feature", title: "Add login", status: "in_progress",
  assignee: "Salomé", severity: null, sensitive: false, marked_sensitive: false, pr_url: "https://github.com/a/b/pull/9",
  review_round: 0, created_at: "2026-11-04T10:00:00Z", updated_at: "2026-11-04T10:00:00Z", apple_build: null,
  description: "", acceptance_criteria: ["It works"], branch: "task/7", ...extra,
});
const renderPage = (platform: ProjectPlatform) => render(<I18nProvider><TaskPage taskId={7} platform={platform} /></I18nProvider>);

afterEach(() => { cleanup(); vi.resetAllMocks(); });

describe("TaskPage", () => {
  it("shows the title, status, assignee and PR link", async () => {
    getTask.mockResolvedValue(task());
    renderPage("generic");
    expect(await screen.findByText("Add login")).toBeTruthy();
    expect(screen.getByText("In progress")).toBeTruthy();
    expect(screen.getByText("Salomé")).toBeTruthy();
    expect(screen.getByRole("link", { name: "View pull request (opens in a new tab)" }).getAttribute("href")).toBe("https://github.com/a/b/pull/9");
    expect(document.activeElement).toBe(screen.getByRole("heading", { level: 1, name: "Add login" }));
  });

  it("shows the Swift build on an Apple project only", async () => {
    getTask.mockResolvedValue(task());
    getTaskBuild.mockResolvedValue({ apple_build: null });
    renderPage("apple");
    expect(await screen.findByRole("heading", { name: "Swift build" })).toBeTruthy();
    cleanup();
    renderPage("generic");
    await screen.findByText("Add login");
    expect(screen.queryByRole("heading", { name: "Swift build" })).toBeNull();
  });

  it("shows the empty values and never links a non-http PR url", async () => {
    getTask.mockResolvedValue(task({ assignee: null, pr_url: "javascript:alert(1)" }));
    renderPage("generic");
    expect(await screen.findByText("Nobody yet")).toBeTruthy();
    expect(screen.getByText("No pull request yet")).toBeTruthy();
    expect(screen.queryByRole("link")).toBeNull();
  });

  it("shows the error state", async () => {
    getTask.mockRejectedValue(new ApiError(500, "boom"));
    renderPage("generic");
    expect((await screen.findByRole("alert")).textContent).toBe("Could not load the task.");
  });
});
