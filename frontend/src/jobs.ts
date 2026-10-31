import type { Role, RoleCategory } from "./api";

/** Display order of the categories (the server sends the keys). */
const CATEGORIES: RoleCategory[] = ["management", "engineering", "quality", "product", "support", "research"];

/** The team counter warns from this share of the server's agent limit. */
const TEAM_WARNING_RATIO = 0.8;

/** Jobs matching a search, in catalog order, grouped by category (empty groups left out). */
export function groupJobs(roles: Record<string, Role>, search: string): [RoleCategory, Role[]][] {
  const needle = search.trim().toLowerCase();
  const matching = Object.values(roles)
    .filter((role) => !needle || `${role.title} ${role.description}`.toLowerCase().includes(needle))
    .sort((a, b) => a.order - b.order);
  return CATEGORIES.map((category): [RoleCategory, Role[]] => [category, matching.filter((r) => r.category === category)])
    .filter(([, jobs]) => jobs.length > 0);
}

/** Team size from which the counter warns that the limit is close. */
export function teamWarningThreshold(maxAgents: number): number {
  return Math.ceil(maxAgents * TEAM_WARNING_RATIO);
}
