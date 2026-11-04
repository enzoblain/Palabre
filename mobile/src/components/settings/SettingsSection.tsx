import type { ReactNode } from "react";
import { StyleSheet, Text, View } from "react-native";
import { FONT_SIZE, MAX_FONT_SCALE, RADIUS, SPACING, useColors } from "../../theme";

type Props = { title?: string; intro?: string; children: ReactNode };

/** A grouped block of the settings screen: heading, short explanation, then its content. */
export function SettingsSection({ title, intro, children }: Props) {
  const colors = useColors();
  return (
    <View style={styles.section}>
      {title ? (
        <Text accessibilityRole="header" maxFontSizeMultiplier={MAX_FONT_SCALE} style={[styles.heading, { color: colors.secondaryText }]}>
          {title}
        </Text>
      ) : null}
      <View style={[styles.group, { backgroundColor: colors.secondaryBackground }]}>
        {intro ? (
          <Text maxFontSizeMultiplier={MAX_FONT_SCALE} style={[styles.intro, { color: colors.secondaryText }]}>
            {intro}
          </Text>
        ) : null}
        {children}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  section: { marginTop: SPACING.lg },
  heading: { fontSize: FONT_SIZE.caption, fontWeight: "600", textTransform: "uppercase", marginHorizontal: SPACING.lg, marginBottom: SPACING.xs },
  group: { marginHorizontal: SPACING.lg, padding: SPACING.md, borderRadius: RADIUS.button, gap: SPACING.sm },
  intro: { fontSize: FONT_SIZE.body },
});
