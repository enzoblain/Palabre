import { readFileSync } from "node:fs";
import { join } from "node:path";
import { ERROR_CODES } from "../src/api";

jest.mock("expo-localization", () => ({ getLocales: () => [{ languageCode: "en" }] }));

const WEB_API = join(__dirname, "..", "..", "frontend", "src", "api.ts");

/** The web client is the reference: a copied ERROR_CODES that drifts from it fails here. */
describe("API client drift", () => {
  it("has the same ERROR_CODES as frontend/src/api.ts", () => {
    const block = readFileSync(WEB_API, "utf8").match(/ERROR_CODES = \[([^\]]*)\]/)?.[1] ?? "";
    const webCodes = [...block.matchAll(/"(\w+)"/g)].map((match) => match[1]);
    expect(webCodes.length).toBeGreaterThan(0);
    expect([...ERROR_CODES]).toEqual(webCodes);
  });
});
