import { Pressable, StyleSheet, Text, View } from "react-native";
import { bubbleLabel, type ChatItem } from "../format/messages";
import { translate } from "../i18n";
import { FONT_SIZE, MAX_FONT_SCALE, MIN_TOUCH_TARGET, RADIUS, SPACING, useColors } from "../theme";

export const BUBBLE_MAX_WIDTH = "75%";
export const SERIES_GAP = 2;
export const SENDING_OPACITY = 0.6;
const TAIL_RADIUS = 4; // the corner next to the tail, as on iMessage
const BUBBLE_PADDING_VERTICAL = 8;
const BUBBLE_PADDING_HORIZONTAL = 12;

type BubbleItem = Extract<ChatItem, { kind: "bubble" }>;
type Props = { item: BubbleItem; onRetry: (key: string) => void };

/** One bubble: boss on the right in blue, the team on the left with the author's name. */
export function MessageBubble({ item, onRetry }: Props) {
  const colors = useColors();
  const { message, showAuthor, tail, firstInSeries } = item;
  const failed = message.status === "failed";
  const background = message.own ? colors.sentBubble : colors.receivedBubble;
  const textColor = message.own ? colors.sentBubbleText : colors.text;
  const tailCorner = message.own ? { borderBottomRightRadius: TAIL_RADIUS } : { borderBottomLeftRadius: TAIL_RADIUS };

  const bubble = (
    <View
      accessible={!failed}
      accessibilityLabel={failed ? undefined : bubbleLabel(message)}
      style={[
        styles.bubble,
        { backgroundColor: background },
        tail && tailCorner,
        message.status === "sending" && { opacity: SENDING_OPACITY },
      ]}
    >
      {message.isRequest ? (
        <Text maxFontSizeMultiplier={MAX_FONT_SCALE} style={[styles.request, { color: textColor }]}>
          {translate("conversation.request")}
        </Text>
      ) : null}
      <Text maxFontSizeMultiplier={MAX_FONT_SCALE} style={[styles.content, { color: textColor }]}>
        {message.content}
      </Text>
    </View>
  );

  return (
    <View style={[styles.row, message.own ? styles.own : styles.received, { marginTop: firstInSeries ? SPACING.sm : SERIES_GAP }]}>
      {showAuthor ? (
        <Text maxFontSizeMultiplier={MAX_FONT_SCALE} style={[styles.author, { color: colors.secondaryText }]}>
          {message.author}
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
        <Text maxFontSizeMultiplier={MAX_FONT_SCALE} style={[styles.failure, { color: colors.error }]}>
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
  content: { fontSize: FONT_SIZE.body },
  request: { fontSize: FONT_SIZE.caption, fontWeight: "700", marginBottom: SPACING.xs },
  author: { fontSize: FONT_SIZE.caption, marginLeft: SPACING.md, marginBottom: SERIES_GAP },
  retry: { maxWidth: "100%", minHeight: MIN_TOUCH_TARGET / 2, alignItems: "flex-end" },
  failure: { fontSize: FONT_SIZE.caption, marginTop: SERIES_GAP, textAlign: "right" },
});
