import { type Connection, type ErrorCode, isErrorCode, type CatalogLimits, type AppSettings, type OrchestratorStatus, type PersonalityPreset, type Role, type Device, type ProjectListItem, type ProjectDetail, type ProjectUpdated, type Employee, type MemberIn, type Conversation, type Message } from "@palabre/shared";
import { translate } from "./i18n";

// Opened from the server's web port: the API is on the page's own address
export const pageServer: string | null = import.meta.env.DEV ? null : location.origin;

export * from "@palabre/shared";

// --- Connection to the server ------------------------------------------------------

const STORAGE_KEY = "palabre.connection";
try {
  // Older versions kept the raw ADMIN_TOKEN here for good: drop it
  localStorage.removeItem(STORAGE_KEY);
} catch {
  // Storage unavailable: nothing to drop
}
let current: Connection | null = readConnection();
let onUnauthorized: () => void = () => {};

function readConnection(): Connection | null {
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY);
    return raw ? (JSON.parse(raw) as Connection) : null;
  } catch {
    return null;
  }
}

export function getConnection(): Connection | null {
  return current;
}

export function saveConnection(conn: Connection | null): void {
  current = conn;
  try {
    if (conn) sessionStorage.setItem(STORAGE_KEY, JSON.stringify(conn));
    else sessionStorage.removeItem(STORAGE_KEY);
  } catch {
    // Storage unavailable: the connection lasts until the app is closed
  }
}

export function setUnauthorizedHandler(handler: () => void): void {
  onUnauthorized = handler;
}

/** "192.168.1.10:8000/" → "http://192.168.1.10:8000" */
export function normalizeServer(input: string): string {
  let server = input.trim().replace(/\/+$/, "");
  if (!/^https?:\/\//i.test(server)) server = `http://${server}`;
  return server.replace(/\/api$/, "");
}

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
    /** The backend's own text (English), kept for logs and debugging, never shown as is. */
    public detail?: string,
    public code?: ErrorCode,
  ) {
    super(message);
  }
}

/** The message in the project's language: by code, else a generic one with the status. */
function errorMessage(status: number, code: unknown): string {
  if (!isErrorCode(code)) return translate("api.error", { status });
  return translate(`error.${code}`);
}

async function request<T>(conn: Connection, path: string, method = "GET", body?: unknown): Promise<T> {
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
  if (!res.ok) {
    let detail = res.statusText || `HTTP ${res.status}`;
    let code: unknown;
    try {
      const data = await res.json();
      code = data.code;
      if (typeof data.detail === "string") detail = data.detail;
      else if (Array.isArray(data.detail)) detail = data.detail.map((d: { msg: string }) => d.msg).join(", ");
    } catch {
      // Not JSON: keep the status text
    }
    throw new ApiError(res.status, errorMessage(res.status, code), detail, isErrorCode(code) ? code : undefined);
  }
  return (res.status === 204 ? undefined : await res.json()) as T;
}

function call<T>(path: string, method = "GET", body?: unknown): Promise<T> {
  if (!current) return Promise.reject(new ApiError(401, translate("api.notConnected")));
  return request<T>(current, path, method, body).catch((err) => {
    if (err instanceof ApiError && err.status === 401) onUnauthorized();
    throw err;
  });
}

/** Exchanges the ADMIN_TOKEN for a session token; only the session token is kept. */
export async function login(server: string, adminToken: string): Promise<Connection> {
  try {
    const session = await request<{ token: string }>({ server, token: adminToken }, "/auth/session", "POST");
    return { server, token: session.token };
  } catch (err) {
    if (err instanceof ApiError && err.status === 401) throw new ApiError(401, translate("api.wrongToken"));
    if (err instanceof ApiError && err.status === 404) throw new ApiError(404, translate("api.notPalabre"));
    throw err;
  }
}

// --- Endpoints ---------------------------------------------------------------------

export const api = {
  orchestratorStatus: () => call<OrchestratorStatus>("/orchestrator"),
  getSettings: () => call<AppSettings>("/settings"),
  saveSettings: (changes: { boss_name?: string; language?: string }) =>
    call<AppSettings>("/settings", "PUT", changes),

  personalities: () => call<Record<string, PersonalityPreset>>("/catalog/personalities"),
  roles: () => call<Record<string, Role>>("/catalog/roles"),
  limits: () => call<CatalogLimits>("/catalog/limits"),
  names: () => call<string[]>("/catalog/names"),

  listDevices: () => call<Device[]>("/auth/devices"),
  revokeDevice: (id: number) => call<void>(`/auth/devices/${id}`, "DELETE"),

  listProjects: () => call<ProjectListItem[]>("/projects"),
  getProject: (id: number) => call<ProjectDetail>(`/projects/${id}`),
  updateProject: (id: number, fields: { name?: string; main_branch?: string }) =>
    call<ProjectUpdated>(`/projects/${id}`, "PATCH", fields),
  publishTestflight: (id: number) => call<{ version: string }>(`/projects/${id}/testflight`, "POST"),
  deleteProject: (id: number) => call<void>(`/projects/${id}`, "DELETE"),
  deleteProjects: (ids: number[]) => call<void>("/projects/delete", "POST", { ids }),
  createProject: (body: {
    name: string;
    repo_url?: string;
    mode: string;
    creation_mode?: "manual" | "auto";
    description?: string;
    employee_count?: number;
    employees?: MemberIn[];
  }) => call<ProjectDetail>("/projects", "POST", body),
  setAccount: (employeeId: number, account: number | null) =>
    call<Employee>(`/employees/${employeeId}`, "PATCH", { account }),
  addEmployee: (projectId: number, body: { roles: string[]; personality: string | null }) =>
    call<Employee>(`/projects/${projectId}/employees`, "POST", body),
  updateEmployee: (employeeId: number, changes: { roles?: string[]; personality?: string }) =>
    call<Employee>(`/employees/${employeeId}`, "PATCH", changes),
  removeEmployee: (employeeId: number) => call<void>(`/employees/${employeeId}`, "DELETE"),

  listConversations: (roomId: number) => call<Conversation[]>(`/rooms/${roomId}/conversations`),
  listMessages: (conversationId: number, sinceId?: number) =>
    call<Message[]>(
      `/conversations/${conversationId}/messages?limit=200${sinceId !== undefined ? `&since_id=${sinceId}` : ""}`,
    ),
  postMessage: (conversationId: number, content: string) =>
    call<Message>(`/conversations/${conversationId}/messages`, "POST", { content }),
  markDirectionRead: (projectId: number) => call<ProjectListItem>(`/projects/${projectId}/direction/read`, "POST"),
  liftRateLimit: (conversationId: number) =>
    call<void>(`/conversations/${conversationId}/lift-rate-limit`, "POST"),
};
