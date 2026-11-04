import { useState } from "react";
import { Pressable, ScrollView, StyleSheet, Text, View } from "react-native";
import type { Employee } from "../../api";
import { translate } from "../../i18n";
import type { TeamCatalog } from "../../hooks/useTeamCatalog";
import { FONT_SIZE, MAX_FONT_SCALE, MIN_TOUCH_TARGET, SPACING, useColors } from "../../theme";
import { SheetModal } from "../SheetModal";
import { ActionButton } from "../settings/ActionButton";
import { StatusText, type Outcome } from "../settings/StatusText";
import { JobPicker } from "../team/JobPicker";
import { PersonalityPicker } from "../team/PersonalityPicker";

type Page = "form" | "jobs" | "personality";

type Props = {
  /** The member being edited; absent when adding one. */
  member?: Employee;
  catalog: TeamCatalog;
  busy: boolean;
  outcome: Outcome | null;
  onSubmit: (roles: string[], personality: string | null) => void;
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
      <Text maxFontSizeMultiplier={MAX_FONT_SCALE} style={[styles.text, { color: colors.text }]}>{label}</Text>
      <Text maxFontSizeMultiplier={MAX_FONT_SCALE} numberOfLines={2} style={[styles.value, { color: colors.link }]}>{value}</Text>
    </Pressable>
  );
}

/** Sheet to pick the jobs and the personality of one member, saved with a single request (as the web form). */
export function MemberEditor({ member, catalog, busy, outcome, onSubmit, onClose }: Props) {
  const colors = useColors();
  const [page, setPage] = useState<Page>("form");
  const [roles, setRoles] = useState<string[]>(member?.roles ?? []);
  // The current personality is not known to the client: "random" keeps it on an edit
  const [personality, setPersonality] = useState<string | null>(null);
  const back = () => setPage("form");

  const jobs = roles.map((key) => catalog.roles[key]?.title ?? key).join(" + ") || translate("editor.noRole");
  const personalityLabel = personality && catalog.presets[personality] ? catalog.presets[personality].label : translate("presets.random");
  const titles: Record<Page, string> = {
    form: member ? member.name : translate("team.addTitle"),
    jobs: translate("jobs.title"),
    personality: translate("presets.title"),
  };
  const submitLabel = busy
    ? translate(member ? "common.saving" : "team.adding")
    : translate(member ? "common.save" : "common.add");

  return (
    <SheetModal
      title={titles[page]}
      closeLabel={translate(page === "form" ? "common.cancel" : "common.done")}
      visible
      onClose={page === "form" ? onClose : back}
    >
      {page === "form" ? (
        <ScrollView keyboardShouldPersistTaps="handled">
          <FieldRow label={translate("jobs.title")} value={jobs} onPress={() => setPage("jobs")} />
          <FieldRow label={translate("presets.title")} value={personalityLabel} onPress={() => setPage("personality")} />
          <View style={styles.footer}>
            <Text maxFontSizeMultiplier={MAX_FONT_SCALE} style={[styles.hint, { color: colors.secondaryText }]}>
              {translate(member ? "team.editHint" : "team.addHint")}
            </Text>
            {roles.length === 0 ? (
              <Text maxFontSizeMultiplier={MAX_FONT_SCALE} style={[styles.hint, { color: colors.secondaryText }]}>
                {translate("team.noRole")}
              </Text>
            ) : null}
            <StatusText outcome={outcome} />
            <ActionButton label={submitLabel} disabled={busy || roles.length === 0} onPress={() => onSubmit(roles, personality)} />
          </View>
        </ScrollView>
      ) : null}
      {page === "jobs" ? <JobPicker roles={catalog.roles} selected={roles} onChange={setRoles} /> : null}
      {page === "personality" ? (
        <PersonalityPicker presets={catalog.presets} selected={personality} onSelect={(key) => { setPersonality(key); back(); }} />
      ) : null}
    </SheetModal>
  );
}

const styles = StyleSheet.create({
  field: {
    minHeight: MIN_TOUCH_TARGET, flexDirection: "row", alignItems: "center", justifyContent: "space-between",
    gap: SPACING.md, paddingHorizontal: SPACING.lg, borderBottomWidth: StyleSheet.hairlineWidth,
  },
  text: { fontSize: FONT_SIZE.body },
  value: { flex: 1, fontSize: FONT_SIZE.body, textAlign: "right" },
  footer: { padding: SPACING.lg, gap: SPACING.sm },
  hint: { fontSize: FONT_SIZE.caption },
});
