import { Ionicons } from "@expo/vector-icons";
import { Modal, Pressable, ScrollView, StyleSheet, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { translate } from "../../i18n";
import { CHECKMARK_ICON_SIZE, FONT_SIZE, MAX_FONT_SCALE, MIN_TOUCH_TARGET, SPACING, useColors } from "../../theme";

export type Option<T> = { value: T; label: string };

type Props<T> = {
  title: string;
  options: Option<T>[];
  selected: T;
  visible: boolean;
  onPick: (value: T) => void;
  onClose: () => void;
};

/** Single-choice list in a bottom sheet, for the pickers too long for an alert. */
export function OptionPicker<T extends string | number | null>({ title, options, selected, visible, onPick, onClose }: Props<T>) {
  const colors = useColors();
  return (
    <Modal visible={visible} animationType="slide" presentationStyle="pageSheet" onRequestClose={onClose}>
      <SafeAreaView style={[styles.screen, { backgroundColor: colors.background }]}>
        <View style={[styles.bar, { borderBottomColor: colors.separator }]}>
          <Text accessibilityRole="header" maxFontSizeMultiplier={MAX_FONT_SCALE} style={[styles.title, { color: colors.text }]}>
            {title}
          </Text>
          <Pressable accessibilityRole="button" onPress={onClose} style={styles.close}>
            <Text maxFontSizeMultiplier={MAX_FONT_SCALE} style={[styles.closeText, { color: colors.link }]}>
              {translate("common.cancel")}
            </Text>
          </Pressable>
        </View>
        <ScrollView>
          {options.map((option) => {
            const isSelected = option.value === selected;
            return (
              <Pressable
                key={String(option.value)}
                accessibilityRole="radio"
                accessibilityState={{ selected: isSelected, checked: isSelected }}
                onPress={() => onPick(option.value)}
                style={[styles.row, { borderBottomColor: colors.separator }]}
              >
                <Text maxFontSizeMultiplier={MAX_FONT_SCALE} style={[styles.label, { color: colors.text }]}>
                  {option.label}
                </Text>
                {isSelected ? <Ionicons accessible={false} name="checkmark" size={CHECKMARK_ICON_SIZE} color={colors.link} /> : null}
              </Pressable>
            );
          })}
        </ScrollView>
      </SafeAreaView>
    </Modal>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1 },
  bar: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingLeft: SPACING.lg, borderBottomWidth: StyleSheet.hairlineWidth },
  title: { flex: 1, fontSize: FONT_SIZE.body, fontWeight: "600" },
  close: { minHeight: MIN_TOUCH_TARGET, justifyContent: "center", paddingHorizontal: SPACING.lg },
  closeText: { fontSize: FONT_SIZE.body },
  row: {
    minHeight: MIN_TOUCH_TARGET,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    paddingHorizontal: SPACING.lg,
    borderBottomWidth: StyleSheet.hairlineWidth,
  },
  label: { flex: 1, fontSize: FONT_SIZE.body },
});
