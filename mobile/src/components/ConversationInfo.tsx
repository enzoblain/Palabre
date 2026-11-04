import { Modal, Pressable, ScrollView, StyleSheet, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import type { Room } from "../api";
import { translate } from "../i18n";
import { FONT_SIZE, MAX_FONT_SCALE, MIN_TOUCH_TARGET, SPACING, useColors } from "../theme";

type Props = { room: Room; visible: boolean; onClose: () => void };

/** The room document (objective, summary) and its members, as the web conversation info. */
export function ConversationInfo({ room, visible, onClose }: Props) {
  const colors = useColors();
  const sections = [
    { title: translate("conversation.objective"), body: room.objective },
    { title: translate("conversation.summary"), body: room.summary },
  ].filter((section) => section.body.trim() !== "");
  return (
    <Modal visible={visible} animationType="slide" presentationStyle="pageSheet" onRequestClose={onClose}>
      <SafeAreaView style={[styles.screen, { backgroundColor: colors.background }]}>
        <View style={[styles.bar, { borderBottomColor: colors.separator }]}>
          <Text accessibilityRole="header" maxFontSizeMultiplier={MAX_FONT_SCALE} style={[styles.title, { color: colors.text }]}>
            {translate("conversation.info")}
          </Text>
          <Pressable accessibilityRole="button" onPress={onClose} style={styles.close}>
            <Text maxFontSizeMultiplier={MAX_FONT_SCALE} style={[styles.closeText, { color: colors.link }]}>
              {translate("conversation.close")}
            </Text>
          </Pressable>
        </View>
        <ScrollView contentContainerStyle={styles.content}>
          {sections.length === 0 ? (
            <Text maxFontSizeMultiplier={MAX_FONT_SCALE} style={[styles.body, { color: colors.secondaryText }]}>
              {translate("conversation.noInfo")}
            </Text>
          ) : null}
          {sections.map((section) => (
            <View key={section.title}>
              <Text accessibilityRole="header" maxFontSizeMultiplier={MAX_FONT_SCALE} style={[styles.heading, { color: colors.secondaryText }]}>
                {section.title}
              </Text>
              <Text maxFontSizeMultiplier={MAX_FONT_SCALE} style={[styles.body, { color: colors.text }]}>
                {section.body}
              </Text>
            </View>
          ))}
          <Text accessibilityRole="header" maxFontSizeMultiplier={MAX_FONT_SCALE} style={[styles.heading, { color: colors.secondaryText }]}>
            {translate(room.members.length > 1 ? "conversation.members" : "conversation.member", { count: room.members.length })}
          </Text>
          {room.members.map((member) => (
            <Text key={member.id} maxFontSizeMultiplier={MAX_FONT_SCALE} style={[styles.body, { color: colors.text }]}>
              {member.name} · {member.title}
            </Text>
          ))}
        </ScrollView>
      </SafeAreaView>
    </Modal>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1 },
  bar: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingLeft: SPACING.lg, borderBottomWidth: StyleSheet.hairlineWidth },
  title: { fontSize: FONT_SIZE.body, fontWeight: "600" },
  close: { minHeight: MIN_TOUCH_TARGET, justifyContent: "center", paddingHorizontal: SPACING.lg },
  closeText: { fontSize: FONT_SIZE.body },
  content: { padding: SPACING.lg, gap: SPACING.sm },
  heading: { fontSize: FONT_SIZE.caption, fontWeight: "600", textTransform: "uppercase", marginTop: SPACING.md },
  body: { fontSize: FONT_SIZE.body },
});
