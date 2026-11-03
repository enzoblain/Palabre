import { StyleSheet, Text, View } from "react-native";
import { FONT_SIZE, SPACING, useColors } from "../theme";

type Props = { title: string; message: string };

/** Empty screen the next tasks replace with the real content. */
export function Placeholder({ title, message }: Props) {
  const colors = useColors();
  return (
    <View style={[styles.container, { backgroundColor: colors.background }]}>
      <Text accessibilityRole="header" style={[styles.title, { color: colors.text }]}>
        {title}
      </Text>
      <Text style={[styles.message, { color: colors.secondaryText }]}>{message}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, padding: SPACING.lg, gap: SPACING.sm },
  title: { fontSize: FONT_SIZE.largeTitle, fontWeight: "700" },
  message: { fontSize: FONT_SIZE.body },
});
