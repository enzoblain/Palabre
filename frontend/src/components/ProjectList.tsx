import type { ProjectListItem } from "../api";
import { useI18n } from "../i18n";
import { go } from "../router";
import { Avatar } from "./Avatar";

export type ProjectListProps = {
  projects: ProjectListItem[];
  /** Project currently open, highlighted in the list */
  selectedId?: number | null;
  onSelect?: (project: ProjectListItem) => void;
  /** Edit mode: rows slide right to show a checkbox, and a click ticks the project instead of opening it */
  editing?: boolean;
  checkedIds?: ReadonlySet<number>;
  onToggle?: (project: ProjectListItem) => void;
};

/** Projects with their unread count and a one-line preview of the latest message. */
export function ProjectList({ projects, selectedId = null, onSelect, editing = false, checkedIds, onToggle }: ProjectListProps) {
  const { t } = useI18n();
  return (
    <ul className={`project-list${editing ? " editing" : ""}`} aria-label={t("projects.title")}>
      {projects.map((p) => {
        const open = () => (editing ? onToggle?.(p) : onSelect ? onSelect(p) : go(`/p/${p.id}`));
        return (
          <li key={p.id}>
            <input type="checkbox" className="project-check" checked={checkedIds?.has(p.id) ?? false}
              disabled={!editing} tabIndex={editing ? 0 : -1} onChange={() => onToggle?.(p)}
              aria-label={t("projects.select", { name: p.name })} />
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
