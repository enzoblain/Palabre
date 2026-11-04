import { StyleSheet, TextInput } from "react-native";
import { FONT_SIZE, MAX_FONT_SCALE, MIN_TOUCH_TARGET, RADIUS, SPACING, useColors } from "../../theme";

type Props = { value: string; placeholder: string; onChange: (value: string) => void };

/** Search box of the pickers. */
export function SearchField({ value, placeholder, onChange }: Props) {
  const colors = useColors();
  return (
    <TextInput
      accessibilityLabel={placeholder}
      placeholder={placeholder}
      placeholderTextColor={colors.secondaryText}
      value={value}
      onChangeText={onChange}
      autoCapitalize="none"
      autoCorrect={false}
      clearButtonMode="while-editing"
      returnKeyType="search"
      maxFontSizeMultiplier={MAX_FONT_SCALE}
      style={[styles.input, { backgroundColor: colors.secondaryBackground, color: colors.text }]}
    />
  );
}

const styles = StyleSheet.create({
  input: { minHeight: MIN_TOUCH_TARGET, margin: SPACING.md, paddingHorizontal: SPACING.md, borderRadius: RADIUS.input, fontSize: FONT_SIZE.body },
});
