import { defineConfig } from "vite";
import { fileURLToPath, URL } from "node:url";
import react from "@vitejs/plugin-react";
import { VitePWA } from "vite-plugin-pwa";

export default defineConfig({
  // Keep Vite anchored to this config file when the portable build uses a
  // no-space junction on Windows for the native resource compiler.
  root: fileURLToPath(new URL(".", import.meta.url)),
  plugins: [
    react(),
    VitePWA({
      registerType: "autoUpdate",
      manifest: {
        name: "Clear English Speaking",
        short_name: "Clear English Speaking",
        description: "A private, local-first English listening practice player.",
        theme_color: "#f4f4eb",
        background_color: "#f4f4eb",
        display: "standalone"
      }
    })
  ],
  server: { host: "0.0.0.0" }
});
