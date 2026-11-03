import { render, screen } from "@testing-library/react-native";
import { COLORS } from "../src/theme";
import ConversationScreen from "../app/conversation/[id]";
import ConversationListScreen from "../app/index";
import LoginScreen from "../app/login";
import { SessionProvider } from "../src/session";

jest.mock("expo-secure-store", () => ({
  getItemAsync: jest.fn().mockResolvedValue(null),
  setItemAsync: jest.fn(),
  deleteItemAsync: jest.fn(),
}));
jest.mock("expo-localization", () => ({ getLocales: () => [{ languageCode: "fr" }] }));

describe("placeholder screens", () => {
  it("renders the conversation list in French", async () => {
    await render(<ConversationListScreen />);
    expect(screen.getByRole("header", { name: "Messages" })).toBeTruthy();
    expect(screen.getByText("Aucune conversation. Les messages de l'équipe apparaîtront ici.")).toBeTruthy();
  });

  it("renders the login screen", async () => {
    await render(<SessionProvider><LoginScreen /></SessionProvider>);
    expect(screen.getByRole("header", { name: "Palabre" })).toBeTruthy();
  });

  it("renders the conversation screen", async () => {
    await render(<ConversationScreen />);
    expect(screen.getByText("Aucun message. Écris le premier.")).toBeTruthy();
  });
});

describe("theme tokens", () => {
  it("has the same keys in light and dark", () => {
    expect(Object.keys(COLORS.dark)).toEqual(Object.keys(COLORS.light));
  });

  it("uses the spec values", () => {
    expect(COLORS.light.sentBubble).toBe("#0066E0");
    expect(COLORS.dark.receivedBubble).toBe("#26262A");
  });
});
