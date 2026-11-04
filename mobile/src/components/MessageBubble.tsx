import { Pressable, StyleSheet, Text, View } from "react-native";
import { bubbleLabel, type ChatItem, type DisplayMessage } from "../format/messages";
import { translate } from "../i18n";
import { mentionsAny } from "../markdown/parse";
import { FONT_SIZE, MAX_FONT_SCALE, MIN_TOUCH_TARGET, RADIUS, SPACING, useColors } from "../theme";
import { Markdown } from "./Markdown";

export const BUBBLE_MAX_WIDTH = "75%";
export const SERIES_GAP = 2;
const TAIL_RADIUS = 4; // the corner next to the tail, as on iMessage
const BUBBLE_PADDING_VERTICAL = 8;
const BUBBLE_PADDING_HORIZONTAL = 12;
const MENTION_BORDER_WIDTH = 2; // the non-color cue of a bubble that mentions the boss

type BubbleItem = Extract<ChatItem, { kind: "bubble" }>;
type Props = {
  item: BubbleItem;
  title?: string; // the author's job title
  selfNames: string[]; // the names that mention the boss
  onRetry: (key: string) => void;
  onMenu: (message: DisplayMessage) => void; // long press: the Copy / Info sheet
  onCopy: (message: DisplayMessage) => void; // screen reader action, so copying needs no gesture
};

/** One bubble: boss on the right in blue, the team on the left with the author's name and title. */
export function MessageBubble({ item, title, selfNames, onRetry, onMenu, onCopy }: Props) {
  const colors = useColors();
  const { message, showAuthor, tail, firstInSeries } = item;
  const failed = message.status === "failed";
  const sending = message.status === "sending";
  const forBoss = !message.own && mentionsAny(message.content, selfNames);
  const sentBackground = sending ? colors.sendingBubble : colors.sentBubble;
  const receivedBackground = forBoss ? colors.mentionedBubble : colors.receivedBubble;
  const background = message.own ? sentBackground : receivedBackground;
  const textColor = message.own ? colors.sentBubbleText : colors.text;
  const linkColor = message.own ? colors.sentBubbleText : colors.link;
  const tailCorner = message.own ? { borderBottomRightRadius: TAIL_RADIUS } : { borderBottomLeftRadius: TAIL_RADIUS };
  const actionable = !failed && !sending;
  const label = bubbleLabel(message);

  const bubble = (
    <Pressable
      accessible={!failed}
      accessibilityLabel={failed ? undefined : forBoss ? `${translate("conversation.mentionsYou")}, ${label}` : label}
      accessibilityActions={
        actionable
          ? [
              { name: "copy", label: translate("conversation.copy") },
              { name: "info", label: translate("conversation.messageInfo") },
            ]
          : undefined
      }
      onAccessibilityAction={(event) => (event.nativeEvent.actionName === "copy" ? onCopy(message) : onMenu(message))}
      onLongPress={actionable ? () => onMenu(message) : undefined}
      style={[
        styles.bubble,
        { backgroundColor: background },
        forBoss && { borderWidth: MENTION_BORDER_WIDTH, borderColor: colors.link },
        tail && tailCorner,
      ]}
    >
      {message.isRequest ? (
        <Text maxFontSizeMultiplier={MAX_FONT_SCALE} style={[styles.request, { color: textColor }]}>
          {translate("conversation.request")}
        </Text>
      ) : null}
      <Markdown content={message.content} selfNames={selfNames} color={textColor} linkColor={linkColor} />
    </Pressable>
  );

  return (
    <View style={[styles.row, message.own ? styles.own : styles.received, { marginTop: firstInSeries ? SPACING.sm : SERIES_GAP }]}>
      {showAuthor ? (
        <Text maxFontSizeMultiplier={MAX_FONT_SCALE} style={[styles.author, { color: colors.secondaryText }]}>
          {message.author}
          {title ? ` · ${title}` : ""}
        </Text>
      ) : null}
      {failed ? (
        <Pressable onPress={() => onRetry(message.key)} accessibilityRole="button" accessibilityLabel={bubbleLabel(message)} style={styles.retry}>
          {bubble}
        </Pressable>
      ) : (
        bubble
      )}
      {failed ? (
        <Text
          accessibilityElementsHidden
          importantForAccessibility="no-hide-descendants"
          maxFontSizeMultiplier={MAX_FONT_SCALE}
          style={[styles.failure, { color: colors.error }]}
        >
          {"! "}
          {translate("conversation.sendFailed")}
        </Text>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  row: { paddingHorizontal: SPACING.lg },
  own: { alignItems: "flex-end" },
  received: { alignItems: "flex-start" },
  bubble: {
    maxWidth: BUBBLE_MAX_WIDTH,
    paddingVertical: BUBBLE_PADDING_VERTICAL,
    paddingHorizontal: BUBBLE_PADDING_HORIZONTAL,
    borderRadius: RADIUS.bubble,
  },
  request: { fontSize: FONT_SIZE.caption, fontWeight: "700", marginBottom: SPACING.xs },
  author: { fontSize: FONT_SIZE.caption, marginLeft: SPACING.md, marginBottom: SERIES_GAP },
  retry: { maxWidth: "100%", minHeight: MIN_TOUCH_TARGET / 2, alignItems: "flex-end" },
  failure: { fontSize: FONT_SIZE.caption, marginTop: SERIES_GAP, textAlign: "right" },
});
