// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, type AppleHost, api } from "../api";
import { I18nProvider } from "../i18n";
import { ProjectTypeChoice } from "./ProjectTypeChoice";

vi.mock("../api", async (importOriginal) => {
  const original = await importOriginal<typeof import("../api")>();
  return { ...original, api: { listAppleHosts: vi.fn() } };
});

const listAppleHosts = vi.mocked(api.listAppleHosts);
const host = (connected: boolean): AppleHost => ({
  id: 1, name: "mac", created_at: "2026-01-01T00:00:00Z", expires_at: "2027-01-01T00:00:00Z",
  last_seen_at: null, revoked_at: null, connected,
});

function renderChoice(onChange = vi.fn()) {
  render(<I18nProvider><ProjectTypeChoice platform="generic" onChange={onChange} /></I18nProvider>);
  return onChange;
}
const appleRadio = () => screen.getByRole("radio", { name: /Apple – Swift/ });

afterEach(() => { cleanup(); vi.resetAllMocks(); });

describe("ProjectTypeChoice", () => {
  it("offers Apple when a Mac is connected", async () => {
    listAppleHosts.mockResolvedValue([host(true)]);
    const onChange = renderChoice();
    await screen.findByRole("radio", { name: /Standard/ });
    await vi.waitFor(() => expect(appleRadio().getAttribute("aria-disabled")).toBe("false"));
    await userEvent.click(appleRadio());
    expect(onChange).toHaveBeenCalledWith("apple");
  });

  it("explains a missing Mac, links to the settings and ignores the selection", async () => {
    listAppleHosts.mockResolvedValue([host(false)]);
    const onChange = renderChoice();
    expect(await screen.findByText("No Mac connected.")).toBeTruthy();
    expect(appleRadio().getAttribute("aria-disabled")).toBe("true");
    expect(appleRadio().getAttribute("aria-describedby")).toBe("apple-help");
    expect(screen.getByRole("link", { name: "Connect a Mac" }).getAttribute("href")).toBe("#/settings");
    await userEvent.click(appleRadio());
    expect(onChange).not.toHaveBeenCalled();
  });

  it("says Apple mode is off, without a link", async () => {
    listAppleHosts.mockRejectedValue(new ApiError(404, "Not found"));
    renderChoice();
    expect(await screen.findByText("Apple mode is off on this server")).toBeTruthy();
    expect(screen.queryByRole("link")).toBeNull();
  });

  it("shows a loading state, then a retry when the check fails", async () => {
    listAppleHosts.mockRejectedValueOnce(new ApiError(500, "boom"));
    renderChoice();
    expect(screen.getByText("Checking the Mac…")).toBeTruthy();
    expect(appleRadio().getAttribute("aria-disabled")).toBe("true");
    listAppleHosts.mockResolvedValue([host(true)]);
    await userEvent.click(await screen.findByRole("button", { name: "Retry" }));
    await vi.waitFor(() => expect(appleRadio().getAttribute("aria-disabled")).toBe("false"));
  });
});
