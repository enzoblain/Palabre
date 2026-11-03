// @vitest-environment jsdom
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError, type Device, api } from "../api";
import { I18nProvider } from "../i18n";
import { ConnectedDevices } from "./ConnectedDevices";

vi.mock("../api", async (importOriginal) => {
  const original = await importOriginal<typeof import("../api")>();
  return { ...original, api: { listDevices: vi.fn(), revokeDevice: vi.fn() } };
});

const listDevices = vi.mocked(api.listDevices);
const revokeDevice = vi.mocked(api.revokeDevice);

const device = (id: number, name: string): Device => ({
  id, name, created_at: "2026-01-01T00:00:00Z", last_used_at: "2026-01-01T00:00:00Z", expires_at: "2026-02-01T00:00:00Z",
});

const renderSection = () => render(<I18nProvider><ConnectedDevices /></I18nProvider>);

beforeEach(() => { listDevices.mockResolvedValue([device(1, "Pixel"), device(2, "iPhone")]); });
afterEach(() => { cleanup(); vi.resetAllMocks(); });

describe("ConnectedDevices", () => {
  it("shows a loading status, then one row per device", async () => {
    renderSection();
    expect(screen.getByText("Loading devices…").getAttribute("role")).toBe("status");
    expect(await screen.findByText("Pixel")).toBeTruthy();
    expect(screen.getAllByText(/Last used: Never/)).toHaveLength(2);
  });

  it("shows the empty message", async () => {
    listDevices.mockResolvedValue([]);
    renderSection();
    expect(await screen.findByText("No phone connected. Pair one from the mobile app.")).toBeTruthy();
  });

  it("shows the error and loads again on Retry", async () => {
    listDevices.mockRejectedValueOnce(new ApiError(500, "boom"));
    renderSection();
    expect((await screen.findByRole("alert")).textContent).toContain("boom");
    await userEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(await screen.findByText("Pixel")).toBeTruthy();
  });

  it("cancels the confirmation with Escape and returns focus to the opener", async () => {
    renderSection();
    const opener = await screen.findByRole("button", { name: /Revoke.*Pixel/ });
    await userEvent.click(opener);
    expect(screen.getByRole("dialog").textContent).toContain('Revoke "Pixel"?');
    expect(document.activeElement).toBe(screen.getByRole("button", { name: "Cancel" }));
    await userEvent.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(document.activeElement).toBe(opener);
    expect(revokeDevice).not.toHaveBeenCalled();
  });

  it("traps Tab inside the dialog", async () => {
    renderSection();
    await userEvent.click(await screen.findByRole("button", { name: /Revoke.*Pixel/ }));
    await userEvent.tab();
    expect(document.activeElement).toBe(screen.getByRole("button", { name: "Revoke" }));
    await userEvent.tab();
    expect(document.activeElement).toBe(screen.getByRole("button", { name: "Cancel" }));
  });

  it("removes the row after a revocation, announces it and focuses the next row's Revoke button", async () => {
    revokeDevice.mockResolvedValue(undefined);
    renderSection();
    await userEvent.click(await screen.findByRole("button", { name: /Revoke.*Pixel/ }));
    await userEvent.click(screen.getByRole("button", { name: "Revoke" }));
    await waitFor(() => expect(screen.queryByText("Pixel")).toBeNull());
    expect(revokeDevice).toHaveBeenCalledWith(1);
    expect(screen.getByText("Device revoked")).toBeTruthy();
    expect(document.activeElement).toBe(screen.getByRole("button", { name: /Revoke.*iPhone/ }));
  });

  it("focuses the section title when the revoked row was the last one", async () => {
    revokeDevice.mockResolvedValue(undefined);
    renderSection();
    await userEvent.click(await screen.findByRole("button", { name: /Revoke.*iPhone/ }));
    await userEvent.click(screen.getByRole("button", { name: "Revoke" }));
    await waitFor(() => expect(screen.queryByText("iPhone")).toBeNull());
    expect(document.activeElement).toBe(screen.getByRole("heading", { name: "Connected devices" }));
  });

  it("keeps the row and shows an error when the revocation fails", async () => {
    revokeDevice.mockRejectedValue(new ApiError(500, "nope"));
    renderSection();
    await userEvent.click(await screen.findByRole("button", { name: /Revoke.*Pixel/ }));
    await userEvent.click(screen.getByRole("button", { name: "Revoke" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(screen.getByText("Pixel")).toBeTruthy();
    expect(screen.getByRole("alert").textContent).toContain("nope");
    expect(document.activeElement).toBe(screen.getByRole("button", { name: /Revoke.*Pixel/ }));
  });
});
