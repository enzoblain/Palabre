import { useEffect, useRef, useState } from "react";
import type { Conversation, Presence, Project, ProjectDetail, Room } from "../api";
import { type Route, go } from "../router";
import { Avatar } from "./Avatar";
import { DocumentIcon, GearIcon, HashIcon, PlusIcon } from "./Icons";

export type ProjectState = { detail: ProjectDetail; conversations: Record<number, Conversation[]> };

/** "Malik·Léa" → "Malik ↔ Léa" */
export const dmLabel = (room: Room) => room.name.replace("·", " ↔ ");

function Badge({ count, label, quiet }: { count: number; label: string; quiet?: boolean }) {
  // The count is text, and the label tells what it counts: no meaning carried by color alone
  return count > 0 ? <span className={quiet ? "badge-count" : "badge-count urgent"} aria-label={label}>{count}</span> : null;
}

const firstConversation = (project: ProjectState, room: Room) => project.conversations[room.id]?.[0];
const roomUnread = (project: ProjectState, room: Room, unread: Record<number, number>, active: number | null) =>
  (project.conversations[room.id] ?? []).reduce((n, c) => n + (c.id === active ? 0 : unread[c.id] ?? 0), 0);

/** Button with the project's name; opens the menu to switch project or reach the settings. */
export function ProjectMenu({ route, projects, project, bossName, onNavigate }: {
  route: Route;
  projects: Project[];
  project: ProjectState | null;
  bossName: string;
  onNavigate?: () => void;
}) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const buttonRef = useRef<HTMLButtonElement>(null);
  const projectId = "projectId" in route ? route.projectId : null;
  const name = project?.detail.name ?? projects.find((p) => p.id === projectId)?.name ?? "Palabre";
  const items = () => [...(rootRef.current?.querySelectorAll<HTMLElement>('[role="menuitem"]') ?? [])];

  useEffect(() => {
    if (!open) return;
    items()[0]?.focus();
    const onDown = (e: MouseEvent) => {
      if (!rootRef.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [open]);

  function onKeyDown(e: React.KeyboardEvent) {
    if (!open) return;
    const list = items();
    const at = list.indexOf(document.activeElement as HTMLElement);
    if (e.key === "Escape") {
      e.stopPropagation();
      setOpen(false);
      buttonRef.current?.focus();
    } else if (e.key === "ArrowDown") {
      e.preventDefault();
      list[(at + 1) % list.length]?.focus();
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      list[(at - 1 + list.length) % list.length]?.focus();
    } else if (e.key === "Tab") {
      setOpen(false);
    }
  }

  const close = () => {
    setOpen(false);
    onNavigate?.();
  };

  return (
    <div className="project-menu" ref={rootRef} onKeyDown={onKeyDown}>
      <button ref={buttonRef} className="project-menu-btn" aria-haspopup="menu" aria-expanded={open}
        aria-label={`${name}: switch project or open settings`} onClick={() => setOpen(!open)}>
        <span className="project-initial" aria-hidden="true">{name.slice(0, 1).toUpperCase()}</span>
        <span className="truncate">{name}</span>
        <span className="caret" aria-hidden="true">▾</span>
      </button>
      {open && (
        <div className="menu" role="menu" aria-label="Projects and settings">
          {project && (
            <a role="menuitem" className="menu-item" href={`#/p/${project.detail.id}/report`} onClick={close}>
              <DocumentIcon size={15} /> {project.detail.kind === "research" ? "Report" : "Document"}
            </a>
          )}
          <div className="section-label" role="presentation">Projects</div>
          {projects.map((p) => (
            <a key={p.id} role="menuitem" className="menu-item" href={`#/p/${p.id}`} onClick={close}
              aria-current={p.id === projectId ? "true" : undefined}>
              <span className="project-initial" aria-hidden="true">{p.name.slice(0, 1).toUpperCase()}</span>
              <span className="truncate">{p.name}</span>
            </a>
          ))}
          <a role="menuitem" className="menu-item" href="#/new" onClick={close}><PlusIcon size={15} /> New project</a>
          <hr />
          <a role="menuitem" className="menu-item" href="#/settings" onClick={close}>
            <GearIcon size={15} /> <span className="truncate">{bossName ? `Settings · ${bossName}` : "Settings"}</span>
          </a>
        </div>
      )}
    </div>
  );
}

function stateText(p: Presence | undefined) {
  return p?.state === "working" ? "Working" : "Available";
}

/** What a working person is doing, shown under their name. */
function subtitle(p: Presence | undefined, project: ProjectState): string | null {
  if (p?.state !== "working") return null;
  if (p.kind === "task" && p.task_id) return `Task #${p.task_id}`;
  const room = project.detail.rooms.find((r) => project.conversations[r.id]?.some((c) => c.id === p.conversation_id));
  return room ? `In ${room.kind === "dm" ? dmLabel(room) : `#${room.name}`}` : null;
}

/** The right-hand "Team" column: people with their state, then the rooms. Fixed at 280px, a drawer on small screens. */
export function TeamPanel({ route, projects, project, presence, bossName, pending, unread, open, onClose }: {
  route: Route;
  projects: Project[];
  project: ProjectState | null;
  presence: Presence[];
  bossName: string;
  // Requests of the lead waiting for the CEO
  pending: number;
  unread: Record<number, number>;
  open: boolean;
  onClose: () => void;
}) {
  const active = route.name === "project" ? route.conversationId : null;
  const [expanded, setExpanded] = useState<number | null>(null);
  const [note, setNote] = useState("");
  const [announce, setAnnounce] = useState("");
  const previous = useRef<Map<number, string> | null>(null);
  const navRef = useRef<HTMLElement>(null);

  // Announce state changes to screen readers, politely, not the whole list on each poll
  useEffect(() => {
    const now = new Map(presence.map((p) => [p.employee_id, p.state]));
    const before = previous.current;
    previous.current = now;
    if (!before || before.size === 0) return;
    const changes = presence.filter((p) => before.has(p.employee_id) && before.get(p.employee_id) !== p.state);
    if (changes.length) setAnnounce(changes.map((p) => `${p.name} is now ${stateText(p).toLowerCase()}`).join(". "));
  }, [presence]);
  useEffect(() => {
    previous.current = null;
    setExpanded(null);
    setNote("");
  }, [project?.detail.id]);

  if (!project) {
    return (
      <aside className={`team-panel${open ? " open" : ""}`} aria-label="Team">
        <header className="panel-head"><ProjectMenu route={route} projects={projects} project={null} bossName={bossName} onNavigate={onClose} /></header>
        <p className="muted panel-empty">Loading…</p>
      </aside>
    );
  }

  const byId = new Map(presence.map((p) => [p.employee_id, p]));
  const rooms = project.detail.rooms;
  const direction = rooms.find((r) => r.kind === "direction");
  const dms = rooms.filter((r) => r.kind === "dm");
  const salons = rooms.filter((r) => r.kind === "team");
  const people = [...project.detail.employees].sort((a, b) => {
    const lead = Number(b.roles.includes("lead")) - Number(a.roles.includes("lead"));
    const busy = Number(byId.get(b.id)?.state === "working") - Number(byId.get(a.id)?.state === "working");
    return lead || busy || a.name.localeCompare(b.name);
  });
  const link = (c: Conversation | undefined) => (c ? `#/p/${project.detail.id}/c/${c.id}` : undefined);

  function pick(employeeId: number) {
    const mine = dms.filter((r) => r.members.some((m) => m.id === employeeId));
    if (mine.length === 1 && firstConversation(project!, mine[0])) {
      go(`/p/${project!.detail.id}/c/${firstConversation(project!, mine[0])!.id}`);
      onClose();
      return;
    }
    setNote(mine.length === 0 ? "No direct message yet." : "");
    setExpanded(expanded === employeeId ? null : employeeId);
  }

  // Arrow keys move through the people and rooms; Tab still works the same
  function onKeyDown(e: React.KeyboardEvent) {
    if (e.key !== "ArrowDown" && e.key !== "ArrowUp") return;
    const items = [...(navRef.current?.querySelectorAll<HTMLElement>("[data-nav]") ?? [])];
    const at = items.indexOf(document.activeElement as HTMLElement);
    if (at < 0) return;
    e.preventDefault();
    items[Math.min(Math.max(at + (e.key === "ArrowDown" ? 1 : -1), 0), items.length - 1)]?.focus();
  }

  return (
    <aside className={`team-panel${open ? " open" : ""}`} aria-label="Team" onKeyDown={(e) => e.key === "Escape" && onClose()}>
      <header className="panel-head">
        <ProjectMenu route={route} projects={projects} project={project} bossName={bossName} onNavigate={onClose} />
      </header>
      <nav className="panel-body" ref={navRef} aria-label="People and rooms" onKeyDown={onKeyDown}>
        <div className="section-label" id="people-label">People</div>
        <ul className="panel-list" aria-labelledby="people-label">
          {people.map((e) => {
            const p = byId.get(e.id);
            const isLead = e.roles.includes("lead");
            const state = stateText(p);
            const sub = subtitle(p, project);
            const mine = dms.filter((r) => r.members.some((m) => m.id === e.id));
            const fresh = isLead && direction
              ? roomUnread(project, direction, unread, active)
              : mine.reduce((n, r) => n + roomUnread(project, r, unread, active), 0);
            const label = `${e.name}, ${e.title}, ${state.toLowerCase()}${sub ? `, ${sub.toLowerCase()}` : ""}${isLead ? ", pinned" : ""}`;
            const inner = (
              <>
                <span className="member-avatar">
                  <Avatar name={e.name} size={30} />
                  <span className={`presence presence-${p?.state ?? "idle"}`} aria-hidden="true" />
                </span>
                <span className="member-text">
                  <span className="truncate">{e.name}</span>
                  <span className="member-role truncate">{e.title}</span>
                  <span className={`presence-label presence-label-${p?.state ?? "idle"} truncate`}>
                    {state}{sub ? ` · ${sub}` : ""}
                  </span>
                </span>
                {isLead && pending > 0
                  ? <Badge count={pending} label={`${pending} waiting for you`} />
                  : <Badge count={fresh} label={`${fresh} new messages`} quiet />}
              </>
            );
            const dmActive = mine.some((r) => project.conversations[r.id]?.some((c) => c.id === active));
            const leadActive = isLead && !!direction && !!project.conversations[direction.id]?.some((c) => c.id === active);
            return (
              <li key={e.id}>
                {isLead && direction ? (
                  <a className={`nav-item member${leadActive ? " active" : ""}`} data-nav aria-label={label}
                    aria-current={leadActive ? "page" : undefined}
                    href={link(firstConversation(project, direction))} onClick={onClose}>{inner}</a>
                ) : (
                  <button className={`nav-item member${dmActive ? " active" : ""}`} data-nav aria-label={label}
                    aria-expanded={mine.length > 1 ? expanded === e.id : undefined} onClick={() => pick(e.id)}>{inner}</button>
                )}
                {expanded === e.id && mine.length > 1 && (
                  <ul className="panel-list dm-list" aria-label={`Direct messages of ${e.name}`}>
                    {mine.map((r) => (
                      <li key={r.id}>
                        <a className={`nav-item nav-sub${project.conversations[r.id]?.some((c) => c.id === active) ? " active" : ""}`}
                          data-nav href={link(firstConversation(project, r))} onClick={onClose}>
                          <span className="truncate">{dmLabel(r)}</span>
                          <Badge count={roomUnread(project, r, unread, active)} label={`${roomUnread(project, r, unread, active)} new messages`} quiet />
                        </a>
                      </li>
                    ))}
                  </ul>
                )}
              </li>
            );
          })}
        </ul>
        <div className="sr-only" role="status" aria-live="polite">{announce}{note ? ` ${note}` : ""}</div>
        {note && <p className="muted panel-note" aria-hidden="true">{note}</p>}

        {salons.length > 0 && (
          <>
            <div className="section-label" id="rooms-label">Rooms</div>
            <ul className="panel-list" aria-labelledby="rooms-label">
              {salons.map((room) => {
                const isActive = !!project.conversations[room.id]?.some((c) => c.id === active);
                const fresh = roomUnread(project, room, unread, active);
                return (
                  <li key={room.id}>
                    <a className={`nav-item${isActive ? " active" : ""}`} data-nav aria-current={isActive ? "page" : undefined}
                      href={link(firstConversation(project, room))} onClick={onClose}>
                      <HashIcon size={15} /> <span className="truncate">{room.name}</span>
                      <Badge count={fresh} label={`${fresh} new messages`} quiet />
                    </a>
                  </li>
                );
              })}
            </ul>
          </>
        )}
      </nav>
    </aside>
  );
}
