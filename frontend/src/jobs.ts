import type { CoreCategory, ExtendedCategory, Role, RoleCategory } from "./api";

/** The historic roles' categories come first, so they stay at the top of the list. */
const CORE_CATEGORIES: CoreCategory[] = ["management", "engineering", "quality", "product", "support", "research"];

/** Display order of the extended categories (the server sends the keys). */
const EXTENDED_CATEGORIES: ExtendedCategory[] = [
  "direction_strategy", "architecture", "software_development", "artificial_intelligence", "data_databases",
  "cybersecurity", "cloud_devops_infrastructure", "networks_telecom", "blockchain_web3", "quality_testing",
  "performance_reliability", "product_project_management", "ux_ui_design", "iot_robotics_embedded",
  "games_3d_multimedia", "advanced_research", "ecommerce_fintech_business", "support_operations",
  "technical_documentation", "specialized_roles",
];

const CATEGORIES: RoleCategory[] = [...CORE_CATEGORIES, ...EXTENDED_CATEGORIES];

/** The team counter warns from this share of the server's agent limit. */
const TEAM_WARNING_RATIO = 0.8;

/** Jobs whose name matches a search, in catalog order, grouped by category (empty groups left out). */
export function groupJobs(roles: Record<string, Role>, search: string): [RoleCategory, Role[]][] {
  const needle = search.trim().toLowerCase();
  const matching = Object.values(roles)
    .filter((role) => !needle || role.title.toLowerCase().includes(needle))
    .sort((a, b) => a.order - b.order);
  return CATEGORIES.map((category): [RoleCategory, Role[]] => [category, matching.filter((r) => r.category === category)])
    .filter(([, jobs]) => jobs.length > 0);
}

/** Team size from which the counter warns that the limit is close. */
export function teamWarningThreshold(maxAgents: number): number {
  return Math.ceil(maxAgents * TEAM_WARNING_RATIO);
}

/** A company needs at least this many members, the lead included (MIN_AUTO_TEAM_SIZE on the server). */
export const MIN_COMPANY_TEAM_SIZE = 4;

/** Whether a team of this size is below the minimum. */
export function isTeamTooSmall(size: number, minSize: number): boolean {
  return size < minSize;
}
