import { render, screen } from "@testing-library/react-native";
import TabsLayout from "../app/(tabs)/_layout";

type ScreenProps = { name: string; options: { title: string; tabBarIcon: (p: { color: string }) => React.ReactNode } };

const mockScreens: string[] = [];
jest.mock("expo-router", () => {
  const { Text } = jest.requireActual("react-native");
  function Screen({ name, options }: ScreenProps) {
    mockScreens.push(name);
    return <Text accessibilityRole="tab">{options.title}{options.tabBarIcon({ color: "#000" })}</Text>;
  }
  function Tabs({ children }: { children: React.ReactNode }) {
    return <>{children}</>;
  }
  Tabs.Screen = Screen;
  return { Tabs };
});
jest.mock("expo-localization", () => ({ getLocales: () => [{ languageCode: "fr" }] }));

describe("bottom tab bar", () => {
  it("lists the web sections in order", async () => {
    await render(<TabsLayout />);
    expect(mockScreens).toEqual(["index", "new", "settings"]);
    expect(screen.getAllByRole("tab").map((tab) => tab.props.children[0])).toEqual(["Projets", "Nouveau projet", "Réglages"]);
  });
});
