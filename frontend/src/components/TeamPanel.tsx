import { useEffect, useRef, useState } from "react";
import type { Conversation, Presence, Project, ProjectDetail } from "../api";
import type { Route } from "../router";
import { Avatar } from "./Avatar";
import { DocumentIcon, GearIcon, PlusIcon } from "./Icons";

export type ProjectState = { detail: ProjectDetail; conversations: Record<number, Conversation[]> };

/** Button with the project's name; opens the menu to switch project or reach the settings. */
export function ProjectMenu({ route, projects, project, bossName, onNavigate, asTitle }: {
  route: Route;
  projects: Project[];
  project: ProjectState | null;
  bossName: string;
  onNavigate?: () => void;
  // The button is the page title (the conversation header), so it sits in the heading
  asTitle?: boolean;
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

  const button = (
    <button ref={buttonRef} className="project-menu-btn" aria-haspopup="menu" aria-expanded={open}
      aria-label={`${name}: switch project or open settings`} onClick={() => setOpen(!open)}>
      <span className="project-initial" aria-hidden="true">{name.slice(0, 1).toUpperCase()}</span>
      <span className="truncate">{name}</span>
      <span className="caret" aria-hidden="true">▾</span>
    </button>
  );

  return (
    <div className={`project-menu${asTitle ? " as-title" : ""}`} ref={rootRef} onKeyDown={onKeyDown}>
      {asTitle ? <h1>{button}</h1> : button}
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

const stateText = (p: Presence | undefined) => (p?.state === "working" ? "Busy" : "Available");

/** The right-hand "Team" column: who is there and whether they are busy. Fixed at 280px, a drawer on small screens. */
export function TeamPanel({ project, presence, open, onClose }: {
  project: ProjectState | null;
  presence: Presence[];
  open: boolean;
  onClose: () => void;
}) {
  const [announce, setAnnounce] = useState("");
  const previous = useRef<Map<number, string> | null>(null);

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
    setAnnounce("");
  }, [project?.detail.id]);

  const byId = new Map(presence.map((p) => [p.employee_id, p]));
  const people = [...(project?.detail.employees ?? [])].sort((a, b) => {
    const lead = Number(b.roles.includes("lead")) - Number(a.roles.includes("lead"));
    const busy = Number(byId.get(b.id)?.state === "working") - Number(byId.get(a.id)?.state === "working");
    return lead || busy || a.name.localeCompare(b.name);
  });

  return (
    <aside className={`team-panel${open ? " open" : ""}`} aria-label="Team" onKeyDown={(e) => e.key === "Escape" && onClose()}>
      <header className="panel-head">
        <h2 className="panel-title" id="people-label">Team</h2>
        <button className="icon-btn panel-close" onClick={onClose} aria-label="Close the team panel">×</button>
      </header>
      {!project ? <p className="muted panel-empty">Loading…</p> : (
        <div className="panel-body">
          <ul className="panel-list" aria-labelledby="people-label">
            {people.map((e) => {
              const p = byId.get(e.id);
              const state = stateText(p);
              const task = p?.state === "working" && p.kind === "task" && p.task_id ? `Task #${p.task_id}` : null;
              return (
                <li key={e.id} className="person member"
                  aria-label={`${e.name}, ${e.title}, ${state.toLowerCase()}${task ? `, ${task.toLowerCase()}` : ""}`}>
                  <span className="member-avatar">
                    <Avatar name={e.name} size={30} />
                    <span className={`presence presence-${p?.state ?? "idle"}`} aria-hidden="true" />
                  </span>
                  <span className="member-text" aria-hidden="true">
                    <span className="truncate">{e.name}</span>
                    <span className="member-role truncate">{e.title}</span>
                    <span className={`presence-label presence-label-${p?.state ?? "idle"} truncate`}>
                      {state}{task ? ` · ${task}` : ""}
                    </span>
                  </span>
                </li>
              );
            })}
          </ul>
          <div className="sr-only" role="status" aria-live="polite">{announce}</div>
        </div>
      )}
    </aside>
  );
}
