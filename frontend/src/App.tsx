import { useCallback, useEffect, useRef, useState } from "react";
import { type AppSettings, type Connection, type EmployeeStatus, type Project, api, getConnection, saveConnection, setUnauthorizedHandler } from "./api";
import { Connect } from "./components/Connect";
import { ConversationView } from "./components/ConversationView";
import { DocumentView } from "./components/DocumentView";
import { Home } from "./components/Home";
import { MenuIcon } from "./components/Icons";
import { NewProject } from "./components/NewProject";
import { Settings } from "./components/Settings";
import { type ProjectState, Sidebar } from "./components/Sidebar";
import { go, useRoute } from "./router";
import { usePolling } from "./util";

const STATUS_POLL_MS = 3000;
const PENDING_POLL_MS = 4000;

export default function App() {
  const [conn, setConn] = useState<Connection | null>(getConnection);
  const disconnect = useCallback(() => {
    saveConnection(null);
    setConn(null);
  }, []);
  useEffect(() => setUnauthorizedHandler(disconnect), [disconnect]);

  if (!conn) {
    return (
      <Connect onConnected={(c) => {
        saveConnection(c);
        setConn(c);
      }} />
    );
  }
  return <Shell key={conn.server} onDisconnect={disconnect} />;
}

function useProject(projectId: number | null) {
  const [project, setProject] = useState<ProjectState | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    setProject(null);
    setError(null);
    if (projectId === null) return;
    let cancelled = false;
    (async () => {
      const detail = await api.getProject(projectId);
      const lists = await Promise.all(detail.rooms.map((r) => api.listConversations(r.id)));
      if (!cancelled) {
        setProject({ detail, conversations: Object.fromEntries(detail.rooms.map((r, i) => [r.id, lists[i]])) });
      }
    })().catch((err) => !cancelled && setError(String(err.message ?? err)));
    return () => {
      cancelled = true;
    };
  }, [projectId]);
  // Until the effect above has run, `project` may still be the one we just left
  return { project: project?.detail.id === projectId ? project : null, error };
}

const UNREAD_POLL_MS = 4000;
const seenKey = (conversationId: number) => `palabre.seen.${conversationId}`;

/** Unread messages per direction conversation since the CEO's last visit; the open conversation is always read.
 * Team channels get no count: the CEO only follows them, and the live dot is enough there. */
function useUnread(project: ProjectState | null, activeConversation: number | null) {
  const [unread, setUnread] = useState<Record<number, number>>({});
  // Per conversation: last message id fetched, last id the CEO saw, and ids of unseen messages from others
  const state = useRef<Record<number, { last: number; seen: number | null; fresh: number[] }>>({});
  const activeRef = useRef(activeConversation);
  activeRef.current = activeConversation;
  const projectId = project?.detail.id;
  useEffect(() => {
    state.current = {};
    setUnread({});
  }, [projectId]);
  const publish = () =>
    setUnread(Object.fromEntries(Object.entries(state.current).map(([id, s]) => [id, s.fresh.length])));
  const markRead = (id: number) => {
    const s = state.current[id];
    if (!s) return;
    s.fresh = [];
    s.seen = s.last;
    localStorage.setItem(seenKey(id), String(s.last));
  };
  useEffect(() => {
    if (activeConversation === null) return;
    markRead(activeConversation);
    publish();
  }, [activeConversation]);
  const conversations = project
    ? project.detail.rooms.filter((r) => r.kind === "direction").flatMap((r) => project.conversations[r.id] ?? [])
    : [];
  usePolling(
    project ? async () => {
      await Promise.all(conversations.map(async (c) => {
        const s = (state.current[c.id] ??= {
          last: 0,
          seen: localStorage.getItem(seenKey(c.id)) === null ? null : Number(localStorage.getItem(seenKey(c.id))),
          fresh: [],
        });
        const messages = await api.listMessages(c.id, s.last || undefined);
        for (const m of messages) {
          s.last = Math.max(s.last, m.id);
          // Messages written by the CEO themself (no employee) are never unread
          if (m.employee_id !== null && (s.seen === null || m.id > s.seen) && !s.fresh.includes(m.id)) s.fresh.push(m.id);
        }
        // First visit ever: start from a clean slate rather than flag the whole history
        if (s.seen === null) {
          s.fresh = [];
          s.seen = s.last;
          localStorage.setItem(seenKey(c.id), String(s.last));
        }
        if (c.id === activeRef.current) markRead(c.id);
      }));
      publish();
    } : null,
    UNREAD_POLL_MS,
    [projectId],
  );
  return unread;
}

function Shell({ onDisconnect }: { onDisconnect: () => void }) {
  const route = useRoute();
  const [projects, setProjects] = useState<Project[]>([]);
  const [settings, setSettings] = useState<AppSettings>({
    boss_name: "", language: "French", languages: {}, claude_accounts: 1,
  });
  const bossName = settings.boss_name;
  const claudeAccounts = settings.claude_accounts;
  const projectId = "projectId" in route ? route.projectId : null;
  const { project, error } = useProject(projectId);
  const [statuses, setStatuses] = useState<EmployeeStatus[]>([]);
  // Small screens: the sidebar slides over the page, and closes once a link is followed
  const [navOpen, setNavOpen] = useState(false);
  useEffect(() => setNavOpen(false), [route]);

  const reloadProjects = useCallback(() => api.listProjects().then(setProjects).catch(() => {}), []);
  useEffect(() => {
    reloadProjects();
    api.getSettings().then((s) => {
      setSettings(s);
      if (!s.boss_name) go("/settings"); // First time: the team needs a name for its CEO
    }).catch(() => {});
  }, [reloadProjects]);

  // Requests of the lead still waiting for the CEO, in the direction channel (badge in the sidebar)
  const [pending, setPending] = useState(0);
  const direction = project?.detail.rooms.find((r) => r.kind === "direction");
  const directionConversation = direction && project?.conversations[direction.id]?.[0]?.id;
  useEffect(() => setPending(0), [projectId]);
  usePolling(
    directionConversation ? async () => {
      const messages = await api.listMessages(directionConversation);
      setPending(messages.filter((m) => m.request_status === "pending").length);
    } : null,
    PENDING_POLL_MS,
    [directionConversation],
  );

  useEffect(() => setStatuses([]), [projectId]);
  usePolling(
    projectId === null ? null : async () => {
      const result = await api.teamStatus(projectId);
      setStatuses(result);
    },
    STATUS_POLL_MS,
    [projectId],
  );

  const unread = useUnread(project, route.name === "project" ? route.conversationId : null);

  // Opening a project lands in the direction channel, where the CEO talks to the lead
  const conversationId = route.name === "project" ? route.conversationId : null;
  useEffect(() => {
    if (route.name === "project" && project && conversationId === null) {
      const home = project.detail.rooms.find((r) => r.kind === "direction") ?? project.detail.rooms[0];
      const first = project.conversations[home?.id]?.[0];
      if (first) go(`/p/${project.detail.id}/c/${first.id}`, true);
    }
  }, [route.name, project, conversationId]);

  let main: React.ReactNode;
  if (route.name === "new") {
    main = <NewProject claudeAccounts={claudeAccounts} onCreated={(p) => {
      reloadProjects();
      go(`/p/${p.id}`);
    }} />;
  } else if (route.name === "settings") {
    main = <Settings settings={settings} projects={projects} onSaved={setSettings}
      onProjectsChanged={reloadProjects} onDisconnect={onDisconnect} />;
  } else if (route.name === "report") {
    if (error) main = <p className="error center">{error}</p>;
    else if (project) main = <DocumentView project={project} />;
    else main = <p className="muted center">Loading…</p>;
  } else if (route.name === "project") {
    const room = project?.detail.rooms.find((r) => project.conversations[r.id]?.some((c) => c.id === conversationId));
    const conversation = room && project?.conversations[room.id].find((c) => c.id === conversationId);
    if (error) main = <p className="error center">{error}</p>;
    else if (project && room && conversation) {
      main = <ConversationView conversation={conversation} room={room} project={project.detail}
        statuses={statuses} bossName={bossName} />;
    } else if (project && conversationId !== null) {
      main = <p className="muted center">This conversation does not exist.</p>;
    } else {
      main = <p className="muted center">Loading…</p>;
    }
  } else {
    main = <Home hasProjects={projects.length > 0} />;
  }

  return (
    <div className={navOpen ? "shell nav-open" : "shell"}>
      <header className="mobile-bar">
        <button className="icon-btn" onClick={() => setNavOpen(true)} aria-label="Menu">
          <MenuIcon />
        </button>
        <span className="sidebar-title truncate">{project?.detail.name ?? "Palabre"}</span>
        {pending > 0 && <span className="badge-count urgent" aria-label={`${pending} waiting for you`}>{pending}</span>}
      </header>
      <Sidebar route={route} projects={projects} project={project} statuses={statuses} bossName={bossName}
        claudeAccounts={claudeAccounts} pending={pending} unread={unread} />
      <div className="nav-backdrop" onClick={() => setNavOpen(false)} />
      <main className="main">{main}</main>
    </div>
  );
}
