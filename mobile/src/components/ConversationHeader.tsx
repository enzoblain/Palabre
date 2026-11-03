import { Pressable, StyleSheet, Text, View } from "react-native";
import { avatarColor, initials } from "../format/conversations";
import { translate } from "../i18n";
import { AVATAR_INITIALS_MAX_FONT_SCALE, FONT_SIZE, MAX_FONT_SCALE, MIN_TOUCH_TARGET, SPACING, useColors } from "../theme";

export const HEADER_AVATAR_SIZE = 32;
const SIDE_MIN_WIDTH = 96; // both sides share this minimum so the name is centered by default; at the largest text sizes the back label grows past it and the name drifts off-center rather than truncating the label

type Props = { name: string | null; onBack: () => void };

/** "< Messages" on the left, avatar and name centered. */
export function ConversationHeader({ name, onBack }: Props) {
  const colors = useColors();
  const title = name ?? translate("conversation.title");
  return (
    <View style={[styles.header, { backgroundColor: colors.background, borderBottomColor: colors.separator }]}>
      <Pressable accessibilityRole="button" accessibilityLabel={translate("list.title")} onPress={onBack} style={styles.side}>
        <Text maxFontSizeMultiplier={MAX_FONT_SCALE} style={[styles.back, { color: colors.link }]}>
          {"‹ "}
          {translate("list.title")}
        </Text>
      </Pressable>
      <View accessible accessibilityRole="header" accessibilityLabel={title} style={styles.center}>
        <View style={[styles.avatar, { backgroundColor: avatarColor(title) }]}>
          <Text maxFontSizeMultiplier={AVATAR_INITIALS_MAX_FONT_SCALE} style={[styles.initials, { color: colors.avatarText }]}>
            {initials(title)}
          </Text>
        </View>
        <Text maxFontSizeMultiplier={MAX_FONT_SCALE} numberOfLines={1} style={[styles.name, { color: colors.text }]}>
          {title}
        </Text>
      </View>
      <View style={styles.side} />
    </View>
  );
}

const styles = StyleSheet.create({
  header: { flexDirection: "row", alignItems: "center", minHeight: MIN_TOUCH_TARGET + SPACING.sm, borderBottomWidth: StyleSheet.hairlineWidth },
  side: { minWidth: SIDE_MIN_WIDTH, minHeight: MIN_TOUCH_TARGET, justifyContent: "center", paddingHorizontal: SPACING.md },
  back: { fontSize: FONT_SIZE.body },
  center: { flex: 1, flexShrink: 1, alignItems: "center", gap: SPACING.xs },
  avatar: { width: HEADER_AVATAR_SIZE, height: HEADER_AVATAR_SIZE, borderRadius: HEADER_AVATAR_SIZE / 2, alignItems: "center", justifyContent: "center" },
  initials: { fontSize: FONT_SIZE.caption, fontWeight: "600" },
  name: { fontSize: FONT_SIZE.caption, fontWeight: "600" },
});
