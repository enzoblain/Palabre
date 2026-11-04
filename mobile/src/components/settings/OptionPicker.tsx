import { Ionicons } from "@expo/vector-icons";
import { Pressable, ScrollView, StyleSheet, Text } from "react-native";
import { translate } from "../../i18n";
import { CHECKMARK_ICON_SIZE, FONT_SIZE, MAX_FONT_SCALE, MIN_TOUCH_TARGET, SPACING, useColors } from "../../theme";
import { SheetModal } from "../SheetModal";

export type Option<T> = { value: T; label: string };

type ListProps<T> = { options: Option<T>[]; selected: T; onPick: (value: T) => void };

type Props<T> = ListProps<T> & { title: string; visible: boolean; onClose: () => void };

/** The rows of a single-choice list, for a sheet that is already open. */
export function OptionList<T extends string | number | null>({ options, selected, onPick }: ListProps<T>) {
  const colors = useColors();
  return (
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
  );
}

/** Single-choice list in a bottom sheet, for the pickers too long for an alert. */
export function OptionPicker<T extends string | number | null>({ title, visible, onClose, ...list }: Props<T>) {
  return (
    <SheetModal title={title} closeLabel={translate("common.cancel")} visible={visible} onClose={onClose}>
      <OptionList {...list} />
    </SheetModal>
  );
}

const styles = StyleSheet.create({
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
