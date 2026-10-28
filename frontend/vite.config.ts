import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// Tauri expects a fixed port, and the Rust sources must not trigger reloads
export default defineConfig({
  plugins: [react()],
  clearScreen: false,
  server: { port: 1420, strictPort: true, watch: { ignored: ["**/src-tauri/**"] } },
});
