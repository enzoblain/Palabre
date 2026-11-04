import { act, fireEvent, render, screen, waitFor } from "@testing-library/react-native";
import { Alert } from "react-native";
import SettingsScreen from "../app/(tabs)/settings";
import { ApiError, api, type AppSettings, type Device, type Employee, type ProjectDetail } from "../src/api";

const mockSignOut = jest.fn();
jest.mock("../src/session", () => ({ useSession: () => ({ signOut: mockSignOut }) }));
jest.mock("expo-localization", () => ({ getLocales: () => [{ languageCode: "fr" }] }));
jest.mock("expo-secure-store", () => ({}));
jest.mock("@expo/vector-icons", () => ({ Ionicons: () => null }));
jest.mock("../src/api", () => ({
  ...jest.requireActual("../src/api"),
  getConnection: () => ({ server: "https://palabre.example.com", token: "t" }),
  api: {
    getSettings: jest.fn(),
    saveSettings: jest.fn(),
    listDevices: jest.fn(),
    revokeDevice: jest.fn(),
    listProjects: jest.fn(),
    getProject: jest.fn(),
    setAccount: jest.fn(),
  },
}));

const mocked = api as unknown as Record<keyof typeof api, jest.Mock>;
const alertSpy = jest.spyOn(Alert, "alert");

const settings = (over: Partial<AppSettings> = {}): AppSettings => ({
  boss_name: "Enzo",
  language: "fr",
  languages: { fr: "Français", en: "English" },
  claude_accounts: 1,
  ...over,
});
const device = (id: number, over: Partial<Device> = {}): Device => ({
  id,
  name: `Phone ${id}`,
  created_at: "2026-01-01T10:00:00",
  last_used_at: "2026-01-01T10:00:00",
  expires_at: "2026-02-01T10:00:00",
  ...over,
});
const employee = (id: number, account: number | null): Employee => ({
  id,
  name: `Agent${id}`,
  title: "Dev",
  project_id: 1,
  roles: [],
  model: "sonnet",
  permissions: [],
  traits: {},
  quirks: [],
  style: {},
  account,
});

/** Presses the button of the last alert that has this label. */
const confirmAlert = async (label: string) => {
  const buttons = alertSpy.mock.calls.at(-1)?.[2] ?? [];
  const button = buttons.find((candidate) => candidate.text === label);
  await act(async () => {
    button?.onPress?.();
  });
};

beforeEach(() => {
  jest.clearAllMocks();
  mocked.getSettings.mockResolvedValue(settings());
  mocked.listDevices.mockResolvedValue([]);
});

describe("settings screen: boss name", () => {
  it("saves a changed name and shows the confirmation", async () => {
    mocked.saveSettings.mockResolvedValue(settings({ boss_name: "Enzo B" }));
    await render(<SettingsScreen />);
    const field = await screen.findByLabelText("Votre nom");
    await fireEvent.changeText(field, "Enzo B");
    await fireEvent.press(screen.getByRole("button", { name: "Enregistrer" }));
    expect(mocked.saveSettings).toHaveBeenCalledWith({ boss_name: "Enzo B" });
    expect(await screen.findByText("Enregistré. Votre équipe vous connaît désormais sous ce nom.")).toBeTruthy();
  });

  it("disables save while the name is unchanged or empty", async () => {
    await render(<SettingsScreen />);
    const field = await screen.findByLabelText("Votre nom");
    expect(screen.getByRole("button", { name: "Enregistrer" })).toBeDisabled();
    await fireEvent.changeText(field, "   ");
    expect(screen.getByRole("button", { name: "Enregistrer" })).toBeDisabled();
  });

  it("shows the hint when no name is set and the API error when saving fails", async () => {
    mocked.getSettings.mockResolvedValue(settings({ boss_name: "" }));
    mocked.saveSettings.mockRejectedValue(new ApiError(500, "Échec"));
    await render(<SettingsScreen />);
    expect(await screen.findByText("Dites à votre équipe comment vous appeler avant de commencer.")).toBeTruthy();
    await fireEvent.changeText(screen.getByLabelText("Votre nom"), "Enzo");
    await fireEvent.press(screen.getByRole("button", { name: "Enregistrer" }));
    expect(await screen.findByText("Échec")).toBeTruthy();
  });

  it("offers a retry when the settings cannot be loaded", async () => {
    mocked.getSettings.mockRejectedValueOnce(new Error("down"));
    await render(<SettingsScreen />);
    expect(await screen.findByText("Impossible de charger les réglages.")).toBeTruthy();
    await fireEvent.press(screen.getByRole("button", { name: "Réessayer" }));
    expect(await screen.findByLabelText("Votre nom")).toBeTruthy();
  });
});

describe("settings screen: team language", () => {
  it("saves the picked language and marks it selected", async () => {
    mocked.saveSettings.mockResolvedValue(settings({ language: "en" }));
    await render(<SettingsScreen />);
    await fireEvent.press(await screen.findByRole("radio", { name: "English" }));
    expect(mocked.saveSettings).toHaveBeenCalledWith({ language: "en" });
    expect(await screen.findByText("Enregistré. Elle s’applique dès leur prochain message.")).toBeTruthy();
    await waitFor(() => expect(screen.getByRole("radio", { name: "English" })).toBeChecked());
  });
});

describe("settings screen: connected devices", () => {
  it("shows the loading state while the devices load", async () => {
    mocked.listDevices.mockReturnValue(new Promise(() => {}));
    await render(<SettingsScreen />);
    expect(screen.getByText("Chargement des appareils")).toBeTruthy();
  });

  it("shows the error then the empty state", async () => {
    mocked.listDevices.mockRejectedValueOnce(new ApiError(500, "boom"));
    await render(<SettingsScreen />);
    expect(await screen.findByText("Impossible de charger les appareils : boom")).toBeTruthy();
    await fireEvent.press(screen.getAllByRole("button", { name: "Réessayer" })[0]);
    expect(await screen.findByText("Aucun téléphone connecté. Connectez-en un depuis l’app mobile.")).toBeTruthy();
  });

  it("lists the devices and writes 'never' for an unused one", async () => {
    mocked.listDevices.mockResolvedValue([device(1), device(2, { last_used_at: "2026-01-05T10:00:00" })]);
    await render(<SettingsScreen />);
    expect(await screen.findByText("Phone 1")).toBeTruthy();
    expect(screen.getByText("Dernière utilisation : Jamais")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Révoquer Phone 2" })).toBeTruthy();
  });

  it("revokes only after the confirmation", async () => {
    mocked.listDevices.mockResolvedValue([device(1), device(2)]);
    mocked.revokeDevice.mockResolvedValue(undefined);
    await render(<SettingsScreen />);
    await fireEvent.press(await screen.findByRole("button", { name: "Révoquer Phone 1" }));
    expect(alertSpy.mock.calls.at(-1)?.[0]).toBe("Révoquer « Phone 1 » ?");
    expect(mocked.revokeDevice).not.toHaveBeenCalled();
    await confirmAlert("Révoquer");
    expect(mocked.revokeDevice).toHaveBeenCalledWith(1);
    expect(await screen.findByText("Appareil révoqué")).toBeTruthy();
    expect(screen.queryByText("Phone 1")).toBeNull();
    expect(screen.getByText("Phone 2")).toBeTruthy();
  });

  it("keeps the device and says why when the revocation fails", async () => {
    mocked.listDevices.mockResolvedValue([device(1)]);
    mocked.revokeDevice.mockRejectedValue(new ApiError(404, "Introuvable"));
    await render(<SettingsScreen />);
    await fireEvent.press(await screen.findByRole("button", { name: "Révoquer Phone 1" }));
    await confirmAlert("Révoquer");
    expect(await screen.findByText("Impossible de révoquer l’appareil : Introuvable")).toBeTruthy();
    expect(screen.getByText("Phone 1")).toBeTruthy();
  });
});

describe("settings screen: Claude accounts", () => {
  it("only explains the count when there is at most one account", async () => {
    await render(<SettingsScreen />);
    expect(await screen.findByText(/^Un seul compte/)).toBeTruthy();
    expect(mocked.listProjects).not.toHaveBeenCalled();
  });

  it("lets the boss pin an employee to an account, with the automatic one labelled", async () => {
    mocked.getSettings.mockResolvedValue(settings({ claude_accounts: 2 }));
    mocked.listProjects.mockResolvedValue([{ id: 1 }]);
    const project = { id: 1, name: "Alpha", employees: [employee(1, null), employee(2, null)] } as ProjectDetail;
    mocked.getProject.mockResolvedValue(project);
    mocked.setAccount.mockResolvedValue(employee(2, 2));
    await render(<SettingsScreen />);
    expect(await screen.findByText("Alpha")).toBeTruthy();
    expect(screen.getByText("Auto (compte 1)")).toBeTruthy();
    expect(screen.getByText("Auto (compte 2)")).toBeTruthy();
    await fireEvent.press(screen.getByRole("button", { name: "Compte Claude de Agent2" }));
    await fireEvent.press(await screen.findByRole("radio", { name: "Compte 2" }));
    expect(mocked.setAccount).toHaveBeenCalledWith(2, 2);
    expect(await screen.findByText("Compte 2", { exact: true })).toBeTruthy();
  });
});

describe("settings screen: server", () => {
  it("shows the server and signs out only after the confirmation", async () => {
    await render(<SettingsScreen />);
    expect(await screen.findByText("Connecté à https://palabre.example.com")).toBeTruthy();
    await fireEvent.press(screen.getByRole("button", { name: "Se déconnecter" }));
    expect(mockSignOut).not.toHaveBeenCalled();
    await confirmAlert("Se déconnecter");
    expect(mockSignOut).toHaveBeenCalledTimes(1);
  });
});
