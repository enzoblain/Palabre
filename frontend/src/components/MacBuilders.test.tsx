// @vitest-environment jsdom
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, type AppleHost, api } from "../api";
import { I18nProvider } from "../i18n";
import { MacBuilders } from "./MacBuilders";

vi.mock("../api", async (importOriginal) => {
  const original = await importOriginal<typeof import("../api")>();
  return { ...original, api: { listAppleHosts: vi.fn(), revokeAppleHost: vi.fn(), createAppleEnrollmentCode: vi.fn() } };
});

const listAppleHosts = vi.mocked(api.listAppleHosts);
const revokeAppleHost = vi.mocked(api.revokeAppleHost);
const createAppleEnrollmentCode = vi.mocked(api.createAppleEnrollmentCode);

const host = (id: number, connected: boolean, revoked = false): AppleHost => ({
  id, name: `mac-${id}`, created_at: "2026-01-01T00:00:00Z", expires_at: "2027-01-01T00:00:00Z",
  last_seen_at: "2026-01-01T00:00:00Z", revoked_at: revoked ? "2026-01-02T00:00:00Z" : null, connected,
});
const renderSection = () => render(<I18nProvider><MacBuilders /></I18nProvider>);

afterEach(() => { cleanup(); vi.resetAllMocks(); });

describe("MacBuilders", () => {
  it("shows each Mac with its state written, and hides the revoked ones", async () => {
    listAppleHosts.mockResolvedValue([host(1, true), host(2, false), host(3, true, true)]);
    renderSection();
    expect(await screen.findByText("mac-1")).toBeTruthy();
    expect(screen.getByText("Connected")).toBeTruthy();
    expect(screen.getByText("Offline")).toBeTruthy();
    expect(screen.getByText("Swift builds stay queued while the Mac is offline.")).toBeTruthy();
    expect(screen.queryByText("mac-3")).toBeNull();
  });

  it("shows the empty state, and nothing at all while Apple mode is off", async () => {
    listAppleHosts.mockResolvedValue([]);
    renderSection();
    expect(await screen.findByText(/No Mac connected/)).toBeTruthy();
    cleanup();
    listAppleHosts.mockRejectedValue(new ApiError(404, "Not found"));
    const { container } = renderSection();
    await waitFor(() => expect(container.querySelector("section")).toBeNull());
  });

  it("shows the load error and retries", async () => {
    listAppleHosts.mockRejectedValueOnce(new ApiError(500, "boom"));
    renderSection();
    expect((await screen.findByRole("alert")).textContent).toBe("Could not load the Mac state.");
    listAppleHosts.mockResolvedValue([host(1, true)]);
    await userEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(await screen.findByText("mac-1")).toBeTruthy();
  });

  it("revokes after a confirmation focused on Cancel, and announces it", async () => {
    listAppleHosts.mockResolvedValueOnce([host(1, true)]).mockResolvedValue([]);
    revokeAppleHost.mockResolvedValue(undefined);
    renderSection();
    await userEvent.click(await screen.findByRole("button", { name: "Revoke mac-1" }));
    expect(document.activeElement).toBe(screen.getByRole("button", { name: "Cancel" }));
    await userEvent.click(screen.getByRole("button", { name: "Revoke" }));
    expect(revokeAppleHost).toHaveBeenCalledWith(1);
    expect(await screen.findByText("Mac revoked")).toBeTruthy();
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("keeps the dialog open with an alert when the revocation fails", async () => {
    listAppleHosts.mockResolvedValue([host(1, true)]);
    revokeAppleHost.mockRejectedValue(new ApiError(500, "nope"));
    renderSection();
    await userEvent.click(await screen.findByRole("button", { name: "Revoke mac-1" }));
    await userEvent.click(screen.getByRole("button", { name: "Revoke" }));
    expect((await screen.findByRole("alert")).textContent).toBe("Could not revoke the Mac. Try again.");
    expect(screen.getByRole("dialog")).toBeTruthy();
  });

  it("shows the one-time code with the lifetime from the API", async () => {
    listAppleHosts.mockResolvedValue([]);
    createAppleEnrollmentCode.mockResolvedValue({ code: "ABC-123", expires_at: "2999-01-01T00:00:00Z", ttl_seconds: 900 });
    renderSection();
    await userEvent.click(await screen.findByRole("button", { name: "Generate a connection code" }));
    expect((await screen.findByRole("dialog")).textContent).toContain("ABC-123");
    expect(screen.getByText(/valid for 15 minutes/)).toBeTruthy();
    await userEvent.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("replaces an expired code with a button to generate a new one", async () => {
    listAppleHosts.mockResolvedValue([]);
    createAppleEnrollmentCode.mockResolvedValue({ code: "OLD", expires_at: "2000-01-01T00:00:00Z", ttl_seconds: 60 });
    renderSection();
    await userEvent.click(await screen.findByRole("button", { name: "Generate a connection code" }));
    expect(await screen.findByText("Code expired")).toBeTruthy();
    expect(screen.queryByText("OLD")).toBeNull();
    expect(screen.getByRole("button", { name: "Generate a new code" })).toBeTruthy();
  });

  it("shows an alert when the code cannot be generated", async () => {
    listAppleHosts.mockResolvedValue([]);
    createAppleEnrollmentCode.mockRejectedValue(new ApiError(500, "boom"));
    renderSection();
    await userEvent.click(await screen.findByRole("button", { name: "Generate a connection code" }));
    expect((await screen.findByRole("alert")).textContent).toBe("Could not generate the code. Try again.");
  });
});
