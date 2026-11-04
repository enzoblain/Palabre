import { act, fireEvent, render, screen, waitFor } from "@testing-library/react-native";
import { Alert } from "react-native";
import ConversationListScreen from "../app/(tabs)/index";
import { api, type ProjectListItem } from "../src/api";

const mockPush = jest.fn();
const mockNavigate = jest.fn();
jest.mock("expo-router", () => ({ useRouter: () => ({ push: mockPush, navigate: mockNavigate }) }));
jest.mock("@expo/vector-icons", () => ({ Ionicons: () => null }));
jest.mock("expo-localization", () => ({ getLocales: () => [{ languageCode: "fr" }] }));
const mockStore = new Map<string, string>();
jest.mock("expo-secure-store", () => ({
  getItemAsync: async (key: string) => mockStore.get(key) ?? null,
  setItemAsync: async (key: string, value: string) => void mockStore.set(key, value),
}));
jest.mock("../src/api", () => ({ ...jest.requireActual("../src/api"), api: { listProjects: jest.fn(), deleteProjects: jest.fn(), orchestratorStatus: jest.fn(), getSettings: jest.fn() },
}));

const listProjects = api.listProjects as jest.Mock;

const project = (over: Partial<ProjectListItem>): ProjectListItem => ({
  id: 1,
  name: "Alpha",
  repo_url: "",
  default_branch: "main",
  mode: "enterprise",
  seed: 1,
  platform: "generic",
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

beforeEach(() => {
  jest.clearAllMocks();
  mockStore.clear();
});

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

  it("offers to create a project when there is none", async () => {
    listProjects.mockResolvedValue([]);
    await render(<ConversationListScreen />);
    await fireEvent.press(await screen.findByRole("button", { name: "Créer un projet" }));
    expect(mockNavigate).toHaveBeenCalledWith("/new");
  });

  it("lists the most recently opened project first, and remembers the one just opened", async () => {
    mockStore.set("palabre.lastOpenedProject", "2");
    listProjects.mockResolvedValue([project({ id: 1, name: "Alpha" }), project({ id: 2, name: "Beta" })]);
    await render(<ConversationListScreen />);
    await waitFor(() => expect(screen.getAllByRole("button", { name: /^(Alpha|Beta)/ })[0]).toHaveAccessibleName(/^Beta/));
    await fireEvent.press(screen.getByRole("button", { name: /^Alpha/ }));
    expect(mockStore.get("palabre.lastOpenedProject")).toBe("1");
  });

  describe("edit mode", () => {
    const confirmDeletion = () => {
      const buttons = (Alert.alert as jest.Mock).mock.calls[0][2] as { text: string; onPress?: () => void }[];
      return buttons.find((b) => b.text === "Supprimer définitivement")!.onPress!();
    };
    beforeEach(() => {
      jest.spyOn(Alert, "alert").mockImplementation(() => {});
      listProjects.mockResolvedValue([project({ id: 1, name: "Alpha" }), project({ id: 2, name: "Beta" })]);
    });

    it("ticks projects instead of opening them, then deletes them after a confirmation", async () => {
      (api.deleteProjects as jest.Mock).mockResolvedValue(undefined);
      await render(<ConversationListScreen />);
      await screen.findByText("Beta");
      await fireEvent.press(screen.getByRole("button", { name: "Modifier" }));
      expect(screen.getByRole("button", { name: "Supprimer (0)" })).toBeDisabled();
      await fireEvent.press(screen.getByRole("checkbox", { name: "Sélectionner Beta" }));
      expect(mockPush).not.toHaveBeenCalled();
      expect(screen.getByRole("checkbox", { name: "Sélectionner Beta" })).toBeChecked();
      await fireEvent.press(screen.getByRole("button", { name: "Supprimer (1)" }));
      expect(api.deleteProjects).not.toHaveBeenCalled();
      await act(async () => confirmDeletion());
      expect(api.deleteProjects).toHaveBeenCalledWith([2]);
      await waitFor(() => expect(screen.queryByRole("button", { name: /^Supprimer/ })).toBeNull());
    });

    it("labels the delete button while the deletion is pending", async () => {
      (api.deleteProjects as jest.Mock).mockReturnValue(new Promise(() => {}));
      await render(<ConversationListScreen />);
      await screen.findByText("Beta");
      await fireEvent.press(screen.getByRole("button", { name: "Modifier" }));
      await fireEvent.press(screen.getByRole("checkbox", { name: "Sélectionner Alpha" }));
      await fireEvent.press(screen.getByRole("button", { name: "Supprimer (1)" }));
      await act(async () => {
        confirmDeletion();
      });
      expect(screen.getByRole("button", { name: "Suppression…" })).toBeBusy();
    });

    it("shows the error and stays in edit mode when the deletion fails", async () => {
      (api.deleteProjects as jest.Mock).mockRejectedValue(new Error("boom"));
      await render(<ConversationListScreen />);
      await screen.findByText("Beta");
      await fireEvent.press(screen.getByRole("button", { name: "Modifier" }));
      await fireEvent.press(screen.getByRole("checkbox", { name: "Sélectionner Alpha" }));
      await fireEvent.press(screen.getByRole("button", { name: "Supprimer (1)" }));
      await act(async () => confirmDeletion());
      expect(await screen.findByText("Impossible de supprimer les projets.")).toBeTruthy();
      expect(screen.getByRole("checkbox", { name: "Sélectionner Alpha" })).toBeChecked();
    });

    it("leaves edit mode with Done and clears the selection", async () => {
      await render(<ConversationListScreen />);
      await screen.findByText("Beta");
      await fireEvent.press(screen.getByRole("button", { name: "Modifier" }));
      await fireEvent.press(screen.getByRole("checkbox", { name: "Sélectionner Alpha" }));
      await fireEvent.press(screen.getByRole("button", { name: "OK" }));
      expect(screen.queryByRole("checkbox")).toBeNull();
    });
  });
});
