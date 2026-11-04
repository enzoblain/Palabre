import { fileURLToPath } from "node:url";

import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// Fixed port: the backend allows it in CORS_ORIGINS
export default defineConfig({
  plugins: [react()],
  resolve: { alias: { "@palabre/shared": fileURLToPath(new URL("../shared/index.ts", import.meta.url)) } },
  clearScreen: false,
  test: { include: ["src/**/*.test.{ts,tsx}"] },
  server: { port: 1420, strictPort: true },
});
