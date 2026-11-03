import "@testing-library/react-native/matchers";
import * as SecureStore from "expo-secure-store";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react-native";
import { Text, TextInput } from "react-native";
import LoginScreen from "../app/login";
import { api } from "../src/api";
import { SessionProvider, pairAndStore, useSession } from "../src/session";

jest.mock("expo-secure-store", () => ({
  getItemAsync: jest.fn(),
  setItemAsync: jest.fn(),
  deleteItemAsync: jest.fn(),
}));
jest.mock("expo-localization", () => ({ getLocales: () => [{ languageCode: "en" }] }));

const SERVER = "https://palabre.example.com";
const ACCESS_CODE = "admin-secret";
const fetchMock = jest.fn();
global.fetch = fetchMock as unknown as typeof fetch;
const jsonResponse = (status: number, body: unknown) =>
  ({ ok: status < 400, status, statusText: "", json: async () => body }) as Response;

beforeEach(() => {
  jest.clearAllMocks();
  (SecureStore.getItemAsync as jest.Mock).mockResolvedValue(null);
});

describe("pairAndStore", () => {
  it("stores the device token and never the access code", async () => {
    fetchMock.mockResolvedValue(jsonResponse(201, { token: "pdev_new" }));
    expect(await pairAndStore("palabre.example.com", ACCESS_CODE, " iPhone ")).toBe(SERVER);
    const stored = (SecureStore.setItemAsync as jest.Mock).mock.calls.map(([, value]) => value).join();
    expect(stored).toContain("pdev_new");
    expect(stored).not.toContain(ACCESS_CODE);
  });

  it("stores nothing on a wrong code", async () => {
    fetchMock.mockResolvedValue(jsonResponse(401, { code: "auth_invalid_token" }));
    await expect(pairAndStore(SERVER, "nope", "iPhone")).rejects.toMatchObject({ status: 401, message: "Wrong access token" });
    expect(SecureStore.setItemAsync).not.toHaveBeenCalled();
  });

  it("reports too many attempts on a 429", async () => {
    fetchMock.mockResolvedValue(jsonResponse(429, {}));
    await expect(pairAndStore(SERVER, "nope", "iPhone")).rejects.toMatchObject({
      status: 429,
      message: "Too many failed attempts, try again in a moment",
    });
    expect(SecureStore.setItemAsync).not.toHaveBeenCalled();
  });

  it("refuses clear-text HTTP without calling the server", async () => {
    await expect(pairAndStore("http://palabre.example.com", ACCESS_CODE, "iPhone")).rejects.toMatchObject({
      message: "The server address must start with https://",
    });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("reports an unreachable server", async () => {
    fetchMock.mockRejectedValue(new TypeError("Network request failed"));
    await expect(pairAndStore(SERVER, ACCESS_CODE, "iPhone")).rejects.toMatchObject({ status: 0 });
  });
});

function Probe() {
  const { status, server, expired } = useSession();
  return <Text>{`${status}|${server}|${expired}`}</Text>;
}

describe("SessionProvider", () => {
  it("restores a stored session without asking again", async () => {
    (SecureStore.getItemAsync as jest.Mock).mockResolvedValue(JSON.stringify({ server: SERVER, token: "pdev_abc" }));
    await render(<SessionProvider><Probe /></SessionProvider>);
    await waitFor(() => expect(screen.getByText(`signedIn|${SERVER}|false`)).toBeTruthy());
  });

  it("goes back to sign-in on a 401, keeping the server and clearing the token", async () => {
    (SecureStore.getItemAsync as jest.Mock).mockResolvedValue(JSON.stringify({ server: SERVER, token: "pdev_abc" }));
    await render(<SessionProvider><Probe /></SessionProvider>);
    await waitFor(() => expect(screen.getByText(`signedIn|${SERVER}|false`)).toBeTruthy());
    fetchMock.mockResolvedValue(jsonResponse(401, { code: "auth_invalid_token" }));
    await act(async () => {
      await api.listProjects().catch(() => undefined);
    });
    expect(SecureStore.deleteItemAsync).toHaveBeenCalledWith("palabre.connection");
    expect(screen.getByText(`signedOut|${SERVER}|true`)).toBeTruthy();
  });

  it("signs in from the login screen and shows an error on a wrong code", async () => {
    const focusSpy = jest.spyOn(TextInput.prototype, "focus");
    await render(<SessionProvider><LoginScreen /></SessionProvider>);
    await waitFor(() => expect(screen.getByLabelText("Server address")).toBeTruthy());
    await fireEvent.changeText(screen.getByLabelText("Server address"), SERVER);
    await fireEvent.changeText(screen.getByLabelText("Administrator token"), "nope");
    fetchMock.mockResolvedValue(jsonResponse(401, {}));
    await fireEvent.press(screen.getByRole("button", { name: "Sign in" }));
    await waitFor(() => expect(screen.getByRole("alert")).toBeTruthy());
    expect(screen.getByText("Wrong access token")).toBeTruthy();
    expect(focusSpy).toHaveBeenCalled();
    expect(screen.getByText("⚠︎", { includeHiddenElements: true })).not.toBeVisible();
    expect(SecureStore.setItemAsync).not.toHaveBeenCalled();
  });

  it("announces the disconnected device message to screen readers", async () => {
    (SecureStore.getItemAsync as jest.Mock).mockResolvedValue(JSON.stringify({ server: SERVER, token: "pdev_abc" }));
    await render(<SessionProvider><Probe /><LoginScreen /></SessionProvider>);
    await waitFor(() => expect(screen.getByText(`signedIn|${SERVER}|false`)).toBeTruthy());
    fetchMock.mockResolvedValue(jsonResponse(401, { code: "auth_invalid_token" }));
    await act(async () => {
      await api.listProjects().catch(() => undefined);
    });
    expect(screen.getByRole("alert")).toHaveTextContent("This device was signed out. Sign in again.");
  });

  it("pairs when the device name is submitted from the keyboard", async () => {
    fetchMock.mockResolvedValue(jsonResponse(201, { token: "pdev_new" }));
    await render(<SessionProvider><LoginScreen /></SessionProvider>);
    await waitFor(() => expect(screen.getByLabelText("Server address")).toBeTruthy());
    await fireEvent.changeText(screen.getByLabelText("Server address"), SERVER);
    await fireEvent.changeText(screen.getByLabelText("Administrator token"), ACCESS_CODE);
    await fireEvent(screen.getByLabelText("Device name"), "submitEditing");
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
  });

  it("does not call the network when the keyboard submits an empty access code", async () => {
    await render(<SessionProvider><LoginScreen /></SessionProvider>);
    await waitFor(() => expect(screen.getByLabelText("Server address")).toBeTruthy());
    await fireEvent.changeText(screen.getByLabelText("Server address"), SERVER);
    await fireEvent(screen.getByLabelText("Device name"), "submitEditing");
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
