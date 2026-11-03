import { StyleSheet, View } from "react-native";
import { translate } from "../i18n";
import { RADIUS, SPACING, useColors } from "../theme";

export const SKELETON_BUBBLES = 5;
const BUBBLE_HEIGHT = 36;
const BUBBLE_WIDTHS = ["55%", "40%", "65%", "35%", "50%"];

/** Five alternating placeholder bubbles; VoiceOver reads one "loading" label instead of the blocks. */
export function MessageSkeleton() {
  const colors = useColors();
  return (
    <View accessible accessibilityLabel={translate("conversation.loading")} accessibilityLiveRegion="polite" style={styles.container}>
      {Array.from({ length: SKELETON_BUBBLES }, (_, index) => (
        <View
          key={index}
          style={[
            styles.bubble,
            { width: BUBBLE_WIDTHS[index % BUBBLE_WIDTHS.length] as `${number}%` },
            index % 2 === 0 ? styles.received : styles.own,
            { backgroundColor: colors.secondaryBackground },
          ]}
        />
      ))}
    </View>
  );
}

const styles = StyleSheet.create({
  container: { padding: SPACING.lg, gap: SPACING.sm },
  bubble: { height: BUBBLE_HEIGHT, borderRadius: RADIUS.bubble },
  received: { alignSelf: "flex-start" },
  own: { alignSelf: "flex-end" },
});
