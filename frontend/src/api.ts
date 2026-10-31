import { fetch as tauriFetch } from "@tauri-apps/plugin-http";
import { translate } from "./i18n";

// In the desktop app, requests go through Rust (no CORS / mixed-content limits).
// In a plain browser (`npm run dev`), the regular fetch is used.
const inTauri = "__TAURI_INTERNALS__" in window;
const doFetch: typeof fetch = inTauri ? tauriFetch : window.fetch.bind(window);
// Opened from the server's web port: the API is on the page's own address
export const pageServer: string | null = inTauri || import.meta.env.DEV ? null : location.origin;

// --- Types (mirror backend/app/api/schemas.py) -------------------------------------

export type ProjectKind = "company" | "research";
export type ResearchPhase = "research" | "debate" | "conclusion" | "report" | "done";

export type Project = {
  id: number;
  name: string;
  // "company": a software company on a GitHub repository; "research": peers on a topic
  kind: ProjectKind;
  topic: string | null;
  // Research: where the current question stands
  research_phase: ResearchPhase | null;
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
  // "direction": the only channel where the CEO writes; "team": read-only for the CEO;
  // "dm": between two employees (name "A·B"), read-only for the CEO
  kind: "direction" | "team" | "dm";
  objective: string;
  summary: string;
  created_at: string;
  updated_at: string;
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
  // Automatic line from the platform (not the CEO, although it has no employee)
  is_system: boolean;
  // Set when the lead asks the CEO something (Validate / Reject / Nuance)
  request_kind: string | null;
  request_status: "pending" | RequestAnswer | "withdrawn" | "merged" | null;
  request_comment: string | null;
  request_answered_at: string | null;
  // The new request that replaced this one (status "merged")
  request_merged_into: number | null;
  request_decision_id: number | null;
};
export type RequestAnswer = "validated" | "rejected" | "nuanced";

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

/** Who is busy right now ("blocked" is not derived by the server yet). */
export type Presence = {
  employee_id: number;
  name: string;
  roles: string[];
  state: "working" | "idle";
  kind: string | null;
  task_id: number | null;
  conversation_id: number | null;
  last_run_at: string | null;
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
export type UsageTotals = {
  runs: number;
  input_tokens: number;
  output_tokens: number;
  cache_creation_tokens: number;
  cache_read_tokens: number;
  cost_usd: number;
  // Runs that reported no tokens / no cost: the sums leave them out
  runs_without_tokens: number;
  runs_without_cost: number;
};
export type UsagePeriod = "day" | "week" | "total";
// id and name are null where unknown (account: runs before it was recorded)
export type UsageEntry = { id: number | null; name: string | null } & Record<UsagePeriod, UsageTotals>;
export type Usage = {
  accounts: UsageEntry[];
  employees: UsageEntry[];
  projects: UsageEntry[];
} & Record<UsagePeriod, UsageTotals>;
// Real quota of a Claude account, as /usage shows it. `resets_at` is null when unknown
export type QuotaWindow = { used_percent: number; resets_at: string | null };
export type ModelQuota = QuotaWindow & { model: string };
// On error, `error` says why and the windows are empty
export type AccountQuota = {
  account: number;
  error: string | null;
  session: QuotaWindow | null;
  week: QuotaWindow | null;
  models: ModelQuota[];
};
export type ExhaustedAccount = { account: number; resets_at: string; estimated: boolean };
export type OrchestratorStatus = {
  enabled: boolean;
  running_employee_ids: number[];
  pending_wakeups: number;
  exhausted_accounts: ExhaustedAccount[];
};
export type Quota = { accounts: AccountQuota[] };
export type TeamPreview = { mode: string; seed: number; employees: TeamMember[] };

export type Decision = {
  id: number;
  room_id: number;
  title: string;
  rationale: string;
  status: "proposed" | "validated" | "rejected";
  proposed_by: string;
  // A release: validating it merges this PR into production
  pr_number: number | null;
  pr_url: string | null;
  created_at: string;
  decided_at: string | null;
};

export type Axis = { key: string; label: string; low: string; high: string };
export type Personality = {
  levels: number[];
  axes: Axis[];
  quirks: string[];
  // Style key (verbosity, tone) → possible values
  style: Record<string, string[]>;
};

export type Role = { title: string; mission: string; model: string; permissions: string[] };

/** An agent of a team built by hand (MemberIn on the server). */
export type MemberIn = {
  name: string;
  roles: string[];
  model: string | null;
  traits: Record<string, number>;
  quirks: string[];
  style: Record<string, string>;
  account: number | null;
};

// --- Connection to the server ------------------------------------------------------

/** `token` is a short-lived session token, never the ADMIN_TOKEN itself. */
export type Connection = { server: string; token: string };

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

/** Codes of the backend's error responses (backend/app/errors.py); each has an `error.<code>` message. */
export const ERROR_CODES = [
  "auth_invalid_token",
  "auth_locked",
  "validation_error",
  "workflow_error",
  "github_error",
  "github_merge_refused",
  "project_not_found",
  "room_not_found",
  "task_not_found",
  "conversation_not_found",
  "decision_not_found",
  "employee_not_found",
  "message_not_found",
  "question_not_found",
  "mode_not_found",
  "unknown_mode",
  "research_topic_required",
  "invalid_repository",
  "duplicate_employee_name",
  "unknown_roles",
  "lead_required",
  "invalid_account",
  "research_has_no_repository",
  "direction_room_immutable",
  "dm_immutable",
  "boss_direction_only",
  "boss_read_only_room",
  "members_not_in_project",
  "employee_other_project",
  "direction_room_reserved",
  "conversation_not_in_room",
  "invalid_language",
  "not_found",
  "invalid_personality",
  "invalid_branch_name",
  "branch_already_used",
  "no_name_left",
  "task_wrong_status",
  "task_not_yours",
  "task_waiting_for_dependencies",
  "task_no_branch",
  "task_no_pull_request",
  "invalid_pr_title",
  "cannot_review_own_task",
  "merge_blocked",
  "no_commits",
  "github_not_configured",
  "invalid_github_url",
  "github_branch_missing",
  "production_branch_boss_only",
] as const;
export type ErrorCode = (typeof ERROR_CODES)[number];

const isErrorCode = (code: unknown): code is ErrorCode => ERROR_CODES.includes(code as ErrorCode);

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
    res = await doFetch(`${conn.server}/api${path}`, {
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
  getQuota: () => call<Quota>("/settings/quota"),
  getUsage: () => call<Usage>("/settings/usage"),
  orchestratorStatus: () => call<OrchestratorStatus>("/orchestrator"),
  getSettings: () => call<AppSettings>("/settings"),
  saveSettings: (changes: { boss_name?: string; language?: string }) =>
    call<AppSettings>("/settings", "PUT", changes),

  modes: (kind: ProjectKind) => call<Record<string, Mode>>(`/catalog/modes?kind=${kind}`),
  personality: (kind: ProjectKind) => call<Personality>(`/catalog/personality?kind=${kind}`),
  roles: (kind: ProjectKind) => call<Record<string, Role>>(`/catalog/roles?kind=${kind}`),
  names: () => call<string[]>("/catalog/names"),
  previewTeam: (mode: string, seed?: number) =>
    call<TeamPreview>(`/catalog/modes/${mode}/team${seed !== undefined ? `?seed=${seed}` : ""}`),

  listProjects: () => call<Project[]>("/projects"),
  getProject: (id: number) => call<ProjectDetail>(`/projects/${id}`),
  deleteProject: (id: number) => call<void>(`/projects/${id}`, "DELETE"),
  changeBranch: (id: number, branch: string) => call<ProjectDetail>(`/projects/${id}/branch`, "PUT", { branch }),
  createProject: (body: {
    name: string;
    repo_url?: string;
    topic?: string;
    rapporteur?: string | null;
    mode: string;
    seed: number;
    accounts: Record<string, number>;
    employees?: MemberIn[];
  }) => call<ProjectDetail>("/projects", "POST", body),
  setAccount: (employeeId: number, account: number | null) =>
    call<Employee>(`/employees/${employeeId}`, "PATCH", { account }),
  researchPhase: (projectId: number) => call<{ phase: ResearchPhase | null }>(`/projects/${projectId}/research-phase`),
  presence: (projectId: number) => call<Presence[]>(`/projects/${projectId}/presence`),
  teamStatus: (projectId: number) => call<EmployeeStatus[]>(`/projects/${projectId}/team-status`),

  roomDocument: <T>(roomId: number) => call<T>(`/rooms/${roomId}/document`),
  decide: (decisionId: number, status: "validated" | "rejected") =>
    call<Decision>(`/decisions/${decisionId}`, "PATCH", { status }),

  listConversations: (roomId: number) => call<Conversation[]>(`/rooms/${roomId}/conversations`),
  listMessages: (conversationId: number, sinceId?: number) =>
    call<Message[]>(
      `/conversations/${conversationId}/messages?limit=200${sinceId !== undefined ? `&since_id=${sinceId}` : ""}`,
    ),
  postMessage: (conversationId: number, content: string) =>
    call<Message>(`/conversations/${conversationId}/messages`, "POST", { content }),
  liftRateLimit: (conversationId: number) =>
    call<void>(`/conversations/${conversationId}/lift-rate-limit`, "POST"),
  answerRequest: (messageId: number, answer: RequestAnswer, comment = "") =>
    call<Message>(`/messages/${messageId}/answer`, "POST", { answer, comment }),
};
