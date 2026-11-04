import { ScrollView, StyleSheet, Text } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { AccountsSection } from "../../src/components/settings/AccountsSection";
import { BossNameSection } from "../../src/components/settings/BossNameSection";
import { DevicesSection } from "../../src/components/settings/DevicesSection";
import { LanguageSection } from "../../src/components/settings/LanguageSection";
import { ServerSection } from "../../src/components/settings/ServerSection";
import { ErrorBanner } from "../../src/components/ErrorBanner";
import { useAppSettings } from "../../src/hooks/useAppSettings";
import { translate } from "../../src/i18n";
import { FONT_SIZE, MAX_FONT_SCALE, SPACING, useColors } from "../../src/theme";
import { getConnection } from "../../src/api";
import { useSession } from "../../src/session";

const SCREEN_EDGES = ["top", "left", "right"] as const; // the tab bar owns the bottom safe area

/** Settings, as the web page: boss name, team language, paired devices, Claude accounts and the server. */
export default function SettingsScreen() {
  const colors = useColors();
  const { signOut } = useSession();
  const connection = getConnection();
  const { settings, failed, reload, save } = useAppSettings();
  return (
    <SafeAreaView edges={SCREEN_EDGES} style={[styles.screen, { backgroundColor: colors.background }]}>
      <ScrollView keyboardShouldPersistTaps="handled" contentContainerStyle={styles.content}>
        <Text accessibilityRole="header" maxFontSizeMultiplier={MAX_FONT_SCALE} style={[styles.title, { color: colors.text }]}>
          {translate("nav.settings")}
        </Text>
        {failed ? <ErrorBanner message={translate("settings.error")} onRetry={() => void reload()} /> : null}
        {settings === null && !failed ? (
          <Text accessibilityRole="progressbar" maxFontSizeMultiplier={MAX_FONT_SCALE} style={[styles.loading, { color: colors.secondaryText }]}>
            {translate("settings.loading")}
          </Text>
        ) : null}
        {settings ? (
          <>
            <BossNameSection bossName={settings.boss_name} onSave={(name) => save({ boss_name: name })} />
            <LanguageSection settings={settings} onSave={(language) => save({ language })} />
          </>
        ) : null}
        <DevicesSection />
        {settings ? <AccountsSection count={settings.claude_accounts} /> : null}
        {connection ? <ServerSection server={connection.server} onDisconnect={() => void signOut()} /> : null}
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1 },
  content: { paddingBottom: SPACING.xl },
  title: { fontSize: FONT_SIZE.largeTitle, fontWeight: "700", paddingHorizontal: SPACING.lg, paddingTop: SPACING.sm },
  loading: { fontSize: FONT_SIZE.body, padding: SPACING.lg },
});
