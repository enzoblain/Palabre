import { Pressable, StyleSheet, Text, TextInput, View } from "react-native";
import type { CatalogLimits, MemberIn, PersonalityPreset, Role } from "../../api";
import { DESCRIPTION_MAX_LENGTH } from "../../format/team";
import { translate } from "../../i18n";
import { FONT_SIZE, MAX_FONT_SCALE, MIN_TOUCH_TARGET, RADIUS, SPACING, useColors } from "../../theme";
import { SettingsSection } from "../settings/SettingsSection";
import { TeamEditor } from "./TeamEditor";

export type CreationMode = "auto" | "manual";

type Props = {
  creation: CreationMode;
  onCreationChange: (creation: CreationMode) => void;
  description: string;
  onDescriptionChange: (description: string) => void;
  employeeCount: number;
  onEmployeeCountChange: (count: number) => void;
  custom: MemberIn[] | null;
  onCustomChange: (members: MemberIn[]) => void;
  roles: Record<string, Role> | null;
  presets: Record<string, PersonalityPreset> | null;
  limits: CatalogLimits | null;
  names: string[];
  claudeAccounts: number;
  presetsFailed: boolean;
  onRetryPresets: () => void;
  problems: string[];
};

function Segment({ label, selected, disabled, onPress }: { label: string; selected: boolean; disabled?: boolean; onPress: () => void }) {
  const colors = useColors();
  return (
    <Pressable
      accessibilityRole="tab"
      accessibilityState={{ selected, disabled: !!disabled }}
      disabled={disabled}
      onPress={onPress}
      style={[styles.segment, selected && { backgroundColor: colors.background }]}
    >
      <Text maxFontSizeMultiplier={MAX_FONT_SCALE} style={[styles.segmentText, { color: selected ? colors.text : colors.link }, disabled && styles.disabled]}>
        {label}
      </Text>
    </Pressable>
  );
}

/** Company team: hired from a description (automatic) or listed by hand (manual). */
export function CompanyTeamSection(props: Props) {
  const colors = useColors();
  const { creation, roles, presets, limits, custom } = props;
  const inputStyle = [styles.input, { backgroundColor: colors.background, color: colors.text }];
  return (
    <SettingsSection title={translate("new.yourTeam")}>
      <View accessibilityRole="tablist" style={[styles.segmented, { backgroundColor: colors.separator }]}>
        <Segment label={translate("new.creationAuto")} selected={creation === "auto"} onPress={() => props.onCreationChange("auto")} />
        <Segment label={translate("new.creationManual")} selected={creation === "manual"} disabled={!roles || !presets || !limits}
          onPress={() => props.onCreationChange("manual")} />
      </View>
      {props.presetsFailed ? (
        <View accessibilityRole="alert">
          <Text maxFontSizeMultiplier={MAX_FONT_SCALE} style={[styles.text, { color: colors.error }]}>{translate("new.presetsFailed")}</Text>
          <Pressable accessibilityRole="button" onPress={props.onRetryPresets} style={styles.retry}>
            <Text maxFontSizeMultiplier={MAX_FONT_SCALE} style={[styles.text, { color: colors.link }]}>{translate("new.presetsRetry")}</Text>
          </Pressable>
        </View>
      ) : null}
      {creation === "auto" ? (
        <>
          <Text maxFontSizeMultiplier={MAX_FONT_SCALE} style={[styles.text, { color: colors.secondaryText }]}>{translate("new.introAuto")}</Text>
          <TextInput
            accessibilityLabel={translate("new.description")}
            placeholder={translate("new.descriptionPlaceholder")}
            placeholderTextColor={colors.secondaryText}
            value={props.description}
            onChangeText={props.onDescriptionChange}
            maxLength={DESCRIPTION_MAX_LENGTH}
            multiline
            maxFontSizeMultiplier={MAX_FONT_SCALE}
            style={[...inputStyle, styles.multiline]}
          />
          <Text maxFontSizeMultiplier={MAX_FONT_SCALE} style={[styles.text, { color: colors.text }]}>{translate("new.employeeCount")}</Text>
          <TextInput
            accessibilityLabel={translate("new.employeeCount")}
            keyboardType="number-pad"
            value={String(props.employeeCount)}
            onChangeText={(text) => props.onEmployeeCountChange(Number(text.replace(/\D/g, "")))}
            maxFontSizeMultiplier={MAX_FONT_SCALE}
            style={inputStyle}
          />
        </>
      ) : (
        <>
          {limits ? <Text maxFontSizeMultiplier={MAX_FONT_SCALE} style={[styles.text, { color: colors.secondaryText }]}>{translate("new.introManual", { min: limits.min_team_size })}</Text> : null}
          {custom && roles && presets && limits ? (
            <TeamEditor members={custom} onChange={props.onCustomChange} roles={roles} presets={presets}
              names={props.names} claudeAccounts={props.claudeAccounts} limits={limits} />
          ) : null}
        </>
      )}
      {props.problems.map((problem) => (
        <Text key={problem} accessibilityRole="alert" maxFontSizeMultiplier={MAX_FONT_SCALE} style={[styles.text, { color: colors.error }]}>{problem}</Text>
      ))}
    </SettingsSection>
  );
}

const SEGMENT_INSET = 2;
const DESCRIPTION_MIN_HEIGHT = 120;

const styles = StyleSheet.create({
  segmented: { flexDirection: "row", borderRadius: RADIUS.button, padding: SEGMENT_INSET },
  segment: { flex: 1, minHeight: MIN_TOUCH_TARGET, alignItems: "center", justifyContent: "center", borderRadius: RADIUS.button - SEGMENT_INSET },
  segmentText: { fontSize: FONT_SIZE.body, fontWeight: "600" },
  disabled: { opacity: 0.4 },
  text: { fontSize: FONT_SIZE.body },
  retry: { minHeight: MIN_TOUCH_TARGET, justifyContent: "center", alignSelf: "flex-start" },
  input: { minHeight: MIN_TOUCH_TARGET, paddingHorizontal: SPACING.md, borderRadius: RADIUS.input, fontSize: FONT_SIZE.body },
  multiline: { minHeight: DESCRIPTION_MIN_HEIGHT, paddingTop: SPACING.sm, textAlignVertical: "top" },
});
