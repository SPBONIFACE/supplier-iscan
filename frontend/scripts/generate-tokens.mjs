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

// The PDF (#39) has its own copies, because the backend Docker build context cannot read `_docs/` or
// `frontend/`: the same tokens, and the same @font-face rules with URLs relative to backend/app/pdf/.
const pdfTokens = resolve(here, "../../backend/app/pdf/tokens.css");
const pdfFonts = resolve(here, "../../backend/app/pdf/fonts.css");
const fontsSource = resolve(here, "../src/styles/fonts.css");
// The PDF sets CJK text in the regular weight only (backend/app/pdf/render.py), so the SemiBold files of
// Sans JP, KR and SC (about 10 MB) are left out of its copy.
const dropForPdf = (block) =>
  /IBM Plex Sans (JP|KR|SC)"/.test(block) && /font-weight: 600/.test(block);
const fontsCss = readFileSync(fontsSource, "utf8")
  .replaceAll('url("/fonts/', 'url("fonts/')
  .split(/\n\n+/)
  .filter((block) => !dropForPdf(block))
  .join("\n\n");
const copies = [
  [target, css, "src/styles/tokens.css"],
  [pdfTokens, css, "backend/app/pdf/tokens.css"],
  [pdfFonts, fontsCss, "backend/app/pdf/fonts.css"],
];

if (process.argv.includes("--check")) {
  let stale = false;
  for (const [file, expected, name] of copies) {
    const current = existsSync(file) ? readFileSync(file, "utf8") : "";
    if (current !== expected) {
      console.error(`tokens: ${name} differs from its source; run \`pnpm tokens\``);
      stale = true;
    }
  }
  if (stale) process.exit(1);
  console.log("tokens: up to date");
} else {
  for (const [file, expected] of copies) writeFileSync(file, expected);
  console.log("tokens: written");
}
