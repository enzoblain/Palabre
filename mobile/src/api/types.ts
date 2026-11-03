// Mirrors the backend contract (backend/app/api/schemas.py), as in frontend/src/api.ts.

/** A paired phone (mirrors DeviceOut); the device token is never returned by the list. */
export type Device = {
  id: number;
  name: string;
  created_at: string;
  last_used_at: string;
  expires_at: string;
};

export type Project = {
  id: number;
  name: string;
  repo_url: string;
  default_branch: string;
  mode: string;
  seed: number;
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

/** The device session returned once by the pairing, `token` included (DevicePaired on the server). */
export type DevicePaired = Device & { token: string };

/** `token` is a device token (`pdev_...`), never the ADMIN_TOKEN itself. */
export type Connection = { server: string; token: string };
