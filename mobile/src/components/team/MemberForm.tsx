import { useState } from "react";
import { Pressable, ScrollView, StyleSheet, Text, TextInput, View } from "react-native";
import type { CatalogLimits, MemberIn, PersonalityPreset, Role } from "../../api";
import { MEMBER_NAME_MAX_LENGTH, freeName } from "../../format/team";
import { translate } from "../../i18n";
import { FONT_SIZE, MAX_FONT_SCALE, MIN_TOUCH_TARGET, RADIUS, SPACING, useColors } from "../../theme";
import { SheetModal } from "../SheetModal";
import { OptionList, type Option } from "../settings/OptionPicker";
import { JobPicker } from "./JobPicker";
import { PersonalityPicker } from "./PersonalityPicker";

type Page = "form" | "jobs" | "personality" | "model" | "account";

type Props = {
  member: MemberIn;
  /** The mandatory lead: only the personality can change. */
  locked: boolean;
  teamNames: string[];
  roles: Record<string, Role>;
  presets: Record<string, PersonalityPreset>;
  limits: CatalogLimits;
  names: string[];
  claudeAccounts: number;
  effectiveAccount: number;
  onChange: (changes: Partial<MemberIn>) => void;
  onClose: () => void;
};

function FieldRow({ label, value, onPress }: { label: string; value: string; onPress: () => void }) {
  const colors = useColors();
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={label}
      accessibilityValue={{ text: value }}
      onPress={onPress}
      style={[styles.field, { borderBottomColor: colors.separator }]}
    >
      <Text maxFontSizeMultiplier={MAX_FONT_SCALE} style={[styles.fieldLabel, { color: colors.text }]}>{label}</Text>
      <Text maxFontSizeMultiplier={MAX_FONT_SCALE} numberOfLines={2} style={[styles.fieldValue, { color: colors.link }]}>{value}</Text>
    </Pressable>
  );
}

/** Sheet to edit one agent of the team; the jobs, personality, model and account are sub-pages of the same sheet. */
export function MemberForm({
  member, locked, teamNames, roles, presets, limits, names, claudeAccounts, effectiveAccount, onChange, onClose,
}: Props) {
  const colors = useColors();
  const [page, setPage] = useState<Page>("form");
  const back = () => setPage("form");

  const modelOptions: Option<string | null>[] = [
    { value: null, label: translate("editor.modelAuto") },
    ...limits.models.map((model) => ({ value: model as string | null, label: model })),
  ];
  const accountOptions: Option<number | null>[] = [
    { value: null, label: translate("account.auto", { account: effectiveAccount }) },
    ...Array.from({ length: claudeAccounts }, (_, index) => ({ value: index + 1, label: translate("account.n", { account: index + 1 }) })),
  ];
  const jobsValue = member.roles.map((key) => roles[key]?.title ?? key).join(" + ") || translate("editor.noRole");
  const personality = member.personality && presets[member.personality] ? presets[member.personality].label : translate("presets.random");
  const accountValue = member.account === null
    ? translate("account.auto", { account: effectiveAccount })
    : translate("account.n", { account: member.account });

  const titles: Record<Page, string> = {
    form: member.name || translate("editor.namePlaceholder"),
    jobs: translate("jobs.title"),
    personality: translate("presets.title"),
    model: translate("editor.model"),
    account: translate("editor.account"),
  };

  return (
    <SheetModal
      title={titles[page]}
      closeLabel={translate(page === "form" ? "common.close" : "common.done")}
      visible
      onClose={page === "form" ? onClose : back}
    >
      {page === "form" ? (
        <ScrollView keyboardShouldPersistTaps="handled">
          <View style={styles.nameRow}>
            <TextInput
              accessibilityLabel={translate("editor.nameField")}
              placeholder={translate("editor.namePlaceholder")}
              placeholderTextColor={colors.secondaryText}
              value={member.name}
              editable={!locked}
              maxLength={MEMBER_NAME_MAX_LENGTH}
              autoCapitalize="none"
              autoCorrect={false}
              maxFontSizeMultiplier={MAX_FONT_SCALE}
              onChangeText={(text) => onChange({ name: text.replace(/\s/g, "") })}
              style={[styles.input, { backgroundColor: colors.secondaryBackground, color: colors.text }]}
            />
            {locked ? null : (
              <Pressable
                accessibilityRole="button"
                accessibilityLabel={translate("editor.pickName")}
                onPress={() => onChange({ name: freeName(names, teamNames) })}
                style={styles.shuffle}
              >
                <Text accessible={false} style={[styles.shuffleIcon, { color: colors.link }]}>🔀</Text>
              </Pressable>
            )}
          </View>
          {locked ? null : <FieldRow label={translate("jobs.title")} value={jobsValue} onPress={() => setPage("jobs")} />}
          <FieldRow label={translate("presets.title")} value={personality} onPress={() => setPage("personality")} />
          {locked ? null : <FieldRow label={translate("editor.model")} value={member.model ?? translate("editor.modelAuto")} onPress={() => setPage("model")} />}
          {claudeAccounts > 1 && !locked
            ? <FieldRow label={translate("editor.account")} value={accountValue} onPress={() => setPage("account")} />
            : null}
        </ScrollView>
      ) : null}
      {page === "jobs" ? <JobPicker roles={roles} selected={member.roles} onChange={(selected) => onChange({ roles: selected })} /> : null}
      {page === "personality" ? (
        <PersonalityPicker presets={presets} selected={member.personality} onSelect={(key) => { onChange({ personality: key }); back(); }} />
      ) : null}
      {page === "model" ? (
        <OptionList options={modelOptions} selected={member.model} onPick={(model) => { onChange({ model }); back(); }} />
      ) : null}
      {page === "account" ? (
        <OptionList options={accountOptions} selected={member.account} onPick={(account) => { onChange({ account }); back(); }} />
      ) : null}
    </SheetModal>
  );
}

const styles = StyleSheet.create({
  nameRow: { flexDirection: "row", alignItems: "center", padding: SPACING.md, gap: SPACING.sm },
  input: { flex: 1, minHeight: MIN_TOUCH_TARGET, paddingHorizontal: SPACING.md, borderRadius: RADIUS.input, fontSize: FONT_SIZE.body },
  shuffle: { minWidth: MIN_TOUCH_TARGET, minHeight: MIN_TOUCH_TARGET, alignItems: "center", justifyContent: "center" },
  shuffleIcon: { fontSize: FONT_SIZE.glyph },
  field: {
    minHeight: MIN_TOUCH_TARGET, flexDirection: "row", alignItems: "center", justifyContent: "space-between",
    gap: SPACING.md, paddingHorizontal: SPACING.lg, borderBottomWidth: StyleSheet.hairlineWidth,
  },
  fieldLabel: { fontSize: FONT_SIZE.body },
  fieldValue: { flex: 1, fontSize: FONT_SIZE.body, textAlign: "right" },
});
