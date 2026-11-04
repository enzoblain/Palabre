// Metro must watch and resolve ../shared (types and constants used by the web app too).
const path = require("path");
const { getDefaultConfig } = require("expo/metro-config");

const sharedRoot = path.resolve(__dirname, "../shared");
const config = getDefaultConfig(__dirname);

config.watchFolders = [...(config.watchFolders ?? []), sharedRoot];
config.resolver.resolveRequest = (context, moduleName, platform) =>
  moduleName === "@palabre/shared"
    ? { type: "sourceFile", filePath: path.join(sharedRoot, "index.ts") }
    : context.resolveRequest(context, moduleName, platform);

module.exports = config;
