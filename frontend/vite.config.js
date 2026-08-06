import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Backend port is overridable via VITE_BACKEND_PROXY_TARGET -- this
// machine runs several sibling forecast-dashboard projects that also
// default to 8000/5173/5174, so a collision here is a recurring real
// problem, not hypothetical (confirmed live more than once).
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5174,
    proxy: {
      "/api": {
        target: process.env.VITE_BACKEND_PROXY_TARGET || "http://127.0.0.1:8000",
        changeOrigin: true,
      },
    },
  },
});
