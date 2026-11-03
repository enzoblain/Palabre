import { Pressable, StyleSheet, Text, View } from "react-native";
import { translate } from "../i18n";
import { FONT_SIZE, MIN_TOUCH_TARGET, RADIUS, SPACING, useColors } from "../theme";

type Props = { message: string; onRetry: () => void };

/** Error text (never on a bubble) with a "Try again" button; announced when it appears. */
export function ErrorBanner({ message, onRetry }: Props) {
  const colors = useColors();
  return (
    <View
      accessibilityRole="alert"
      accessibilityLiveRegion="polite"
      style={[styles.banner, { backgroundColor: colors.secondaryBackground }]}
    >
      <Text maxFontSizeMultiplier={2} style={[styles.message, { color: colors.error }]}>
        {message}
      </Text>
      <Pressable accessibilityRole="button" onPress={onRetry} style={styles.button}>
        <Text maxFontSizeMultiplier={2} style={[styles.retry, { color: colors.sentBubble }]}>
          {translate("common.retry")}
        </Text>
      </Pressable>
    </View>
  );
}

const styles = StyleSheet.create({
  banner: {
    flexDirection: "row",
    alignItems: "center",
    marginHorizontal: SPACING.lg,
    marginVertical: SPACING.sm,
    paddingLeft: SPACING.md,
    borderRadius: RADIUS.button,
  },
  message: { flex: 1, fontSize: FONT_SIZE.body, paddingVertical: SPACING.sm },
  button: { minHeight: MIN_TOUCH_TARGET, justifyContent: "center", paddingHorizontal: SPACING.md },
  retry: { fontSize: FONT_SIZE.body, fontWeight: "600" },
});
