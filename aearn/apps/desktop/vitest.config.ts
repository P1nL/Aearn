import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    setupFiles: ["./src/ui/dsh-derived/tests/setup.ts"],
    css: true,
    clearMocks: true,
  },
});
