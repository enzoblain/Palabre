import { bossNames, isOpenableLink, mentionsAny, parseMarkdown } from "../src/markdown/parse";

describe("parseMarkdown", () => {
  it("parses paragraphs with hard line breaks and inline styles", () => {
    expect(parseMarkdown("a **b** *c*\nd `e`")).toEqual([
      {
        type: "paragraph",
        children: [
          { type: "text", value: "a " },
          { type: "strong", children: [{ type: "text", value: "b" }] },
          { type: "text", value: " " },
          { type: "em", children: [{ type: "text", value: "c" }] },
          { type: "break" },
          { type: "text", value: "d " },
          { type: "code", value: "e" },
        ],
      },
    ]);
  });

  it("parses headings, lists, quotes and fenced code", () => {
    const blocks = parseMarkdown("# Titre\n1. un\n2. deux\n\n- a\n\n> cité\n\n```ts\nlet x = 1;\n```");
    expect(blocks.map((block) => block.type)).toEqual(["heading", "list", "list", "quote", "code"]);
    expect(blocks[1]).toMatchObject({ ordered: true });
    expect(blocks[4]).toEqual({ type: "code", value: "let x = 1;" });
  });

  it("parses GFM tables and bare links", () => {
    const [table, paragraph] = parseMarkdown("| a | b |\n|---|---|\n| 1 | 2 |\n\nvoir https://example.com");
    expect(table).toMatchObject({ type: "table", rows: [[[{ type: "text", value: "1" }], [{ type: "text", value: "2" }]]] });
    expect(paragraph).toMatchObject({ children: [{ type: "text" }, { type: "link", href: "https://example.com" }] });
  });

  it("flags mentions of the boss and keeps code literal", () => {
    const [paragraph] = parseMarkdown("@Enzo @Bob `@Enzo`", ["enzo"]);
    expect(paragraph).toMatchObject({
      children: [{ type: "mention", self: true }, { type: "text" }, { type: "mention", self: false }, { type: "text" }, { type: "code" }],
    });
  });

  it("does not hang on an unclosed fence", () => {
    expect(parseMarkdown("```\nx")).toEqual([{ type: "code", value: "x" }]);
  });
});

describe("mentions and links", () => {
  it("knows the names that aim at the boss", () => {
    expect(bossNames("Enzo")).toEqual(["boss", "ceo", "Enzo"]);
    expect(bossNames("")).toEqual(["boss", "ceo"]);
    expect(mentionsAny("salut @CEO", bossNames(""))).toBe(true);
    expect(mentionsAny("salut @Bob", bossNames("Enzo"))).toBe(false);
  });

  it("only lets http(s) and mailto leave the app", () => {
    expect(isOpenableLink("https://a.b")).toBe(true);
    expect(isOpenableLink("mailto:a@b.c")).toBe(true);
    expect(isOpenableLink("javascript:alert(1)")).toBe(false);
    expect(isOpenableLink("file:///etc/passwd")).toBe(false);
  });
});
