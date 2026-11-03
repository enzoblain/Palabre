import { Stack } from "expo-router";
import { StatusBar } from "expo-status-bar";
import { useColors } from "../src/theme";

export default function RootLayout() {
  const colors = useColors();
  return (
    <>
      <StatusBar style="auto" />
      <Stack screenOptions={{ contentStyle: { backgroundColor: colors.background } }}>
        <Stack.Screen name="index" options={{ headerShown: false }} />
        <Stack.Screen name="login" options={{ headerShown: false }} />
        <Stack.Screen name="conversation/[id]" options={{ headerShown: false }} />
      </Stack>
    </>
  );
}
