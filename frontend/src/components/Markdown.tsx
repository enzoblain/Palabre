import { openUrl } from "@tauri-apps/plugin-opener";
import ReactMarkdown, { type Components } from "react-markdown";
import remarkBreaks from "remark-breaks";
import remarkGfm from "remark-gfm";

const MENTION_RE = /@[\p{L}\p{N}_-]+/gu;
const HAS_MENTION = /@[\p{L}\p{N}_-]+/u; // No "g": test() must not keep state between calls

type MdNode = { type: string; value?: string; children?: MdNode[]; data?: Record<string, unknown> };

/** remark plugin: "@Name" in plain text becomes <span class="mention">, with
 * "mention-me" when it is one of `selfNames` (the boss). */
function remarkMentions({ selfNames }: { selfNames: string[] }) {
  const self = new Set(selfNames.map((n) => n.toLowerCase()));
  const walk = (node: MdNode) => {
    if (!node.children) return;
    node.children = node.children.flatMap((child) => {
      if (child.type !== "text" || !child.value || !HAS_MENTION.test(child.value)) {
        walk(child);
        return [child];
      }
      const out: MdNode[] = [];
      let last = 0;
      for (const match of child.value.matchAll(MENTION_RE)) {
        const at = match.index ?? 0;
        if (at > last) out.push({ type: "text", value: child.value.slice(last, at) });
        out.push({
          type: "mention",
          children: [{ type: "text", value: match[0] }],
          data: {
            hName: "span",
            hProperties: { className: self.has(match[0].slice(1).toLowerCase()) ? "mention mention-me" : "mention" },
          },
        });
        last = at + match[0].length;
      }
      if (last < child.value.length) out.push({ type: "text", value: child.value.slice(last) });
      return out;
    });
  };
  return (tree: MdNode) => walk(tree);
}

function openExternal(href: string) {
  if ("__TAURI_INTERNALS__" in window) openUrl(href).catch(() => {});
  else window.open(href, "_blank", "noopener");
}

// Links open in the system browser: navigating would replace the app itself
const components: Components = {
  a: ({ href, children }) => (
    <a href={href} onClick={(e) => {
      e.preventDefault();
      if (href && /^(https?:|mailto:)/i.test(href)) openExternal(href);
    }}>
      {children}
    </a>
  ),
};

/** How the team can mention the boss (see BOSS_ALIASES in backend/app/services.py). */
export function bossNames(bossName: string): string[] {
  return ["boss", "ceo", ...(bossName ? [bossName] : [])];
}

export function mentionsAny(content: string, names: string[]): boolean {
  const self = new Set(names.map((n) => n.toLowerCase()));
  return [...content.matchAll(MENTION_RE)].some((m) => self.has(m[0].slice(1).toLowerCase()));
}

export function Markdown({ content, selfNames = [] }: { content: string; selfNames?: string[] }) {
  return (
    <div className="markdown">
      <ReactMarkdown remarkPlugins={[remarkGfm, remarkBreaks, [remarkMentions, { selfNames }]]} components={components}>
        {content}
      </ReactMarkdown>
    </div>
  );
}
