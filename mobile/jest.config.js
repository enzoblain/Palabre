module.exports = {
  preset: "jest-expo",
  testTimeout: 30000, // cold jest-expo start on CI is slow
  testPathIgnorePatterns: ["/node_modules/"],
};
