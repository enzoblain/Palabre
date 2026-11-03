import { useEffect, useRef } from "react";
import type { Employee } from "../api";
import { useI18n } from "../i18n";
import { Avatar } from "./Avatar";

/** The right-hand team column of a conversation on large screens. Takes the focus when it opens. */
export function ConversationTeam({ employees, onClose }: { employees: Employee[]; onClose: () => void }) {
  const { t } = useI18n();
  const panelRef = useRef<HTMLElement>(null);

  useEffect(() => panelRef.current?.focus(), []);

  return (
    <aside ref={panelRef} id="conv-team" className="conv-team" tabIndex={-1} aria-label={t("team.title")}
      onKeyDown={(e) => {
        if (e.key !== "Escape") return;
        e.stopPropagation();
        onClose();
      }}>
      <h2 className="section-label" id="conv-team-label">{t("team.title")}</h2>
      <ul className="panel-list" aria-labelledby="conv-team-label">
        {sortedPeople(employees).map((e) => (
          <li key={e.id} className="person member">
            <Avatar name={e.name} size={30} />
            <span className="member-text">
              <span className="truncate">{e.name}</span>
              <span className="member-role truncate">{e.title}</span>
            </span>
          </li>
        ))}
      </ul>
    </aside>
  );
}

/** The lead first, then the others by name. */
export function sortedPeople(employees: Employee[]): Employee[] {
  return [...employees].sort((a, b) => {
    const lead = Number(b.roles.includes("lead")) - Number(a.roles.includes("lead"));
    return lead || a.name.localeCompare(b.name);
  });
}
