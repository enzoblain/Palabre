import { translate } from "../i18n";
import { ApiError, errorMessage, readErrorCode } from "./errors";
import { deleteStoredConnection, readStoredConnection, writeStoredConnection } from "./storage";
import type {
  Connection,
  Conversation,
  Device,
  DevicePaired,
  Message,
  ProjectDetail,
  ProjectListItem,
} from "./types";

const MESSAGES_PAGE_SIZE = 200;
const PAIRING_DEVICE_NAME_MAX = 100;

let current: Connection | null = null;
let onUnauthorized: () => void = () => {};

export function getConnection(): Connection | null {
  return current;
}

/** Loads the connection kept in secure storage; call once at startup. */
export async function restoreConnection(): Promise<Connection | null> {
  current = await readStoredConnection();
  return current;
}

export async function saveConnection(conn: Connection): Promise<void> {
  current = conn;
  await writeStoredConnection(conn);
}

export async function clearConnection(): Promise<void> {
  current = null;
  await deleteStoredConnection();
}

export function setUnauthorizedHandler(handler: () => void): void {
  onUnauthorized = handler;
}

const HTTPS_PREFIX = /^https:\/\//i;

/** "palabre.example.com/" → "https://palabre.example.com"; a scheme is kept as typed, `request` refuses anything but https:// (see `isSecureServer`). */
export function normalizeServer(input: string): string {
  const server = input.trim().replace(/\/+$/, "").replace(/\/api$/, "");
  if (/^[a-z][a-z0-9+.-]*:\/\//i.test(server)) return server;
  return `https://${server}`;
}

export function isSecureServer(server: string): boolean {
  return HTTPS_PREFIX.test(server);
}

async function readFailure(res: Response): Promise<ApiError> {
  let detail = res.statusText || `HTTP ${res.status}`;
  let code: unknown;
  try {
    const data: { code?: unknown; detail?: unknown } = await res.json();
    code = data.code;
    if (typeof data.detail === "string") detail = data.detail;
    else if (Array.isArray(data.detail)) detail = data.detail.map((d: { msg: string }) => d.msg).join(", ");
  } catch {
    // Not JSON: keep the status text
  }
  return new ApiError(res.status, errorMessage(res.status, code), detail, readErrorCode(code));
}

async function request<T>(conn: Connection, path: string, method = "GET", body?: unknown): Promise<T> {
  if (!isSecureServer(conn.server)) throw new ApiError(0, translate("api.insecureServer"));
  let res: Response;
  try {
    res = await fetch(`${conn.server}/api${path}`, {
      method,
      headers: {
        Authorization: `Bearer ${conn.token}`,
        ...(body !== undefined ? { "Content-Type": "application/json" } : {}),
      },
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
  } catch {
    throw new ApiError(0, translate("api.unreachable", { server: conn.server }));
  }
  if (!res.ok) throw await readFailure(res);
  return (res.status === 204 ? undefined : await res.json()) as T;
}

function call<T>(path: string, method = "GET", body?: unknown): Promise<T> {
  if (!current) return Promise.reject(new ApiError(401, translate("api.notConnected")));
  const issuedOn = current;
  return request<T>(issuedOn, path, method, body).catch((err: unknown) => {
    // A late 401 from a previous session must not sign out the current one
    if (err instanceof ApiError && err.status === 401 && current === issuedOn) onUnauthorized();
    throw err;
  });
}

/**
 * Pairs this phone: exchanges the ADMIN_TOKEN for a device token. Only the device token is returned
 * (and to be stored); the ADMIN_TOKEN is never kept.
 */
export async function pairDevice(server: string, adminToken: string, deviceName: string): Promise<Connection> {
  try {
    const paired = await request<DevicePaired>({ server, token: adminToken }, "/auth/devices", "POST", {
      name: deviceName.slice(0, PAIRING_DEVICE_NAME_MAX),
    });
    return { server, token: paired.token };
  } catch (err) {
    if (err instanceof ApiError && err.status === 401) throw new ApiError(401, translate("api.wrongToken"));
    if (err instanceof ApiError && err.status === 404) throw new ApiError(404, translate("api.notPalabre"));
    if (err instanceof ApiError && err.status === 429) throw new ApiError(429, errorMessage(429, "auth_locked"), err.detail, "auth_locked");
    throw err;
  }
}

export const api = {
  listDevices: () => call<Device[]>("/auth/devices"),
  revokeDevice: (id: number) => call<void>(`/auth/devices/${id}`, "DELETE"),

  listProjects: () => call<ProjectListItem[]>("/projects"),
  getProject: (id: number) => call<ProjectDetail>(`/projects/${id}`),

  listConversations: (roomId: number) => call<Conversation[]>(`/rooms/${roomId}/conversations`),
  listMessages: (conversationId: number, sinceId?: number) =>
    call<Message[]>(
      `/conversations/${conversationId}/messages?limit=${MESSAGES_PAGE_SIZE}${sinceId !== undefined ? `&since_id=${sinceId}` : ""}`,
    ),
  postMessage: (conversationId: number, content: string) =>
    call<Message>(`/conversations/${conversationId}/messages`, "POST", { content }),
  markDirectionRead: (projectId: number) => call<ProjectListItem>(`/projects/${projectId}/direction/read`, "POST"),
};
