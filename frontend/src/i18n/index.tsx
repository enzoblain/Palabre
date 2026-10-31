import { Fragment, type ReactNode, createContext, useContext, useEffect, useMemo, useState } from "react";
import { en } from "./en";
import { fr } from "./fr";

type En = typeof en;
export type Key = keyof En;
/** A dictionary has every key of the English one: a missing key breaks `npm run check`. */
export type Messages = { [K in Key]: string };

/** The names of the {placeholders} of a message, read from its English literal. */
type Vars<S extends string> = S extends `${string}{${infer N}}${infer R}` ? N | Vars<R> : never;
type Params<K extends Key> = [Vars<En[K]>] extends [never] ? [] : [vars: Record<Vars<En[K]>, string | number>];
type RichParams<K extends Key> = [Vars<En[K]>] extends [never] ? [] : [vars: Record<Vars<En[K]>, ReactNode>];

// Keys are the backend's team languages (services.LANGUAGES). The others fall back to English.
const DICTIONARIES: Record<string, Messages> = { French: fr, English: en };
const LOCALES: Record<string, string> = {
  French: "fr", English: "en", Spanish: "es", German: "de", Italian: "it", Portuguese: "pt", Dutch: "nl",
};
const STORAGE_KEY = "palabre.language";
export const DEFAULT_LANGUAGE = "French";

/** Before the settings are known (login screen): the last language seen, else the browser's. */
function initialLanguage(): string {
  const saved = localStorage.getItem(STORAGE_KEY);
  if (saved && saved in LOCALES) return saved;
  const browser = navigator.language.slice(0, 2);
  return Object.keys(LOCALES).find((k) => LOCALES[k] === browser) ?? DEFAULT_LANGUAGE;
}

let current = initialLanguage();

export function locale(): string {
  return LOCALES[current] ?? LOCALES[DEFAULT_LANGUAGE];
}

function template(key: Key, vars: Record<string, string | number> = {}): string {
  const text = (DICTIONARIES[current] ?? en)[key];
  return text.replace(/\{(\w+)\}/g, (_, name) => String(vars[name] ?? `{${name}}`));
}

/** Translation outside React (API errors, helpers): follows the language of the provider. */
export function translate<K extends Key>(key: K, ...[vars]: Params<K>): string {
  return template(key, vars as Record<string, string | number> | undefined);
}

function rich(key: Key, vars: Record<string, ReactNode> = {}): ReactNode {
  const text = (DICTIONARIES[current] ?? en)[key];
  return text.split(/(\{\w+\})/).map((part, i) => {
    const name = /^\{(\w+)\}$/.exec(part)?.[1];
    return <Fragment key={i}>{name ? vars[name] : part}</Fragment>;
  });
}

type I18n = {
  language: string;
  setLanguage: (language: string) => void;
  t: typeof translate;
  /** Like `t`, with elements as values (links, <code>). */
  tr: <K extends Key>(key: K, ...vars: RichParams<K>) => ReactNode;
};

const Context = createContext<I18n | null>(null);

export function I18nProvider({ children }: { children: ReactNode }) {
  const [language, setLanguageState] = useState(current);
  current = language; // Set during render so children and `translate` agree
  useEffect(() => {
    localStorage.setItem(STORAGE_KEY, language);
    document.documentElement.lang = locale();
  }, [language]);
  const value = useMemo<I18n>(() => ({
    language,
    setLanguage: (l) => setLanguageState(l in LOCALES ? l : DEFAULT_LANGUAGE),
    t: translate,
    tr: (key, ...[vars]) => rich(key, vars as Record<string, ReactNode> | undefined),
  }), [language]);
  return <Context.Provider value={value}>{children}</Context.Provider>;
}

export function useI18n(): I18n {
  const value = useContext(Context);
  if (!value) throw new Error("useI18n outside I18nProvider");
  return value;
}
