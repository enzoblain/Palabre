import { Tabs } from "expo-router";
import { Ionicons } from "@expo/vector-icons";
import { translate, type Key } from "../../src/i18n";
import { MIN_TOUCH_TARGET, useColors } from "../../src/theme";

type IconName = keyof typeof Ionicons.glyphMap;

/** The three root sections of the web bottom bar, in the same order. */
const TABS = [
  { name: "index", label: "nav.projects", icon: "mail" },
  { name: "new", label: "nav.newProject", icon: "add-circle" },
  { name: "settings", label: "nav.settings", icon: "settings" },
] as const satisfies readonly { name: string; label: Key; icon: IconName }[];

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
        tabBarItemStyle: { minHeight: MIN_TOUCH_TARGET },
        tabBarStyle: { backgroundColor: colors.background, borderTopColor: colors.separator },
        sceneStyle: { backgroundColor: colors.background },
      }}
    >
      {TABS.map(({ name, label, icon }) => (
        <Tabs.Screen
          key={name}
          name={name}
          options={{
            title: translate(label),
            tabBarAccessibilityLabel: translate(label),
            tabBarIcon: ({ size, focused }) => (
              <Ionicons
                accessible={false}
                name={focused ? icon : (`${icon}-outline` as IconName)}
                size={size}
                color={focused ? colors.link : colors.secondaryText}
              />
            ),
          }}
        />
      ))}
    </Tabs>
  );
}
