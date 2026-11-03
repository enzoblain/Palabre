import { useColorScheme } from "react-native";
import { COLORS, type Colors } from "./tokens";

/** The colors of the system's appearance (light unless the phone is in dark mode). */
export function useColors(): Colors {
  return COLORS[useColorScheme() === "dark" ? "dark" : "light"];
}

export * from "./tokens";
