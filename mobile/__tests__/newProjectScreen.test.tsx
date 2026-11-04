import { fireEvent, render, screen, waitFor } from "@testing-library/react-native";
import NewProjectScreen from "../app/(tabs)/new";
import { ApiError, api, type CatalogLimits, type ProjectDetail, type Role } from "../src/api";

const mockPush = jest.fn();
const mockNavigate = jest.fn();
jest.mock("expo-router", () => ({ useRouter: () => ({ push: mockPush, navigate: mockNavigate }) }));
jest.mock("expo-localization", () => ({ getLocales: () => [{ languageCode: "en" }] }));
jest.mock("expo-secure-store", () => ({}));
jest.mock("@expo/vector-icons", () => ({ Ionicons: () => null }));
jest.mock("../src/api", () => ({
  ...jest.requireActual("../src/api"),
  api: {
    getSettings: jest.fn(),
    personalities: jest.fn(),
    roles: jest.fn(),
    limits: jest.fn(),
    names: jest.fn(),
    createProject: jest.fn(),
  },
}));

const mocked = api as unknown as Record<keyof typeof api, jest.Mock>;

const limits: CatalogLimits = { models: ["haiku", "sonnet"], max_agents: 5, min_team_size: 2, mandatory_role: "lead" };
const role = (key: string, title: string): Role => ({
  key, title, description: `${title} description`, category: "engineering", order: 1, model: "sonnet", effort: null,
  mission: `${title} mission`, responsibilities: ["Ship"], forbidden: [], deliverables: [], escalation: "", success: "",
  permissions: [], wakes_on: [], tools: { mcp: ["a"], claude: ["b"] },
});
const created = { id: 42 } as ProjectDetail;

beforeEach(() => {
  jest.clearAllMocks();
  mocked.getSettings.mockResolvedValue({ boss_name: "Enzo", language: "en", languages: {}, claude_accounts: 1 });
  mocked.personalities.mockResolvedValue({ calm: { key: "calm", label: "Calm", description: "Steady" } });
  mocked.roles.mockResolvedValue({ lead: role("lead", "Lead"), dev: role("dev", "Developer") });
  mocked.limits.mockResolvedValue(limits);
  mocked.names.mockResolvedValue(["Ana"]);
  mocked.createProject.mockResolvedValue(created);
});

const fillProject = async (name = "Alpha", repo = "https://github.com/acme/alpha") => {
  await fireEvent.changeText(screen.getByLabelText("Name"), name);
  await fireEvent.changeText(screen.getByLabelText("GitHub repository"), repo);
};
const create = () => screen.getByRole("button", { name: "Create project" });

describe("new project screen, automatic team", () => {
  it("creates the project from a description and opens its conversation", async () => {
    await render(<NewProjectScreen />);
    await waitFor(() => expect(mocked.limits).toHaveBeenCalled());
    await fillProject();
    await fireEvent.changeText(screen.getByLabelText("Project description"), " A shop ");
    await waitFor(() => expect(create().props.accessibilityState.disabled).toBe(false));
    await fireEvent.press(create());
    expect(mocked.createProject).toHaveBeenCalledWith({
      name: "Alpha", mode: "startup", repo_url: "https://github.com/acme/alpha", creation_mode: "auto",
      description: "A shop", employee_count: 2,
    });
    expect(mockPush).toHaveBeenCalledWith({ pathname: "/conversation/[id]", params: { id: "42" } });
    expect(screen.getByLabelText("Name").props.value).toBe("");
  });

  it("keeps the button disabled until the form is valid and flags an invalid repository", async () => {
    await render(<NewProjectScreen />);
    await waitFor(() => expect(mocked.limits).toHaveBeenCalled());
    await fillProject("Alpha", "gitlab.com/x/y");
    await fireEvent.changeText(screen.getByLabelText("Project description"), "A shop");
    expect(screen.getByText("Expected a GitHub URL, like https://github.com/owner/repo")).toBeTruthy();
    expect(create().props.accessibilityState.disabled).toBe(true);
  });

  it("warns when the head count is outside the server limits", async () => {
    await render(<NewProjectScreen />);
    await waitFor(() => expect(mocked.limits).toHaveBeenCalled());
    await fireEvent.changeText(screen.getByLabelText("Number of employees (lead included)"), "9");
    expect(await screen.findByText("A team has at most 5 members.")).toBeTruthy();
    expect(create().props.accessibilityState.disabled).toBe(true);
  });

  it("shows the API error and lets the user try again", async () => {
    mocked.createProject.mockRejectedValue(new ApiError(409, "Name already used"));
    await render(<NewProjectScreen />);
    await waitFor(() => expect(mocked.limits).toHaveBeenCalled());
    await fillProject();
    await fireEvent.changeText(screen.getByLabelText("Project description"), "A shop");
    await fireEvent.press(create());
    expect(await screen.findByText("Name already used")).toBeTruthy();
    expect(mockPush).not.toHaveBeenCalled();
    expect(create().props.accessibilityState.disabled).toBe(false);
  });

  it("goes back to the project list on cancel", async () => {
    await render(<NewProjectScreen />);
    await fireEvent.press(screen.getByRole("button", { name: "Cancel" }));
    expect(mockNavigate).toHaveBeenCalledWith("/");
  });
});

describe("new project screen, manual team", () => {
  const openManual = async () => {
    await render(<NewProjectScreen />);
    await waitFor(() => expect(screen.getByRole("tab", { name: "Manual" }).props.accessibilityState.disabled).toBe(false));
    await fireEvent.press(screen.getByRole("tab", { name: "Manual" }));
  };

  it("keeps the manual tab disabled while the catalog is not loaded", async () => {
    mocked.roles.mockReturnValue(new Promise(() => {}));
    await render(<NewProjectScreen />);
    await waitFor(() => expect(mocked.limits).toHaveBeenCalled());
    expect(screen.getByRole("tab", { name: "Manual" }).props.accessibilityState.disabled).toBe(true);
  });

  it("offers a retry when the personalities fail to load", async () => {
    mocked.personalities.mockRejectedValueOnce(new ApiError(500, "boom"));
    await render(<NewProjectScreen />);
    expect(await screen.findByText(/Could not load the personality presets/)).toBeTruthy();
    expect(screen.getByRole("tab", { name: "Manual" }).props.accessibilityState.disabled).toBe(true);
    await fireEvent.press(screen.getByRole("button", { name: "Retry" }));
    await waitFor(() => expect(screen.getByRole("tab", { name: "Manual" }).props.accessibilityState.disabled).toBe(false));
    expect(screen.queryByText(/Could not load the personality presets/)).toBeNull();
  });

  it("starts with the locked lead and asks for the missing members", async () => {
    await openManual();
    expect(screen.getByText("Ana")).toBeTruthy();
    expect(screen.getByText("Required")).toBeTruthy();
    expect(screen.getByText("Team: 1 / 5 members")).toBeTruthy();
    expect(screen.getByText("A team needs at least 2 members, the lead included.")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Remove Ana" })).toBeNull();
  });

  it("adds an agent, gives it a name and a job, then creates the team", async () => {
    await openManual();
    await fillProject();
    await fireEvent.press(screen.getByRole("button", { name: "+ Add an agent" }));
    await fireEvent.changeText(await screen.findByLabelText("Agent name"), "Bob");
    await fireEvent.press(screen.getByRole("button", { name: "Jobs" }));
    await fireEvent.press(await screen.findByRole("checkbox", { name: "Developer" }));
    await fireEvent.press(screen.getByRole("button", { name: "Done" }));
    await fireEvent.press(screen.getByRole("button", { name: "Close" }));
    await waitFor(() => expect(create().props.accessibilityState.disabled).toBe(false));
    await fireEvent.press(create());
    expect(mocked.createProject).toHaveBeenCalledWith(expect.objectContaining({
      creation_mode: "manual",
      employees: [
        { name: "Ana", roles: ["lead"], model: null, account: null, personality: null },
        { name: "Bob", roles: ["dev"], model: null, account: null, personality: null },
      ],
    }));
  });

  it("removes an agent with a labelled button and stops adding at the limit", async () => {
    await openManual();
    for (let added = 0; added < 4; added++) {
      await fireEvent.press(screen.getByRole("button", { name: "+ Add an agent" }));
      await fireEvent.press(await screen.findByRole("button", { name: "Close" }));
    }
    expect(screen.getByText(/Team: 5 \/ 5 members/)).toBeTruthy();
    expect(screen.getByText("The team cannot have more than 5 members.")).toBeTruthy();
    expect(screen.getByRole("button", { name: "+ Add an agent" }).props.accessibilityState.disabled).toBe(true);
    await fireEvent.press(screen.getAllByRole("button", { name: "Remove Name" })[0]);
    expect(screen.getByText(/Team: 4 \/ 5 members/)).toBeTruthy();
  });

  it("picks a personality from the searchable list, with a random option", async () => {
    await openManual();
    await fireEvent.press(screen.getByRole("button", { name: "Edit Ana" }));
    await fireEvent.press(await screen.findByRole("button", { name: "Personality" }));
    await fireEvent.changeText(screen.getByLabelText("Search a personality…"), "zzz");
    expect(screen.getByText("No personality matches your search.")).toBeTruthy();
    await fireEvent.changeText(screen.getByLabelText("Search a personality…"), "stead");
    await fireEvent.press(screen.getByRole("radio", { name: "Calm. Steady" }));
    expect(screen.getByRole("button", { name: "Personality" }).props.accessibilityValue.text).toBe("Calm");
  });

  it("searches jobs, opens a job's details and clears a search with no match", async () => {
    await openManual();
    await fireEvent.press(screen.getByRole("button", { name: "+ Add an agent" }));
    await fireEvent.press(await screen.findByRole("button", { name: "Jobs" }));
    await fireEvent.changeText(screen.getByLabelText("Search a job…"), "zzz");
    expect(screen.getByText('No job matches "zzz".')).toBeTruthy();
    await fireEvent.press(screen.getByRole("button", { name: "Clear search" }));
    expect(screen.getByRole("button", { name: "Engineering (2)" })).toBeTruthy();
    await fireEvent.changeText(screen.getByLabelText("Search a job…"), "devel");
    expect(screen.queryByRole("checkbox", { name: "Lead" })).toBeNull();
    await fireEvent.press(screen.getByRole("button", { name: "Show details, Developer" }));
    expect(screen.getByText("Developer mission")).toBeTruthy();
    expect(screen.getByText("• Ship")).toBeTruthy();
  });

  it("lets the locked lead change only the personality, back to random", async () => {
    await openManual();
    await fireEvent.press(screen.getByRole("button", { name: "Edit Ana" }));
    expect(screen.queryByRole("button", { name: "Jobs" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Model" })).toBeNull();
    await fireEvent.press(screen.getByRole("button", { name: "Personality" }));
    await fireEvent.press(screen.getByRole("radio", { name: "Random. A personality is drawn at random." }));
    expect(screen.getByRole("button", { name: "Personality" }).props.accessibilityValue.text).toBe("Random");
  });
});
