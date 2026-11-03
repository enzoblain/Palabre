import * as SecureStore from "expo-secure-store";
import {
  ApiError,
  api,
  clearConnection,
  normalizeServer,
  pairDevice,
  restoreConnection,
  saveConnection,
  setUnauthorizedHandler,
} from "../src/api";

jest.mock("expo-secure-store", () => ({
  getItemAsync: jest.fn(),
  setItemAsync: jest.fn(),
  deleteItemAsync: jest.fn(),
}));
jest.mock("expo-localization", () => ({ getLocales: () => [{ languageCode: "en" }] }));

const SERVER = "https://palabre.example.com";
const fetchMock = jest.fn();
global.fetch = fetchMock as unknown as typeof fetch;

const jsonResponse = (status: number, body: unknown) =>
  ({ ok: status < 400, status, statusText: "", json: async () => body }) as Response;

beforeEach(() => {
  jest.clearAllMocks();
});

describe("normalizeServer", () => {
  it("defaults to https and strips the trailing slash and /api", () => {
    expect(normalizeServer(" palabre.example.com/api/ ")).toBe(SERVER);
  });

  it("keeps an explicit scheme so that http can be refused later", () => {
    expect(normalizeServer("http://palabre.example.com")).toBe("http://palabre.example.com");
  });
});

describe("secure storage", () => {
  it("saves and restores the connection through expo-secure-store", async () => {
    await saveConnection({ server: SERVER, token: "pdev_abc" });
    expect(SecureStore.setItemAsync).toHaveBeenCalledWith(
      "palabre.connection",
      JSON.stringify({ server: SERVER, token: "pdev_abc" }),
    );
    (SecureStore.getItemAsync as jest.Mock).mockResolvedValue(JSON.stringify({ server: SERVER, token: "pdev_abc" }));
    expect(await restoreConnection()).toEqual({ server: SERVER, token: "pdev_abc" });
  });

  it("ignores a corrupted stored value", async () => {
    (SecureStore.getItemAsync as jest.Mock).mockResolvedValue("{not json");
    expect(await restoreConnection()).toBeNull();
    (SecureStore.getItemAsync as jest.Mock).mockResolvedValue(JSON.stringify({ server: 3 }));
    expect(await restoreConnection()).toBeNull();
  });

  it("deletes the stored value on clear", async () => {
    await clearConnection();
    expect(SecureStore.deleteItemAsync).toHaveBeenCalledWith("palabre.connection");
  });
});

describe("requests", () => {
  it("sends the bearer token to the server's /api", async () => {
    await saveConnection({ server: SERVER, token: "pdev_abc" });
    fetchMock.mockResolvedValue(jsonResponse(200, []));
    await api.listProjects();
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe(`${SERVER}/api/projects`);
    expect(init.headers).toMatchObject({ Authorization: "Bearer pdev_abc" });
  });

  it("refuses a clear-text server without calling it", async () => {
    await saveConnection({ server: "http://palabre.example.com", token: "pdev_abc" });
    await expect(api.listProjects()).rejects.toMatchObject({ message: "The server address must start with https://" });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("maps an error code to its message", async () => {
    await saveConnection({ server: SERVER, token: "pdev_abc" });
    fetchMock.mockResolvedValue(jsonResponse(404, { code: "project_not_found", detail: "No such project" }));
    const error = await api.getProject(1).catch((err: unknown) => err);
    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({ status: 404, code: "project_not_found", detail: "No such project" });
  });

  it("calls the unauthorized handler on a 401", async () => {
    const handler = jest.fn();
    setUnauthorizedHandler(handler);
    await saveConnection({ server: SERVER, token: "pdev_abc" });
    fetchMock.mockResolvedValue(jsonResponse(401, { code: "auth_invalid_token" }));
    await expect(api.listProjects()).rejects.toBeInstanceOf(ApiError);
    expect(handler).toHaveBeenCalledTimes(1);
  });

  it("ignores a 401 for a request sent with a previous connection", async () => {
    const handler = jest.fn();
    setUnauthorizedHandler(handler);
    await saveConnection({ server: SERVER, token: "pdev_old" });
    let answer: (res: Response) => void = () => {};
    fetchMock.mockReturnValue(new Promise<Response>((resolve) => (answer = resolve)));
    const pending = api.listProjects();
    await saveConnection({ server: SERVER, token: "pdev_new" });
    answer(jsonResponse(401, { code: "auth_invalid_token" }));
    await expect(pending).rejects.toBeInstanceOf(ApiError);
    expect(handler).not.toHaveBeenCalled();
  });

  it("reports an unreachable server", async () => {
    await saveConnection({ server: SERVER, token: "pdev_abc" });
    fetchMock.mockRejectedValue(new TypeError("Network request failed"));
    await expect(api.listProjects()).rejects.toMatchObject({ status: 0 });
  });
});

describe("pairDevice", () => {
  it("posts the device name with the admin token and returns only the device token", async () => {
    fetchMock.mockResolvedValue(jsonResponse(201, { id: 1, name: "iPhone", token: "pdev_new" }));
    const conn = await pairDevice(SERVER, "admin-secret", "iPhone");
    expect(conn).toEqual({ server: SERVER, token: "pdev_new" });
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe(`${SERVER}/api/auth/devices`);
    expect(init.method).toBe("POST");
    expect(init.headers).toMatchObject({ Authorization: "Bearer admin-secret" });
    expect(init.body).toBe(JSON.stringify({ name: "iPhone" }));
    expect(SecureStore.setItemAsync).not.toHaveBeenCalled();
  });

  it("turns a 401 into a wrong token error", async () => {
    fetchMock.mockResolvedValue(jsonResponse(401, {}));
    await expect(pairDevice(SERVER, "nope", "iPhone")).rejects.toMatchObject({ message: "Wrong access token" });
  });

  it("turns a 404 into a not a Palabre server error", async () => {
    fetchMock.mockResolvedValue(jsonResponse(404, {}));
    await expect(pairDevice(SERVER, "admin-secret", "iPhone")).rejects.toMatchObject({
      status: 404,
      message: "This is not a Palabre server",
    });
  });

  it("joins the messages of an array detail", async () => {
    fetchMock.mockResolvedValue(jsonResponse(422, { detail: [{ msg: "name too short" }, { msg: "name invalid" }] }));
    await expect(pairDevice(SERVER, "admin-secret", "")).rejects.toMatchObject({
      status: 422,
      detail: "name too short, name invalid",
    });
  });
});
