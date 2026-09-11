import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
export default defineConfig({
  plugins: [react()],
  server: {
    host: "0.0.0.0",
    port: 5174,
    strictPort: true,
    allowedHosts: ["uclams.54ucl.com", "localhost", "127.0.0.1"],
    proxy: {
      "/api": { target: process.env.AMS_API_TARGET || "http://127.0.0.1:8001" },
    },
  },
  build: { chunkSizeWarningLimit: 1100 },
});
