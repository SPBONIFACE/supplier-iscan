// Fails when src/lib/api-schema.d.ts is not what openapi-typescript generates from ../openapi.yaml.
// Skipped when openapi.yaml is not available (a build context limited to frontend/).
import { execFileSync } from "node:child_process";
import { existsSync, mkdtempSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const spec = resolve(here, "../../openapi.yaml");
const committed = resolve(here, "../src/lib/api-schema.d.ts");
const cli = resolve(here, "../node_modules/.bin/openapi-typescript");

if (!existsSync(spec)) {
  console.log("api types: openapi.yaml not available here, check skipped");
  process.exit(0);
}
const out = join(mkdtempSync(join(tmpdir(), "isc-api-")), "api-schema.d.ts");
execFileSync(cli, [spec, "-o", out], { stdio: "ignore" });
if (readFileSync(out, "utf8") !== readFileSync(committed, "utf8")) {
  console.error(
    "api types: src/lib/api-schema.d.ts differs from openapi.yaml; run `pnpm api:types`",
  );
  process.exit(1);
}
console.log("api types: up to date");
