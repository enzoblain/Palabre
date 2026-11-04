import { StyleSheet, View } from "react-native";
import { translate } from "../i18n";
import { RADIUS, SPACING, useColors } from "../theme";

const DOT_SIZE = 8;
const DOT_COUNT = 3;

/** The three dots of a received bubble, shown while the lead is writing. */
export function TypingDots({ name }: { name: string }) {
  const colors = useColors();
  return (
    <View
      accessible
      accessibilityRole="text"
      accessibilityLiveRegion="polite"
      accessibilityLabel={translate("conversation.typing", { name })}
      style={styles.row}
    >
      <View style={[styles.bubble, { backgroundColor: colors.receivedBubble }]}>
        {Array.from({ length: DOT_COUNT }, (_, index) => (
          <View key={index} style={[styles.dot, { backgroundColor: colors.secondaryText }]} />
        ))}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  row: { alignSelf: "flex-start", paddingHorizontal: SPACING.md, marginTop: SPACING.sm },
  bubble: { flexDirection: "row", gap: SPACING.xs, paddingVertical: SPACING.md, paddingHorizontal: SPACING.lg, borderRadius: RADIUS.bubble },
  dot: { width: DOT_SIZE, height: DOT_SIZE, borderRadius: DOT_SIZE / 2 },
});
