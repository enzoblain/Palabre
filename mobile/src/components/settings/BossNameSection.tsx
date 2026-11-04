import { useState } from "react";
import { StyleSheet, Text, TextInput } from "react-native";
import { ApiError } from "../../api";
import { translate } from "../../i18n";
import { FONT_SIZE, MAX_FONT_SCALE, MIN_TOUCH_TARGET, RADIUS, SPACING, useColors } from "../../theme";
import { ActionButton } from "./ActionButton";
import { SettingsSection } from "./SettingsSection";
import { StatusText, type Outcome } from "./StatusText";

const NAME_MAX_LENGTH = 100;

type Props = { bossName: string; onSave: (name: string) => Promise<void> };

/** The name the team uses for the CEO: required before starting, saved only when it changed. */
export function BossNameSection({ bossName, onSave }: Props) {
  const colors = useColors();
  const [name, setName] = useState(bossName);
  const [outcome, setOutcome] = useState<Outcome | null>(null);
  const [saving, setSaving] = useState(false);
  // Follow the saved name when it changes under the field (derived state, no effect)
  const [syncedName, setSyncedName] = useState(bossName);
  if (syncedName !== bossName) {
    setSyncedName(bossName);
    setName(bossName);
  }

  const trimmed = name.trim();
  const save = async () => {
    setSaving(true);
    try {
      await onSave(trimmed);
      setOutcome({ ok: true, text: translate("settings.nameSaved") });
    } catch (err) {
      setOutcome({ ok: false, text: err instanceof ApiError ? err.message : String(err) });
    } finally {
      setSaving(false);
    }
  };

  return (
    <SettingsSection title={translate("settings.you")} intro={translate("settings.youIntro")}>
      {bossName ? null : (
        <Text maxFontSizeMultiplier={MAX_FONT_SCALE} style={[styles.hint, { color: colors.text }]}>
          {translate("settings.nameHint")}
        </Text>
      )}
      <TextInput
        accessibilityLabel={translate("settings.name")}
        placeholder={translate("settings.namePlaceholder")}
        placeholderTextColor={colors.secondaryText}
        value={name}
        onChangeText={setName}
        maxLength={NAME_MAX_LENGTH}
        autoCorrect={false}
        returnKeyType="done"
        maxFontSizeMultiplier={MAX_FONT_SCALE}
        style={[styles.input, { backgroundColor: colors.background, color: colors.text }]}
      />
      <ActionButton
        label={translate("common.save")}
        disabled={saving || !trimmed || trimmed === bossName}
        onPress={() => void save()}
      />
      <StatusText outcome={outcome} />
    </SettingsSection>
  );
}

const styles = StyleSheet.create({
  hint: { fontSize: FONT_SIZE.body, fontWeight: "600" },
  input: { minHeight: MIN_TOUCH_TARGET, paddingHorizontal: SPACING.md, borderRadius: RADIUS.input, fontSize: FONT_SIZE.body },
});
