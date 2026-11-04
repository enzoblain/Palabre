// API data types shared by frontend/ and mobile/; they mirror backend/app/api/schemas.py. Types only, no runtime code.

/** A paired phone (mirrors DeviceOut); the device token is never returned by the list. */
export type Device = {
  id: number;
  name: string;
  created_at: string;
  last_used_at: string;
  expires_at: string;
};

/** A Mac builder (mirrors AppleHostOut); `connected` is the server's own verdict, never guessed from `last_seen_at`. */
export type AppleHost = {
  id: number;
  name: string;
  created_at: string;
  expires_at: string;
  last_seen_at: string | null;
  revoked_at: string | null;
  connected: boolean;
};

/** The one-time code a Mac enrolls with (mirrors AppleEnrollmentCodeOut); it is returned only once. */
export type AppleEnrollmentCode = { code: string; expires_at: string; ttl_seconds: number };

export type AppleBuildStatus = "queued" | "running" | "passed" | "failed" | "error";

/** The newest Swift build of a task (mirrors AppleBuildOut); `errors` is untrusted log text. */
export type AppleBuild = {
  job_id: number;
  status: AppleBuildStatus;
  commit_sha: string;
  infra_error: boolean;
  summary: string;
  errors: string[];
  finished_at: string | null;
};

/** What the front reads of a task detail: only its Swift build, null until one is queued (or for a standard project). */
export type TaskBuild = { apple_build: AppleBuild | null };

export type ProjectPlatform = "generic" | "apple";

export type Project = {
  id: number;
  name: string;
  repo_url: string;
  default_branch: string;
  mode: string;
  seed: number;
  platform?: ProjectPlatform;
  created_at: string;
};

export type LastMessage = { content: string; author: string; created_at: string };

export type ProjectListItem = Project & {
  unread_count: number;
  lead_writing: boolean;
  // Latest message of direction; null when there is none
  last_message: LastMessage | null;
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
/** A project with the conversations of each of its rooms, by room id. */
export type ProjectState = { detail: ProjectDetail; conversations: Record<number, Conversation[]> };
/** The project after an edit; `warning` is set when the team still works on the previous main branch. */
export type ProjectUpdated = ProjectDetail & { warning: string | null };

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
  // Set when the lead asks the CEO something (the CEO answers in the chat, which closes it)
  request_kind: string | null;
  request_status: "pending" | "answered" | "validated" | "rejected" | "nuanced" | "withdrawn" | "merged" | null;
  request_comment: string | null;
  request_answered_at: string | null;
  // The new request that replaced this one (status "merged")
  request_merged_into: number | null;
  request_decision_id: number | null;
};

export type AppSettings = {
  boss_name: string;
  // Language the agents speak and write in: a key of `languages` (key → native name)
  language: string;
  languages: Record<string, string>;
  claude_accounts: number;
};
export type ExhaustedAccount = { account: number; resets_at: string; estimated: boolean };
export type OrchestratorStatus = {
  enabled: boolean;
  running_employee_ids: number[];
  pending_wakeups: number;
  exhausted_accounts: ExhaustedAccount[];
};

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

/** A named personality of the catalog (PersonalityPresetOut on the server): the screen only shows its name and description. */
export type PersonalityPreset = {
  key: string;
  label: string;
  description: string;
};

export type Model = "haiku" | "sonnet" | "opus";
export type Effort = "low" | "medium" | "high" | "xhigh" | "max";
/** Categories of the historic roles. */
export type CoreCategory = "management" | "engineering" | "quality" | "product" | "support";
/** Categories of the extended jobs (extended_roles.toml on the server). */
export type ExtendedCategory =
  | "direction_strategy" | "architecture" | "software_development" | "artificial_intelligence" | "data_databases"
  | "cybersecurity" | "cloud_devops_infrastructure" | "networks_telecom" | "blockchain_web3" | "quality_testing"
  | "performance_reliability" | "product_project_management" | "ux_ui_design" | "iot_robotics_embedded"
  | "games_3d_multimedia" | "advanced_research" | "ecommerce_fintech_business" | "support_operations"
  | "technical_documentation" | "specialized_roles";
export type RoleCategory = CoreCategory | ExtendedCategory;

/** The tools the permissions of a job give (RoleToolsOut on the server). */
export type RoleTools = { mcp: string[]; claude: string[] };

/** A job of the catalog (RoleOut on the server). */
export type Role = {
  key: string;
  title: string;
  description: string;
  category: RoleCategory;
  order: number;
  model: Model;
  effort: Effort | null;
  mission: string;
  responsibilities: string[];
  forbidden: string[];
  deliverables: string[];
  escalation: string;
  success: string;
  permissions: string[];
  wakes_on: string[];
  tools: RoleTools;
};

/** Models an employee can run on and the biggest custom team (CatalogLimitsOut on the server). */
export type CatalogLimits = { models: Model[]; max_agents: number; min_team_size: number; mandatory_role: string };

/** An agent of a team built by hand (MemberIn on the server). */
export type MemberIn = {
  name: string;
  roles: string[];
  model: string | null;
  // Key of a personality preset; null: the server draws one at random
  personality: string | null;
  account: number | null;
};

/** The device session returned once by the pairing, `token` included (DevicePaired on the server). */
export type DevicePaired = Device & { token: string };

/** `token` is a short-lived session or device token, never the ADMIN_TOKEN itself. */
export type Connection = { server: string; token: string };
