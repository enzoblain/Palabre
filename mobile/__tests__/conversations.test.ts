import type { ProjectListItem } from "../src/api";
import { avatarColor, filterConversations, formatListTime, initials, sortByActivity } from "../src/format/conversations";

jest.mock("expo-localization", () => ({ getLocales: () => [{ languageCode: "fr" }] }));

const item = (over: Partial<ProjectListItem>): ProjectListItem => ({
  id: 1,
  name: "Alpha",
  repo_url: "",
  default_branch: "main",
  mode: "enterprise",
  seed: 1,
  created_at: "2026-01-01T10:00:00",
  unread_count: 0,
  lead_writing: false,
  last_message: null,
  ...over,
});

const message = (content: string, created_at: string) => ({ content, author: "Élise", created_at });

describe("sortByActivity", () => {
  it("puts the latest message first and falls back to the creation date", () => {
    const old = item({ id: 1, last_message: message("a", "2026-03-01T10:00:00") });
    const recent = item({ id: 2, last_message: message("b", "2026-04-01T10:00:00") });
    const silent = item({ id: 3, created_at: "2026-03-15T10:00:00" });
    expect(sortByActivity([old, silent, recent]).map((i) => i.id)).toEqual([2, 3, 1]);
  });

  it("does not mutate its input", () => {
    const input = [item({ id: 1 }), item({ id: 2, created_at: "2027-01-01T00:00:00" })];
    sortByActivity(input);
    expect(input.map((i) => i.id)).toEqual([1, 2]);
  });
});

describe("filterConversations", () => {
  const items = [item({ id: 1, name: "Alpha" }), item({ id: 2, name: "Beta", last_message: message("Hello ALPHA", "2026-03-01T10:00:00") })];
  it("matches the name and the preview, ignoring case", () => {
    expect(filterConversations(items, "alpha").map((i) => i.id)).toEqual([1, 2]);
    expect(filterConversations(items, "bet").map((i) => i.id)).toEqual([2]);
  });
  it("keeps everything for a blank query", () => {
    expect(filterConversations(items, "  ")).toBe(items);
  });
});

describe("initials and avatar color", () => {
  it("takes up to two initials", () => {
    expect(initials("palabre web app")).toBe("PW");
    expect(initials("alpha")).toBe("A");
  });
  it("takes the first code point of each word, outside the BMP too", () => {
    expect(initials("😀 Team")).toBe("😀T");
    expect(initials("𝒜lpha 𠮷野家")).toBe("𝒜𠮷");
  });
  it("is stable for a name", () => {
    expect(avatarColor("Alpha")).toBe(avatarColor("Alpha"));
    expect(avatarColor("Alpha")).toMatch(/^hsl\(\d+, 45%, 38%\)$/);
  });
});

describe("formatListTime", () => {
  const now = new Date(2026, 5, 10, 15, 0);
  it("shows the time today", () => {
    expect(formatListTime(new Date(2026, 5, 10, 9, 5).toISOString(), now, "fr-FR")).toBe("09:05");
  });
  it("shows Hier for yesterday", () => {
    expect(formatListTime(new Date(2026, 5, 9, 23, 0).toISOString(), now, "fr-FR")).toBe("Hier");
  });
  it("shows the weekday within a week", () => {
    expect(formatListTime(new Date(2026, 5, 6, 12, 0).toISOString(), now, "fr-FR")).toBe("samedi");
  });
  it("shows the short date beyond a week", () => {
    expect(formatListTime(new Date(2026, 4, 1, 12, 0).toISOString(), now, "fr-FR")).toBe("01/05/26");
  });
});
