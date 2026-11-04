import { StyleSheet, Text } from "react-native";
import { FONT_SIZE, MAX_FONT_SCALE, useColors } from "../../theme";

export type Outcome = { ok: boolean; text: string };

/** Result of an action, announced to screen readers when it appears. */
export function StatusText({ outcome }: { outcome: Outcome | null }) {
  const colors = useColors();
  if (!outcome) return null;
  return (
    <Text
      accessibilityRole={outcome.ok ? undefined : "alert"}
      accessibilityLiveRegion="polite"
      maxFontSizeMultiplier={MAX_FONT_SCALE}
      style={[styles.text, { color: outcome.ok ? colors.success : colors.error }]}
    >
      {outcome.text}
    </Text>
  );
}

const styles = StyleSheet.create({ text: { fontSize: FONT_SIZE.body } });
