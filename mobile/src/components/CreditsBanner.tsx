import { StyleSheet, Text, View } from "react-native";
import { formatResetTime } from "../format/conversations";
import { useAppShell } from "../hooks/useAppShell";
import { translate } from "../i18n";
import { FONT_SIZE, MAX_FONT_SCALE, RADIUS, SPACING, useColors } from "../theme";

/** Claude accounts out of credits and when they come back; renders nothing while all accounts have credits. */
export function CreditsBanner() {
  const colors = useColors();
  const { exhausted, claudeAccounts } = useAppShell();
  if (exhausted.length === 0) return null;
  const perAccount = claudeAccounts > 1;
  return (
    <View
      accessibilityRole="alert"
      accessibilityLiveRegion="polite"
      style={[styles.banner, { backgroundColor: colors.secondaryBackground }]}
    >
      <Text maxFontSizeMultiplier={MAX_FONT_SCALE} style={[styles.title, { color: colors.error }]}>
        {translate("credits.title")}
      </Text>
      {exhausted.map((a) => {
        const time = formatResetTime(a.resets_at);
        const text = perAccount
          ? a.estimated
            ? translate("credits.backAroundAccount", { account: a.account, time })
            : translate("credits.backAtAccount", { account: a.account, time })
          : a.estimated
            ? translate("credits.backAround", { time })
            : translate("credits.backAt", { time });
        return (
          <Text key={a.account} maxFontSizeMultiplier={MAX_FONT_SCALE} style={[styles.line, { color: colors.text }]}>
            {text}
          </Text>
        );
      })}
    </View>
  );
}

const styles = StyleSheet.create({
  banner: { marginHorizontal: SPACING.lg, marginVertical: SPACING.sm, padding: SPACING.md, borderRadius: RADIUS.button, gap: SPACING.xs },
  title: { fontSize: FONT_SIZE.body, fontWeight: "700" },
  line: { fontSize: FONT_SIZE.body },
});
