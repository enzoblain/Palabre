import { StyleSheet, View } from "react-native";
import { translate } from "../i18n";
import { SPACING, useColors } from "../theme";
import { AVATAR_SIZE, ROW_MIN_HEIGHT } from "./ConversationRow";

export const SKELETON_ROWS = 8;
const NAME_WIDTH = "40%";
const PREVIEW_WIDTH = "80%";
const LINE_HEIGHT = 12;

/** Placeholder rows shown during the first load; VoiceOver reads one "loading" label instead of the blocks. */
export function ConversationSkeleton() {
  const colors = useColors();
  const block = { backgroundColor: colors.secondaryBackground };
  return (
    <View accessible accessibilityLabel={translate("list.loading")} accessibilityLiveRegion="polite">
      {Array.from({ length: SKELETON_ROWS }, (_, index) => (
        <View key={index} style={styles.row}>
          <View style={[styles.avatar, block]} />
          <View style={styles.lines}>
            <View style={[styles.line, block, { width: NAME_WIDTH }]} />
            <View style={[styles.line, block, { width: PREVIEW_WIDTH }]} />
          </View>
        </View>
      ))}
    </View>
  );
}

const styles = StyleSheet.create({
  row: { flexDirection: "row", alignItems: "center", minHeight: ROW_MIN_HEIGHT, paddingHorizontal: SPACING.lg, gap: SPACING.md },
  avatar: { width: AVATAR_SIZE, height: AVATAR_SIZE, borderRadius: AVATAR_SIZE / 2 },
  lines: { flex: 1, gap: SPACING.sm },
  line: { height: LINE_HEIGHT, borderRadius: LINE_HEIGHT / 2 },
});
