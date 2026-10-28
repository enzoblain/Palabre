import { fetch as tauriFetch } from "@tauri-apps/plugin-http";

// In the desktop app, requests go through Rust (no CORS / mixed-content limits).
// In a plain browser (`npm run dev`), the regular fetch is used.
const inTauri = "__TAURI_INTERNALS__" in window;
const doFetch: typeof fetch = inTauri ? tauriFetch : window.fetch.bind(window);

// --- Types (mirror backend/app/api/schemas.py) -------------------------------------

export type Project = {
  id: number;
  name: string;
  repo_url: string;
  default_branch: string;
  mode: string;
  seed: number;
  created_at: string;
};

export type EmployeeBrief = { id: number; name: string; title: string };

export type Employee = EmployeeBrief & {
  project_id: number;
  roles: string[];
  model: string;
  permissions: string[];
  traits: Record<string, number>;
  quirks: string[];
  style: Record<string, string>;
  // Claude account chosen by the boss; null: spread automatically
  account: number | null;
};

export type Room = {
  id: number;
  project_id: number;
  name: string;
  objective: string;
  summary: string;
  created_at: string;
  members: EmployeeBrief[];
};

export type ProjectDetail = Project & { employees: Employee[]; rooms: Room[] };

export type Conversation = { id: number; room_id: number; title: string; created_at: string };

export type Message = {
  id: number;
  conversation_id: number;
  employee_id: number | null;
  author_name: string;
  content: string;
  created_at: string;
};

export type EmployeeStatus = {
  employee_id: number;
  name: string;
  title: string;
  status: "working" | "waiting" | "resting" | "offline";
  account: number;
  kind: string | null;
  conversation_id: number | null;
  task_id: number | null;
  since: string | null;
};

export type Mode = {
  label: string;
  seats: { roles: string[]; count?: number }[];
  rules: string[];
  process: Record<string, unknown>;
};

export type TeamMember = Omit<Employee, "id" | "project_id" | "account">;

export type AppSettings = {
  boss_name: string;
  // Language the agents speak and write in: a key of `languages` (key → native name)
  language: string;
  languages: Record<string, string>;
  claude_accounts: number;
};
export type TeamPreview = { mode: string; seed: number; employees: TeamMember[] };

export type Axis = { key: string; label: string; low: string; high: string };
export type Personality = { levels: number[]; axes: Axis[]; quirks: string[] };

// --- Connection to the server ------------------------------------------------------

export type Connection = { server: string; token: string };

const STORAGE_KEY = "palabre.connection";
let current: Connection | null = readConnection();
let onUnauthorized: () => void = () => {};

function readConnection(): Connection | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
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
    if (conn) localStorage.setItem(STORAGE_KEY, JSON.stringify(conn));
    else localStorage.removeItem(STORAGE_KEY);
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
  ) {
    super(message);
  }
}

async function request<T>(conn: Connection, path: string, method = "GET", body?: unknown): Promise<T> {
  let res: Response;
  try {
    res = await doFetch(`${conn.server}/api${path}`, {
      method,
      headers: {
        Authorization: `Bearer ${conn.token}`,
        ...(body !== undefined ? { "Content-Type": "application/json" } : {}),
      },
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
  } catch (err) {
    throw new ApiError(0, `Cannot reach the server at ${conn.server} (${err instanceof Error ? err.message : String(err)})`);
  }
  if (!res.ok) {
    let detail = res.statusText || `HTTP ${res.status}`;
    try {
      const data = await res.json();
      if (typeof data.detail === "string") detail = data.detail;
      else if (Array.isArray(data.detail)) detail = data.detail.map((d: { msg: string }) => d.msg).join(", ");
    } catch {
      // Not JSON: keep the status text
    }
    throw new ApiError(res.status, detail);
  }
  return (res.status === 204 ? undefined : await res.json()) as T;
}

function call<T>(path: string, method = "GET", body?: unknown): Promise<T> {
  if (!current) return Promise.reject(new ApiError(401, "Not connected"));
  return request<T>(current, path, method, body).catch((err) => {
    if (err instanceof ApiError && err.status === 401) onUnauthorized();
    throw err;
  });
}

/** Checks the address and token before saving them. */
export async function testConnection(conn: Connection): Promise<void> {
  try {
    await request(conn, "/settings");
  } catch (err) {
    if (err instanceof ApiError && err.status === 401) throw new ApiError(401, "Wrong access token");
    if (err instanceof ApiError && err.status === 404) throw new ApiError(404, "This is not a Palabre server");
    throw err;
  }
}

// --- Endpoints ---------------------------------------------------------------------

export const api = {
  getSettings: () => call<AppSettings>("/settings"),
  saveSettings: (changes: { boss_name?: string; language?: string }) =>
    call<AppSettings>("/settings", "PUT", changes),

  modes: () => call<Record<string, Mode>>("/catalog/modes"),
  personality: () => call<Personality>("/catalog/personality"),
  previewTeam: (mode: string, seed?: number) =>
    call<TeamPreview>(`/catalog/modes/${mode}/team${seed !== undefined ? `?seed=${seed}` : ""}`),

  listProjects: () => call<Project[]>("/projects"),
  getProject: (id: number) => call<ProjectDetail>(`/projects/${id}`),
  createProject: (body: {
    name: string;
    repo_url: string;
    mode: string;
    default_branch: string;
    seed: number;
    accounts: Record<string, number>;
  }) => call<ProjectDetail>("/projects", "POST", body),
  setAccount: (employeeId: number, account: number | null) =>
    call<Employee>(`/employees/${employeeId}`, "PATCH", { account }),
  teamStatus: (projectId: number) => call<EmployeeStatus[]>(`/projects/${projectId}/team-status`),

  listConversations: (roomId: number) => call<Conversation[]>(`/rooms/${roomId}/conversations`),
  listMessages: (conversationId: number, sinceId?: number) =>
    call<Message[]>(
      `/conversations/${conversationId}/messages?limit=200${sinceId !== undefined ? `&since_id=${sinceId}` : ""}`,
    ),
  postMessage: (conversationId: number, content: string) =>
    call<Message>(`/conversations/${conversationId}/messages`, "POST", { content }),
};
