import { useState } from "react";
import { Alert, StyleSheet, Text, View } from "react-native";
import { ApiError, api, type Employee } from "../../api";
import { avatarColor, initials } from "../../format/conversations";
import { useTeamCatalog } from "../../hooks/useTeamCatalog";
import { translate } from "../../i18n";
import { AVATAR_INITIALS_MAX_FONT_SCALE, FONT_SIZE, MAX_FONT_SCALE, SPACING, useColors } from "../../theme";
import { ErrorBanner } from "../ErrorBanner";
import { ActionButton } from "../settings/ActionButton";
import { SettingsSection } from "../settings/SettingsSection";
import { StatusText, type Outcome } from "../settings/StatusText";
import { MemberEditor } from "./MemberEditor";

const MEMBER_AVATAR_SIZE = 34;

type Props = {
  projectId: number;
  members: Employee[];
  /** A member was added, edited or removed: reload the project. */
  onChanged: () => void;
};

const errorOutcome = (err: unknown): Outcome => ({ ok: false, text: err instanceof ApiError ? err.message : String(err) });

function MemberRow({ member, isLead, busy, onEdit, onRemove }: {
  member: Employee;
  isLead: boolean;
  busy: boolean;
  onEdit: () => void;
  onRemove: () => void;
}) {
  const colors = useColors();
  return (
    <View style={[styles.member, { borderBottomColor: colors.separator }]}>
      <View style={styles.head}>
        <View style={[styles.avatar, { backgroundColor: avatarColor(member.name) }]}>
          <Text maxFontSizeMultiplier={AVATAR_INITIALS_MAX_FONT_SCALE} style={[styles.initials, { color: colors.avatarText }]}>
            {initials(member.name)}
          </Text>
        </View>
        <View style={styles.text}>
          <Text maxFontSizeMultiplier={MAX_FONT_SCALE} style={[styles.name, { color: colors.text }]}>{member.name}</Text>
          <Text maxFontSizeMultiplier={MAX_FONT_SCALE} style={[styles.meta, { color: colors.secondaryText }]}>{member.title}</Text>
          {member.quirks.length > 0 ? (
            <Text maxFontSizeMultiplier={MAX_FONT_SCALE} style={[styles.meta, { color: colors.secondaryText }]}>
              {member.quirks.join(" · ")}
            </Text>
          ) : null}
        </View>
        {isLead ? (
          <Text accessibilityHint={translate("team.leadLocked")} maxFontSizeMultiplier={MAX_FONT_SCALE} style={[styles.meta, { color: colors.secondaryText }]}>
            {translate("team.lead")}
          </Text>
        ) : null}
      </View>
      {isLead ? null : (
        <View style={styles.actions}>
          <ActionButton label={translate("common.edit")} accessibilityLabel={translate("team.editAria", { name: member.name })} disabled={busy} onPress={onEdit} />
          <ActionButton destructive label={translate("common.remove")} accessibilityLabel={translate("team.removeAria", { name: member.name })} disabled={busy} onPress={onRemove} />
        </View>
      )}
    </View>
  );
}

/** The team of the project page: members with jobs and quirks, add, edit and remove (confirmed) unless the lead. */
export function TeamSection({ projectId, members, onChanged }: Props) {
  const colors = useColors();
  const { catalog, failed, retry } = useTeamCatalog();
  const [editing, setEditing] = useState<Employee | "new" | null>(null);
  const [busy, setBusy] = useState(false);
  const [outcome, setOutcome] = useState<Outcome | null>(null);
  const sorted = [...members].sort((a, b) => a.name.localeCompare(b.name));

  // Runs a change; on failure the message stays where the user is (the sheet or the list) and nothing closes
  const run = async (action: () => Promise<unknown>) => {
    setBusy(true);
    setOutcome(null);
    try {
      await action();
      setEditing(null);
      onChanged();
    } catch (err) {
      setOutcome(errorOutcome(err));
    } finally {
      setBusy(false);
    }
  };

  const save = (roles: string[], personality: string | null) =>
    run(() =>
      editing === "new" || editing === null
        ? api.addEmployee(projectId, { roles, personality })
        : api.updateEmployee(editing.id, { roles, ...(personality ? { personality } : {}) }),
    );
  const confirmRemove = (member: Employee) =>
    Alert.alert(translate("team.removeConfirmTitle"), translate("team.removeConfirm", { name: member.name }), [
      { text: translate("common.cancel"), style: "cancel" },
      { text: translate("team.removeForGood"), style: "destructive", onPress: () => void run(() => api.removeEmployee(member.id)) },
    ]);
  const open = (target: Employee | "new" | null) => {
    setOutcome(null);
    setEditing(target);
  };

  return (
    <SettingsSection title={translate("team.title")}>
      {failed ? <ErrorBanner message={translate("team.loadError")} onRetry={retry} /> : null}
      {!catalog && !failed ? <Text accessibilityRole="progressbar" maxFontSizeMultiplier={MAX_FONT_SCALE} style={[styles.meta, { color: colors.secondaryText }]}>
          {translate("team.loading")}
        </Text> : null}
      {catalog ? (
        <>
          {sorted.length === 0 ? <Text maxFontSizeMultiplier={MAX_FONT_SCALE} style={[styles.meta, { color: colors.secondaryText }]}>{translate("team.empty")}</Text> : null}
          {sorted.map((member) => (
            <MemberRow
              key={member.id}
              member={member}
              isLead={member.roles.includes(catalog.limits.mandatory_role)}
              busy={busy}
              onEdit={() => open(member)}
              onRemove={() => confirmRemove(member)}
            />
          ))}
          <ActionButton label={translate("team.add")} disabled={busy} onPress={() => open("new")} />
          {editing === null ? <StatusText outcome={outcome} /> : null}
          {editing !== null ? (
            <MemberEditor
              key={editing === "new" ? "new" : editing.id}
              member={editing === "new" ? undefined : editing}
              catalog={catalog}
              busy={busy}
              outcome={outcome}
              onSubmit={save}
              onClose={() => open(null)}
            />
          ) : null}
        </>
      ) : null}
    </SettingsSection>
  );
}

const styles = StyleSheet.create({
  member: { paddingVertical: SPACING.sm, borderBottomWidth: StyleSheet.hairlineWidth },
  head: { flexDirection: "row", alignItems: "center", gap: SPACING.md },
  avatar: { width: MEMBER_AVATAR_SIZE, height: MEMBER_AVATAR_SIZE, borderRadius: MEMBER_AVATAR_SIZE / 2, alignItems: "center", justifyContent: "center" },
  initials: { fontSize: FONT_SIZE.caption, fontWeight: "600" },
  text: { flex: 1 },
  name: { fontSize: FONT_SIZE.body, fontWeight: "600" },
  meta: { fontSize: FONT_SIZE.caption },
  actions: { flexDirection: "row", gap: SPACING.lg },
});
