import type { PersonalityPreset } from "./api";

/** Value of the "Random" radio: no preset, the server draws a personality. */
export const RANDOM_PRESET = "random";

/** Lowercase text without accents, so that a search for "deterge" finds "Déterminé". */
function normalize(text: string): string {
  return text.normalize("NFD").replace(/\p{M}/gu, "").toLowerCase();
}

/** Presets whose name or description contains every word of the query, sorted by name. */
export function filterPresets(presets: Record<string, PersonalityPreset>, query: string): PersonalityPreset[] {
  const words = normalize(query).split(/\s+/).filter(Boolean);
  return Object.values(presets)
    .filter(({ label, description }) => {
      const haystack = normalize(`${label} ${description}`);
      return words.every((word) => haystack.includes(word));
    })
    .sort((a, b) => a.label.localeCompare(b.label));
}
