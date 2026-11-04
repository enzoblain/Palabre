import { useState } from "react";
import { Pressable, StyleSheet, Text, View } from "react-native";
import type { CatalogLimits, MemberIn, PersonalityPreset, Role } from "../../api";
import { newMember, teamWarningThreshold } from "../../format/team";
import { spreadAccounts } from "../../format/settings";
import { translate } from "../../i18n";
import { DESTRUCTIVE_TOUCH_TARGET, FONT_SIZE, MAX_FONT_SCALE, MIN_TOUCH_TARGET, RADIUS, SPACING, useColors } from "../../theme";
import { MemberForm } from "./MemberForm";

type Props = {
  members: MemberIn[];
  onChange: (members: MemberIn[]) => void;
  roles: Record<string, Role>;
  presets: Record<string, PersonalityPreset>;
  names: string[];
  claudeAccounts: number;
  limits: CatalogLimits;
};

/** Team built by hand. The first member is the mandatory lead: only their personality changes and they cannot be removed. */
export function TeamEditor({ members, onChange, roles, presets, names, claudeAccounts, limits }: Props) {
  const colors = useColors();
  const [editing, setEditing] = useState<number | null>(null);
  const effective = spreadAccounts(members.map((member) => member.account), claudeAccounts);

  const update = (index: number, changes: Partial<MemberIn>) =>
    onChange(members.map((member, other) => (other === index ? { ...member, ...changes } : member)));
  const add = () => {
    onChange([...members, newMember()]);
    setEditing(members.length); // open the new agent to fill it in
  };

  const atLimit = members.length >= limits.max_agents;
  const nearLimit = members.length >= teamWarningThreshold(limits.max_agents);
  const count = translate("editor.teamCount", { count: members.length, max: limits.max_agents });
  const limitNote = nearLimit ? ` ${translate(atLimit ? "editor.limitReached" : "editor.limitClose")}` : "";

  return (
    <View style={styles.editor}>
      <Text
        accessibilityLiveRegion="polite"
        maxFontSizeMultiplier={MAX_FONT_SCALE}
        style={[styles.count, { color: nearLimit ? colors.error : colors.secondaryText }]}
      >
        {`${nearLimit ? "⚠ " : ""}${count}${limitNote}`}
      </Text>
      {members.length === 0 ? (
        <Text maxFontSizeMultiplier={MAX_FONT_SCALE} style={[styles.count, { color: colors.secondaryText }]}>{translate("editor.empty")}</Text>
      ) : null}
      {members.map((member, index) => {
        const locked = index === 0;
        const name = member.name || translate("editor.namePlaceholder");
        const jobs = member.roles.map((key) => roles[key]?.title ?? key).join(" + ") || translate("editor.noRole");
        return (
          <View key={index} style={[styles.card, { borderBottomColor: colors.separator }]}>
            <Pressable
              accessibilityRole="button"
              accessibilityLabel={translate("editor.editAria", { name })}
              accessibilityValue={{ text: jobs }}
              onPress={() => setEditing(index)}
              style={styles.summary}
            >
              <Text maxFontSizeMultiplier={MAX_FONT_SCALE} style={[styles.name, { color: colors.text }]}>{name}</Text>
              <Text maxFontSizeMultiplier={MAX_FONT_SCALE} numberOfLines={2} style={[styles.jobs, { color: colors.secondaryText }]}>{jobs}</Text>
            </Pressable>
            {locked ? (
              <Text maxFontSizeMultiplier={MAX_FONT_SCALE} style={[styles.badge, { color: colors.secondaryText }]}>{translate("editor.mandatory")}</Text>
            ) : (
              <Pressable
                accessibilityRole="button"
                accessibilityLabel={translate("editor.removeAria", { name })}
                onPress={() => onChange(members.filter((_, other) => other !== index))}
                style={styles.remove}
              >
                <Text maxFontSizeMultiplier={MAX_FONT_SCALE} style={[styles.removeText, { color: colors.error }]}>{translate("common.remove")}</Text>
              </Pressable>
            )}
          </View>
        );
      })}
      <Pressable
        accessibilityRole="button"
        accessibilityState={{ disabled: atLimit }}
        disabled={atLimit}
        onPress={add}
        style={styles.add}
      >
        <Text maxFontSizeMultiplier={MAX_FONT_SCALE} style={[styles.addText, { color: colors.link }, atLimit && styles.disabled]}>
          {translate("editor.addAgent")}
        </Text>
      </Pressable>
      {atLimit ? (
        <Text maxFontSizeMultiplier={MAX_FONT_SCALE} style={[styles.count, { color: colors.secondaryText }]}>
          {translate("editor.limitHelp", { max: limits.max_agents })}
        </Text>
      ) : null}
      {editing !== null && members[editing] ? (
        <MemberForm
          member={members[editing]}
          locked={editing === 0}
          teamNames={members.map((member) => member.name)}
          roles={roles}
          presets={presets}
          limits={limits}
          names={names}
          claudeAccounts={claudeAccounts}
          effectiveAccount={effective[editing]}
          onChange={(changes) => update(editing, changes)}
          onClose={() => setEditing(null)}
        />
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  editor: { gap: SPACING.xs },
  count: { fontSize: FONT_SIZE.body },
  card: { flexDirection: "row", alignItems: "center", gap: SPACING.sm, borderBottomWidth: StyleSheet.hairlineWidth },
  summary: { flex: 1, minHeight: DESTRUCTIVE_TOUCH_TARGET, justifyContent: "center" },
  name: { fontSize: FONT_SIZE.body, fontWeight: "600" },
  jobs: { fontSize: 15 },
  badge: { fontSize: FONT_SIZE.caption + 1, borderRadius: RADIUS.button },
  remove: { minHeight: DESTRUCTIVE_TOUCH_TARGET, justifyContent: "center", paddingHorizontal: SPACING.sm },
  removeText: { fontSize: FONT_SIZE.body, fontWeight: "600" },
  add: { minHeight: MIN_TOUCH_TARGET, justifyContent: "center", alignSelf: "flex-start" },
  addText: { fontSize: FONT_SIZE.body, fontWeight: "600" },
  disabled: { opacity: 0.4 },
});
