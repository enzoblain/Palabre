import { render, screen, waitFor } from "@testing-library/react-native";
import { CreditsBanner } from "../src/components/CreditsBanner";
import { AppShellProvider } from "../src/hooks/useAppShell";
import { api } from "../src/api";

jest.mock("expo-router", () => ({ useRouter: () => ({ navigate: jest.fn() }) }));
jest.mock("expo-localization", () => ({ getLocales: () => [{ languageCode: "en" }] }));
jest.mock("expo-secure-store", () => ({}));
jest.mock("../src/api", () => ({ api: { getSettings: jest.fn(), orchestratorStatus: jest.fn() } }));

const mocked = api as unknown as Record<string, jest.Mock>;
const FUTURE = "2999-01-01T08:30:00Z";

const renderBanner = () =>
  render(
    <AppShellProvider>
      <CreditsBanner />
    </AppShellProvider>,
  );

beforeEach(() => {
  jest.clearAllMocks();
  mocked.getSettings.mockResolvedValue({ boss_name: "Enzo", claude_accounts: 1 });
});

describe("credits banner", () => {
  it("renders nothing while every account has credits", async () => {
    mocked.orchestratorStatus.mockResolvedValue({ exhausted_accounts: [] });
    await renderBanner();
    await waitFor(() => expect(mocked.orchestratorStatus).toHaveBeenCalled());
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("announces the pause and when the credits come back", async () => {
    mocked.orchestratorStatus.mockResolvedValue({ exhausted_accounts: [{ account: 1, resets_at: FUTURE, estimated: false }] });
    await renderBanner();
    expect(await screen.findByText("Claude credits exhausted, the team is paused.")).toBeTruthy();
    expect(screen.getByText(/^back at /)).toBeTruthy();
  });

  it("says 'around' for an estimated time", async () => {
    mocked.orchestratorStatus.mockResolvedValue({ exhausted_accounts: [{ account: 1, resets_at: FUTURE, estimated: true }] });
    await renderBanner();
    expect(await screen.findByText(/^back around /)).toBeTruthy();
  });

  it("names each account when there are several", async () => {
    mocked.getSettings.mockResolvedValue({ boss_name: "Enzo", claude_accounts: 2 });
    mocked.orchestratorStatus.mockResolvedValue({
      exhausted_accounts: [
        { account: 1, resets_at: FUTURE, estimated: false },
        { account: 2, resets_at: FUTURE, estimated: true },
      ],
    });
    await renderBanner();
    expect(await screen.findByText(/^Account 1: back at /)).toBeTruthy();
    await waitFor(() => expect(screen.getByText(/^Account 2: back around /)).toBeTruthy());
  });
});
