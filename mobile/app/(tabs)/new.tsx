import { useRouter } from "expo-router";
import { useState } from "react";
import { KeyboardAvoidingView, Platform, ScrollView, StyleSheet, Text, TextInput } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { ApiError, api, type MemberIn } from "../../src/api";
import { SettingsSection } from "../../src/components/settings/SettingsSection";
import { ActionButton } from "../../src/components/settings/ActionButton";
import { StatusText } from "../../src/components/settings/StatusText";
import { CompanyTeamSection, type CreationMode } from "../../src/components/team/CompanyTeamSection";
import {
  PROJECT_NAME_MAX_LENGTH, autoTeamProblems, isGithubUrl, mandatoryMember, problemMessages, teamBounds, teamProblems,
} from "../../src/format/team";
import { useAppSettings } from "../../src/hooks/useAppSettings";
import { useCatalog } from "../../src/hooks/useCatalog";
import { translate } from "../../src/i18n";
import { FONT_SIZE, MAX_FONT_SCALE, MIN_TOUCH_TARGET, RADIUS, SPACING, useColors } from "../../src/theme";

const SCREEN_EDGES = ["top", "left", "right"] as const; // the tab bar owns the bottom safe area
const DEFAULT_MODE = "startup";

function NewProjectForm({ onCreated }: { onCreated: (projectId: number) => void }) {
  const colors = useColors();
  const router = useRouter();
  const catalog = useCatalog();
  const { settings } = useAppSettings();
  const { limits, roles, presets, names } = catalog;
  const [name, setName] = useState("");
  const [repoUrl, setRepoUrl] = useState("");
  // The team is hired from a description (auto) or listed by hand (manual)
  const [creation, setCreation] = useState<CreationMode>("auto");
  const [description, setDescription] = useState("");
  const [employeeCount, setEmployeeCount] = useState<number | null>(null);
  // Team built by hand (null: the team drawn at random is used)
  const [custom, setCustom] = useState<MemberIn[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  // Manual: the team starts with the mandatory member, who cannot be removed
  const chooseCreation = (next: CreationMode) => {
    setCreation(next);
    if (next === "auto") return setCustom(null);
    if (limits) setCustom((current) => current ?? [mandatoryMember(names, limits.mandatory_role)]);
  };

  const repoValid = isGithubUrl(repoUrl);
  const { minSize, maxSize } = teamBounds(limits);
  // The automatic head count starts at the minimum the server asks for
  const headCount = employeeCount ?? minSize;
  const problemCodes = custom
    ? teamProblems(custom, limits?.mandatory_role ?? null, minSize, maxSize)
    : creation === "auto" ? autoTeamProblems(headCount, minSize, maxSize) : [];
  const problems = problemMessages(problemCodes, minSize, maxSize);
  const teamReady = !!limits && (creation === "auto" || !!custom);
  const canSubmit = !busy && teamReady && !!name.trim() && repoValid && (creation !== "auto" || !!description.trim()) && problems.length === 0;

  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      const project = await api.createProject({
        name: name.trim(),
        mode: DEFAULT_MODE,
        repo_url: repoUrl.trim(),
        creation_mode: creation,
        ...(creation === "auto" ? { description: description.trim(), employee_count: headCount } : {}),
        ...(custom ? { employees: custom.map((member) => ({ ...member, name: member.name.trim() })) } : {}),
      });
      onCreated(project.id);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
      setBusy(false);
    }
  };

  const inputStyle = [styles.input, { backgroundColor: colors.background, color: colors.text }];
  return (
    <>
      <SettingsSection title={translate("new.sectionProject")}>
        <TextInput
          accessibilityLabel={translate("new.name")}
          placeholder={translate("new.namePlaceholderProject")}
          placeholderTextColor={colors.secondaryText}
          value={name}
          onChangeText={setName}
          maxLength={PROJECT_NAME_MAX_LENGTH}
          maxFontSizeMultiplier={MAX_FONT_SCALE}
          style={inputStyle}
        />
        <TextInput
          accessibilityLabel={translate("new.repo")}
          placeholder={translate("new.repoPlaceholder")}
          placeholderTextColor={colors.secondaryText}
          value={repoUrl}
          onChangeText={setRepoUrl}
          autoCapitalize="none"
          autoCorrect={false}
          keyboardType="url"
          maxFontSizeMultiplier={MAX_FONT_SCALE}
          style={inputStyle}
        />
        {repoUrl && !repoValid ? <StatusText outcome={{ ok: false, text: translate("new.repoInvalid") }} /> : null}
      </SettingsSection>
      <CompanyTeamSection
        creation={creation} onCreationChange={chooseCreation}
        description={description} onDescriptionChange={setDescription}
        employeeCount={headCount} onEmployeeCountChange={setEmployeeCount}
        custom={custom} onCustomChange={setCustom}
        roles={roles} presets={presets} limits={limits} names={names}
        claudeAccounts={settings?.claude_accounts ?? 1}
        presetsFailed={catalog.presetsFailed} onRetryPresets={catalog.retryPresets} problems={problems}
      />
      <SettingsSection>
        <StatusText outcome={error ? { ok: false, text: error } : null} />
        <ActionButton label={busy ? translate("new.creating") : translate("new.create")} disabled={!canSubmit} onPress={() => void submit()} />
        <ActionButton label={translate("common.cancel")} onPress={() => router.navigate("/")} />
      </SettingsSection>
    </>
  );
}

/** New project, as the web page: name, GitHub repository and the team, hired from a description or built by hand. */
export default function NewProjectScreen() {
  const colors = useColors();
  const router = useRouter();
  // A new key resets the form once the project exists, so coming back shows an empty one
  const [formKey, setFormKey] = useState(0);
  const created = (projectId: number) => {
    setFormKey((key) => key + 1);
    router.push({ pathname: "/conversation/[id]", params: { id: String(projectId) } });
  };
  return (
    <SafeAreaView edges={SCREEN_EDGES} style={[styles.screen, { backgroundColor: colors.background }]}>
      <KeyboardAvoidingView behavior={Platform.OS === "ios" ? "padding" : undefined} style={styles.screen}>
        <ScrollView keyboardShouldPersistTaps="handled" contentContainerStyle={styles.content}>
          <Text accessibilityRole="header" maxFontSizeMultiplier={MAX_FONT_SCALE} style={[styles.title, { color: colors.text }]}>
            {translate("nav.newProject")}
          </Text>
          <NewProjectForm key={formKey} onCreated={created} />
        </ScrollView>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1 },
  content: { paddingBottom: SPACING.xl },
  title: { fontSize: FONT_SIZE.largeTitle, fontWeight: "700", paddingHorizontal: SPACING.lg, paddingTop: SPACING.sm },
  input: { minHeight: MIN_TOUCH_TARGET, paddingHorizontal: SPACING.md, borderRadius: RADIUS.input, fontSize: FONT_SIZE.body },
});
