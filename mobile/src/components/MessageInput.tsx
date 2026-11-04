import { useState } from "react";
import { Pressable, StyleSheet, Text, TextInput, View } from "react-native";
import { translate } from "../i18n";
import { FONT_SIZE, MAX_FONT_SCALE, MIN_TOUCH_TARGET, RADIUS, SPACING, useColors } from "../theme";

export const SEND_BUTTON_SIZE = 32;
export const INPUT_MAX_LINES = 5;
export const DISABLED_OPACITY = 0.4;
const INPUT_LINE_HEIGHT = 22;
const INPUT_PADDING_VERTICAL = 8;
const SEND_HIT_SLOP = (MIN_TOUCH_TARGET - SEND_BUTTON_SIZE) / 2;

/** A name to insert as "@Name"; `nonce` changes on every request so the same name can be inserted twice. */
export type MentionRequest = { name: string; nonce: number };
type Props = { placeholder: string; mention?: MentionRequest | null; onSend: (content: string) => void };

/** Multiline field (up to 5 lines) and the round send button, disabled while the field is empty. */
export function MessageInput({ placeholder, mention, onSend }: Props) {
  const colors = useColors();
  const [text, setText] = useState("");
  const content = text.trim();

  // A new request is applied while rendering (not in an effect) so the field updates in the same pass.
  const [appliedNonce, setAppliedNonce] = useState(mention?.nonce);
  if (mention && mention.nonce !== appliedNonce) {
    setAppliedNonce(mention.nonce);
    setText(`${text}${text && !text.endsWith(" ") ? " " : ""}@${mention.name} `);
  }

  const submit = () => {
    if (!content) return;
    onSend(content);
    setText("");
  };

  return (
    <View style={[styles.bar, { backgroundColor: colors.background, borderTopColor: colors.separator }]}>
      <TextInput
        accessibilityLabel={translate("conversation.input")}
        placeholder={placeholder}
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
        <Text maxFontSizeMultiplier={MAX_FONT_SCALE} style={[styles.arrow, { color: colors.sentBubbleText }]}>↑</Text>
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
  disabled: { opacity: DISABLED_OPACITY },
  arrow: { fontSize: FONT_SIZE.body, fontWeight: "700" },
});
