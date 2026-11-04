import { useLocalSearchParams, useRouter } from "expo-router";
import { Linking, Pressable, ScrollView, StyleSheet, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { DeleteProject } from "../../src/components/project/DeleteProject";
import { ProjectForm } from "../../src/components/project/ProjectForm";
import { ErrorBanner } from "../../src/components/ErrorBanner";
import { SettingsSection } from "../../src/components/settings/SettingsSection";
import { useProject } from "../../src/hooks/useProject";
import { translate } from "../../src/i18n";
import { isOpenableLink } from "../../src/markdown/parse";
import { FONT_SIZE, MAX_FONT_SCALE, MIN_TOUCH_TARGET, SPACING, useColors } from "../../src/theme";

/** Own page of a project, as the web one: name, main branch, description, git link and deletion. */
export default function ProjectScreen() {
  const colors = useColors();
  const router = useRouter();
  const { id } = useLocalSearchParams<{ id: string }>();
  const { detail, failed, reload } = useProject(Number(id));
  // The boss's objective for the project lives on the direction room
  const description = (detail?.rooms.find((room) => room.kind === "direction") ?? detail?.rooms[0])?.objective.trim();
  const openRepo = (url: string) => {
    if (isOpenableLink(url)) void Linking.openURL(url).catch(() => {});
  };

  return (
    <SafeAreaView style={[styles.screen, { backgroundColor: colors.background }]}>
      <View style={[styles.bar, { borderBottomColor: colors.separator }]}>
        <Pressable accessibilityRole="button" accessibilityLabel={translate("common.back")} onPress={() => router.back()} style={styles.back}>
          <Text maxFontSizeMultiplier={MAX_FONT_SCALE} style={[styles.body, { color: colors.link }]}>
            {"‹ "}
            {translate("common.back")}
          </Text>
        </Pressable>
        <Text accessibilityRole="header" numberOfLines={1} maxFontSizeMultiplier={MAX_FONT_SCALE} style={[styles.title, { color: colors.text }]}>
          {detail?.name ?? translate("project.title")}
        </Text>
      </View>
      <ScrollView keyboardShouldPersistTaps="handled" contentContainerStyle={styles.content}>
        {failed ? <ErrorBanner message={translate("project.error")} onRetry={() => void reload()} /> : null}
        {detail === null && !failed ? (
          <Text accessibilityRole="progressbar" maxFontSizeMultiplier={MAX_FONT_SCALE} style={[styles.body, styles.loading, { color: colors.secondaryText }]}>
            {translate("project.loading")}
          </Text>
        ) : null}
        {detail ? (
          <>
            <ProjectForm detail={detail} onSaved={() => void reload()} />
            <SettingsSection title={translate("project.description")}>
              <Text maxFontSizeMultiplier={MAX_FONT_SCALE} style={[styles.body, { color: description ? colors.text : colors.secondaryText }]}>
                {description || translate("project.noDescription")}
              </Text>
              <Text maxFontSizeMultiplier={MAX_FONT_SCALE} style={[styles.hint, { color: colors.secondaryText }]}>
                {translate("project.descriptionHint")}
              </Text>
            </SettingsSection>
            <SettingsSection title={translate("project.git")}>
              {detail.repo_url ? (
                <Pressable accessibilityRole="link" onPress={() => openRepo(detail.repo_url)} style={styles.link}>
                  <Text maxFontSizeMultiplier={MAX_FONT_SCALE} style={[styles.body, styles.underline, { color: colors.link }]}>
                    {detail.repo_url}
                  </Text>
                </Pressable>
              ) : (
                <Text maxFontSizeMultiplier={MAX_FONT_SCALE} style={[styles.body, { color: colors.secondaryText }]}>
                  {translate("project.noGit")}
                </Text>
              )}
            </SettingsSection>
            <DeleteProject detail={detail} onDeleted={() => router.replace("/")} />
          </>
        ) : null}
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1 },
  bar: { flexDirection: "row", alignItems: "center", minHeight: MIN_TOUCH_TARGET + SPACING.sm, borderBottomWidth: StyleSheet.hairlineWidth },
  back: { minHeight: MIN_TOUCH_TARGET, justifyContent: "center", paddingHorizontal: SPACING.md },
  title: { flex: 1, fontSize: FONT_SIZE.body, fontWeight: "600", paddingRight: SPACING.lg },
  content: { paddingBottom: SPACING.xl },
  body: { fontSize: FONT_SIZE.body },
  hint: { fontSize: FONT_SIZE.caption },
  loading: { padding: SPACING.lg },
  link: { minHeight: MIN_TOUCH_TARGET, justifyContent: "center" },
  underline: { textDecorationLine: "underline" },
});
