import type { ProjectListItem } from "../api";
import { useI18n } from "../i18n";
import { go } from "../router";
import { Avatar } from "./Avatar";

export type ProjectListProps = {
  projects: ProjectListItem[];
  /** Project currently open, highlighted in the list */
  selectedId?: number | null;
  onSelect?: (project: ProjectListItem) => void;
};

/** Projects with their unread count and a one-line preview of the latest message. */
export function ProjectList({ projects, selectedId = null, onSelect }: ProjectListProps) {
  const { t } = useI18n();
  return (
    <ul className="project-list" aria-label={t("projects.title")}>
      {projects.map((p) => {
        const open = () => (onSelect ? onSelect(p) : go(`/p/${p.id}`));
        return (
          <li key={p.id}>
            <a href={`#/p/${p.id}`} className={`project-row${p.id === selectedId ? " active" : ""}`}
              aria-current={p.id === selectedId ? "page" : undefined}
              onClick={(e) => { e.preventDefault(); open(); }}>
              <Avatar name={p.name} />
              <span className="project-row-text">
                <span className="project-row-name truncate">{p.name}</span>
                {p.last_message && (
                  // Rendered as plain text (React escapes it), cut to one line by CSS
                  <span className="project-row-preview truncate">{p.last_message.content}</span>
                )}
              </span>
              {p.unread_count > 0 && (
                <span className="unread-badge" aria-label={t("projects.unread", { count: p.unread_count })}>
                  {p.unread_count}
                </span>
              )}
            </a>
          </li>
        );
      })}
    </ul>
  );
}
