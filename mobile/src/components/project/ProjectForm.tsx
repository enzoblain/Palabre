import { useState } from "react";
import { StyleSheet, Text, TextInput } from "react-native";
import { ApiError, api, type ProjectDetail } from "../../api";
import { translate } from "../../i18n";
import { FONT_SIZE, MAX_FONT_SCALE, MIN_TOUCH_TARGET, RADIUS, SPACING, useColors } from "../../theme";
import { ActionButton } from "../settings/ActionButton";
import { SettingsSection } from "../settings/SettingsSection";
import { StatusText, type Outcome } from "../settings/StatusText";

export const PROJECT_NAME_MAX_LENGTH = 100;

type Props = { detail: ProjectDetail; onSaved: () => void };

/** Name and main branch of the project, saved together; the backend reports a missing branch. */
export function ProjectForm({ detail, onSaved }: Props) {
  const colors = useColors();
  const [name, setName] = useState(detail.name);
  const [branch, setBranch] = useState(detail.default_branch);
  const [saving, setSaving] = useState(false);
  const [outcome, setOutcome] = useState<Outcome | null>(null);
  // Follow the saved values when they change under the fields (derived state, no effect)
  const [synced, setSynced] = useState({ name: detail.name, branch: detail.default_branch });
  if (synced.name !== detail.name || synced.branch !== detail.default_branch) {
    setSynced({ name: detail.name, branch: detail.default_branch });
    setName(detail.name);
    setBranch(detail.default_branch);
  }

  const trimmedName = name.trim();
  const trimmedBranch = branch.trim();
  const changed = trimmedName !== detail.name || trimmedBranch !== detail.default_branch;

  const save = async () => {
    setSaving(true);
    setOutcome(null);
    try {
      const updated = await api.updateProject(detail.id, {
        ...(trimmedName !== detail.name ? { name: trimmedName } : {}),
        ...(trimmedBranch !== detail.default_branch ? { main_branch: trimmedBranch } : {}),
      });
      setOutcome(updated.warning ? { ok: false, text: updated.warning } : { ok: true, text: translate("project.saved") });
      onSaved();
    } catch (err) {
      setOutcome({ ok: false, text: err instanceof ApiError ? err.message : String(err) });
    } finally {
      setSaving(false);
    }
  };

  return (
    <SettingsSection title={translate("project.details")}>
      <TextInput
        accessibilityLabel={translate("project.name")}
        value={name}
        onChangeText={setName}
        maxLength={PROJECT_NAME_MAX_LENGTH}
        returnKeyType="done"
        maxFontSizeMultiplier={MAX_FONT_SCALE}
        placeholderTextColor={colors.secondaryText}
        style={[styles.input, { backgroundColor: colors.background, color: colors.text }]}
      />
      <TextInput
        accessibilityLabel={translate("project.branch")}
        accessibilityHint={translate("project.branchHint")}
        value={branch}
        onChangeText={setBranch}
        autoCapitalize="none"
        autoCorrect={false}
        spellCheck={false}
        returnKeyType="done"
        maxFontSizeMultiplier={MAX_FONT_SCALE}
        placeholderTextColor={colors.secondaryText}
        style={[styles.input, { backgroundColor: colors.background, color: colors.text }]}
      />
      <Text maxFontSizeMultiplier={MAX_FONT_SCALE} style={[styles.hint, { color: colors.secondaryText }]}>
        {translate("project.branchHint")}
      </Text>
      <ActionButton
        label={saving ? translate("project.saving") : translate("common.save")}
        disabled={saving || !changed || !trimmedName || !trimmedBranch}
        onPress={() => void save()}
      />
      <StatusText outcome={outcome} />
    </SettingsSection>
  );
}

const styles = StyleSheet.create({
  input: { minHeight: MIN_TOUCH_TARGET, paddingHorizontal: SPACING.md, borderRadius: RADIUS.input, fontSize: FONT_SIZE.body },
  hint: { fontSize: FONT_SIZE.caption },
});
