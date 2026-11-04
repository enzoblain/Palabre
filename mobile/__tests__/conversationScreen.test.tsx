import { act, fireEvent, render, screen } from "@testing-library/react-native";
import * as Clipboard from "expo-clipboard";
import { Linking, StyleSheet } from "react-native";
import ConversationScreen from "../app/conversation/[id]";
import { api, ApiError, type Message } from "../src/api";
import { COPIED_FEEDBACK_MS } from "../src/components/MessageActions";
import { MAX_FONT_SCALE } from "../src/theme";
import { COLORS } from "../src/theme/tokens";

const WCAG_AA_CONTRAST = 4.5;
const WCAG_NON_TEXT_CONTRAST = 3;

const luminance = (hex: string): number => {
  const [red, green, blue] = [1, 3, 5].map((start) => {
    const channel = parseInt(hex.slice(start, start + 2), 16) / 255;
    return channel <= 0.03928 ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * red + 0.7152 * green + 0.0722 * blue;
};
const contrast = (first: string, second: string): number => {
  const [light, dark] = [luminance(first), luminance(second)].sort((a, b) => b - a);
  return (light + 0.05) / (dark + 0.05);
};

const mockBack = jest.fn();
const mockPush = jest.fn();
jest.mock("expo-router", () => ({ useRouter: () => ({ back: mockBack, push: mockPush }), useLocalSearchParams: () => ({ id: "1" }) }));
jest.mock("expo-localization", () => ({ getLocales: () => [{ languageCode: "fr" }] }));
jest.mock("expo-secure-store", () => ({}));
jest.mock("expo-clipboard", () => ({ setStringAsync: jest.fn() }));
jest.mock("../src/api", () => ({
  ...jest.requireActual("../src/api"),
  api: {
    getProject: jest.fn(),
    listProjects: jest.fn(),
    listConversations: jest.fn(),
    listMessages: jest.fn(),
    postMessage: jest.fn(),
    markDirectionRead: jest.fn(),
    getSettings: jest.fn(),
    liftRateLimit: jest.fn(),
  },
}));

const mocked = api as unknown as Record<string, jest.Mock>;

const message = (id: number, content: string, employeeId: number | null): Message => ({
  id,
  conversation_id: 9,
  employee_id: employeeId,
  author_name: employeeId === null ? "Enzo" : "Élise",
  content,
  created_at: "2026-01-01T10:00:00Z",
  is_system: false,
  request_kind: null,
  request_status: null,
  request_comment: null,
  request_answered_at: null,
  request_merged_into: null,
  request_decision_id: null,
});

beforeEach(() => {
  jest.clearAllMocks();
  mocked.getProject.mockResolvedValue({
    name: "Alpha",
    employees: [{ id: 5, name: "Élise", title: "Lead / CTO", roles: ["lead"] }],
    rooms: [
      {
        id: 4,
        kind: "direction",
        objective: "Ship the app",
        summary: "",
        members: [{ id: 5, name: "Élise", title: "Lead / CTO" }],
      },
    ],
  });
  mocked.listProjects.mockResolvedValue([{ id: 1, lead_writing: false }]);
  mocked.listConversations.mockResolvedValue([{ id: 9 }]);
  mocked.markDirectionRead.mockResolvedValue({});
  mocked.getSettings.mockResolvedValue({ boss_name: "Enzo" });
  (Clipboard.setStringAsync as jest.Mock).mockResolvedValue(true);
});

describe("conversation screen", () => {
  it("shows the typing indicator while the lead is writing", async () => {
    mocked.listMessages.mockResolvedValue([message(1, "Salut", 5)]);
    mocked.listProjects.mockResolvedValue([{ id: 1, lead_writing: true }]);
    await render(<ConversationScreen />);
    expect(await screen.findByLabelText("Élise est en train d’écrire…")).toBeTruthy();
  });

  it("hides the typing indicator when the lead is not writing", async () => {
    mocked.listMessages.mockResolvedValue([message(1, "Salut", 5)]);
    await render(<ConversationScreen />);
    await screen.findByText("Salut");
    expect(screen.queryByLabelText("Élise est en train d’écrire…")).toBeNull();
  });

  it("opens the conversation info with the objective and the members", async () => {
    mocked.listMessages.mockResolvedValue([]);
    await render(<ConversationScreen />);
    fireEvent.press(await screen.findByText("Infos"));
    expect(await screen.findByText("Ship the app")).toBeTruthy();
    expect(screen.getByText("Élise · Lead / CTO")).toBeTruthy();
    expect(screen.getByText("1 membre")).toBeTruthy();
  });

  it("re-reads the room each time the info sheet opens", async () => {
    mocked.listMessages.mockResolvedValue([]);
    await render(<ConversationScreen />);
    const loaded = mocked.getProject.mock.calls.length;
    const fresh = await mocked.getProject();
    mocked.getProject.mockResolvedValue({ ...fresh, rooms: [{ ...fresh.rooms[0], objective: "New objective" }] });
    fireEvent.press(await screen.findByText("Infos"));
    expect(await screen.findByText("New objective")).toBeTruthy();
    expect(mocked.getProject.mock.calls.length).toBeGreaterThan(loaded);
  });

  it("keeps the known info when the refresh on open fails", async () => {
    mocked.listMessages.mockResolvedValue([]);
    await render(<ConversationScreen />);
    const infos = await screen.findByText("Infos");
    mocked.getProject.mockRejectedValue(new Error("down"));
    fireEvent.press(infos);
    expect(await screen.findByText("Ship the app")).toBeTruthy();
  });

  it("opens the project page from the info sheet", async () => {
    mocked.listMessages.mockResolvedValue([]);
    await render(<ConversationScreen />);
    fireEvent.press(await screen.findByText("Infos"));
    fireEvent.press(await screen.findByText("Page du projet"));
    expect(mockPush).toHaveBeenCalledWith({ pathname: "/project/[id]", params: { id: "1" } });
  });

  it("shows skeleton bubbles while loading", async () => {
    mocked.listMessages.mockReturnValue(new Promise(() => {}));
    await render(<ConversationScreen />);
    expect(screen.getByLabelText("Chargement des messages")).toBeTruthy();
  });

  it("shows the empty message", async () => {
    mocked.listMessages.mockResolvedValue([]);
    await render(<ConversationScreen />);
    expect(await screen.findByText("Parlez de Alpha à votre équipe")).toBeTruthy();
  });

  it("shows the history, the author of the team messages and the project name", async () => {
    mocked.listMessages.mockResolvedValue([message(1, "Salut", 5), message(2, "Bonjour", null)]);
    await render(<ConversationScreen />);
    expect(await screen.findByText("Salut")).toBeTruthy();
    expect(screen.getByText("Bonjour")).toBeTruthy();
    expect(screen.getAllByText("Élise · Lead / CTO")).toHaveLength(1);
    expect(screen.getByRole("header", { name: "Alpha" })).toBeTruthy();
    expect(mocked.markDirectionRead).toHaveBeenCalledWith(1);
  });

  it("goes back to the list", async () => {
    mocked.listMessages.mockResolvedValue([]);
    await render(<ConversationScreen />);
    await fireEvent.press(screen.getByRole("button", { name: "Messages" }));
    expect(mockBack).toHaveBeenCalled();
  });

  it("shows an error banner and retries", async () => {
    mocked.listMessages.mockRejectedValueOnce(new Error("down"));
    await render(<ConversationScreen />);
    expect(await screen.findByText("Messages indisponibles")).toBeTruthy();
    mocked.listMessages.mockResolvedValue([message(1, "Salut", 5)]);
    await fireEvent.press(screen.getByRole("button", { name: "Réessayer" }));
    expect(await screen.findByText("Salut")).toBeTruthy();
  });

  it("disables send when empty, sends at once, and offers a retry after a failure", async () => {
    mocked.listMessages.mockResolvedValue([]);
    mocked.postMessage.mockRejectedValueOnce(new Error("down"));
    await render(<ConversationScreen />);
    await screen.findByText("Parlez de Alpha à votre équipe");
    expect(screen.getByRole("button", { name: "Envoyer" })).toBeDisabled();

    await fireEvent.changeText(screen.getByLabelText("Message"), "  Go  ");
    await fireEvent.press(screen.getByRole("button", { name: "Envoyer" }));
    expect(mocked.postMessage).toHaveBeenCalledWith(9, "Go");
    const failure = await screen.findByRole("button", { name: /Go, .*Non envoyé\. Touchez pour réessayer\./ });
    expect(screen.getByLabelText("Message").props.value).toBe("");

    mocked.postMessage.mockResolvedValue(message(3, "Go", null));
    await fireEvent.press(failure);
    await screen.findByLabelText(/^Moi, Go, (?!.*Non envoyé)/);
    expect(screen.queryByText(/Non envoyé/)).toBeNull();
  });

  it("paints the sending bubble with the pale background and no opacity", async () => {
    mocked.listMessages.mockResolvedValue([]);
    mocked.postMessage.mockReturnValue(new Promise(() => {}));
    await render(<ConversationScreen />);
    await screen.findByText("Parlez de Alpha à votre équipe");
    await fireEvent.changeText(screen.getByLabelText("Message"), "Go");
    await fireEvent.press(screen.getByRole("button", { name: "Envoyer" }));
    const text = await screen.findByText("Go");
    const bubble = screen.getByLabelText(/^Moi, Go/);
    const bubbleStyle = StyleSheet.flatten(bubble.props.style);
    expect(bubbleStyle.backgroundColor).toBe(COLORS.light.sendingBubble);
    expect(bubbleStyle.opacity).toBeUndefined();
    expect(StyleSheet.flatten(text.props.style).opacity).toBeUndefined();
  });

  it("caps the send glyph font scale like the other texts", async () => {
    mocked.listMessages.mockResolvedValue([]);
    await render(<ConversationScreen />);
    await screen.findByText("Parlez de Alpha à votre équipe");
    expect(screen.getByText("↑").props.maxFontSizeMultiplier).toBe(MAX_FONT_SCALE);
  });

  it("keeps the sending bubble text readable and the failure line out of VoiceOver", async () => {
    for (const scheme of ["light", "dark"] as const) {
      expect(contrast(COLORS[scheme].sendingBubble, COLORS[scheme].sentBubbleText)).toBeGreaterThanOrEqual(WCAG_AA_CONTRAST);
    }
    mocked.listMessages.mockResolvedValue([]);
    mocked.postMessage.mockRejectedValueOnce(new Error("down"));
    await render(<ConversationScreen />);
    await screen.findByText("Parlez de Alpha à votre équipe");
    await fireEvent.changeText(screen.getByLabelText("Message"), "Go");
    await fireEvent.press(screen.getByRole("button", { name: "Envoyer" }));
    await screen.findByRole("button", { name: /Non envoyé/ });
    expect(screen.getByText(/Non envoyé/, { includeHiddenElements: true }).props.accessibilityElementsHidden).toBe(true);
    expect(screen.queryByText(/Non envoyé/)).toBeNull();
  });
});

describe("conversation message content and actions", () => {
  it("renders Markdown in the bubbles and opens only allowed links", async () => {
    const openURL = jest.spyOn(Linking, "openURL").mockResolvedValue();
    mocked.listMessages.mockResolvedValue([
      message(1, "Voir [la doc](https://example.com) ou [pirate](javascript:alert(1))\n- un\n- deux", 5),
    ]);
    await render(<ConversationScreen />);
    await fireEvent.press(await screen.findByText("la doc"));
    expect(openURL).toHaveBeenCalledWith("https://example.com");
    await fireEvent.press(screen.getByText("pirate"));
    expect(openURL).toHaveBeenCalledTimes(1);
    expect(screen.getByText(/• un/)).toBeTruthy();
  });

  it("keeps mentions bold and marks a bubble that mentions the boss without color alone", async () => {
    mocked.listMessages.mockResolvedValue([message(1, "Salut @Enzo, ça va ?", 5), message(2, "Salut @Bob", 5)]);
    await render(<ConversationScreen />);
    const mention = await screen.findByText("@Enzo");
    expect(StyleSheet.flatten(mention.props.style)).toMatchObject({ fontWeight: "700", textDecorationLine: "underline" });
    expect(StyleSheet.flatten(screen.getByText("@Bob").props.style).textDecorationLine).toBeUndefined();
    const tinted = screen.getByLabelText(/^Vous mentionne, Élise, Salut @Enzo/);
    expect(StyleSheet.flatten(tinted.props.style)).toMatchObject({ backgroundColor: COLORS.light.mentionedBubble, borderWidth: 2 });
    expect(screen.getByLabelText(/^Élise, Salut @Bob/)).toBeTruthy();
  });

  it("keeps the mention cue readable in both themes", () => {
    for (const scheme of ["light", "dark"] as const) {
      const { mentionedBubble, receivedBubble, link, text, background } = COLORS[scheme];
      expect(contrast(link, mentionedBubble)).toBeGreaterThanOrEqual(WCAG_NON_TEXT_CONTRAST);
      expect(contrast(link, background)).toBeGreaterThanOrEqual(WCAG_NON_TEXT_CONTRAST);
      expect(contrast(text, mentionedBubble)).toBeGreaterThanOrEqual(WCAG_AA_CONTRAST);
      expect(contrast(link, receivedBubble)).toBeGreaterThanOrEqual(WCAG_NON_TEXT_CONTRAST);
    }
  });

  it("shows the author's job title and labels platform lines", async () => {
    mocked.listMessages.mockResolvedValue([message(1, "Salut", 5), { ...message(2, "Déploiement fini", null), is_system: true }]);
    await render(<ConversationScreen />);
    expect(await screen.findByText("Élise · Lead / CTO")).toBeTruthy();
    expect(screen.getByText("Plateforme")).toBeTruthy();
    expect(screen.getByText("Déploiement fini")).toBeTruthy();
  });

  it("copies a message from the long press sheet and shows when it was sent", async () => {
    mocked.listMessages.mockResolvedValue([message(1, "Salut", 5)]);
    await render(<ConversationScreen />);
    await screen.findByText("Salut");
    await fireEvent(screen.getByLabelText(/^Élise, Salut/), "longPress");
    await fireEvent.press(await screen.findByRole("button", { name: "Copier" }));
    expect(Clipboard.setStringAsync).toHaveBeenCalledWith("Salut");
    expect(await screen.findByRole("button", { name: "Copié" })).toBeTruthy();
    await fireEvent.press(screen.getAllByRole("button", { name: "Infos" }).at(-1)!);
    expect(await screen.findByText(/^Envoyé le .*2026/)).toBeTruthy();
  });

  it("reports a failed copy", async () => {
    (Clipboard.setStringAsync as jest.Mock).mockRejectedValue(new Error("denied"));
    mocked.listMessages.mockResolvedValue([message(1, "Salut", 5)]);
    await render(<ConversationScreen />);
    await screen.findByText("Salut");
    await fireEvent(screen.getByLabelText(/^Élise, Salut/), "longPress");
    await fireEvent.press(await screen.findByRole("button", { name: "Copier" }));
    expect(await screen.findByRole("button", { name: "Copie impossible" })).toBeTruthy();
  });

  it("closes the sheet after a successful copy, once the feedback delay has passed", async () => {
    jest.useFakeTimers();
    try {
      mocked.listMessages.mockResolvedValue([message(1, "Salut", 5)]);
      await render(<ConversationScreen />);
      await screen.findByText("Salut");
      await fireEvent(screen.getByLabelText(/^Élise, Salut/), "longPress");
      await fireEvent.press(await screen.findByRole("button", { name: "Copier" }));
      expect(await screen.findByRole("button", { name: "Copié" })).toBeTruthy();
      await act(async () => { jest.advanceTimersByTime(COPIED_FEEDBACK_MS); });
      expect(screen.queryByRole("button", { name: "Copié" })).toBeNull();
    } finally {
      jest.useRealTimers();
    }
  });

  it("keeps the sheet open after a failed copy", async () => {
    jest.useFakeTimers();
    try {
      (Clipboard.setStringAsync as jest.Mock).mockRejectedValue(new Error("denied"));
      mocked.listMessages.mockResolvedValue([message(1, "Salut", 5)]);
      await render(<ConversationScreen />);
      await screen.findByText("Salut");
      await fireEvent(screen.getByLabelText(/^Élise, Salut/), "longPress");
      await fireEvent.press(await screen.findByRole("button", { name: "Copier" }));
      expect(await screen.findByRole("button", { name: "Copie impossible" })).toBeTruthy();
      await act(async () => { jest.advanceTimersByTime(COPIED_FEEDBACK_MS * 2); });
      expect(screen.getByRole("button", { name: "Copie impossible" })).toBeTruthy();
    } finally {
      jest.useRealTimers();
    }
  });

  it("offers Copy as a screen reader action without the gesture", async () => {
    mocked.listMessages.mockResolvedValue([message(1, "Salut", 5)]);
    await render(<ConversationScreen />);
    await screen.findByText("Salut");
    const bubble = screen.getByLabelText(/^Élise, Salut/);
    expect(bubble.props.accessibilityActions).toEqual([
      { name: "copy", label: "Copier" },
      { name: "info", label: "Infos" },
    ]);
    await fireEvent(bubble, "accessibilityAction", { nativeEvent: { actionName: "copy" } });
    expect(Clipboard.setStringAsync).toHaveBeenCalledWith("Salut");
  });

  it("names the project and the boss in the placeholder, and shows the intro in an empty conversation", async () => {
    mocked.listMessages.mockResolvedValue([]);
    await render(<ConversationScreen />);
    expect(await screen.findByText("Parlez de Alpha à votre équipe")).toBeTruthy();
    expect(screen.getByText(/Élise \(Lead \/ CTO\) le lira/)).toBeTruthy();
    expect(screen.getByPlaceholderText("Décrivez le projet à votre équipe…")).toBeTruthy();
  });

  it("uses the boss name in the placeholder once there are messages", async () => {
    mocked.listMessages.mockResolvedValue([message(1, "Salut", 5)]);
    await render(<ConversationScreen />);
    await screen.findByText("Salut");
    expect(await screen.findByPlaceholderText("Message à Alpha en tant que Enzo")).toBeTruthy();
  });

  it("inserts a mention in the composer when a member is tapped in the info sheet", async () => {
    mocked.listMessages.mockResolvedValue([message(1, "Salut", 5)]);
    await render(<ConversationScreen />);
    await fireEvent.press(await screen.findByText("Infos"));
    await fireEvent.press(await screen.findByRole("button", { name: "Élise, Lead / CTO" }));
    expect(screen.getByLabelText("Message").props.value).toBe("@Élise ");
  });

  it("appends a mention after typed text with a separating space, and inserts the same member twice", async () => {
    mocked.listMessages.mockResolvedValue([message(1, "Salut", 5)]);
    await render(<ConversationScreen />);
    await screen.findByText("Salut");
    await fireEvent.changeText(screen.getByLabelText("Message"), "Salut");
    await fireEvent.press(await screen.findByText("Infos"));
    await fireEvent.press(await screen.findByRole("button", { name: "Élise, Lead / CTO" }));
    expect(screen.getByLabelText("Message").props.value).toBe("Salut @Élise ");
    await fireEvent.press(await screen.findByText("Infos"));
    await fireEvent.press(await screen.findByRole("button", { name: "Élise, Lead / CTO" }));
    expect(screen.getByLabelText("Message").props.value).toBe("Salut @Élise @Élise ");
  });

  it("lifts the loop limit from the info sheet and reports the result", async () => {
    mocked.listMessages.mockResolvedValue([]);
    mocked.liftRateLimit.mockResolvedValue(undefined);
    await render(<ConversationScreen />);
    await fireEvent.press(await screen.findByText("Infos"));
    await fireEvent.press(await screen.findByRole("button", { name: "Lever la limite de boucle" }));
    expect(mocked.liftRateLimit).toHaveBeenCalledWith(9);
    expect(await screen.findByText(/Limite de boucle levée/)).toBeTruthy();
  });

  it("shows the error when lifting the limit fails", async () => {
    mocked.listMessages.mockResolvedValue([]);
    mocked.liftRateLimit.mockRejectedValue(new ApiError(500, "Boom"));
    await render(<ConversationScreen />);
    await fireEvent.press(await screen.findByText("Infos"));
    await fireEvent.press(await screen.findByRole("button", { name: "Lever la limite de boucle" }));
    expect(await screen.findByText("Boom")).toBeTruthy();
  });
});

describe("conversation scrolling", () => {
  const metrics = (offsetY: number) => ({
    nativeEvent: {
      contentOffset: { x: 0, y: offsetY },
      contentSize: { width: 300, height: 2000 },
      layoutMeasurement: { width: 300, height: 600 },
    },
  });

  it("stays at the bottom on layout events, then flags new messages once the user scrolled up", async () => {
    mocked.listMessages.mockResolvedValue([message(1, "Salut", 5)]);
    await render(<ConversationScreen />);
    await screen.findByText("Salut");
    const list = screen.getByTestId("message-list");
    fireEvent.scroll(list, metrics(0));
    fireEvent(list, "contentSizeChange", 300, 2000);
    expect(screen.queryByRole("button", { name: /nouveau/i })).toBeNull();

    fireEvent(list, "scrollBeginDrag", metrics(0));
    fireEvent.scroll(list, metrics(0));
    fireEvent(list, "momentumScrollEnd", metrics(0));
    fireEvent(list, "contentSizeChange", 300, 2100);
    expect(await screen.findByRole("button", { name: /nouveau/i })).toBeTruthy();
  });
});
