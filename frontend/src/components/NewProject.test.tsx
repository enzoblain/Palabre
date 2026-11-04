// @vitest-environment jsdom
import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError, type ErrorCode, type ProjectDetail, api } from "../api";
import { I18nProvider } from "../i18n";
import { NewProject } from "./NewProject";

vi.mock("../api", async (importOriginal) => {
  const original = await importOriginal<typeof import("../api")>();
  return {
    ...original,
    api: {
      names: vi.fn(), limits: vi.fn(), personalities: vi.fn(), roles: vi.fn(), listAppleHosts: vi.fn(), createProject: vi.fn(),
    },
  };
});

const createProject = vi.mocked(api.createProject);
const REFUSAL = "No Mac builder is connected: connect one to create a Swift project";

beforeEach(() => {
  vi.mocked(api.names).mockResolvedValue([]);
  vi.mocked(api.limits).mockResolvedValue({ models: [], max_agents: 10, min_team_size: 1, mandatory_role: "lead" });
  vi.mocked(api.personalities).mockResolvedValue({});
  vi.mocked(api.roles).mockResolvedValue({});
  vi.mocked(api.listAppleHosts).mockResolvedValue([]);
});
afterEach(() => { cleanup(); vi.resetAllMocks(); });

async function submitForm() {
  const user = userEvent.setup();
  render(<I18nProvider><NewProject claudeAccounts={1} onCreated={vi.fn<(project: ProjectDetail) => void>()} /></I18nProvider>);
  await user.type(screen.getByLabelText("Name"), "Demo");
  await user.type(screen.getByLabelText("GitHub repository"), "https://github.com/you/demo");
  await user.type(screen.getByLabelText("Project description"), "A demo app");
  await user.click(screen.getByRole("button", { name: "Create project" }));
}

describe("NewProject creation refusal", () => {
  it("shows the refusal and a link to the settings when no Mac is connected", async () => {
    createProject.mockRejectedValue(new ApiError(409, REFUSAL, undefined, "apple_host_required"));
    await submitForm();
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain(REFUSAL);
    expect(within(alert).getByRole("link", { name: "Connect a Mac" }).getAttribute("href")).toBe("#/settings");
  });

  it("shows no link for another error", async () => {
    createProject.mockRejectedValue(new ApiError(500, "Boom", undefined, "unknown" as ErrorCode));
    await submitForm();
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("Boom");
    expect(within(alert).queryByRole("link")).toBeNull();
  });
});
