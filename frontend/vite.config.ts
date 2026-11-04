import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// Fixed port: the backend allows it in CORS_ORIGINS
export default defineConfig({
  plugins: [react()],
  resolve: { alias: { "@palabre/shared": new URL("../shared/index.ts", import.meta.url).pathname } },
  clearScreen: false,
  test: { include: ["src/**/*.test.{ts,tsx}"] },
  server: { port: 1420, strictPort: true },
});
