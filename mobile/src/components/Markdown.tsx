import { Linking, Platform, StyleSheet, Text, View } from "react-native";
import { type Block, type Inline, isOpenableLink, parseMarkdown } from "../markdown/parse";
import { FONT_SIZE, MAX_FONT_SCALE, SPACING, useColors } from "../theme";

const CODE_FONT = Platform.select({ ios: "Menlo", default: "monospace" });
const HEADING_SCALE = [1.3, 1.2, 1.1, 1, 1, 1]; // by level 1..6, relative to the body size
const TABLE_CELL_MIN_WIDTH = 80;

type Props = { content: string; selfNames?: string[]; color: string; linkColor: string };
type Style = { color: string; linkColor: string; codeBackground: string };

function openLink(href: string): void {
  if (isOpenableLink(href)) void Linking.openURL(href).catch(() => {});
}

/** Mentions are bold (and underlined when aimed at the boss) so they never rely on color alone. */
function renderInline(nodes: Inline[], style: Style, keyPrefix = ""): React.ReactNode[] {
  return nodes.map((node, index) => {
    const key = `${keyPrefix}${index}`;
    switch (node.type) {
      case "text":
        return node.value;
      case "break":
        return "\n";
      case "code":
        return (
          <Text key={key} style={[styles.code, { backgroundColor: style.codeBackground }]}>
            {node.value}
          </Text>
        );
      case "strong":
        return <Text key={key} style={styles.strong}>{renderInline(node.children, style, `${key}.`)}</Text>;
      case "em":
        return <Text key={key} style={styles.em}>{renderInline(node.children, style, `${key}.`)}</Text>;
      case "del":
        return <Text key={key} style={styles.del}>{renderInline(node.children, style, `${key}.`)}</Text>;
      case "link":
        return (
          <Text
            key={key}
            accessibilityRole="link"
            onPress={() => openLink(node.href)}
            style={[styles.link, { color: style.linkColor }]}
          >
            {renderInline(node.children, style, `${key}.`)}
          </Text>
        );
      case "mention":
        return (
          <Text key={key} style={[styles.strong, node.self && styles.underline]}>
            {`@${node.name}`}
          </Text>
        );
    }
  });
}

function BlockView({ block, style, size }: { block: Block; style: Style; size: number }) {
  const colors = useColors();
  switch (block.type) {
    case "paragraph":
      return (
        <Text maxFontSizeMultiplier={MAX_FONT_SCALE} style={[styles.paragraph, { color: style.color, fontSize: size }]}>
          {renderInline(block.children, style)}
        </Text>
      );
    case "heading":
      return (
        <Text
          accessibilityRole="header"
          maxFontSizeMultiplier={MAX_FONT_SCALE}
          style={[styles.strong, styles.paragraph, { color: style.color, fontSize: size * HEADING_SCALE[block.level - 1] }]}
        >
          {renderInline(block.children, style)}
        </Text>
      );
    case "code":
      return (
        <View style={[styles.codeBlock, { backgroundColor: style.codeBackground }]}>
          <Text maxFontSizeMultiplier={MAX_FONT_SCALE} style={[styles.code, { color: style.color, fontSize: size - 2 }]}>
            {block.value}
          </Text>
        </View>
      );
    case "quote":
      return (
        <View style={[styles.quote, { borderLeftColor: colors.separator }]}>
          {block.children.map((child, index) => <BlockView key={index} block={child} style={style} size={size} />)}
        </View>
      );
    case "list":
      return (
        <View style={styles.list}>
          {block.items.map((item, index) => (
            <Text key={index} maxFontSizeMultiplier={MAX_FONT_SCALE} style={[styles.paragraph, { color: style.color, fontSize: size }]}>
              {block.ordered ? `${index + 1}. ` : "• "}
              {renderInline(item, style)}
            </Text>
          ))}
        </View>
      );
    case "table":
      return (
        <View style={[styles.table, { borderColor: colors.separator }]}>
          {[block.header, ...block.rows].map((row, rowIndex) => (
            <View key={rowIndex} style={styles.row}>
              {row.map((cell, cellIndex) => (
                <Text
                  key={cellIndex}
                  maxFontSizeMultiplier={MAX_FONT_SCALE}
                  style={[styles.cell, rowIndex === 0 && styles.strong, { color: style.color, fontSize: size, borderColor: colors.separator }]}
                >
                  {renderInline(cell, style)}
                </Text>
              ))}
            </View>
          ))}
        </View>
      );
  }
}

/** A message body: the Markdown subset of the web app, drawn with native text. */
export function Markdown({ content, selfNames = [], color, linkColor }: Props) {
  const colors = useColors();
  const style: Style = { color, linkColor, codeBackground: colors.codeBackground };
  return (
    <View>
      {parseMarkdown(content, selfNames).map((block, index) => (
        <BlockView key={index} block={block} style={style} size={FONT_SIZE.body} />
      ))}
    </View>
  );
}

const styles = StyleSheet.create({
  paragraph: { fontSize: FONT_SIZE.body },
  strong: { fontWeight: "700" },
  em: { fontStyle: "italic" },
  del: { textDecorationLine: "line-through" },
  underline: { textDecorationLine: "underline" },
  link: { textDecorationLine: "underline" },
  code: { fontFamily: CODE_FONT },
  codeBlock: { padding: SPACING.sm, borderRadius: SPACING.sm, marginVertical: SPACING.xs },
  quote: { borderLeftWidth: 3, paddingLeft: SPACING.sm, marginVertical: SPACING.xs },
  list: { marginVertical: SPACING.xs },
  table: { borderWidth: StyleSheet.hairlineWidth, marginVertical: SPACING.xs },
  row: { flexDirection: "row" },
  cell: { flex: 1, minWidth: TABLE_CELL_MIN_WIDTH, padding: SPACING.xs, borderWidth: StyleSheet.hairlineWidth },
});
