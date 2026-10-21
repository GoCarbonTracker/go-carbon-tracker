import { createHash } from "node:crypto";
import { readdirSync, readFileSync, writeFileSync } from "node:fs";
import { join, resolve } from "node:path";
import { defineConfig, type ResolvedConfig } from "vite";
import react from "@vitejs/plugin-react";

const TOP = ["index.html", "package.json", "package-lock.json", "vite.config.ts", "tsconfig.json"];

function sha256(data: Buffer | string): string {
  return createHash("sha256").update(data).digest("hex");
}

function walk(dir: string, rel: string): string[] {
  return readdirSync(join(dir, rel), { withFileTypes: true }).flatMap((e) =>
    e.isDirectory() ? walk(dir, `${rel}/${e.name}`) : [`${rel}/${e.name}`],
  );
}

// The same algorithm as tests/test_viewer.py: one "<sha256>  <path>\n" line per source file, sorted by path,
// then the SHA-256 of those lines.
function sourceHash(dir: string): string {
  const files = [...TOP, ...walk(dir, "src")].sort();
  return sha256(files.map((f) => `${sha256(readFileSync(join(dir, f)))}  ${f}\n`).join(""));
}

function writeSourceHash() {
  let config: ResolvedConfig;
  return {
    name: "gct-source-hash",
    configResolved(c: ResolvedConfig) {
      config = c;
    },
    closeBundle() {
      const out = resolve(config.root, config.build.outDir);
      writeFileSync(join(out, "SOURCE.sha256"), sourceHash(config.root) + "\n");
    },
  };
}

export default defineConfig({
  base: "./",
  plugins: [react(), writeSourceHash()],
  build: { outDir: "../gct/viewer_dist", emptyOutDir: true },
});
