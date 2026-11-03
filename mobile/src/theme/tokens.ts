/** Design tokens of docs/mobile-ui.md, light and dark. */
export type ColorScheme = "light" | "dark";

export type Colors = {
  background: string;
  secondaryBackground: string;
  text: string;
  secondaryText: string;
  separator: string;
  sentBubble: string;
  sentBubbleText: string;
  receivedBubble: string;
  error: string;
  success: string;
};

export const COLORS: Record<ColorScheme, Colors> = {
  light: {
    background: "#FFFFFF",
    secondaryBackground: "#F2F2F7",
    text: "#000000",
    secondaryText: "#6C6C70",
    separator: "#C6C6C8",
    sentBubble: "#0066E0",
    sentBubbleText: "#FFFFFF",
    receivedBubble: "#E9E9EB",
    error: "#D70015",
    success: "#17743A",
  },
  dark: {
    background: "#000000",
    secondaryBackground: "#1C1C1E",
    text: "#FFFFFF",
    secondaryText: "#98989F",
    separator: "#38383A",
    sentBubble: "#0066E0",
    sentBubbleText: "#FFFFFF",
    receivedBubble: "#26262A",
    error: "#FF453A",
    success: "#34C759",
  },
};

export const SPACING = { xs: 4, sm: 8, md: 12, lg: 16, xl: 24 } as const;
export const RADIUS = { bubble: 18, input: 18, button: 14 } as const;
export const FONT_SIZE = { body: 17, caption: 12, largeTitle: 34 } as const;
export const MIN_TOUCH_TARGET = 44;
export const BUTTON_HEIGHT = 50;
