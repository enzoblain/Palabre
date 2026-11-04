import { useEffect, useRef, useState } from "react";
import { Alert, StyleSheet, Text, View } from "react-native";
import { ApiError, api, type Device } from "../../api";
import { formatDateTime, neverUsed, withoutDevice } from "../../format/settings";
import { translate } from "../../i18n";
import { FONT_SIZE, MAX_FONT_SCALE, SPACING, useColors } from "../../theme";
import { ErrorBanner } from "../ErrorBanner";
import { ActionButton } from "./ActionButton";
import { SettingsSection } from "./SettingsSection";
import { StatusText, type Outcome } from "./StatusText";

const errorText = (err: unknown): string => (err instanceof ApiError ? err.message : String(err));

/** The phones paired with the server, each revocable after a confirmation. */
export function DevicesSection() {
  const colors = useColors();
  const [devices, setDevices] = useState<Device[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [outcome, setOutcome] = useState<Outcome | null>(null);
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    api
      .listDevices()
      .then((loaded) => mounted.current && setDevices(loaded))
      .catch((err: unknown) => mounted.current && setLoadError(errorText(err)));
  }, [attempt]);
  const retry = () => {
    setLoadError(null);
    setAttempt((count) => count + 1);
  };

  const revoke = async (device: Device) => {
    try {
      await api.revokeDevice(device.id);
      if (!mounted.current) return;
      setDevices((current) => current && withoutDevice(current, device.id));
      setOutcome({ ok: true, text: translate("settings.deviceRevoked") });
    } catch (err) {
      if (mounted.current) setOutcome({ ok: false, text: translate("settings.deviceRevokeFailed", { message: errorText(err) }) });
    }
  };

  const confirmRevoke = (device: Device) => {
    setOutcome(null);
    Alert.alert(translate("settings.deviceRevokeTitle", { name: device.name }), translate("settings.deviceRevokeMessage"), [
      { text: translate("common.cancel"), style: "cancel" },
      { text: translate("settings.deviceRevoke"), style: "destructive", onPress: () => void revoke(device) },
    ]);
  };

  return (
    <SettingsSection title={translate("settings.devices")} intro={translate("settings.devicesIntro")}>
      {devices === null && !loadError ? (
        <Text accessibilityRole="progressbar" maxFontSizeMultiplier={MAX_FONT_SCALE} style={[styles.line, { color: colors.secondaryText }]}>
          {translate("settings.devicesLoading")}
        </Text>
      ) : null}
      {loadError ? <ErrorBanner message={translate("settings.devicesError", { message: loadError })} onRetry={retry} /> : null}
      {devices?.length === 0 ? (
        <Text maxFontSizeMultiplier={MAX_FONT_SCALE} style={[styles.line, { color: colors.secondaryText }]}>
          {translate("settings.devicesEmpty")}
        </Text>
      ) : null}
      {devices?.map((device) => (
        <View key={device.id} style={[styles.device, { borderTopColor: colors.separator }]}>
          <Text maxFontSizeMultiplier={MAX_FONT_SCALE} style={[styles.name, { color: colors.text }]}>
            {device.name}
          </Text>
          <Text maxFontSizeMultiplier={MAX_FONT_SCALE} style={[styles.line, { color: colors.secondaryText }]}>
            {translate("settings.deviceAdded", { date: formatDateTime(device.created_at) })}
          </Text>
          <Text maxFontSizeMultiplier={MAX_FONT_SCALE} style={[styles.line, { color: colors.secondaryText }]}>
            {translate("settings.deviceLastUsed", {
              date: neverUsed(device) ? translate("settings.deviceNeverUsed") : formatDateTime(device.last_used_at),
            })}
          </Text>
          <Text maxFontSizeMultiplier={MAX_FONT_SCALE} style={[styles.line, { color: colors.secondaryText }]}>
            {translate("settings.deviceExpires", { date: formatDateTime(device.expires_at) })}
          </Text>
          <ActionButton
            destructive
            label={translate("settings.deviceRevoke")}
            accessibilityLabel={translate("settings.deviceRevokeAria", { name: device.name })}
            onPress={() => confirmRevoke(device)}
          />
        </View>
      ))}
      <StatusText outcome={outcome} />
    </SettingsSection>
  );
}

const styles = StyleSheet.create({
  device: { borderTopWidth: StyleSheet.hairlineWidth, paddingTop: SPACING.sm },
  name: { fontSize: FONT_SIZE.body, fontWeight: "600" },
  line: { fontSize: FONT_SIZE.body },
});
