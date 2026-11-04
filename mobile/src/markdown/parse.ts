// Parser for the Markdown subset the team writes (same as the web's GFM): no HTML, no images, no nesting beyond one list level of indentation.

export type Inline =
  | { type: "text"; value: string }
  | { type: "code"; value: string }
  | { type: "strong" | "em" | "del"; children: Inline[] }
  | { type: "link"; href: string; children: Inline[] }
  | { type: "mention"; name: string; self: boolean }
  | { type: "break" };

export type Block =
  | { type: "paragraph"; children: Inline[] }
  | { type: "heading"; level: number; children: Inline[] }
  | { type: "code"; value: string }
  | { type: "quote"; children: Block[] }
  | { type: "list"; ordered: boolean; items: Inline[][] }
  | { type: "table"; header: Inline[][]; rows: Inline[][][] };

export const MENTION_PATTERN = /@[\p{L}\p{N}_-]+/gu;
const ALLOWED_LINK = /^(https?:|mailto:)/i;
const FENCE = /^```/;
const HEADING = /^(#{1,6})\s+(.*)$/;
const BULLET = /^\s*[-*+]\s+(.*)$/;
const NUMBERED = /^\s*\d+[.)]\s+(.*)$/;
const QUOTE = /^>\s?(.*)$/;
const TABLE_SEPARATOR = /^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)*\|?\s*$/;
const INLINE_TOKEN =
  /(`[^`\n]+`)|(\*\*[^*\n]+\*\*|__[^_\n]+__)|(~~[^~\n]+~~)|(\*[^*\n]+\*|(?<![\p{L}\p{N}])_[^_\n]+_(?![\p{L}\p{N}]))|(\[[^\]\n]+\]\([^)\s]+\))|(https?:\/\/[^\s<>)]+)|(@[\p{L}\p{N}_-]+)/gu;

/** How the team can mention the boss (see BOSS_ALIASES in backend/app/services.py). */
export function bossNames(bossName: string): string[] {
  return ["boss", "ceo", ...(bossName ? [bossName] : [])];
}

export function mentionsAny(content: string, names: string[]): boolean {
  const self = new Set(names.map((name) => name.toLowerCase()));
  return [...content.matchAll(MENTION_PATTERN)].some((match) => self.has(match[0].slice(1).toLowerCase()));
}

/** Only http(s) and mailto links may leave the app. */
export function isOpenableLink(href: string): boolean {
  return ALLOWED_LINK.test(href);
}

function inlineToken(token: string, selfNames: Set<string>): Inline {
  if (token.startsWith("`")) return { type: "code", value: token.slice(1, -1) };
  if (token.startsWith("**") || token.startsWith("__")) return { type: "strong", children: parseInline(token.slice(2, -2), selfNames) };
  if (token.startsWith("~~")) return { type: "del", children: parseInline(token.slice(2, -2), selfNames) };
  if (token.startsWith("*") || token.startsWith("_")) return { type: "em", children: parseInline(token.slice(1, -1), selfNames) };
  if (token.startsWith("[")) {
    const split = token.lastIndexOf("](");
    return { type: "link", href: token.slice(split + 2, -1), children: parseInline(token.slice(1, split), selfNames) };
  }
  if (token.startsWith("@")) return { type: "mention", name: token.slice(1), self: selfNames.has(token.slice(1).toLowerCase()) };
  return { type: "link", href: token, children: [{ type: "text", value: token }] };
}

/** Inline spans of one line; a mention is never parsed inside code or a link target. */
export function parseInline(text: string, selfNames: Set<string>): Inline[] {
  const out: Inline[] = [];
  let last = 0;
  for (const match of text.matchAll(INLINE_TOKEN)) {
    const at = match.index ?? 0;
    if (at > last) out.push({ type: "text", value: text.slice(last, at) });
    out.push(inlineToken(match[0], selfNames));
    last = at + match[0].length;
  }
  if (last < text.length) out.push({ type: "text", value: text.slice(last) });
  return out;
}

/** Lines of a paragraph joined with hard breaks, as the web does (remark-breaks). */
function inlineLines(lines: string[], selfNames: Set<string>): Inline[] {
  return lines.flatMap((line, index) => (index === 0 ? [] : [{ type: "break" } as Inline]).concat(parseInline(line, selfNames)));
}

function splitRow(line: string): string[] {
  return line.trim().replace(/^\|/, "").replace(/\|$/, "").split("|").map((cell) => cell.trim());
}

function isBlockStart(line: string): boolean {
  return FENCE.test(line) || HEADING.test(line) || BULLET.test(line) || NUMBERED.test(line) || QUOTE.test(line);
}

/** Blocks of a Markdown text; `selfNames` are the names whose mention is flagged as aimed at the boss. */
export function parseMarkdown(source: string, selfNames: string[] = []): Block[] {
  const self = new Set(selfNames.map((name) => name.toLowerCase()));
  const lines = source.replace(/\r\n?/g, "\n").split("\n");
  const blocks: Block[] = [];
  let index = 0;
  while (index < lines.length) {
    const line = lines[index];
    if (line.trim() === "") {
      index += 1;
    } else if (FENCE.test(line)) {
      const body: string[] = [];
      index += 1;
      while (index < lines.length && !FENCE.test(lines[index])) body.push(lines[index++]);
      index += 1; // closing fence (an unclosed one runs to the end, as in CommonMark)
      blocks.push({ type: "code", value: body.join("\n") });
    } else if (HEADING.test(line)) {
      const [, hashes, title] = line.match(HEADING) as RegExpMatchArray;
      blocks.push({ type: "heading", level: hashes.length, children: parseInline(title, self) });
      index += 1;
    } else if (QUOTE.test(line)) {
      const body: string[] = [];
      while (index < lines.length && QUOTE.test(lines[index])) body.push((lines[index++].match(QUOTE) as RegExpMatchArray)[1]);
      blocks.push({ type: "quote", children: parseMarkdown(body.join("\n"), selfNames) });
    } else if (BULLET.test(line) || NUMBERED.test(line)) {
      const ordered = NUMBERED.test(line);
      const pattern = ordered ? NUMBERED : BULLET;
      const items: Inline[][] = [];
      while (index < lines.length && pattern.test(lines[index])) items.push(parseInline((lines[index++].match(pattern) as RegExpMatchArray)[1], self));
      blocks.push({ type: "list", ordered, items });
    } else if (line.includes("|") && TABLE_SEPARATOR.test(lines[index + 1] ?? "")) {
      const header = splitRow(line).map((cell) => parseInline(cell, self));
      index += 2;
      const rows: Inline[][][] = [];
      while (index < lines.length && lines[index].includes("|") && lines[index].trim() !== "") {
        rows.push(splitRow(lines[index++]).map((cell) => parseInline(cell, self)));
      }
      blocks.push({ type: "table", header, rows });
    } else {
      const paragraph: string[] = [];
      while (index < lines.length && lines[index].trim() !== "" && (paragraph.length === 0 || !isBlockStart(lines[index]))) paragraph.push(lines[index++]);
      blocks.push({ type: "paragraph", children: inlineLines(paragraph, self) });
    }
  }
  return blocks;
}
