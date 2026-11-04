import { Pressable, StyleSheet, Text } from "react-native";
import { DESTRUCTIVE_TOUCH_TARGET, FONT_SIZE, MAX_FONT_SCALE, SPACING, useColors } from "../../theme";

type Props = {
  label: string;
  onPress: () => void;
  accessibilityLabel?: string;
  destructive?: boolean;
  disabled?: boolean;
};

/** Labelled text button with a touch target large enough for destructive actions on both platforms. */
export function ActionButton({ label, onPress, accessibilityLabel, destructive = false, disabled = false }: Props) {
  const colors = useColors();
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={accessibilityLabel ?? label}
      accessibilityState={{ disabled }}
      disabled={disabled}
      onPress={onPress}
      style={styles.button}
    >
      <Text
        maxFontSizeMultiplier={MAX_FONT_SCALE}
        style={[styles.label, { color: destructive ? colors.error : colors.link }, disabled && styles.disabled]}
      >
        {label}
      </Text>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  button: { minHeight: DESTRUCTIVE_TOUCH_TARGET, justifyContent: "center", alignSelf: "flex-start", paddingRight: SPACING.md },
  label: { fontSize: FONT_SIZE.body, fontWeight: "600" },
  disabled: { opacity: 0.4 },
});
