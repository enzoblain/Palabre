import { useState } from "react";
import { Pressable, StyleSheet, Text, TextInput, View } from "react-native";
import { translate } from "../i18n";
import { FONT_SIZE, MAX_FONT_SCALE, MIN_TOUCH_TARGET, RADIUS, SPACING, useColors } from "../theme";

export const SEND_BUTTON_SIZE = 32;
export const INPUT_MAX_LINES = 5;
const INPUT_LINE_HEIGHT = 22;
const INPUT_PADDING_VERTICAL = 8;
const SEND_HIT_SLOP = (MIN_TOUCH_TARGET - SEND_BUTTON_SIZE) / 2;

type Props = { onSend: (content: string) => void };

/** Multiline field (up to 5 lines) and the round send button, disabled while the field is empty. */
export function MessageInput({ onSend }: Props) {
  const colors = useColors();
  const [text, setText] = useState("");
  const content = text.trim();

  const submit = () => {
    if (!content) return;
    onSend(content);
    setText("");
  };

  return (
    <View style={[styles.bar, { backgroundColor: colors.background, borderTopColor: colors.separator }]}>
      <TextInput
        accessibilityLabel={translate("conversation.input")}
        placeholder={translate("conversation.input")}
        placeholderTextColor={colors.secondaryText}
        value={text}
        onChangeText={setText}
        multiline
        maxFontSizeMultiplier={MAX_FONT_SCALE}
        style={[styles.field, { backgroundColor: colors.secondaryBackground, color: colors.text }]}
      />
      <Pressable
        accessibilityRole="button"
        accessibilityLabel={translate("conversation.send")}
        accessibilityState={{ disabled: !content }}
        disabled={!content}
        hitSlop={SEND_HIT_SLOP}
        onPress={submit}
        style={[styles.send, { backgroundColor: colors.sentBubble }, !content && styles.disabled]}
      >
        <Text style={[styles.arrow, { color: colors.sentBubbleText }]}>↑</Text>
      </Pressable>
    </View>
  );
}

const styles = StyleSheet.create({
  bar: {
    flexDirection: "row",
    alignItems: "flex-end",
    gap: SPACING.sm,
    paddingHorizontal: SPACING.md,
    paddingVertical: SPACING.sm,
    borderTopWidth: StyleSheet.hairlineWidth,
  },
  field: {
    flex: 1,
    minHeight: MIN_TOUCH_TARGET,
    maxHeight: INPUT_LINE_HEIGHT * INPUT_MAX_LINES + 2 * INPUT_PADDING_VERTICAL,
    paddingHorizontal: SPACING.md,
    paddingVertical: INPUT_PADDING_VERTICAL,
    borderRadius: RADIUS.input,
    fontSize: FONT_SIZE.body,
    lineHeight: INPUT_LINE_HEIGHT,
  },
  send: {
    width: SEND_BUTTON_SIZE,
    height: SEND_BUTTON_SIZE,
    borderRadius: SEND_BUTTON_SIZE / 2,
    alignItems: "center",
    justifyContent: "center",
    marginBottom: (MIN_TOUCH_TARGET - SEND_BUTTON_SIZE) / 2,
  },
  disabled: { opacity: 0.4 },
  arrow: { fontSize: FONT_SIZE.body, fontWeight: "700" },
});
