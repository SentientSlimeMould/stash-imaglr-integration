// SPDX-License-Identifier: AGPL-3.0-only
// Builds the plugin UI into plugins/imaglrIntegration/imaglrIntegration.{js,css}.
// The output is committed (Stash installs exactly what is in the plugin folder), so it is kept
// readable: not minified, no external source maps. `--watch` adds inline source maps for debugging.
import * as esbuild from "esbuild";
import { fileURLToPath } from "node:url";

const root = fileURLToPath(new URL("..", import.meta.url));
const watch = process.argv.includes("--watch");
const banner =
  "/* Imaglr Integration for Stash. SPDX-License-Identifier: AGPL-3.0-only\n" +
  " * Generated from src/ui by scripts/build.mjs. Do not edit. */";

const options = {
  absWorkingDir: root,
  entryPoints: [
    { in: "src/ui/index.tsx", out: "imaglrIntegration" },
    { in: "src/ui/styles.css", out: "imaglrIntegration" },
  ],
  outdir: "plugins/imaglrIntegration",
  bundle: true,
  format: "iife",
  target: "es2020",
  jsx: "transform",
  alias: { react: "./src/ui/shims/react.ts" },
  legalComments: "none",
  banner: { js: banner, css: banner },
  sourcemap: watch ? "inline" : false,
  logLevel: "info",
};

if (watch) {
  const context = await esbuild.context(options);
  await context.watch();
} else {
  await esbuild.build(options);
}
