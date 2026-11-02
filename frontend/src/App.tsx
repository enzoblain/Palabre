import { useCallback, useEffect, useState } from "react";
import { type AppSettings, type Connection, type EmployeeStatus, type ExhaustedAccount, type Presence, type Project, api, getConnection, saveConnection, setUnauthorizedHandler } from "./api";
import { Connect } from "./components/Connect";
import { ConversationView } from "./components/ConversationView";
import { ReportView } from "./components/ReportView";
import { Home } from "./components/Home";
import { MenuIcon } from "./components/Icons";
import { NewProject } from "./components/NewProject";
import { Settings } from "./components/Settings";
import { ProjectMenu, type ProjectState, TeamPanel } from "./components/TeamPanel";
import { I18nProvider, useI18n } from "./i18n";
import { go, useRoute } from "./router";
import { formatTime, usePolling } from "./util";

const STATUS_POLL_MS = 3000;
const CREDITS_POLL_MS = 15000;

export default function App() {
  return (
    <I18nProvider>
      <Session />
    </I18nProvider>
  );
}

function Session() {
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
  const { t, language, setLanguage } = useI18n();
  const route = useRoute();
  const [projects, setProjects] = useState<Project[]>([]);
  const [settings, setSettings] = useState<AppSettings>({
    boss_name: "", language, languages: {}, claude_accounts: 1,
  });
  const bossName = settings.boss_name;
  // The whole interface speaks the language set for the team
  useEffect(() => {
    setLanguage(settings.language);
  }, [settings.language, setLanguage]);
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
  } else if (route.name === "report" && project?.detail.kind !== "company") {
    if (error) main = <p className="error center">{error}</p>;
    else if (project) main = <ReportView project={project} />;
    else main = <p className="muted center">{t("common.loading")}</p>;
  } else if (route.name === "project") {
    const room = project?.detail.rooms.find((r) => project.conversations[r.id]?.some((c) => c.id === conversationId));
    const conversation = room && project?.conversations[room.id].find((c) => c.id === conversationId);
    if (error) main = <p className="error center">{error}</p>;
    else if (project && room && conversation) {
      main = <ConversationView conversation={conversation} room={room} project={project.detail}
        projects={projects} route={route} statuses={statuses} bossName={bossName} />;
    } else if (project && conversationId !== null) {
      main = <p className="muted center">{t("app.conversationMissing")}</p>;
    } else {
      main = <p className="muted center">{t("common.loading")}</p>;
    }
  } else {
    main = <Home hasProjects={projects.length > 0} />;
  }

  const inProject = projectId !== null && route.name !== "settings" && route.name !== "new";
  return (
    <div className={`shell${navOpen ? " nav-open" : ""}`}>
      <div className="nav-backdrop" onClick={() => setNavOpen(false)} />
      <TeamPanel project={inProject ? project : null} route={route} noProject={!inProject} presence={presence} open={navOpen}
        onClose={() => setNavOpen(false)} />
      <main className="main">
        {inProject ? (
          <header className="mobile-bar">
            <button className="icon-btn" onClick={() => setNavOpen(true)} aria-label={t("app.openTeam")}
              aria-expanded={navOpen}>
              <MenuIcon />
            </button>
            <span className="sidebar-title truncate">{project?.detail.name ?? "Palabre"}</span>
          </header>
        ) : (
          <header className="topbar">
            <button className="icon-btn topbar-nav" onClick={() => setNavOpen(true)} aria-label={t("app.openTeam")}
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
  const { t } = useI18n();
  return (
    <div className="credits-banner" role="status">
      <strong>{t("credits.title")}</strong>
      <ul>
        {accounts.map((a) => (
          <li key={a.account}>
            {showAccount
              ? t(a.estimated ? "credits.backAroundAccount" : "credits.backAtAccount", { account: a.account, time: formatTime(a.resets_at) })
              : t(a.estimated ? "credits.backAround" : "credits.backAt", { time: formatTime(a.resets_at) })}
          </li>
        ))}
      </ul>
    </div>
  );
}
