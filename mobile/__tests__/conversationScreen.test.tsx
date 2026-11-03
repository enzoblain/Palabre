import { fireEvent, render, screen } from "@testing-library/react-native";
import ConversationScreen from "../app/conversation/[id]";
import { api, type Message } from "../src/api";

const mockBack = jest.fn();
jest.mock("expo-router", () => ({ useRouter: () => ({ back: mockBack }), useLocalSearchParams: () => ({ id: "1" }) }));
jest.mock("expo-localization", () => ({ getLocales: () => [{ languageCode: "fr" }] }));
jest.mock("expo-secure-store", () => ({}));
jest.mock("../src/api", () => ({
  ...jest.requireActual("../src/api"),
  api: {
    getProject: jest.fn(),
    listConversations: jest.fn(),
    listMessages: jest.fn(),
    postMessage: jest.fn(),
    markDirectionRead: jest.fn(),
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
  mocked.getProject.mockResolvedValue({ name: "Alpha", rooms: [{ id: 4, kind: "direction" }] });
  mocked.listConversations.mockResolvedValue([{ id: 9 }]);
  mocked.markDirectionRead.mockResolvedValue({});
});

describe("conversation screen", () => {
  it("shows skeleton bubbles while loading", async () => {
    mocked.listMessages.mockReturnValue(new Promise(() => {}));
    await render(<ConversationScreen />);
    expect(screen.getByLabelText("Chargement des messages")).toBeTruthy();
  });

  it("shows the empty message", async () => {
    mocked.listMessages.mockResolvedValue([]);
    await render(<ConversationScreen />);
    expect(await screen.findByText("Aucun message. Écris le premier.")).toBeTruthy();
  });

  it("shows the history, the author of the team messages and the project name", async () => {
    mocked.listMessages.mockResolvedValue([message(1, "Salut", 5), message(2, "Bonjour", null)]);
    await render(<ConversationScreen />);
    expect(await screen.findByText("Salut")).toBeTruthy();
    expect(screen.getByText("Bonjour")).toBeTruthy();
    expect(screen.getAllByText("Élise")).toHaveLength(1);
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
    await screen.findByText("Aucun message. Écris le premier.");
    expect(screen.getByRole("button", { name: "Envoyer" })).toBeDisabled();

    await fireEvent.changeText(screen.getByLabelText("Message"), "  Go  ");
    await fireEvent.press(screen.getByRole("button", { name: "Envoyer" }));
    expect(mocked.postMessage).toHaveBeenCalledWith(9, "Go");
    const failure = await screen.findByRole("button", { name: /Go, .*Non envoyé\. Touche pour réessayer\./ });
    expect(screen.getByLabelText("Message").props.value).toBe("");

    mocked.postMessage.mockResolvedValue(message(3, "Go", null));
    await fireEvent.press(failure);
    await screen.findByLabelText(/^Moi, Go, (?!.*Non envoyé)/);
    expect(screen.queryByText(/Non envoyé/)).toBeNull();
  });
});
