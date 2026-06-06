import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  base: "/context-graph/",
  plugins: [react()],
  build: {
    outDir: "../../src/autopsy_memory/context_graph_viewer/static",
    emptyOutDir: true,
    sourcemap: false,
  },
});
