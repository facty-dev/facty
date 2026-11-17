import { fileURLToPath, URL } from "node:url";
import { defineConfig } from "vite";
import { svelte } from "@sveltejs/vite-plugin-svelte";
import tailwindcss from "@tailwindcss/vite";

// Static build served by `facty serve` (ADR-0011). base "./" so the app works
// under any mount prefix (vite.dev/guide/build.html).
export default defineConfig({
  base: "./",
  plugins: [tailwindcss(), svelte()],
  resolve: {
    alias: { $lib: fileURLToPath(new URL("./src/lib", import.meta.url)) },
  },
  build: { outDir: "dist", emptyOutDir: true },
});
