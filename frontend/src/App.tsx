import { useCallback, useEffect, useRef, useState } from "react";
import { type AppSettings, type Connection, type EmployeeStatus, type ExhaustedAccount, type Presence, type Project, api, getConnection, saveConnection, setUnauthorizedHandler } from "./api";
import { Connect } from "./components/Connect";
import { ConversationView } from "./components/ConversationView";
import { DocumentView } from "./components/DocumentView";
import { Home } from "./components/Home";
import { MenuIcon } from "./components/Icons";
import { NewProject } from "./components/NewProject";
import { Settings } from "./components/Settings";
import { ProjectMenu, type ProjectState, TeamPanel } from "./components/TeamPanel";
import { go, useRoute } from "./router";
import { formatTime, usePolling } from "./util";

const STATUS_POLL_MS = 3000;
const PENDING_POLL_MS = 4000;
const CREDITS_POLL_MS = 15000;

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

/** Unread messages in the direction conversation since the CEO's last visit; the open conversation is always read. */
function useUnread(project: ProjectState | null, directionId: number | null, activeConversation: number | null) {
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
  usePolling(
    project && directionId ? async () => {
      // One call for the whole project; only the direction conversation is followed
      for (const item of (await api.unreadSummary(project.detail.id)).filter((i) => i.conversation_id === directionId)) {
        try {
          const id = item.conversation_id;
          const stored = localStorage.getItem(seenKey(id));
          const s = (state.current[id] ??= {
            last: stored === null ? 0 : Number(stored),
            seen: stored === null ? null : Number(stored),
            fresh: [],
          });
          if (id === activeRef.current) {
            s.last = Math.max(s.last, item.last_id);
            markRead(id);
            continue;
          }
          if (s.seen === null) {
            // First visit ever: start from a clean slate rather than flag the whole history
            s.last = item.last_id;
            markRead(id);
            continue;
          }
          if (item.last_employee_message_id <= s.last) {
            s.last = Math.max(s.last, item.last_id);
            continue;
          }
          const messages = await api.listMessages(id, s.last);
          for (const m of messages) {
            s.last = Math.max(s.last, m.id);
            // Messages written by the CEO themself (no employee) are never unread
            if (m.employee_id !== null && m.id > s.seen && !s.fresh.includes(m.id)) s.fresh.push(m.id);
          }
        } catch {
          // A failing conversation must not stop the others; it is retried at the next tick
        }
      }
      publish();
    } : null,
    UNREAD_POLL_MS,
    [projectId, directionId],
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
  // Small screens: the team panel is a drawer over the page, and closes once a link is followed
  const [navOpen, setNavOpen] = useState(false);
  const [presence, setPresence] = useState<Presence[]>([]);
  useEffect(() => setNavOpen(false), [route]);

  const reloadProjects = useCallback(() => api.listProjects().then(setProjects).catch(() => {}), []);
  useEffect(() => {
    reloadProjects();
    api.getSettings().then((s) => {
      setSettings(s);
      if (!s.boss_name) go("/settings"); // First time: the team needs a name for its CEO
    }).catch(() => {});
  }, [reloadProjects]);

  // Requests of the lead still waiting for the CEO, in the direction channel (badge in the mobile bar)
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

  useEffect(() => setPresence([]), [projectId]);
  usePolling(
    projectId === null ? null : async () => {
      const result = await api.presence(projectId);
      setPresence(result);
    },
    STATUS_POLL_MS,
    [projectId],
  );

  // Claude accounts out of credits: the whole team is paused until they come back
  const [exhausted, setExhausted] = useState<ExhaustedAccount[]>([]);
  usePolling(async () => {
    setExhausted((await api.orchestratorStatus()).exhausted_accounts);
  }, CREDITS_POLL_MS, []);

  const unread = useUnread(project, directionConversation || null, route.name === "project" ? route.conversationId : null);
  const unreadCount = Object.values(unread).reduce((n, c) => n + c, 0);

  // Opening a project lands in the conversation with the lead
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
        projects={projects} route={route} statuses={statuses} bossName={bossName} />;
    } else if (project && conversationId !== null) {
      main = <p className="muted center">This conversation does not exist.</p>;
    } else {
      main = <p className="muted center">Loading…</p>;
    }
  } else {
    main = <Home hasProjects={projects.length > 0} />;
  }

  const inProject = projectId !== null && route.name !== "settings" && route.name !== "new";
  return (
    <div className={`shell${navOpen ? " nav-open" : ""}`}>
      <div className="nav-backdrop" onClick={() => setNavOpen(false)} />
      <TeamPanel project={inProject ? project : null} noProject={!inProject} presence={presence} open={navOpen}
        onClose={() => setNavOpen(false)} />
      <main className="main">
        {inProject ? (
          <header className="mobile-bar">
            <button className="icon-btn" onClick={() => setNavOpen(true)} aria-label="Ouvrir le panneau Équipe"
              aria-expanded={navOpen}>
              <MenuIcon />
            </button>
            <span className="sidebar-title truncate">{project?.detail.name ?? "Palabre"}</span>
            {pending > 0
              ? <span className="badge-count urgent" aria-label={`${pending} en attente de réponse`}>{pending}</span>
              : unreadCount > 0 && <span className="badge-count" aria-label={`${unreadCount} nouveaux messages`}>{unreadCount}</span>}
          </header>
        ) : (
          <header className="topbar">
            <button className="icon-btn topbar-nav" onClick={() => setNavOpen(true)} aria-label="Ouvrir le panneau Équipe"
              aria-expanded={navOpen}>
              <MenuIcon />
            </button>
            <ProjectMenu route={route} projects={projects} project={null} />
          </header>
        )}
        {inProject && route.name === "report" && (
          <header className="topbar report-bar">
            <ProjectMenu route={route} projects={projects} project={project} />
          </header>
        )}
        {exhausted.length > 0 && <CreditsBanner accounts={exhausted} showAccount={claudeAccounts > 1} />}
        {main}
      </main>
    </div>
  );
}

function CreditsBanner({ accounts, showAccount }: { accounts: ExhaustedAccount[]; showAccount: boolean }) {
  return (
    <div className="credits-banner" role="status">
      <strong>Claude credits exhausted, the team is paused.</strong>
      <ul>
        {accounts.map((a) => (
          <li key={a.account}>
            {showAccount && `Account ${a.account}: `}back {a.estimated ? "around " : "at "}{formatTime(a.resets_at)}
          </li>
        ))}
      </ul>
    </div>
  );
}
