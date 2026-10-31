import { useId, useMemo, useState } from "react";
import type { Role, RoleCategory } from "../api";
import { useI18n } from "../i18n";

/** Display order of the categories (the server sends the keys). */
const CATEGORIES: RoleCategory[] = ["management", "engineering", "quality", "product", "support", "research"];

/** Jobs matching a search, in catalog order, grouped by category (empty groups left out). */
export function groupJobs(roles: Record<string, Role>, search: string): [RoleCategory, Role[]][] {
  const needle = search.trim().toLowerCase();
  const matching = Object.values(roles)
    .filter((role) => !needle || `${role.title} ${role.description}`.toLowerCase().includes(needle))
    .sort((a, b) => a.order - b.order);
  return CATEGORIES.map((category): [RoleCategory, Role[]] => [category, matching.filter((r) => r.category === category)])
    .filter(([, jobs]) => jobs.length > 0);
}

function JobCard({ role, selected, onToggle }: { role: Role; selected: boolean; onToggle: () => void }) {
  const { t } = useI18n();
  const [open, setOpen] = useState(false);
  const id = useId();
  const toolCount = role.tools.mcp.length + role.tools.claude.length;
  const lists: [string, string[]][] = [
    [t("jobs.responsibilities"), role.responsibilities],
    [t("jobs.forbidden"), role.forbidden],
    [t("jobs.deliverables"), role.deliverables],
    [t("jobs.toolsMcp"), role.tools.mcp],
    [t("jobs.toolsClaude"), role.tools.claude],
  ];
  return (
    <li className={`job-card${selected ? " selected" : ""}`}>
      <label className="job-head">
        <input type="checkbox" checked={selected} onChange={onToggle} />
        <span className="job-title">{role.title}</span>
        <span className="muted job-model">{role.effort ? `${role.model} · ${role.effort}` : role.model}</span>
      </label>
      <p className="job-description">{role.description}</p>
      <div className="job-foot">
        <span className="muted">{t("jobs.toolsCount", { count: toolCount })}</span>
        <button type="button" className="btn btn-small" aria-expanded={open} aria-controls={id}
          onClick={() => setOpen(!open)}>
          {open ? t("jobs.hideDetails") : t("jobs.showDetails")}
        </button>
      </div>
      {open && (
        <div id={id} className="job-details">
          <p>{role.mission}</p>
          {lists.filter(([, items]) => items.length > 0).map(([label, items]) => (
            <div key={label}>
              <strong>{label}</strong>
              <ul>{items.map((item) => <li key={item}>{item}</li>)}</ul>
            </div>
          ))}
        </div>
      )}
    </li>
  );
}

function CategoryGroup({ category, jobs, selected, forceOpen, onToggle }: {
  category: RoleCategory;
  jobs: Role[];
  selected: string[];
  forceOpen: boolean;
  onToggle: (key: string) => void;
}) {
  const { t } = useI18n();
  const [collapsed, setCollapsed] = useState(false);
  const id = useId();
  const open = forceOpen || !collapsed;
  return (
    <section className="job-group">
      <button type="button" className="job-group-head" aria-expanded={open} aria-controls={id}
        onClick={() => setCollapsed(open)}>
        <span aria-hidden="true">{open ? "▾" : "▸"}</span> {t(`jobs.category.${category}`)} ({jobs.length})
      </button>
      <ul id={id} className="job-list" hidden={!open}>
        {jobs.map((role) => (
          <JobCard key={role.key} role={role} selected={selected.includes(role.key)} onToggle={() => onToggle(role.key)} />
        ))}
      </ul>
    </section>
  );
}

/** Picks the jobs of a member among the catalog's: a member can hold several. */
export function JobPicker({ roles, selected, onChange }: {
  roles: Record<string, Role>;
  selected: string[];
  onChange: (selected: string[]) => void;
}) {
  const { t } = useI18n();
  const [search, setSearch] = useState("");
  const groups = useMemo(() => groupJobs(roles, search), [roles, search]);
  const toggle = (key: string) => onChange(selected.includes(key) ? selected.filter((k) => k !== key) : [...selected, key]);

  return (
    <div className="job-picker">
      <label className="job-search">
        {t("jobs.title")}
        <input type="search" value={search} placeholder={t("jobs.searchPlaceholder")} onChange={(e) => setSearch(e.target.value)} />
      </label>
      {Object.keys(roles).length === 0 && <p className="muted">{t("jobs.none")}</p>}
      {Object.keys(roles).length > 0 && groups.length === 0 && (
        <p className="muted">
          {t("jobs.noMatch", { search })}{" "}
          <button type="button" className="link-btn" onClick={() => setSearch("")}>{t("jobs.clearSearch")}</button>
        </p>
      )}
      {groups.map(([category, jobs]) => (
        <CategoryGroup key={category} category={category} jobs={jobs} selected={selected}
          forceOpen={search.trim() !== ""} onToggle={toggle} />
      ))}
    </div>
  );
}
