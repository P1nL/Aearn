import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

function manualChunks(id: string) {
  const moduleId = id.replace(/\\/g, "/");
  if (!moduleId.includes("/node_modules/")) return undefined;

  if (
    moduleId.includes("/node_modules/react/") ||
    moduleId.includes("/node_modules/react-dom/") ||
    moduleId.includes("/node_modules/scheduler/") ||
    moduleId.includes("/node_modules/use-sync-external-store/")
  ) {
    return "react-vendor";
  }

  if (moduleId.includes("/node_modules/@assistant-ui/") || moduleId.includes("/node_modules/radix-ui/")) {
    return "assistant-ui";
  }

  if (moduleId.includes("/node_modules/@monaco-editor/") || moduleId.includes("/node_modules/monaco-editor/")) {
    return "monaco-editor";
  }

  if (
    moduleId.includes("/node_modules/@tauri-apps/api/") ||
    moduleId.includes("/node_modules/partial-json/") ||
    moduleId.includes("/node_modules/sonner/") ||
    moduleId.includes("/node_modules/zustand/")
  ) {
    return "app-vendor";
  }

  return "vendor";
}

export default defineConfig({
  plugins: [react()],
  clearScreen: false,
  server: {
    host: "127.0.0.1",
    port: 1420,
    strictPort: true,
  },
  build: {
    rollupOptions: {
      output: {
        manualChunks,
      },
    },
  },
});
