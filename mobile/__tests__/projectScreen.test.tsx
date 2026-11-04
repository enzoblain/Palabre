import { act, fireEvent, render, screen, waitFor } from "@testing-library/react-native";
import { Alert, Linking } from "react-native";
import ProjectScreen from "../app/project/[id]";
import { ApiError, api, type ProjectDetail, type ProjectUpdated } from "../src/api";

const mockBack = jest.fn();
const mockReplace = jest.fn();
jest.mock("expo-router", () => ({
  useRouter: () => ({ back: mockBack, replace: mockReplace }),
  useLocalSearchParams: () => ({ id: "1" }),
}));
jest.mock("expo-localization", () => ({ getLocales: () => [{ languageCode: "fr" }] }));
jest.mock("expo-secure-store", () => ({}));
jest.mock("../src/api", () => ({
  ...jest.requireActual("../src/api"),
  api: {
    getProject: jest.fn(), updateProject: jest.fn(), deleteProject: jest.fn(), roles: jest.fn(), personalities: jest.fn(), limits: jest.fn(),
  },
}));

const mocked = api as unknown as Record<string, jest.Mock>;
const alertSpy = jest.spyOn(Alert, "alert");
const openUrl = jest.spyOn(Linking, "openURL").mockResolvedValue();

const detail = (over: Partial<ProjectDetail> = {}): ProjectDetail => ({
  id: 1,
  name: "Alpha",
  repo_url: "https://github.com/acme/alpha",
  default_branch: "main",
  mode: "enterprise",
  seed: 1,
  platform: "generic",
  created_at: "2026-01-01T10:00:00",
  employees: [],
  rooms: [{ id: 4, kind: "direction", objective: "Ship the app", summary: "", members: [] } as unknown as ProjectDetail["rooms"][number]],
  ...over,
});

const confirmAlert = async (label: string) => {
  const buttons = alertSpy.mock.calls.at(-1)?.[2] ?? [];
  await act(async () => {
    buttons.find((button) => button.text === label)?.onPress?.();
  });
};

beforeEach(() => {
  jest.clearAllMocks();
  mocked.getProject.mockResolvedValue(detail());
  mocked.roles.mockResolvedValue({});
  mocked.personalities.mockResolvedValue({});
  mocked.limits.mockResolvedValue({ models: [], max_agents: 5, min_team_size: 2, mandatory_role: "lead" });
});

describe("project screen", () => {
  it("shows a loading state", async () => {
    mocked.getProject.mockReturnValue(new Promise(() => {}));
    await render(<ProjectScreen />);
    expect(screen.getByText("Chargement du projet")).toBeTruthy();
  });

  it("shows the description and opens the git link outside the app", async () => {
    await render(<ProjectScreen />);
    expect(await screen.findByText("Ship the app")).toBeTruthy();
    await fireEvent.press(screen.getByRole("link", { name: "https://github.com/acme/alpha" }));
    expect(openUrl).toHaveBeenCalledWith("https://github.com/acme/alpha");
  });

  it("says so when there is no description and no repository", async () => {
    mocked.getProject.mockResolvedValue(detail({ repo_url: "", rooms: [] }));
    await render(<ProjectScreen />);
    expect(await screen.findByText("Pas encore de description.")).toBeTruthy();
    expect(screen.getByText("Aucun dépôt lié.")).toBeTruthy();
  });

  it("offers a retry when the project cannot be loaded", async () => {
    mocked.getProject.mockRejectedValueOnce(new Error("down"));
    await render(<ProjectScreen />);
    await fireEvent.press(await screen.findByText("Réessayer"));
    expect(await screen.findByText("Ship the app")).toBeTruthy();
  });

  it("enables save only for a change and sends only what changed", async () => {
    mocked.updateProject.mockResolvedValue({ ...detail({ name: "Beta" }), warning: null } satisfies ProjectUpdated);
    await render(<ProjectScreen />);
    const name = await screen.findByLabelText("Nom");
    expect(screen.getByRole("button", { name: "Enregistrer" })).toBeDisabled();
    await fireEvent.changeText(name, "Beta");
    await fireEvent.press(screen.getByRole("button", { name: "Enregistrer" }));
    await waitFor(() => expect(mocked.updateProject).toHaveBeenCalledWith(1, { name: "Beta" }));
    expect(await screen.findByText("Enregistré.")).toBeTruthy();
  });

  it("shows the backend warning about the branch", async () => {
    mocked.updateProject.mockResolvedValue({ ...detail({ default_branch: "dev" }), warning: "Branch not found" });
    await render(<ProjectScreen />);
    await fireEvent.changeText(await screen.findByLabelText("Branche principale"), "dev");
    await fireEvent.press(screen.getByRole("button", { name: "Enregistrer" }));
    expect(await screen.findByText("Branch not found")).toBeTruthy();
    expect(mocked.updateProject).toHaveBeenCalledWith(1, { main_branch: "dev" });
  });

  it("shows the error when the save fails", async () => {
    mocked.updateProject.mockRejectedValue(new ApiError(400, "Nom déjà pris"));
    await render(<ProjectScreen />);
    await fireEvent.changeText(await screen.findByLabelText("Nom"), "Beta");
    await fireEvent.press(screen.getByRole("button", { name: "Enregistrer" }));
    expect(await screen.findByText("Nom déjà pris")).toBeTruthy();
  });

  it("exposes the branch hint as visible text only, not as an accessibility hint", async () => {
    await render(<ProjectScreen />);
    const branchInput = await screen.findByLabelText("Branche principale");
    expect(branchInput.props.accessibilityHint).toBeUndefined();
    expect(screen.getByText(/Là d’où partent les tâches/)).toBeTruthy();
  });

  it("deletes the project after a confirmation, then goes back to the list", async () => {
    mocked.deleteProject.mockResolvedValue(undefined);
    await render(<ProjectScreen />);
    await fireEvent.press(await screen.findByRole("button", { name: "Supprimer ce projet" }));
    expect(mocked.deleteProject).not.toHaveBeenCalled();
    await confirmAlert("Supprimer définitivement");
    expect(mocked.deleteProject).toHaveBeenCalledWith(1);
    expect(mockReplace).toHaveBeenCalledWith("/");
  });

  it("stays on the page and shows the error when the deletion fails", async () => {
    mocked.deleteProject.mockRejectedValue(new ApiError(500, "Boom"));
    await render(<ProjectScreen />);
    await fireEvent.press(await screen.findByRole("button", { name: "Supprimer ce projet" }));
    await confirmAlert("Supprimer définitivement");
    expect(await screen.findByText("Boom")).toBeTruthy();
    expect(mockReplace).not.toHaveBeenCalled();
  });
});
