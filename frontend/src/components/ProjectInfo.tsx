import type { ProjectState } from "./TeamPanel";
import { useI18n } from "../i18n";
import { goBack } from "../router";
import { Avatar } from "./Avatar";
import { BackIcon } from "./Icons";

/** Header of a project screen: back arrow, name, and an optional action on the right. */
export function ProjectBar({ name, onBack, children }: {
  name: string;
  // Absent on large screens, where the project list stays on screen
  onBack?: () => void;
  children?: React.ReactNode;
}) {
  const { t } = useI18n();
  return (
    <header className="project-bar">
      {onBack ? (
        <button className="icon-btn" onClick={onBack} aria-label={t("common.back")}><BackIcon size={22} /></button>
      ) : <span />}
      <h1 className="project-bar-title truncate">{name}</h1>
      <span className="project-bar-end">{children}</span>
    </header>
  );
}

/** Own page of a project: description, git link and the whole team (first name, role). */
export function ProjectInfo({ project }: { project: ProjectState | null }) {
  const { t } = useI18n();
  if (!project) return <p className="muted center">{t("common.loading")}</p>;
  const { detail } = project;
  // The boss's objective for the project lives on the direction room
  const description = (detail.rooms.find((r) => r.kind === "direction") ?? detail.rooms[0])?.objective.trim();
  const members = [...detail.employees].sort((a, b) => a.name.localeCompare(b.name));
  return (
    <>
      <ProjectBar name={detail.name} onBack={() => goBack(`/p/${detail.id}`)} />
      <div className="page project-info">
        <section aria-labelledby="info-description">
          <h2 className="section-label" id="info-description">{t("info.description")}</h2>
          <p className={description ? "info-description" : "muted"}>{description || t("info.noDescription")}</p>
        </section>
        <section aria-labelledby="info-git">
          <h2 className="section-label" id="info-git">{t("info.git")}</h2>
          {detail.repo_url ? (
            <a href={detail.repo_url} target="_blank" rel="noopener noreferrer" className="info-link">{detail.repo_url}</a>
          ) : <p className="muted">{t("info.noGit")}</p>}
        </section>
        <section aria-labelledby="info-members">
          <h2 className="section-label" id="info-members">{t("info.members")}</h2>
          <ul className="panel-list">
            {members.map((e) => (
              <li key={e.id} className="person member">
                <Avatar name={e.name} size={34} />
                <span className="member-text">
                  <span className="truncate">{e.name}</span>
                  <span className="member-role truncate">{e.title}</span>
                </span>
              </li>
            ))}
          </ul>
        </section>
      </div>
    </>
  );
}
