/** Design tokens of docs/mobile-ui.md, light and dark. */
export type ColorScheme = "light" | "dark";

export type Colors = {
  background: string;
  secondaryBackground: string;
  text: string;
  secondaryText: string;
  separator: string;
  sentBubble: string;
  link: string;
  sentBubbleText: string;
  sendingBubble: string;
  receivedBubble: string;
  error: string;
  success: string;
  avatarText: string;
};

export const COLORS: Record<ColorScheme, Colors> = {
  light: {
    background: "#FFFFFF",
    secondaryBackground: "#F2F2F7",
    text: "#000000",
    secondaryText: "#6C6C70",
    separator: "#C6C6C8",
    sentBubble: "#0066E0",
    link: "#0066E0",
    sentBubbleText: "#FFFFFF",
    sendingBubble: "#4472B8", // paler blue that keeps 4.5:1 with white text
    receivedBubble: "#E9E9EB",
    error: "#D70015",
    success: "#17743A",
    avatarText: "#FFFFFF",
  },
  dark: {
    background: "#000000",
    secondaryBackground: "#1C1C1E",
    text: "#FFFFFF",
    secondaryText: "#98989F",
    separator: "#38383A",
    sentBubble: "#0066E0",
    link: "#4DA3FF",
    sentBubbleText: "#FFFFFF",
    sendingBubble: "#4472B8", // paler blue that keeps 4.5:1 with white text
    receivedBubble: "#26262A",
    error: "#FF453A",
    success: "#34C759",
    avatarText: "#FFFFFF",
  },
};

export const SPACING = { xs: 4, sm: 8, md: 12, lg: 16, xl: 24 } as const;
export const RADIUS = { bubble: 18, input: 18, button: 14 } as const;
export const FONT_SIZE = { body: 17, caption: 12, largeTitle: 34 } as const;
export const MAX_FONT_SCALE = 2; // Dynamic Type cap on text that can wrap or grow
export const AVATAR_INITIALS_MAX_FONT_SCALE = 1.2; // initials must stay inside the avatar circle
export const MIN_TOUCH_TARGET = 44;
export const BUTTON_HEIGHT = 50;
