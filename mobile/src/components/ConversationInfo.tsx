import { useState } from "react";
import { Modal, Pressable, ScrollView, StyleSheet, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { api, ApiError, type Room } from "../api";
import { translate } from "../i18n";
import { FONT_SIZE, MAX_FONT_SCALE, MIN_TOUCH_TARGET, SPACING, useColors } from "../theme";

type Props = {
  room: Room;
  conversationId: number;
  visible: boolean;
  onClose: () => void;
  onMention: (name: string) => void; // tapping a member writes "@Name" in the composer
};

type Feedback = { ok: boolean; text: string };

/** Restarts the anti-loop window of the conversation, for the boss who cannot write in a read-only channel. */
function LiftLimit({ conversationId }: { conversationId: number }) {
  const colors = useColors();
  const [busy, setBusy] = useState(false);
  const [feedback, setFeedback] = useState<Feedback | null>(null);

  const lift = async () => {
    if (busy) return;
    setBusy(true);
    try {
      await api.liftRateLimit(conversationId);
      setFeedback({ ok: true, text: translate("conversation.liftLimitDone") });
    } catch (err) {
      setFeedback({ ok: false, text: err instanceof ApiError ? err.message : String(err) });
    } finally {
      setBusy(false);
    }
  };

  return (
    <View>
      <Text maxFontSizeMultiplier={MAX_FONT_SCALE} style={[styles.help, { color: colors.secondaryText }]}>
        {translate("conversation.liftLimitHelp")}
      </Text>
      <Pressable
        accessibilityRole="button"
        accessibilityState={{ disabled: busy, busy }}
        disabled={busy}
        onPress={lift}
        style={[styles.member, busy && styles.busy]}
      >
        <Text maxFontSizeMultiplier={MAX_FONT_SCALE} style={[styles.body, { color: colors.link }]}>
          {translate("conversation.liftLimit")}
        </Text>
      </Pressable>
      <View accessibilityLiveRegion="polite">
        {feedback ? (
          <Text maxFontSizeMultiplier={MAX_FONT_SCALE} style={[styles.body, { color: feedback.ok ? colors.success : colors.error }]}>
            {feedback.text}
          </Text>
        ) : null}
      </View>
    </View>
  );
}

/** The room document (objective, summary) and its members, as the web conversation info. */
export function ConversationInfo({ room, conversationId, visible, onClose, onMention }: Props) {
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
            <Pressable
              key={member.id}
              accessibilityRole="button"
              accessibilityLabel={`${member.name}, ${member.title}`}
              accessibilityHint={translate("conversation.mention", { name: member.name })}
              onPress={() => onMention(member.name)}
              style={styles.member}
            >
              <Text maxFontSizeMultiplier={MAX_FONT_SCALE} style={[styles.body, { color: colors.text }]}>
                {member.name} · {member.title}
              </Text>
            </Pressable>
          ))}
          <LiftLimit conversationId={conversationId} />
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
  help: { fontSize: FONT_SIZE.caption },
  member: { minHeight: MIN_TOUCH_TARGET, justifyContent: "center" },
  busy: { opacity: 0.4 },
});
