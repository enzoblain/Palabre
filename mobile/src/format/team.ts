import { translate } from "../i18n";
import type { CatalogLimits, CoreCategory, ExtendedCategory, MemberIn, PersonalityPreset, Role, RoleCategory } from "../api";

/** Value of the "Random" personality: no preset, the server draws one. */
export const RANDOM_PRESET = "random";

/** The historic roles' categories come first, so they stay at the top of the list. */
const CORE_CATEGORIES: CoreCategory[] = ["management", "engineering", "quality", "product", "support"];

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

export const PROJECT_NAME_MAX_LENGTH = 200;
export const DESCRIPTION_MAX_LENGTH = 10000;
export const MEMBER_NAME_MAX_LENGTH = 40;

const GITHUB_URL = /^(https:\/\/github\.com\/|git@github\.com:)[\w.-]+\/[\w.-]+?(\.git)?\/?$/;
const MEMBER_NAME = new RegExp(`^[\\p{L}\\p{N}_-]{1,${MEMBER_NAME_MAX_LENGTH}}$`, "u");

export type TeamProblem = "none" | "tooSmall" | "tooBig" | "noLead" | "duplicate" | "noName" | "badName" | "noRole";

export function isGithubUrl(url: string): boolean {
  return GITHUB_URL.test(url.trim());
}

/** Lowercase text without accents, so that a search for "deterge" finds "Déterminé". */
function normalize(text: string): string {
  return text.normalize("NFD").replace(/\p{M}/gu, "").toLowerCase();
}

/** Presets whose name or description contains every word of the query, sorted by name. */
export function filterPresets(presets: Record<string, PersonalityPreset>, query: string): PersonalityPreset[] {
  const words = normalize(query).split(/\s+/).filter(Boolean);
  return Object.values(presets)
    .filter(({ label, description }) => {
      const haystack = normalize(`${label} ${description}`);
      return words.every((word) => haystack.includes(word));
    })
    .sort((a, b) => a.label.localeCompare(b.label));
}

/** Jobs whose title matches a search, in catalog order, grouped by category (empty groups left out). */
export function groupJobs(roles: Record<string, Role>, search: string): [RoleCategory, Role[]][] {
  const needle = search.trim().toLowerCase();
  const matching = Object.values(roles)
    .filter((role) => !needle || role.title.toLowerCase().includes(needle))
    .sort((a, b) => a.order - b.order);
  return CATEGORIES.map((category): [RoleCategory, Role[]] => [category, matching.filter((role) => role.category === category)])
    .filter(([, jobs]) => jobs.length > 0);
}

/** Team size from which the counter warns that the limit is close. */
export function teamWarningThreshold(maxAgents: number): number {
  return Math.ceil(maxAgents * TEAM_WARNING_RATIO);
}

/** A blank agent, filled in by the boss: no name, no role, and a personality the server draws. */
export function newMember(): MemberIn {
  return { name: "", roles: [], model: null, account: null, personality: null };
}

/** A first name from the catalog nobody in the team has yet ("" when they are all taken). */
export function freeName(names: string[], taken: string[], random: () => number = Math.random): string {
  const free = names.filter((name) => !taken.some((other) => other.toLowerCase() === name.toLowerCase()));
  return free.length ? free[Math.floor(random() * free.length)] : "";
}

/** The member every company starts with: the lead, with a drawn name. */
export function mandatoryMember(names: string[], role: string): MemberIn {
  return { ...newMember(), name: freeName(names, []), roles: [role] };
}

/** What keeps a team from being created (the server checks the same rules); `leadRole` null: none required. */
export function teamProblems(
  members: Pick<MemberIn, "name" | "roles">[], leadRole: string | null, minSize: number, maxSize: number,
): TeamProblem[] {
  const problems: TeamProblem[] = [];
  if (!members.length) problems.push("none");
  else if (members.length < minSize) problems.push("tooSmall");
  else if (members.length > maxSize) problems.push("tooBig");
  if (leadRole && members.length && !members.some((member) => member.roles.includes(leadRole))) problems.push("noLead");
  const names = members.map((member) => member.name.toLowerCase());
  if (new Set(names).size !== names.length) problems.push("duplicate");
  if (members.some((member) => !member.name)) problems.push("noName");
  if (members.some((member) => member.name && !MEMBER_NAME.test(member.name))) problems.push("badName");
  if (members.some((member) => !member.roles.length)) problems.push("noRole");
  return problems;
}

/** Problems of an automatic team, which is only a head count. */
export function autoTeamProblems(employeeCount: number, minSize: number, maxSize: number): TeamProblem[] {
  if (employeeCount < minSize) return ["tooSmall"];
  return employeeCount > maxSize ? ["tooBig"] : [];
}

/** The team limits as the creation form needs them: the server's, or permissive ones while they load. */
export function teamBounds(limits: CatalogLimits | null): { minSize: number; maxSize: number } {
  return { minSize: limits?.min_team_size ?? 1, maxSize: limits?.max_agents ?? Infinity };
}

/** The messages of the problems that keep the team from being created. */
export function problemMessages(problems: TeamProblem[], minSize: number, maxSize: number): string[] {
  const messages: Record<TeamProblem, () => string> = {
    none: () => translate("editor.problemNone"),
    tooSmall: () => translate("editor.problemTooSmall", { min: minSize }),
    tooBig: () => translate("editor.problemTooBig", { max: maxSize }),
    noLead: () => translate("editor.problemLead"),
    duplicate: () => translate("editor.problemDuplicate"),
    noName: () => translate("editor.problemNoName"),
    badName: () => translate("editor.problemBadName"),
    noRole: () => translate("editor.problemNoRole"),
  };
  return problems.map((problem) => messages[problem]());
}
