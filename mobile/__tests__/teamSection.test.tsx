import { act, fireEvent, render, screen, waitFor } from "@testing-library/react-native";
import { Alert } from "react-native";
import { TeamSection } from "../src/components/project/TeamSection";
import { ApiError, api, type CatalogLimits, type Employee, type Role } from "../src/api";

jest.mock("expo-localization", () => ({ getLocales: () => [{ languageCode: "en" }] }));
jest.mock("expo-secure-store", () => ({}));
jest.mock("../src/api", () => ({
  ...jest.requireActual("../src/api"),
  api: {
    roles: jest.fn(),
    personalities: jest.fn(),
    limits: jest.fn(),
    addEmployee: jest.fn(),
    updateEmployee: jest.fn(),
    removeEmployee: jest.fn(),
  },
}));

const mocked = api as unknown as Record<string, jest.Mock>;
const alertSpy = jest.spyOn(Alert, "alert");
const onChanged = jest.fn();

const limits: CatalogLimits = { models: ["sonnet"], max_agents: 5, min_team_size: 2, mandatory_role: "lead" };
const role = (key: string, title: string): Role => ({
  key, title, description: `${title} description`, category: "engineering", order: 1, model: "sonnet", effort: null,
  mission: `${title} mission`, responsibilities: [], forbidden: [], deliverables: [], escalation: "", success: "",
  permissions: [], wakes_on: [], tools: { mcp: [], claude: [] },
});
const member = (id: number, name: string, roles: string[], quirks: string[] = []): Employee => ({
  id, name, title: roles[0] === "lead" ? "Lead" : "Developer", project_id: 1, roles, model: "sonnet", permissions: [],
  traits: {}, quirks, style: {}, account: null,
});
const members = [member(2, "Zed", ["dev"], ["Loves tests"]), member(1, "Ana", ["lead"])];

const confirmAlert = async (label: string) => {
  const buttons = alertSpy.mock.calls.at(-1)?.[2] ?? [];
  await act(async () => {
    buttons.find((button) => button.text === label)?.onPress?.();
  });
};

beforeEach(() => {
  jest.clearAllMocks();
  mocked.roles.mockResolvedValue({ lead: role("lead", "Lead"), dev: role("dev", "Developer"), qa: role("qa", "Tester") });
  mocked.personalities.mockResolvedValue({ calm: { key: "calm", label: "Calm", description: "Steady" } });
  mocked.limits.mockResolvedValue(limits);
});

describe("team section", () => {
  it("lists members by name with quirks, and locks the lead", async () => {
    await render(<TeamSection projectId={1} members={members} onChanged={onChanged} />);
    expect(await screen.findByText("Loves tests")).toBeTruthy();
    expect(screen.getAllByText("Lead").length).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Edit Ana" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Remove Ana" })).toBeNull();
    expect(screen.getByRole("button", { name: "Edit Zed" })).toBeTruthy();
  });

  it("shows a loading state while the catalog loads", async () => {
    mocked.roles.mockReturnValue(new Promise(() => {}));
    await render(<TeamSection projectId={1} members={members} onChanged={onChanged} />);
    expect(screen.getByText("Loading the team")).toBeTruthy();
  });

  it("shows an error with a retry when the catalog fails", async () => {
    mocked.roles.mockRejectedValueOnce(new Error("down"));
    await render(<TeamSection projectId={1} members={members} onChanged={onChanged} />);
    await fireEvent.press(await screen.findByText("Try again"));
    expect(await screen.findByRole("button", { name: "Edit Zed" })).toBeTruthy();
  });

  it("edits the jobs and the personality of a member with one request", async () => {
    mocked.updateEmployee.mockResolvedValue(members[0]);
    await render(<TeamSection projectId={1} members={members} onChanged={onChanged} />);
    await fireEvent.press(await screen.findByRole("button", { name: "Edit Zed" }));
    await fireEvent.press(screen.getByRole("button", { name: "Personality" }));
    await fireEvent.press(await screen.findByRole("radio", { name: "Calm. Steady" }));
    await fireEvent.press(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(mocked.updateEmployee).toHaveBeenCalledWith(2, { roles: ["dev"], personality: "calm" }));
    expect(onChanged).toHaveBeenCalled();
  });

  it("keeps the current personality when random is left selected", async () => {
    mocked.updateEmployee.mockResolvedValue(members[0]);
    await render(<TeamSection projectId={1} members={members} onChanged={onChanged} />);
    await fireEvent.press(await screen.findByRole("button", { name: "Edit Zed" }));
    await fireEvent.press(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(mocked.updateEmployee).toHaveBeenCalledWith(2, { roles: ["dev"] }));
  });

  it("shows the error and stays open when the save fails", async () => {
    mocked.updateEmployee.mockRejectedValue(new ApiError(400, "Invalid roles"));
    await render(<TeamSection projectId={1} members={members} onChanged={onChanged} />);
    await fireEvent.press(await screen.findByRole("button", { name: "Edit Zed" }));
    await fireEvent.press(screen.getByRole("button", { name: "Save" }));
    expect(await screen.findByText("Invalid roles")).toBeTruthy();
    expect(onChanged).not.toHaveBeenCalled();
  });

  it("adds a member only once a job is picked", async () => {
    mocked.addEmployee.mockResolvedValue(member(3, "New", ["qa"]));
    await render(<TeamSection projectId={1} members={members} onChanged={onChanged} />);
    await fireEvent.press(await screen.findByRole("button", { name: "Add a member" }));
    expect(screen.getByText("Pick at least one role.")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Add" }).props.accessibilityState.disabled).toBe(true);
    await fireEvent.press(screen.getByRole("button", { name: "Jobs" }));
    await fireEvent.press(await screen.findByRole("checkbox", { name: "Tester" }));
    await fireEvent.press(screen.getByRole("button", { name: "Done" }));
    await fireEvent.press(screen.getByRole("button", { name: "Add" }));
    await waitFor(() => expect(mocked.addEmployee).toHaveBeenCalledWith(1, { roles: ["qa"], personality: null }));
    expect(onChanged).toHaveBeenCalled();
  });

  it("removes a member with a labelled button and a confirmation", async () => {
    mocked.removeEmployee.mockResolvedValue(undefined);
    await render(<TeamSection projectId={1} members={members} onChanged={onChanged} />);
    await fireEvent.press(await screen.findByRole("button", { name: "Remove Zed" }));
    expect(mocked.removeEmployee).not.toHaveBeenCalled();
    await confirmAlert("Remove for good");
    expect(mocked.removeEmployee).toHaveBeenCalledWith(2);
    expect(onChanged).toHaveBeenCalled();
  });

  it("shows the error when the removal fails", async () => {
    mocked.removeEmployee.mockRejectedValue(new ApiError(409, "Busy"));
    await render(<TeamSection projectId={1} members={members} onChanged={onChanged} />);
    await fireEvent.press(await screen.findByRole("button", { name: "Remove Zed" }));
    await confirmAlert("Remove for good");
    expect(await screen.findByText("Busy")).toBeTruthy();
    expect(onChanged).not.toHaveBeenCalled();
  });
});
