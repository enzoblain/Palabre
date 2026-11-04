import { StyleSheet, Text, View } from "react-native";
import { translate } from "../i18n";
import { FONT_SIZE, MAX_FONT_SCALE, SPACING, useColors } from "../theme";
import { Markdown } from "./Markdown";

/** A line from the platform: centered, labelled, not a bubble. */
export function SystemMessage({ content }: { content: string }) {
  const colors = useColors();
  return (
    <View accessible accessibilityLabel={`${translate("conversation.platform")}, ${content}`} style={styles.line}>
      <Text maxFontSizeMultiplier={MAX_FONT_SCALE} style={[styles.label, { color: colors.secondaryText }]}>
        {translate("conversation.platform")}
      </Text>
      <Markdown content={content} color={colors.secondaryText} linkColor={colors.link} />
    </View>
  );
}

const styles = StyleSheet.create({
  line: { alignItems: "center", marginVertical: SPACING.sm, paddingHorizontal: SPACING.xl },
  label: { fontSize: FONT_SIZE.caption, fontWeight: "600", textTransform: "uppercase" },
});
