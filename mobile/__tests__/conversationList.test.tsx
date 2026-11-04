import { act, fireEvent, render, screen, waitFor } from "@testing-library/react-native";
import ConversationListScreen from "../app/(tabs)/index";
import { api, type ProjectListItem } from "../src/api";

const mockPush = jest.fn();
jest.mock("expo-router", () => ({ useRouter: () => ({ push: mockPush }) }));
jest.mock("expo-localization", () => ({ getLocales: () => [{ languageCode: "fr" }] }));
jest.mock("expo-secure-store", () => ({}));
jest.mock("../src/api", () => ({ ...jest.requireActual("../src/api"), api: { listProjects: jest.fn() } }));

const listProjects = api.listProjects as jest.Mock;

const project = (over: Partial<ProjectListItem>): ProjectListItem => ({
  id: 1,
  name: "Alpha",
  repo_url: "",
  default_branch: "main",
  mode: "enterprise",
  seed: 1,
  created_at: "2020-01-01T10:00:00Z",
  unread_count: 0,
  lead_writing: false,
  last_message: null,
  ...over,
});

const pullToRefresh = () =>
  act(async () => {
    await screen.getByTestId("conversation-list").props.refreshControl.props.onRefresh();
  });

beforeEach(() => jest.clearAllMocks());

describe("conversation list screen", () => {
  it("shows skeletons while loading", async () => {
    listProjects.mockReturnValue(new Promise(() => {}));
    await render(<ConversationListScreen />);
    expect(screen.getByLabelText("Chargement des conversations")).toBeTruthy();
  });

  it("shows the empty message", async () => {
    listProjects.mockResolvedValue([]);
    await render(<ConversationListScreen />);
    expect(await screen.findByText("Aucune conversation. Les messages de l’équipe apparaîtront ici.")).toBeTruthy();
  });

  it("lists conversations with an accessible label including unread, and opens one on tap", async () => {
    listProjects.mockResolvedValue([
      project({ id: 7, name: "Alpha", unread_count: 2, last_message: { content: "Bonjour", author: "Élise", created_at: "2020-01-02T10:00:00Z" } }),
    ]);
    await render(<ConversationListScreen />);
    const row = await screen.findByRole("button", { name: /^Alpha, Bonjour, .*, non lu$/ });
    await fireEvent.press(row);
    expect(mockPush).toHaveBeenCalledWith({ pathname: "/conversation/[id]", params: { id: "7" } });
  });

  it("filters with the search field", async () => {
    listProjects.mockResolvedValue([project({ id: 1, name: "Alpha" }), project({ id: 2, name: "Beta" })]);
    await render(<ConversationListScreen />);
    await screen.findByText("Beta");
    await fireEvent.changeText(screen.getByLabelText("Rechercher"), "bet");
    await waitFor(() => expect(screen.queryByText("Alpha")).toBeNull());
    await fireEvent.changeText(screen.getByLabelText("Rechercher"), "zzz");
    expect(screen.getByText("Aucun résultat")).toBeTruthy();
  });

  it("shows an error banner, retries, and keeps the list when a cache exists", async () => {
    listProjects.mockRejectedValueOnce(new Error("down"));
    await render(<ConversationListScreen />);
    expect(await screen.findByText("Impossible de charger les conversations.")).toBeTruthy();
    listProjects.mockResolvedValue([project({ name: "Alpha" })]);
    await fireEvent.press(screen.getByRole("button", { name: "Réessayer" }));
    expect(await screen.findByText("Alpha")).toBeTruthy();
    await waitFor(() => expect(screen.queryByText("Impossible de charger les conversations.")).toBeNull());

    listProjects.mockRejectedValue(new Error("down again"));
    await pullToRefresh();
    expect(await screen.findByText("Impossible de charger les conversations.")).toBeTruthy();
    expect(screen.getByText("Alpha")).toBeTruthy();
  });

  it("reloads on pull to refresh", async () => {
    listProjects.mockResolvedValue([project({ name: "Alpha" })]);
    await render(<ConversationListScreen />);
    await screen.findByText("Alpha");
    listProjects.mockResolvedValue([project({ name: "Alpha" }), project({ id: 2, name: "Beta" })]);
    await pullToRefresh();
    expect(await screen.findByText("Beta")).toBeTruthy();
  });
});
