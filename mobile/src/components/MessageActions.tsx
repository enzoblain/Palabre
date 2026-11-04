import { useEffect, useRef, useState } from "react";
import { Modal, Pressable, StyleSheet, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { type DisplayMessage, formatSentAt } from "../format/messages";
import { currentLanguage, translate } from "../i18n";
import { FONT_SIZE, MAX_FONT_SCALE, MIN_TOUCH_TARGET, RADIUS, SPACING, useColors } from "../theme";

export const COPIED_FEEDBACK_MS = 1500;

type CopyState = "idle" | "copied" | "failed";
type Props = { message: DisplayMessage | null; onCopy: (message: DisplayMessage) => Promise<boolean>; onClose: () => void };

const COPY_LABELS = { idle: "conversation.copy", copied: "conversation.copied", failed: "conversation.copyFailed" } as const;

function SheetAction({ label, expanded, onPress }: { label: string; expanded?: boolean; onPress: () => void }) {
  const colors = useColors();
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityState={expanded === undefined ? undefined : { expanded }}
      onPress={onPress}
      style={[styles.action, { borderTopColor: colors.separator }]}
    >
      <Text maxFontSizeMultiplier={MAX_FONT_SCALE} style={[styles.actionText, { color: colors.link }]}>
        {label}
      </Text>
    </Pressable>
  );
}

function ActionsSheet({ message, onCopy, onClose }: { message: DisplayMessage; onCopy: Props["onCopy"]; onClose: () => void }) {
  const colors = useColors();
  const [copyState, setCopyState] = useState<CopyState>("idle");
  const [showInfo, setShowInfo] = useState(false);
  const closeTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);

  useEffect(() => () => clearTimeout(closeTimer.current), []);

  const copy = async () => {
    const succeeded = await onCopy(message);
    setCopyState(succeeded ? "copied" : "failed");
    if (succeeded) closeTimer.current = setTimeout(onClose, COPIED_FEEDBACK_MS);
  };

  return (
    <SafeAreaView edges={["bottom"]} style={[styles.sheet, { backgroundColor: colors.secondaryBackground }]}>
      <Text accessibilityRole="header" maxFontSizeMultiplier={MAX_FONT_SCALE} style={[styles.title, { color: colors.secondaryText }]}>
        {translate("conversation.actions")}
      </Text>
      <SheetAction label={translate(COPY_LABELS[copyState])} onPress={copy} />
      <SheetAction label={translate("conversation.messageInfo")} expanded={showInfo} onPress={() => setShowInfo(true)} />
      <View accessibilityLiveRegion="polite">
        {showInfo ? (
          <Text maxFontSizeMultiplier={MAX_FONT_SCALE} style={[styles.info, { color: colors.text }]}>
            {translate("conversation.sentAt", { date: formatSentAt(message.createdAt, currentLanguage()) })}
          </Text>
        ) : null}
      </View>
      <SheetAction label={translate("conversation.close")} onPress={onClose} />
    </SafeAreaView>
  );
}

/** The bottom sheet of a long press: Copy, and Info (the full date and time of sending). */
export function MessageActions({ message, onCopy, onClose }: Props) {
  return (
    <Modal visible={message !== null} transparent animationType="slide" onRequestClose={onClose}>
      <Pressable accessibilityLabel={translate("conversation.close")} accessibilityRole="button" onPress={onClose} style={styles.backdrop} />
      {message ? <ActionsSheet key={message.key} message={message} onCopy={onCopy} onClose={onClose} /> : null}
    </Modal>
  );
}

const styles = StyleSheet.create({
  backdrop: { flex: 1 },
  sheet: { borderTopLeftRadius: RADIUS.bubble, borderTopRightRadius: RADIUS.bubble },
  title: { fontSize: FONT_SIZE.caption, fontWeight: "600", textTransform: "uppercase", padding: SPACING.md, textAlign: "center" },
  action: { minHeight: MIN_TOUCH_TARGET, justifyContent: "center", alignItems: "center", borderTopWidth: StyleSheet.hairlineWidth },
  actionText: { fontSize: FONT_SIZE.body },
  info: { fontSize: FONT_SIZE.body, padding: SPACING.md, textAlign: "center" },
});
