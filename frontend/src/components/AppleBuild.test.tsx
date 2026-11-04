// @vitest-environment jsdom
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, type AppleBuild as Build, api } from "../api";
import { I18nProvider } from "../i18n";
import { AppleBuild } from "./AppleBuild";

vi.mock("../api", async (importOriginal) => {
  const original = await importOriginal<typeof import("../api")>();
  return { ...original, api: { getTaskBuild: vi.fn(), retryAppleBuild: vi.fn() } };
});

const getTaskBuild = vi.mocked(api.getTaskBuild);
const retryAppleBuild = vi.mocked(api.retryAppleBuild);

const build = (status: Build["status"], extra: Partial<Build> = {}): Build => ({
  job_id: 1, status, commit_sha: "a1b2c3d4e5f6", infra_error: status === "error", summary: "", errors: [], finished_at: null, ...extra,
});
const renderBlock = () => render(<I18nProvider><AppleBuild taskId={7} /></I18nProvider>);

afterEach(() => { cleanup(); vi.resetAllMocks(); });

describe("AppleBuild", () => {
  it.each([
    ["queued", "Waiting"], ["running", "Running"], ["passed", "Passed"], ["failed", "Failed"], ["error", "Infrastructure error"],
  ] as const)("shows the %s state with its word and the short commit", async (status, label) => {
    getTaskBuild.mockResolvedValue({ apple_build: build(status) });
    renderBlock();
    expect(await screen.findByText(label)).toBeTruthy();
    expect(screen.getByText("commit a1b2c3d")).toBeTruthy();
  });

  it("shows an unknown status as plain text", async () => {
    getTaskBuild.mockResolvedValue({ apple_build: build("cancelled" as Build["status"]) });
    renderBlock();
    expect(await screen.findByText("Unknown status: cancelled")).toBeTruthy();
  });

  it("shows the empty and error states", async () => {
    getTaskBuild.mockResolvedValueOnce({ apple_build: null });
    renderBlock();
    expect(await screen.findByText("No build yet")).toBeTruthy();
    cleanup();
    getTaskBuild.mockRejectedValueOnce(new ApiError(500, "boom"));
    renderBlock();
    expect((await screen.findByRole("alert")).textContent).toBe("Could not load the build.");
  });

  it("reveals the errors as plain text in a focusable, labelled block", async () => {
    getTaskBuild.mockResolvedValue({ apple_build: build("failed", { summary: "2 errors", errors: ["<b>error:</b> x"] }) });
    renderBlock();
    expect(await screen.findByText("2 errors")).toBeTruthy();
    const toggle = screen.getByRole("button", { name: "Show the detail" });
    expect(toggle.getAttribute("aria-expanded")).toBe("false");
    await userEvent.click(toggle);
    const log = screen.getByLabelText("Build log");
    expect(log.textContent).toBe("<b>error:</b> x");
    expect(log.getAttribute("tabindex")).toBe("0");
    expect(log.querySelector("b")).toBeNull();
  });

  it("offers a retry only after an infra error, and switches to the new job", async () => {
    getTaskBuild.mockResolvedValue({ apple_build: build("failed") });
    renderBlock();
    await screen.findByText("Failed");
    expect(screen.queryByRole("button", { name: "Retry" })).toBeNull();
    cleanup();
    getTaskBuild.mockResolvedValueOnce({ apple_build: build("error") }).mockResolvedValue({ apple_build: build("queued") });
    retryAppleBuild.mockResolvedValue({ apple_build: build("queued") });
    renderBlock();
    await userEvent.click(await screen.findByRole("button", { name: "Retry" }));
    expect(retryAppleBuild).toHaveBeenCalledWith(7);
    expect(await screen.findByText("Waiting")).toBeTruthy();
    expect(screen.getByText("Build waiting")).toBeTruthy();
  });

  it("shows an alert when the retry fails", async () => {
    getTaskBuild.mockResolvedValue({ apple_build: build("error") });
    retryAppleBuild.mockRejectedValue(new ApiError(422, "no"));
    renderBlock();
    await userEvent.click(await screen.findByRole("button", { name: "Retry" }));
    await waitFor(() => expect(screen.getByRole("alert").textContent).toBe("Could not retry the build. Try again."));
  });
});
