/// <reference types="vitest" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const API_TARGET = process.env.VITE_API_PROXY_TARGET ?? "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [react()],
  resolve: { alias: { "@": new URL("./src", import.meta.url).pathname } },
  server: {
    host: "127.0.0.1",
    port: 5173,
    proxy: { "/api": { target: API_TARGET }, "/docs": { target: API_TARGET }, "/openapi.json": { target: API_TARGET } },
  },
  preview: { proxy: { "/api": { target: API_TARGET }, "/docs": { target: API_TARGET }, "/openapi.json": { target: API_TARGET } } },
  build: {
    chunkSizeWarningLimit: 1600,
    rollupOptions: {
      output: { manualChunks: { three: ["three", "@react-three/fiber", "@react-three/drei"], charts: ["recharts"] } },
    },
  },
  test: { environment: "jsdom", setupFiles: ["./src/test/setup.ts"], css: false },
});
