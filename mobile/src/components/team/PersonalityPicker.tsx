import { useState } from "react";
import { Pressable, ScrollView, StyleSheet, Text, View } from "react-native";
import type { PersonalityPreset } from "../../api";
import { RANDOM_PRESET, filterPresets } from "../../format/team";
import { translate } from "../../i18n";
import { FONT_SIZE, MAX_FONT_SCALE, MIN_TOUCH_TARGET, SPACING, useColors } from "../../theme";
import { SearchField } from "./SearchField";

type Props = {
  presets: Record<string, PersonalityPreset>;
  selected: string | null;
  onSelect: (presetKey: string | null) => void;
};

/** Single-choice list of the catalog's personalities (name and one-line description), searchable, or a random one. */
export function PersonalityPicker({ presets, selected, onSelect }: Props) {
  const colors = useColors();
  const [query, setQuery] = useState("");
  const matches = filterPresets(presets, query);
  const value = selected && presets[selected] ? selected : RANDOM_PRESET;
  const options = [{ key: RANDOM_PRESET, label: translate("presets.random"), description: translate("presets.randomHelp") }, ...matches];
  const status = Object.keys(presets).length === 0 ? translate("presets.none") : matches.length === 0 ? translate("presets.noMatch") : "";

  return (
    <>
      <SearchField value={query} placeholder={translate("presets.searchPlaceholder")} onChange={setQuery} />
      <ScrollView keyboardShouldPersistTaps="handled">
        {options.map(({ key, label, description }) => {
          const checked = value === key;
          return (
            <Pressable
              key={key}
              accessibilityRole="radio"
              accessibilityState={{ selected: checked, checked }}
              accessibilityLabel={`${label}. ${description}`}
              onPress={() => onSelect(key === RANDOM_PRESET ? null : key)}
              style={[styles.row, { borderBottomColor: colors.separator }]}
            >
              <Text accessible={false} style={[styles.radio, { color: colors.link }]}>{checked ? "◉" : "○"}</Text>
              <View style={styles.text}>
                <Text maxFontSizeMultiplier={MAX_FONT_SCALE} style={[styles.label, { color: colors.text }]}>{label}</Text>
                <Text maxFontSizeMultiplier={MAX_FONT_SCALE} style={[styles.description, { color: colors.secondaryText }]}>{description}</Text>
              </View>
            </Pressable>
          );
        })}
        {status ? (
          <Text accessibilityLiveRegion="polite" maxFontSizeMultiplier={MAX_FONT_SCALE} style={[styles.status, { color: colors.secondaryText }]}>
            {status}
          </Text>
        ) : null}
      </ScrollView>
    </>
  );
}

const styles = StyleSheet.create({
  row: { minHeight: MIN_TOUCH_TARGET, flexDirection: "row", alignItems: "center", gap: SPACING.md, padding: SPACING.lg, borderBottomWidth: StyleSheet.hairlineWidth },
  radio: { fontSize: FONT_SIZE.body + 4 },
  text: { flex: 1 },
  label: { fontSize: FONT_SIZE.body, fontWeight: "600" },
  description: { fontSize: 15 },
  status: { fontSize: FONT_SIZE.body, padding: SPACING.lg },
});
