// Fails when the nginx or Tauri CSP is missing, or allows inline scripts in production.
import { readFileSync } from "node:fs";

const read = (path) => readFileSync(new URL(path, import.meta.url), "utf8");
const scriptSrc = (csp) => csp.split(";").map((d) => d.trim()).find((d) => d.startsWith("script-src"));

const policies = {
  "security-headers.conf": read("../security-headers.conf").match(/Content-Security-Policy "([^"]*)"/)?.[1],
  "tauri.conf.json csp": JSON.parse(read("../src-tauri/tauri.conf.json")).app.security.csp,
};
const errors = [];
for (const [name, csp] of Object.entries(policies)) {
  if (!csp) errors.push(`${name}: no CSP`);
  else if (!scriptSrc(csp) || scriptSrc(csp).includes("'unsafe-inline'")) errors.push(`${name}: script-src missing or allows 'unsafe-inline'`);
}
if (errors.length > 0) {
  console.error(errors.join("\n"));
  process.exit(1);
}
