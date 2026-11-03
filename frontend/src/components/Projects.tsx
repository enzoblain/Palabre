import { useState } from "react";
import type { ProjectListItem } from "../api";
import { useI18n } from "../i18n";
import { PROJECT_SEARCH_MIN_COUNT, filterProjects, lastOpenedFirst, readLastOpenedProject } from "../navigation";
import { go } from "../router";
import { ProjectList } from "./ProjectList";
import { DeleteSelection, EditToggle, useProjectsEditing } from "./ProjectsEditing";

const SKELETON_ROWS = 3;

export type ProjectsStatus = "loading" | "ready" | "error";

export function Projects({ projects, status, onRetry, onDeleted }: {
  projects: ProjectListItem[];
  status: ProjectsStatus;
  onRetry: () => void;
  onDeleted: (ids: number[]) => void;
}) {
  const { t } = useI18n();
  const editing = useProjectsEditing(onDeleted);
  const [search, setSearch] = useState("");
  const shown = filterProjects(lastOpenedFirst(projects, readLastOpenedProject()), search);

  let body: React.ReactNode;
  if (status === "loading") {
    body = (
      <div aria-busy="true" aria-label={t("common.loading")}>
        {Array.from({ length: SKELETON_ROWS }, (_, i) => <div key={i} className="project-skeleton" />)}
      </div>
    );
  } else if (status === "error") {
    body = (
      <div className="projects-state" role="alert">
        <p>{t("projects.loadError")}</p>
        <button onClick={onRetry}>{t("common.retry")}</button>
      </div>
    );
  } else if (projects.length === 0) {
    body = (
      <div className="projects-state">
        <p className="muted">{t("projects.empty")}</p>
        <button onClick={() => go("/new")}>{t("projects.create")}</button>
      </div>
    );
  } else if (shown.length === 0) {
    body = <p className="muted" role="status">{t("projects.noMatch", { search: search.trim() })}</p>;
  } else {
    body = <ProjectList projects={shown} editing={editing.editing} checkedIds={editing.checkedIds}
      onToggle={editing.toggle} />;
  }

  return (
    <div className="page">
      <div className="projects-head">
        {status === "ready" && projects.length > 0 && <EditToggle state={editing} />}
        <h1>{t("projects.title")}</h1>
      </div>
      {projects.length > PROJECT_SEARCH_MIN_COUNT && (
        <input type="search" value={search} onChange={(e) => setSearch(e.target.value)}
          placeholder={t("projects.search")} aria-label={t("projects.search")} />
      )}
      {body}
      {editing.editing && <DeleteSelection state={editing} />}
    </div>
  );
}
