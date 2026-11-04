module.exports = {
  preset: "jest-expo",
  testTimeout: 30000, // cold jest-expo start on CI is slow
  moduleNameMapper: { "^@palabre/shared$": "<rootDir>/../shared/index.ts" },
  testPathIgnorePatterns: ["/node_modules/"],
};
