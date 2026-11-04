import { useState } from "react";
import { Alert, StyleSheet, Text } from "react-native";
import { ApiError, api, type ProjectDetail } from "../../api";
import { translate } from "../../i18n";
import { FONT_SIZE, MAX_FONT_SCALE, useColors } from "../../theme";
import { ActionButton } from "../settings/ActionButton";
import { SettingsSection } from "../settings/SettingsSection";
import { StatusText, type Outcome } from "../settings/StatusText";

type Props = { detail: ProjectDetail; onDeleted: () => void };

/** Destructive button at the bottom of the page: asks for a confirmation before calling the backend. */
export function DeleteProject({ detail, onDeleted }: Props) {
  const colors = useColors();
  const [deleting, setDeleting] = useState(false);
  const [outcome, setOutcome] = useState<Outcome | null>(null);

  const remove = async () => {
    setDeleting(true);
    setOutcome(null);
    try {
      await api.deleteProject(detail.id);
      onDeleted();
    } catch (err) {
      setOutcome({ ok: false, text: err instanceof ApiError ? err.message : String(err) });
      setDeleting(false);
    }
  };

  const confirm = () =>
    Alert.alert(translate("project.deleteConfirmTitle"), translate("project.deleteConfirm", { name: detail.name }), [
      { text: translate("common.cancel"), style: "cancel" },
      { text: translate("project.deleteForGood"), style: "destructive", onPress: () => void remove() },
    ]);

  return (
    <SettingsSection title={translate("project.delete")}>
      <Text maxFontSizeMultiplier={MAX_FONT_SCALE} style={[styles.warning, { color: colors.secondaryText }]}>
        {translate("project.deleteWarning")}
      </Text>
      <ActionButton
        destructive
        label={deleting ? translate("project.deleting") : translate("common.delete")}
        accessibilityLabel={deleting ? translate("project.deleting") : translate("project.delete")}
        disabled={deleting}
        onPress={confirm}
      />
      <StatusText outcome={outcome} />
    </SettingsSection>
  );
}

const styles = StyleSheet.create({ warning: { fontSize: FONT_SIZE.body } });
