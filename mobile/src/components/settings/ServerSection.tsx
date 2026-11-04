import { Alert, StyleSheet, Text } from "react-native";
import { translate } from "../../i18n";
import { FONT_SIZE, MAX_FONT_SCALE, useColors } from "../../theme";
import { ActionButton } from "./ActionButton";
import { SettingsSection } from "./SettingsSection";

type Props = { server: string; onDisconnect: () => void };

/** The connected server and the way out: signing out always asks first. */
export function ServerSection({ server, onDisconnect }: Props) {
  const colors = useColors();
  const confirm = () =>
    Alert.alert(translate("settings.disconnectTitle"), translate("settings.disconnectMessage"), [
      { text: translate("common.cancel"), style: "cancel" },
      { text: translate("settings.disconnect"), style: "destructive", onPress: onDisconnect },
    ]);
  return (
    <SettingsSection title={translate("settings.server")}>
      <Text maxFontSizeMultiplier={MAX_FONT_SCALE} style={[styles.server, { color: colors.text }]}>
        {translate("settings.connectedTo", { server })}
      </Text>
      <ActionButton destructive label={translate("settings.disconnect")} onPress={confirm} />
    </SettingsSection>
  );
}

const styles = StyleSheet.create({ server: { fontSize: FONT_SIZE.body } });
