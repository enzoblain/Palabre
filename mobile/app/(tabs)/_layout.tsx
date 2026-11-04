import { Tabs } from "expo-router";
import { Text } from "react-native";
import { translate, type Key } from "../../src/i18n";
import { MAX_FONT_SCALE, useColors } from "../../src/theme";

const TAB_ICON_SIZE = 22;

/** The three root sections of the web bottom bar, in the same order. */
const TABS = [
  { name: "index", label: "nav.projects", glyph: "✉︎" },
  { name: "new", label: "nav.newProject", glyph: "＋" },
  { name: "settings", label: "nav.settings", glyph: "⚙︎" },
] as const satisfies readonly { name: string; label: Key; glyph: string }[];

/** Bottom tab bar of the root screens; the bar sits above the home indicator and the Android gesture bar. */
export default function TabsLayout() {
  const colors = useColors();
  return (
    <Tabs
      screenOptions={{
        headerShown: false,
        tabBarActiveTintColor: colors.link,
        tabBarInactiveTintColor: colors.secondaryText,
        tabBarAllowFontScaling: true,
        tabBarStyle: { backgroundColor: colors.background, borderTopColor: colors.separator },
        sceneStyle: { backgroundColor: colors.background },
      }}
    >
      {TABS.map(({ name, label, glyph }) => (
        <Tabs.Screen
          key={name}
          name={name}
          options={{
            title: translate(label),
            tabBarAccessibilityLabel: translate(label),
            tabBarIcon: ({ color }) => (
              <Text accessible={false} maxFontSizeMultiplier={MAX_FONT_SCALE} style={{ color, fontSize: TAB_ICON_SIZE }}>
                {glyph}
              </Text>
            ),
          }}
        />
      ))}
    </Tabs>
  );
}
