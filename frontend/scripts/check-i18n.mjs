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
if (errors.length) {
  console.error(errors.join("\n"));
  process.exit(1);
}
console.log(`i18n: ${en.size} messages, placeholders consistent`);
