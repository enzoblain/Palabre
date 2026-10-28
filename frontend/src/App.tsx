import { useCallback, useEffect, useState } from "react";
import { type AppSettings, type Connection, type EmployeeStatus, type Project, api, getConnection, saveConnection, setUnauthorizedHandler } from "./api";
import { Connect } from "./components/Connect";
import { ConversationView } from "./components/ConversationView";
import { Home } from "./components/Home";
import { NewProject } from "./components/NewProject";
import { Settings } from "./components/Settings";
import { type ProjectState, Sidebar } from "./components/Sidebar";
import { go, useRoute } from "./router";
import { usePolling } from "./util";

const STATUS_POLL_MS = 3000;

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

function Shell({ onDisconnect }: { onDisconnect: () => void }) {
  const route = useRoute();
  const [projects, setProjects] = useState<Project[]>([]);
  const [settings, setSettings] = useState<AppSettings>({
    boss_name: "", language: "French", languages: {}, claude_accounts: 1,
  });
  const bossName = settings.boss_name;
  const claudeAccounts = settings.claude_accounts;
  const projectId = route.name === "project" ? route.projectId : null;
  const { project, error } = useProject(projectId);
  const [statuses, setStatuses] = useState<EmployeeStatus[]>([]);

  const reloadProjects = useCallback(() => api.listProjects().then(setProjects).catch(() => {}), []);
  useEffect(() => {
    reloadProjects();
    api.getSettings().then((s) => {
      setSettings(s);
      if (!s.boss_name) go("/settings"); // First time: the team needs a name for its CEO
    }).catch(() => {});
  }, [reloadProjects]);

  useEffect(() => setStatuses([]), [projectId]);
  usePolling(
    projectId === null ? null : async () => {
      const result = await api.teamStatus(projectId);
      setStatuses(result);
    },
    STATUS_POLL_MS,
    [projectId],
  );

  // Opening a project lands in its general channel
  const conversationId = route.name === "project" ? route.conversationId : null;
  useEffect(() => {
    if (route.name === "project" && project && conversationId === null) {
      const first = project.conversations[project.detail.rooms[0]?.id]?.[0];
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
    main = <Settings settings={settings} projects={projects} onSaved={setSettings} onDisconnect={onDisconnect} />;
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
    <div className="shell">
      <Sidebar route={route} projects={projects} project={project} statuses={statuses} bossName={bossName}
        claudeAccounts={claudeAccounts} />
      <main className="main">{main}</main>
    </div>
  );
}
