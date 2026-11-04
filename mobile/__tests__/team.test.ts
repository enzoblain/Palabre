import type { PersonalityPreset, Role } from "../src/api";
import {
  autoTeamProblems, filterPresets, freeName, groupJobs, isGithubUrl, mandatoryMember, teamProblems, teamWarningThreshold,
} from "../src/format/team";

const role = (key: string, over: Partial<Role> = {}): Role => ({
  key, title: key, description: "", category: "engineering", order: 1, model: "sonnet", effort: null, mission: "",
  responsibilities: [], forbidden: [], deliverables: [], escalation: "", success: "", permissions: [], wakes_on: [],
  tools: { mcp: [], claude: [] }, ...over,
});
const member = (name: string, roles: string[] = ["dev"]) => ({ name, roles });

describe("isGithubUrl", () => {
  it.each(["https://github.com/owner/repo", "https://github.com/owner/repo.git/", "git@github.com:owner/repo.git"])("accepts %s", (url) => {
    expect(isGithubUrl(url)).toBe(true);
  });
  it.each(["", "github.com/owner/repo", "https://gitlab.com/owner/repo", "https://github.com/owner"])("refuses %s", (url) => {
    expect(isGithubUrl(url)).toBe(false);
  });
});

describe("filterPresets", () => {
  const presets: Record<string, PersonalityPreset> = {
    b: { key: "b", label: "Déterminé", description: "Never gives up" },
    a: { key: "a", label: "Calme", description: "Steady" },
  };
  it("sorts by name when the query is empty", () => {
    expect(filterPresets(presets, "").map((p) => p.key)).toEqual(["a", "b"]);
  });
  it("ignores accents and case and needs every word", () => {
    expect(filterPresets(presets, "DETERMINE up").map((p) => p.key)).toEqual(["b"]);
    expect(filterPresets(presets, "calme up")).toEqual([]);
  });
});

describe("groupJobs", () => {
  const roles = {
    qa: role("qa", { title: "QA", category: "quality", order: 3 }),
    dev: role("dev", { title: "Backend", category: "engineering", order: 2 }),
    lead: role("lead", { title: "Lead", category: "management", order: 1 }),
    hr: role("hr", { title: "Backend HR", category: "specialized_roles", order: 9 }),
  };
  it("groups by category in the catalog's display order and leaves empty groups out", () => {
    expect(groupJobs(roles, "").map(([category, jobs]) => [category, jobs.map((j) => j.key)])).toEqual([
      ["management", ["lead"]], ["engineering", ["dev"]], ["quality", ["qa"]], ["specialized_roles", ["hr"]],
    ]);
  });
  it("filters on the title, case-insensitively", () => {
    expect(groupJobs(roles, " backend ").flatMap(([, jobs]) => jobs.map((j) => j.key))).toEqual(["dev", "hr"]);
    expect(groupJobs(roles, "zzz")).toEqual([]);
  });
});

describe("teamProblems", () => {
  it("accepts a valid team", () => {
    expect(teamProblems([member("Ana", ["lead"]), member("Bob")], "lead", 2, 5)).toEqual([]);
  });
  it("reports an empty team", () => {
    expect(teamProblems([], "lead", 2, 5)).toEqual(["none"]);
  });
  it("reports the size bounds", () => {
    expect(teamProblems([member("Ana", ["lead"])], "lead", 2, 5)).toEqual(["tooSmall"]);
    expect(teamProblems([member("A", ["lead"]), member("B"), member("C")], "lead", 1, 2)).toEqual(["tooBig"]);
  });
  it("reports a missing lead, duplicate names (any case), missing and invalid names, and missing jobs", () => {
    expect(teamProblems([member("Ana"), member("Bob")], "lead", 1, 5)).toEqual(["noLead"]);
    expect(teamProblems([member("Ana", ["lead"]), member("ana")], "lead", 1, 5)).toEqual(["duplicate"]);
    expect(teamProblems([member("Ana", ["lead"]), member("")], "lead", 1, 5)).toContain("noName");
    expect(teamProblems([member("Ana", ["lead"]), member("a b")], "lead", 1, 5)).toEqual(["badName"]);
    expect(teamProblems([member("Ana", ["lead"]), member("Bob", [])], "lead", 1, 5)).toEqual(["noRole"]);
  });
  it("requires no lead when none is asked", () => {
    expect(teamProblems([member("Ana")], null, 1, 5)).toEqual([]);
  });
});

describe("autoTeamProblems", () => {
  it("checks the head count against the bounds", () => {
    expect(autoTeamProblems(1, 2, 5)).toEqual(["tooSmall"]);
    expect(autoTeamProblems(6, 2, 5)).toEqual(["tooBig"]);
    expect(autoTeamProblems(3, 2, 5)).toEqual([]);
  });
});

describe("names", () => {
  it("draws a name nobody has, whatever the case", () => {
    expect(freeName(["Ana", "Bob"], ["ana"], () => 0)).toBe("Bob");
  });
  it("returns an empty name when all are taken", () => {
    expect(freeName(["Ana"], ["ANA"])).toBe("");
  });
  it("starts the team with the lead", () => {
    expect(mandatoryMember(["Ana"], "lead")).toEqual({ name: "Ana", roles: ["lead"], model: null, account: null, personality: null });
  });
});

describe("teamWarningThreshold", () => {
  it("warns from 80% of the limit, rounded up", () => {
    expect(teamWarningThreshold(10)).toBe(8);
    expect(teamWarningThreshold(11)).toBe(9);
  });
});
