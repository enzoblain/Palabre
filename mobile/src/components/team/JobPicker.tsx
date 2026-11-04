import { useMemo, useState } from "react";
import { Pressable, ScrollView, StyleSheet, Text, View } from "react-native";
import type { Role, RoleCategory } from "../../api";
import { groupJobs } from "../../format/team";
import { translate } from "../../i18n";
import { FONT_SIZE, MAX_FONT_SCALE, MIN_TOUCH_TARGET, SPACING, useColors } from "../../theme";
import { SearchField } from "./SearchField";

function JobDetails({ role }: { role: Role }) {
  const colors = useColors();
  const lists: [string, string[]][] = [
    [translate("jobs.responsibilities"), role.responsibilities],
    [translate("jobs.forbidden"), role.forbidden],
    [translate("jobs.deliverables"), role.deliverables],
    [translate("jobs.toolsMcp"), role.tools.mcp],
    [translate("jobs.toolsClaude"), role.tools.claude],
  ];
  return (
    <View style={styles.details}>
      <Text maxFontSizeMultiplier={MAX_FONT_SCALE} style={[styles.body, { color: colors.text }]}>{role.mission}</Text>
      {lists.filter(([, items]) => items.length > 0).map(([label, items]) => (
        <View key={label}>
          <Text maxFontSizeMultiplier={MAX_FONT_SCALE} style={[styles.listTitle, { color: colors.text }]}>{label}</Text>
          {items.map((item) => (
            <Text key={item} maxFontSizeMultiplier={MAX_FONT_SCALE} style={[styles.body, { color: colors.secondaryText }]}>
              {`• ${item}`}
            </Text>
          ))}
        </View>
      ))}
    </View>
  );
}

function JobCard({ role, selected, onToggle }: { role: Role; selected: boolean; onToggle: () => void }) {
  const colors = useColors();
  const [open, setOpen] = useState(false);
  const toolCount = role.tools.mcp.length + role.tools.claude.length;
  return (
    <View style={[styles.card, { borderBottomColor: colors.separator }]}>
      <Pressable
        accessibilityRole="checkbox"
        accessibilityState={{ checked: selected }}
        accessibilityLabel={role.title}
        onPress={onToggle}
        style={styles.head}
      >
        <Text accessible={false} style={[styles.box, { color: colors.link }]}>{selected ? "☑" : "☐"}</Text>
        <Text maxFontSizeMultiplier={MAX_FONT_SCALE} style={[styles.title, { color: colors.text }]}>{role.title}</Text>
        <Text maxFontSizeMultiplier={MAX_FONT_SCALE} style={[styles.meta, { color: colors.secondaryText }]}>
          {role.effort ? `${role.model} · ${role.effort}` : role.model}
        </Text>
      </Pressable>
      <Text maxFontSizeMultiplier={MAX_FONT_SCALE} style={[styles.body, { color: colors.secondaryText }]}>{role.description}</Text>
      <View style={styles.foot}>
        <Text maxFontSizeMultiplier={MAX_FONT_SCALE} style={[styles.meta, { color: colors.secondaryText }]}>
          {translate("jobs.toolsCount", { count: toolCount })}
        </Text>
        <Pressable
          accessibilityRole="button"
          accessibilityState={{ expanded: open }}
          accessibilityLabel={`${open ? translate("jobs.hideDetails") : translate("jobs.showDetails")}, ${role.title}`}
          onPress={() => setOpen(!open)}
          style={styles.detailsButton}
        >
          <Text maxFontSizeMultiplier={MAX_FONT_SCALE} style={[styles.link, { color: colors.link }]}>
            {open ? translate("jobs.hideDetails") : translate("jobs.showDetails")}
          </Text>
        </Pressable>
      </View>
      {open ? <JobDetails role={role} /> : null}
    </View>
  );
}

function CategoryGroup({ category, jobs, selected, forceOpen, onToggle }: {
  category: RoleCategory;
  jobs: Role[];
  selected: string[];
  forceOpen: boolean;
  onToggle: (key: string) => void;
}) {
  const colors = useColors();
  const [collapsed, setCollapsed] = useState(false);
  const open = forceOpen || !collapsed;
  const label = `${translate(`jobs.category.${category}`)} (${jobs.length})`;
  return (
    <View>
      <Pressable
        accessibilityRole="button"
        accessibilityState={{ expanded: open }}
        accessibilityLabel={label}
        onPress={() => setCollapsed(!collapsed)}
        style={[styles.groupHead, { backgroundColor: colors.secondaryBackground }]}
      >
        <Text accessible={false} style={{ color: colors.secondaryText }}>{open ? "▾" : "▸"}</Text>
        <Text maxFontSizeMultiplier={MAX_FONT_SCALE} style={[styles.groupTitle, { color: colors.text }]}>{label}</Text>
      </Pressable>
      {open
        ? jobs.map((role) => (
            <JobCard key={role.key} role={role} selected={selected.includes(role.key)} onToggle={() => onToggle(role.key)} />
          ))
        : null}
    </View>
  );
}

type Props = { roles: Record<string, Role>; selected: string[]; onChange: (selected: string[]) => void };

/** Picks the jobs of a member among the catalog's: a member can hold several. Searchable, grouped by category. */
export function JobPicker({ roles, selected, onChange }: Props) {
  const colors = useColors();
  const [search, setSearch] = useState("");
  const groups = useMemo(() => groupJobs(roles, search), [roles, search]);
  const toggle = (key: string) => onChange(selected.includes(key) ? selected.filter((other) => other !== key) : [...selected, key]);
  const empty = Object.keys(roles).length === 0;

  return (
    <>
      <SearchField value={search} placeholder={translate("jobs.searchPlaceholder")} onChange={setSearch} />
      <ScrollView keyboardShouldPersistTaps="handled">
        {empty ? (
          <Text maxFontSizeMultiplier={MAX_FONT_SCALE} style={[styles.empty, { color: colors.secondaryText }]}>{translate("jobs.none")}</Text>
        ) : null}
        {!empty && groups.length === 0 ? (
          <View style={styles.empty}>
            <Text maxFontSizeMultiplier={MAX_FONT_SCALE} style={{ color: colors.secondaryText, fontSize: FONT_SIZE.body }}>
              {translate("jobs.noMatch", { search })}
            </Text>
            <Pressable accessibilityRole="button" onPress={() => setSearch("")} style={styles.detailsButton}>
              <Text maxFontSizeMultiplier={MAX_FONT_SCALE} style={[styles.link, { color: colors.link }]}>{translate("jobs.clearSearch")}</Text>
            </Pressable>
          </View>
        ) : null}
        {groups.map(([category, jobs]) => (
          <CategoryGroup key={category} category={category} jobs={jobs} selected={selected}
            forceOpen={search.trim() !== ""} onToggle={toggle} />
        ))}
      </ScrollView>
    </>
  );
}

const styles = StyleSheet.create({
  groupHead: { minHeight: MIN_TOUCH_TARGET, flexDirection: "row", alignItems: "center", gap: SPACING.sm, paddingHorizontal: SPACING.lg },
  groupTitle: { flex: 1, fontSize: FONT_SIZE.body, fontWeight: "600" },
  card: { padding: SPACING.lg, gap: SPACING.xs, borderBottomWidth: StyleSheet.hairlineWidth },
  head: { minHeight: MIN_TOUCH_TARGET, flexDirection: "row", alignItems: "center", gap: SPACING.sm },
  box: { fontSize: FONT_SIZE.glyph },
  title: { flex: 1, fontSize: FONT_SIZE.body, fontWeight: "600" },
  meta: { fontSize: FONT_SIZE.meta },
  body: { fontSize: FONT_SIZE.secondary },
  foot: { flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  detailsButton: { minHeight: MIN_TOUCH_TARGET, justifyContent: "center" },
  link: { fontSize: FONT_SIZE.body },
  details: { gap: SPACING.sm, paddingTop: SPACING.xs },
  listTitle: { fontSize: FONT_SIZE.secondary, fontWeight: "700" },
  empty: { padding: SPACING.lg },
});
