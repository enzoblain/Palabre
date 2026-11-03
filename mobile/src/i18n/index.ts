import { getLocales } from "expo-localization";
import { en } from "./en";
import { fr } from "./fr";

type En = typeof en;
export type Key = keyof En;
/** A dictionary has every key of the English one: a missing key breaks `npm run check`. */
export type Messages = { [K in Key]: string };

/** The names of the {placeholders} of a message, read from its English literal. */
type Vars<S extends string> = S extends `${string}{${infer N}}${infer R}` ? N | Vars<R> : never;
type Params<K extends Key> = [Vars<En[K]>] extends [never] ? [] : [vars: Record<Vars<En[K]>, string | number>];

const DICTIONARIES: Record<string, Messages> = { fr, en };
const FALLBACK_LANGUAGE = "en";

/** The phone's language when the app has it, else English. */
export function currentLanguage(): string {
  const code = getLocales()[0]?.languageCode ?? FALLBACK_LANGUAGE;
  return Object.prototype.hasOwnProperty.call(DICTIONARIES, code) ? code : FALLBACK_LANGUAGE;
}

export function translate<K extends Key>(key: K, ...[vars]: Params<K>): string {
  const text = DICTIONARIES[currentLanguage()][key];
  const values: Record<string, string | number> = vars ?? {};
  return text.replace(/\{(\w+)\}/g, (_, name: string) => String(values[name] ?? ""));
}
