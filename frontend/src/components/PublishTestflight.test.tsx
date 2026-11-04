// @vitest-environment jsdom
import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, api } from "../api";
import { I18nProvider } from "../i18n";
import { PublishTestflight } from "./ProjectInfo";

vi.mock("../api", async (importOriginal) => {
  const original = await importOriginal<typeof import("../api")>();
  return { ...original, api: { publishTestflight: vi.fn() } };
});

const publishTestflight = vi.mocked(api.publishTestflight);
const renderSection = () => render(<I18nProvider><PublishTestflight projectId={7} /></I18nProvider>);

afterEach(() => { cleanup(); vi.resetAllMocks(); });

describe("PublishTestflight", () => {
  it("asks for a confirmation and sends nothing when cancelled", async () => {
    renderSection();
    await userEvent.click(screen.getByRole("button", { name: "Publish to TestFlight" }));
    expect(screen.getByRole("dialog")).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(publishTestflight).not.toHaveBeenCalled();
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("shows the version returned by the API once confirmed", async () => {
    publishTestflight.mockResolvedValue({ version: "1.2.3" });
    renderSection();
    await userEvent.click(screen.getByRole("button", { name: "Publish to TestFlight" }));
    await userEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Publish to TestFlight" }));
    expect(await screen.findByText("Version 1.2.3 sent to TestFlight")).toBeTruthy();
    expect(publishTestflight).toHaveBeenCalledWith(7);
  });

  it("shows the translated message of a refused publication", async () => {
    publishTestflight.mockRejectedValue(new ApiError(409, "Build is not green", "x", "apple_publish_build_not_green"));
    renderSection();
    await userEvent.click(screen.getByRole("button", { name: "Publish to TestFlight" }));
    await userEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Publish to TestFlight" }));
    await waitFor(() => expect(screen.getByRole("status").textContent).toBe("Build is not green"));
  });
});
