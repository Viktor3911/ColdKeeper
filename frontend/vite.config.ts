import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// In development the browser talks to Vite only; /api is proxied to the backend, so it is one origin
// (session cookie and CSRF work exactly as behind the production reverse proxy).
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      "/api": { target: "http://localhost:8000", changeOrigin: false },
    },
  },
  build: {
    sourcemap: false,
    chunkSizeWarningLimit: 800,
  },
});
