import type { ReactNode } from "react";
import { Modal, Pressable, StyleSheet, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { FONT_SIZE, MAX_FONT_SCALE, MIN_TOUCH_TARGET, SPACING, useColors } from "../theme";

type Props = {
  title: string;
  closeLabel: string;
  visible: boolean;
  onClose: () => void;
  children: ReactNode;
};

/** Page sheet with a title and a close button on top, shared by the pickers and the forms opened from a screen. */
export function SheetModal({ title, closeLabel, visible, onClose, children }: Props) {
  const colors = useColors();
  return (
    <Modal visible={visible} animationType="slide" presentationStyle="pageSheet" onRequestClose={onClose}>
      <SafeAreaView style={[styles.screen, { backgroundColor: colors.background }]}>
        <View style={[styles.bar, { borderBottomColor: colors.separator }]}>
          <Text accessibilityRole="header" maxFontSizeMultiplier={MAX_FONT_SCALE} style={[styles.title, { color: colors.text }]}>
            {title}
          </Text>
          <Pressable accessibilityRole="button" onPress={onClose} style={styles.close}>
            <Text maxFontSizeMultiplier={MAX_FONT_SCALE} style={[styles.closeText, { color: colors.link }]}>
              {closeLabel}
            </Text>
          </Pressable>
        </View>
        {children}
      </SafeAreaView>
    </Modal>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1 },
  bar: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingLeft: SPACING.lg, borderBottomWidth: StyleSheet.hairlineWidth },
  title: { flex: 1, fontSize: FONT_SIZE.body, fontWeight: "600" },
  close: { minHeight: MIN_TOUCH_TARGET, justifyContent: "center", paddingHorizontal: SPACING.lg },
  closeText: { fontSize: FONT_SIZE.body },
});
