// Generates src/styles/tokens.css from _docs/design/tokens.json (brief, "How the tokens are consumed").
// Node built-ins only. `--check` fails when the committed file differs from what the source gives.
// The source lives outside this folder, so a build context without `_docs/` skips the check.
import { existsSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const source = resolve(here, "../../_docs/design/tokens.json");
const target = resolve(here, "../src/styles/tokens.css");

const collect = (node, path, out) => {
  for (const [key, value] of Object.entries(node)) {
    if (key.startsWith("$")) continue;
    if (value && typeof value === "object" && "$value" in value) {
      out.push([[...path, key].join("-"), value.$value]);
    } else if (value && typeof value === "object") {
      collect(value, [...path, key], out);
    }
  }
  return out;
};

const render = (tokens) => {
  const lines = collect(tokens, [], [])
    .sort((a, b) => (a[0] < b[0] ? -1 : 1))
    .map(([name, raw]) => {
      const value = Array.isArray(raw)
        ? raw.map((f) => (/^[a-z-]+$/i.test(f) ? f : `"${f}"`)).join(", ")
        : String(raw).replace(/\{([^}]+)\}/g, (_, ref) => `var(--isc-${ref.replaceAll(".", "-")})`);
      return `  --isc-${name}: ${value};`;
    });
  return `/* Generated from _docs/design/tokens.json, do not edit. */\n:root {\n${lines.join("\n")}\n}\n`;
};

if (!existsSync(source)) {
  console.log("tokens: _docs/design/tokens.json not available here, check skipped");
  process.exit(0);
}
const css = render(JSON.parse(readFileSync(source, "utf8")));
if (process.argv.includes("--check")) {
  const current = existsSync(target) ? readFileSync(target, "utf8") : "";
  if (current !== css) {
    console.error("tokens: src/styles/tokens.css differs from tokens.json; run `pnpm tokens`");
    process.exit(1);
  }
  console.log("tokens: up to date");
} else {
  writeFileSync(target, css);
  console.log("tokens: written");
}
