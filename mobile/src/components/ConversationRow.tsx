import { Pressable, StyleSheet, Text, View } from "react-native";
import type { ProjectListItem } from "../api";
import { avatarColor, formatListTime, initials } from "../format/conversations";
import { translate } from "../i18n";
import { AVATAR_INITIALS_MAX_FONT_SCALE, FONT_SIZE, MAX_FONT_SCALE, MIN_TOUCH_TARGET, SPACING, useColors } from "../theme";

export const AVATAR_SIZE = 48;
export const ROW_MIN_HEIGHT = 76;
export const SEPARATOR_INSET = 76;
const UNREAD_DOT_SIZE = 10;
const PREVIEW_FONT_SIZE = 15;

type Props = { item: ProjectListItem; onPress: (item: ProjectListItem) => void };

/** One conversation: avatar, name, two-line preview, time and the unread dot. */
export function ConversationRow({ item, onPress }: Props) {
  const colors = useColors();
  const unread = item.unread_count > 0;
  const preview = item.last_message?.content ?? translate("list.noMessage");
  const time = item.last_message ? formatListTime(item.last_message.created_at) : "";
  const label = [item.name, preview, time, unread ? translate("list.unread") : ""].filter(Boolean).join(", ");

  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={label}
      onPress={() => onPress(item)}
      style={({ pressed }) => [styles.row, pressed && { backgroundColor: colors.secondaryBackground }]}
    >
      <View style={[styles.avatar, { backgroundColor: avatarColor(item.name) }]}>
        <Text maxFontSizeMultiplier={AVATAR_INITIALS_MAX_FONT_SCALE} style={[styles.initials, { color: colors.avatarText }]}>
          {initials(item.name)}
        </Text>
      </View>
      <View style={styles.body}>
        <View style={styles.header}>
          <Text maxFontSizeMultiplier={MAX_FONT_SCALE} numberOfLines={1} style={[styles.name, { color: colors.text }]}>
            {item.name}
          </Text>
          <Text maxFontSizeMultiplier={MAX_FONT_SCALE} style={[styles.meta, { color: colors.secondaryText }]}>
            {time}
          </Text>
        </View>
        <View style={styles.previewLine}>
          <Text
            maxFontSizeMultiplier={MAX_FONT_SCALE}
            numberOfLines={2}
            style={[styles.preview, { color: colors.secondaryText }]}
          >
            {preview}
          </Text>
          {unread ? <View style={[styles.dot, { backgroundColor: colors.sentBubble }]} /> : null}
        </View>
      </View>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  row: {
    flexDirection: "row",
    alignItems: "center",
    minHeight: Math.max(ROW_MIN_HEIGHT, MIN_TOUCH_TARGET),
    paddingHorizontal: SPACING.lg,
    paddingVertical: SPACING.sm,
    gap: SPACING.md,
  },
  avatar: { width: AVATAR_SIZE, height: AVATAR_SIZE, borderRadius: AVATAR_SIZE / 2, alignItems: "center", justifyContent: "center" },
  initials: { fontSize: FONT_SIZE.body, fontWeight: "600" },
  body: { flex: 1, gap: SPACING.xs },
  header: { flexDirection: "row", alignItems: "center", gap: SPACING.sm },
  name: { flex: 1, fontSize: FONT_SIZE.body, fontWeight: "700" },
  meta: { fontSize: PREVIEW_FONT_SIZE },
  previewLine: { flexDirection: "row", alignItems: "center", gap: SPACING.sm },
  preview: { flex: 1, fontSize: PREVIEW_FONT_SIZE },
  dot: { width: UNREAD_DOT_SIZE, height: UNREAD_DOT_SIZE, borderRadius: UNREAD_DOT_SIZE / 2 },
});
