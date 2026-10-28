import type { Conversation, EmployeeStatus, Notification, Project, ProjectDetail } from "../api";
import { type Route, go } from "../router";
import { mention } from "../util";
import { Avatar } from "./Avatar";
import { BackIcon, GearIcon, HashIcon, InboxIcon, PlusIcon } from "./Icons";

export type ProjectState = { detail: ProjectDetail; conversations: Record<number, Conversation[]> };

const STATUS_ORDER = { working: 0, waiting: 1, resting: 2, offline: 3 };
const STATUS_LABEL = { working: "Working", waiting: "Starting", resting: "Resting", offline: "Offline" };

function activity(status: EmployeeStatus, project: ProjectState): string {
  if (status.status !== "working") return STATUS_LABEL[status.status];
  if (status.kind === "task" && status.task_id) return `Working on task #${status.task_id}`;
  const room = project.detail.rooms.find((r) =>
    project.conversations[r.id]?.some((c) => c.id === status.conversation_id),
  );
  return room ? `Talking in #${room.name}` : "Working";
}

// Notifications that point at a message in a conversation (the rest are in the inbox only)
const CONVERSATION_TYPES = new Set(["mention", "escalation", "conversation_throttled"]);

function Badge({ count, urgent = false }: { count: number; urgent?: boolean }) {
  return count > 0 ? <span className={`badge-count${urgent ? " urgent" : ""}`}>{count}</span> : null;
}

export function Sidebar({ route, projects, project, statuses, bossName, claudeAccounts, notifications }: {
  route: Route;
  projects: Project[];
  project: ProjectState | null;
  statuses: EmployeeStatus[];
  bossName: string;
  claudeAccounts: number;
  notifications: Notification[];
}) {
  const inProject = route.name === "project" || route.name === "inbox";
  return (
    <aside className="sidebar">
      {inProject ? (
        <ProjectNav route={route} project={project} statuses={statuses} showAccounts={claudeAccounts > 1}
          notifications={notifications.filter((n) => n.project_id === route.projectId)} />
      ) : (
        <>
          <header className="sidebar-head">
            <span className="brand-mark small" aria-hidden="true">P</span>
            <span className="sidebar-title">Palabre</span>
          </header>
          <nav className="sidebar-nav">
            <div className="section-label">Projects</div>
            {projects.map((p) => (
              <a key={p.id} className="nav-item" href={`#/p/${p.id}`}>
                <span className="project-initial">{p.name.slice(0, 1).toUpperCase()}</span>
                <span className="truncate">{p.name}</span>
                <Badge count={notifications.filter((n) => n.project_id === p.id).length} urgent />
              </a>
            ))}
            <a className={`nav-item muted${route.name === "new" ? " active" : ""}`} href="#/new">
              <PlusIcon size={16} /> New project
            </a>
          </nav>
        </>
      )}
      <footer className="sidebar-foot">
        <a className={`nav-item${route.name === "settings" ? " active" : ""}`} href="#/settings">
          <GearIcon size={16} />
          <span className="truncate">{bossName ? `${bossName} · CEO` : "Settings"}</span>
        </a>
      </footer>
    </aside>
  );
}

function ProjectNav({ route, project, statuses, showAccounts, notifications }: {
  route: Extract<Route, { name: "project" | "inbox" }>;
  project: ProjectState | null;
  statuses: EmployeeStatus[];
  showAccounts: boolean;
  notifications: Notification[];
}) {
  const activeConversation = route.name === "project" ? route.conversationId : null;
  const unreadIn = (conversationIds: number[]) =>
    notifications.filter((n) => CONVERSATION_TYPES.has(n.type) && conversationIds.includes(n.conversation_id ?? -1)).length;
  const sorted = [...statuses].sort((a, b) => STATUS_ORDER[a.status] - STATUS_ORDER[b.status]);
  const working = statuses.filter((s) => s.status === "working").length;
  return (
    <>
      <header className="sidebar-head">
        <button className="icon-btn" onClick={() => go("/")} aria-label="Back to projects">
          <BackIcon />
        </button>
        <span className="sidebar-title truncate">{project?.detail.name ?? "…"}</span>
      </header>
      <nav className="sidebar-nav">
        <a className={`nav-item${route.name === "inbox" ? " active" : ""}`} href={`#/p/${route.projectId}/inbox`}>
          <InboxIcon size={15} /> <span className="truncate">Inbox</span>
          <Badge count={notifications.length} urgent />
        </a>
        <div className="section-label">Channels</div>
        {project?.detail.rooms.map((room) => {
          const conversations = project.conversations[room.id] ?? [];
          const first = conversations[0];
          const active = conversations.some((c) => c.id === activeConversation);
          return (
            <div key={room.id}>
              <a className={`nav-item${active && conversations.length === 1 ? " active" : ""}`}
                href={first ? `#/p/${project.detail.id}/c/${first.id}` : undefined}>
                <HashIcon size={15} /> <span className="truncate">{room.name}</span>
                <Badge count={unreadIn(conversations.map((c) => c.id))} />
              </a>
              {conversations.length > 1 &&
                conversations.map((c) => (
                  <a key={c.id} className={`nav-item nav-sub${c.id === activeConversation ? " active" : ""}`}
                    href={`#/p/${project.detail.id}/c/${c.id}`}>
                    <span className="truncate">{c.title}</span>
                  </a>
                ))}
            </div>
          );
        })}

        <div className="section-label team-label">
          Team <span className="count">{working ? `${working} working` : "all resting"}</span>
        </div>
        {project &&
          sorted.map((s) => (
            <button key={s.employee_id} className="nav-item member" onClick={() => mention(s.name)}
              title={`${s.title} — click to mention`}>
              <span className="member-avatar">
                <Avatar name={s.name} size={26} />
                <span className={`dot dot-${s.status}`} />
              </span>
              <span className="member-text">
                <span className="member-line">
                  <span className="truncate">{s.name}</span>
                  {showAccounts && <span className="account-tag" title={`Runs on Claude account ${s.account}`}>{s.account}</span>}
                </span>
                <span className={`member-status status-${s.status} truncate`}>{activity(s, project)}</span>
              </span>
            </button>
          ))}
      </nav>
    </>
  );
}
