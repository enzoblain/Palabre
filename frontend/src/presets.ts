import type { MemberIn, Personality, PersonalityPreset } from "./api";

/** Value of the "Random" radio: no preset, the personality is drawn. */
export const RANDOM_PRESET = "random";

/** Lowest and highest level of an axis: the bar of a preset is drawn on that scale. */
export const MIN_LEVEL = -2;
export const MAX_LEVEL = 2;

/** The member's personality fields once a preset is applied: axes the preset leaves out are neutral,
 * and the style falls back to what the member already has. */
export function applyPreset(
  preset: PersonalityPreset,
  personality: Personality,
  current: Pick<MemberIn, "style">,
): Pick<MemberIn, "traits" | "quirks" | "style" | "personality"> {
  return {
    traits: Object.fromEntries(personality.axes.map((axis) => [axis.key, preset.traits[axis.key] ?? 0])),
    quirks: [...preset.quirks],
    style: { ...current.style, ...preset.style },
    personality: preset.key,
  };
}

/** Axes a preset leans on (non-neutral), strongest first, with the label of the axis. */
export function leaningAxes(preset: PersonalityPreset, personality: Personality): { label: string; level: number }[] {
  return personality.axes
    .map((axis) => ({ label: axis.label, level: preset.traits[axis.key] ?? 0 }))
    .filter(({ level }) => level !== 0)
    .sort((a, b) => Math.abs(b.level) - Math.abs(a.level));
}

/** A level written as a number, always signed except for zero ("+2", "-1", "0"). */
export function formatLevel(level: number): string {
  return level > 0 ? `+${level}` : String(level);
}

/** A level as a bar of (MAX_LEVEL - MIN_LEVEL + 1) cells, at least one filled; decorative, the number says it. */
export function levelBar(level: number): string {
  const cells = MAX_LEVEL - MIN_LEVEL + 1;
  const filled = Math.min(cells, Math.max(1, level - MIN_LEVEL + 1));
  return "▓".repeat(filled) + "░".repeat(cells - filled);
}
