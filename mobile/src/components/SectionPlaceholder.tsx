import { StyleSheet, Text } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { translate } from "../i18n";
import { FONT_SIZE, MAX_FONT_SCALE, SPACING, useColors } from "../theme";

const SCREEN_EDGES = ["top", "left", "right"] as const; // the tab bar owns the bottom safe area

/** Root section whose content is not built yet: a title and a short notice, so its tab already works. */
export function SectionPlaceholder({ title }: { title: "nav.newProject" | "nav.settings" }) {
  const colors = useColors();
  return (
    <SafeAreaView edges={SCREEN_EDGES} style={[styles.screen, { backgroundColor: colors.background }]}>
      <Text accessibilityRole="header" maxFontSizeMultiplier={MAX_FONT_SCALE} style={[styles.title, { color: colors.text }]}>
        {translate(title)}
      </Text>
      <Text maxFontSizeMultiplier={MAX_FONT_SCALE} style={[styles.notice, { color: colors.secondaryText }]}>
        {translate("section.soon")}
      </Text>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1 },
  title: { fontSize: FONT_SIZE.largeTitle, fontWeight: "700", paddingHorizontal: SPACING.lg, paddingTop: SPACING.sm },
  notice: { fontSize: FONT_SIZE.body, padding: SPACING.lg },
});
