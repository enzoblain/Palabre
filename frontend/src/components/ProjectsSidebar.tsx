import type { ProjectListItem } from "../api";
import { useI18n } from "../i18n";
import type { Route } from "../router";
import { GearIcon, PlusIcon } from "./Icons";
import { ProjectList } from "./ProjectList";

/** Left column of the large-screen layout: new project and settings on top, then the projects. */
export function ProjectsSidebar({ projects, route, selectedId }: {
  projects: ProjectListItem[];
  route: Route;
  selectedId: number | null;
}) {
  const { t } = useI18n();
  const actions = [
    { name: "new", href: "#/new", label: "nav.newProject", Icon: PlusIcon },
    { name: "settings", href: "#/settings", label: "nav.settings", Icon: GearIcon },
  ] as const;
  return (
    <aside className="projects-sidebar" aria-label={t("nav.projects")}>
      <header className="sidebar-head">
        <h1 className="sidebar-heading">{t("projects.title")}</h1>
        <nav className="sidebar-actions" aria-label={t("nav.label")}>
          {actions.map(({ name, href, label, Icon }) => (
            <a key={name} href={href} className={`icon-btn${route.name === name ? " active" : ""}`}
              aria-label={t(label)} title={t(label)} aria-current={route.name === name ? "page" : undefined}>
              <Icon size={20} />
            </a>
          ))}
        </nav>
      </header>
      <div className="sidebar-body">
        {projects.length === 0
          ? <p className="muted panel-note">{t("home.firstProject")}</p>
          : <ProjectList projects={projects} selectedId={selectedId} />}
      </div>
    </aside>
  );
}
