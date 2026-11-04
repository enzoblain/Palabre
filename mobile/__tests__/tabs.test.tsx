import { render, screen, waitFor } from "@testing-library/react-native";
import TabsLayout from "../app/(tabs)/_layout";

type ScreenProps = { name: string; options: { title: string; tabBarIcon: (p: { color: string; size: number; focused: boolean }) => React.ReactNode } };

const mockScreens: string[] = [];
const mockNavigate = jest.fn();
const mockGetSettings = jest.fn();
const mockOrchestratorStatus = jest.fn();
jest.mock("../src/api", () => ({
  api: { getSettings: () => mockGetSettings(), orchestratorStatus: () => mockOrchestratorStatus() },
}));
jest.mock("expo-router", () => {
  const { Text, View } = jest.requireActual("react-native");
  function Screen({ name, options }: ScreenProps) {
    mockScreens.push(name);
    return <View accessibilityRole="tab">
        <Text>{options.title}</Text>
        {options.tabBarIcon({ color: "#000", size: 24, focused: name === "index" })}
      </View>;
  }
  function Tabs({ children }: { children: React.ReactNode }) {
    return <>{children}</>;
  }
  Tabs.Screen = Screen;
  return { Tabs, useRouter: () => ({ navigate: mockNavigate }) };
});
jest.mock("@expo/vector-icons", () => {
  const { Text } = jest.requireActual("react-native");
  return { Ionicons: ({ name }: { name: string }) => <Text>{`icon:${name}`}</Text> };
});
jest.mock("expo-localization", () => ({ getLocales: () => [{ languageCode: "fr" }] }));

beforeEach(() => {
  jest.clearAllMocks();
  mockGetSettings.mockResolvedValue({ boss_name: "Enzo", claude_accounts: 1 });
  mockOrchestratorStatus.mockResolvedValue({ exhausted_accounts: [] });
});

describe("bottom tab bar", () => {
  it("lists the web sections in order", async () => {
    await render(<TabsLayout />);
    expect(mockScreens).toEqual(["index", "new", "settings"]);
    for (const label of ["Projets", "Nouveau projet", "Réglages"]) expect(screen.getByText(label)).toBeTruthy();
  });

  it("uses a filled icon for the active tab and an outline one for the others", async () => {
    await render(<TabsLayout />);
    for (const name of ["icon:mail", "icon:add-circle-outline", "icon:settings-outline"]) expect(screen.getByText(name)).toBeTruthy();
  });

  it("opens Settings on the first run, when the boss has no name yet", async () => {
    mockGetSettings.mockResolvedValue({ boss_name: "", claude_accounts: 1 });
    await render(<TabsLayout />);
    await waitFor(() => expect(mockNavigate).toHaveBeenCalledWith("/settings"));
  });

  it("stays on the projects when the boss is named", async () => {
    await render(<TabsLayout />);
    await waitFor(() => expect(mockGetSettings).toHaveBeenCalled());
    expect(mockNavigate).not.toHaveBeenCalled();
  });
});
