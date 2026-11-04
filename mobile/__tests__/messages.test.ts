import type { Message } from "../src/api";
import { buildChatItems, bubbleLabel, mergeMessages, toDisplayMessage, type DisplayMessage } from "../src/format/messages";

jest.mock("expo-localization", () => ({ getLocales: () => [{ languageCode: "fr" }] }));

const message = (over: Partial<Message>): Message => ({
  id: 1,
  conversation_id: 1,
  employee_id: 5,
  author_name: "Élise",
  content: "Salut",
  created_at: "2026-01-01T10:00:00Z",
  is_system: false,
  request_kind: null,
  request_status: null,
  request_comment: null,
  request_answered_at: null,
  request_merged_into: null,
  request_decision_id: null,
  ...over,
});

const display = (...list: Partial<Message>[]): DisplayMessage[] => list.map((over) => toDisplayMessage(message(over)));

describe("toDisplayMessage", () => {
  it("treats a message without employee as the boss's, unless it is a system line", () => {
    expect(toDisplayMessage(message({ employee_id: null })).own).toBe(true);
    expect(toDisplayMessage(message({ employee_id: null, is_system: true })).own).toBe(false);
    expect(toDisplayMessage(message({ employee_id: 5 })).own).toBe(false);
  });

  it("flags the requests", () => {
    expect(toDisplayMessage(message({ request_kind: "question" })).isRequest).toBe(true);
  });
});

describe("mergeMessages", () => {
  it("appends only unknown ids and keeps the same array when nothing is new", () => {
    const known = [message({ id: 1 })];
    expect(mergeMessages(known, [message({ id: 1 })])).toBe(known);
    expect(mergeMessages(known, [message({ id: 1 }), message({ id: 2 })]).map((m) => m.id)).toEqual([1, 2]);
  });
});

describe("buildChatItems", () => {
  const NOW = new Date("2026-01-01T12:00:00Z");

  it("groups consecutive messages of one author, with the author and the tail on the right ones", () => {
    const items = buildChatItems(
      display({ id: 1 }, { id: 2, created_at: "2026-01-01T10:01:00Z" }, { id: 3, employee_id: null, author_name: "Enzo" }),
      NOW,
      "fr",
    );
    expect(items.map((item) => item.kind)).toEqual(["bubble", "bubble", "bubble"]);
    const [first, second, third] = items as Extract<(typeof items)[number], { kind: "bubble" }>[];
    expect([first.showAuthor, first.tail, first.firstInSeries]).toEqual([true, false, true]);
    expect([second.showAuthor, second.tail, second.firstInSeries]).toEqual([false, true, false]);
    expect([third.showAuthor, third.tail]).toEqual([false, true]);
  });

  it("inserts a time after a pause over one hour and starts a new series", () => {
    const items = buildChatItems(display({ id: 1 }, { id: 2, created_at: "2026-01-01T11:30:00Z" }), NOW, "fr");
    expect(items.map((item) => item.kind)).toEqual(["bubble", "timestamp", "bubble"]);
    expect((items[0] as { tail: boolean }).tail).toBe(true);
    expect((items[2] as { showAuthor: boolean }).showAuthor).toBe(true);
  });

  it("keeps system lines out of the series", () => {
    const items = buildChatItems(display({ id: 1 }, { id: 2, is_system: true, employee_id: null }, { id: 3 }), NOW, "fr");
    expect(items.map((item) => item.kind)).toEqual(["bubble", "system", "bubble"]);
  });
});

describe("bubbleLabel", () => {
  it("reads who, what, when and the failure", () => {
    const [mine] = display({ employee_id: null, author_name: "Enzo", content: "Go" });
    expect(bubbleLabel({ ...mine, status: "failed" }, new Date("2026-01-01T12:00:00Z"), "fr")).toMatch(
      /^Moi, Go, .+, Non envoyé\. Touchez pour réessayer\.$/,
    );
    const [theirs] = display({ request_kind: "question" });
    expect(bubbleLabel(theirs, new Date("2026-01-01T12:00:00Z"), "fr")).toMatch(/^Élise, Demande, Salut, /);
  });
});
