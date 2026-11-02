import type { ProjectListItem } from "../api";
import { useI18n } from "../i18n";
import { go } from "../router";
import { PlusIcon } from "./Icons";
import { ProjectList } from "./ProjectList";

export function Projects({ projects }: { projects: ProjectListItem[] }) {
  const { t } = useI18n();
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
      <h1>{t("projects.title")}</h1>
      <ProjectList projects={projects} />
    </div>
  );
}
