// Copies every `<!-- example: ... -->` JSON block of docs/api.md into src/api/fixtures/.
// The fixtures are the contract's own examples, so the fake API never drifts from docs/api.md.
import { readFileSync, writeFileSync, mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const md = readFileSync(join(here, "../../docs/api.md"), "utf8");
const out = join(here, "../src/api/fixtures");
mkdirSync(out, { recursive: true });

const re = /<!-- example: (.+?) -->\s*```json\s*([\s\S]*?)```/g;
const slugs = [];
for (const [, title, body] of md.matchAll(re)) {
  const slug = title
    .toLowerCase()
    .replace(/\{id\}|\{run_id\}/g, "id")
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-|-$/g, "");
  JSON.parse(body); // fail loudly on a broken example
  writeFileSync(join(out, `${slug}.json`), body.trim() + "\n");
  slugs.push(slug);
}
console.log(`${slugs.length} fixtures:\n  ${slugs.join("\n  ")}`);
