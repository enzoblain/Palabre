import { useState } from "react";
import { Pressable, StyleSheet, Text } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { ApiError, type AppSettings } from "../../api";
import { translate } from "../../i18n";
import { FONT_SIZE, MAX_FONT_SCALE, MIN_TOUCH_TARGET, SPACING, useColors } from "../../theme";
import { SettingsSection } from "./SettingsSection";
import { StatusText, type Outcome } from "./StatusText";

type Props = { settings: AppSettings; onSave: (language: string) => Promise<void> };

/** Team language: one radio row per server language, saved as soon as it is picked. */
export function LanguageSection({ settings, onSave }: Props) {
  const colors = useColors();
  const [outcome, setOutcome] = useState<Outcome | null>(null);

  const pick = async (language: string) => {
    setOutcome(null);
    try {
      await onSave(language);
      setOutcome({ ok: true, text: translate("settings.languageSaved") });
    } catch (err) {
      setOutcome({ ok: false, text: err instanceof ApiError ? err.message : String(err) });
    }
  };

  return (
    <SettingsSection title={translate("settings.language")} intro={translate("settings.languageIntro")}>
      {Object.entries(settings.languages).map(([key, label]) => {
        const selected = key === settings.language;
        return (
          <Pressable
            key={key}
            accessibilityRole="radio"
            accessibilityState={{ selected, checked: selected }}
            accessibilityLabel={label}
            onPress={() => void pick(key)}
            style={styles.row}
          >
            <Text maxFontSizeMultiplier={MAX_FONT_SCALE} style={[styles.label, { color: colors.text }]}>
              {label}
            </Text>
            {selected ? <Ionicons accessible={false} name="checkmark" size={22} color={colors.link} /> : null}
          </Pressable>
        );
      })}
      <StatusText outcome={outcome} />
    </SettingsSection>
  );
}

const styles = StyleSheet.create({
  row: { minHeight: MIN_TOUCH_TARGET, flexDirection: "row", alignItems: "center", justifyContent: "space-between", gap: SPACING.md },
  label: { flex: 1, fontSize: FONT_SIZE.body },
});
