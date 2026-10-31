// Fails when a translation drops or invents a {placeholder} compared with the English message.
import { readFileSync } from "node:fs";

const entries = (file) =>
  new Map([...readFileSync(new URL(`../src/i18n/${file}`, import.meta.url), "utf8").matchAll(/^\s*"([\w.]+)":\s*("(?:[^"\\]|\\.)*"),?\s*$/gm)]
    .map(([, key, literal]) => [key, JSON.parse(literal)]));
const names = (text) => [...text.matchAll(/\{(\w+)\}/g)].map((m) => m[1]).sort().join(",");

const en = entries("en.ts");
const fr = entries("fr.ts");
const errors = [];
if (en.size === 0) errors.push("no English message parsed");
for (const [key, text] of en) {
  if (!fr.has(key)) errors.push(`${key}: missing in fr`);
  else if (names(text) !== names(fr.get(key))) errors.push(`${key}: placeholders differ (en {${names(text)}} / fr {${names(fr.get(key))}})`);
}
for (const key of fr.keys()) if (!en.has(key)) errors.push(`${key}: only in fr`);
// Every backend error code must be in ERROR_CODES and have an error.<code> message in both languages.
const backendCodes = [...readFileSync(new URL("../../backend/app/errors.py", import.meta.url), "utf8").matchAll(/^\s+[A-Z_]+ = "(\w+)"$/gm)].map((m) => m[1]);
const listed = readFileSync(new URL("../src/api.ts", import.meta.url), "utf8").match(/ERROR_CODES = \[([^\]]*)\]/)?.[1] ?? "";
if (backendCodes.length === 0) errors.push("no backend error code parsed");
for (const code of backendCodes) {
  if (!listed.includes(`"${code}"`)) errors.push(`${code}: missing in ERROR_CODES`);
  for (const [lang, map] of [["en", en], ["fr", fr]]) if (!map.has(`error.${code}`)) errors.push(`error.${code}: missing in ${lang}`);
}
if (errors.length) {
  console.error(errors.join("\n"));
  process.exit(1);
}
console.log(`i18n: ${en.size} messages, placeholders consistent`);
