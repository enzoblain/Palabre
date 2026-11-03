import type { ProjectListItem } from "../api";
import { useI18n } from "../i18n";
import { go } from "../router";
import { PlusIcon } from "./Icons";
import { ProjectList } from "./ProjectList";
import { DeleteSelection, EditToggle, useProjectsEditing } from "./ProjectsEditing";

export function Projects({ projects, onDeleted }: { projects: ProjectListItem[]; onDeleted: (ids: number[]) => void }) {
  const { t } = useI18n();
  const editing = useProjectsEditing(onDeleted);
  if (projects.length === 0) {
    return (
      <div className="home">
        <button className="big-plus" onClick={() => go("/new")} aria-label={t("home.newProjectAria")}>
          <PlusIcon size={44} />
        </button>
        <p className="home-caption">{t("home.firstProject")}</p>
      </div>
    );
  }
  return (
    <div className="page">
      <div className="projects-head">
        <EditToggle state={editing} />
        <h1>{t("projects.title")}</h1>
      </div>
      <ProjectList projects={projects} editing={editing.editing} checkedIds={editing.checkedIds}
        onToggle={editing.toggle} />
      {editing.editing && <DeleteSelection state={editing} />}
    </div>
  );
}
