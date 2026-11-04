import { ActivityIndicator, Pressable, StyleSheet, Text, View } from "react-native";
import { translate } from "../i18n";
import { BUTTON_HEIGHT, FONT_SIZE, MAX_FONT_SCALE, RADIUS, SPACING, useColors } from "../theme";

type Props = { count: number; busy: boolean; error: string | null; onDelete: () => void };

/** Bottom bar of the edit mode: a labelled destructive button (never swipe-only), disabled until a project is ticked. */
export function DeleteBar({ count, busy, error, onDelete }: Props) {
  const colors = useColors();
  const disabled = count === 0 || busy;
  return (
    <View style={[styles.bar, { borderTopColor: colors.separator, backgroundColor: colors.background }]}>
      {error ? (
        <Text accessibilityRole="alert" maxFontSizeMultiplier={MAX_FONT_SCALE} style={[styles.error, { color: colors.error }]}>
          {error}
        </Text>
      ) : null}
      <Pressable
        accessibilityRole="button"
        accessibilityState={{ disabled, busy }}
        disabled={disabled}
        onPress={onDelete}
        style={[styles.button, { backgroundColor: colors.error, opacity: disabled ? 0.5 : 1 }]}
      >
        {busy ? (
          <ActivityIndicator color={colors.background} />
        ) : (
          <Text maxFontSizeMultiplier={MAX_FONT_SCALE} style={[styles.label, { color: colors.background }]}>
            {translate("list.deleteSelected", { count })}
          </Text>
        )}
      </Pressable>
    </View>
  );
}

const styles = StyleSheet.create({
  bar: { padding: SPACING.lg, gap: SPACING.sm, borderTopWidth: StyleSheet.hairlineWidth },
  error: { fontSize: FONT_SIZE.body },
  button: { minHeight: BUTTON_HEIGHT, borderRadius: RADIUS.button, alignItems: "center", justifyContent: "center" },
  label: { fontSize: FONT_SIZE.body, fontWeight: "600" },
});
