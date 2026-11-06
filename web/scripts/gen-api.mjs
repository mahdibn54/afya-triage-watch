// Regenerates src/api/types.ts from FastAPI's /openapi.json (E7-10). Cross-platform (npm runs scripts with cmd on
// Windows, where ${API_URL:-...} does not work). API_URL defaults to the UI's proxy of the running compose stack.
import { execFileSync } from "node:child_process";
import { createRequire } from "node:module";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const require = createRequire(import.meta.url);
const pkg = require.resolve("openapi-typescript/package.json");
const cli = join(dirname(pkg), require(pkg).bin["openapi-typescript"]);
const base = (process.env.API_URL ?? "http://127.0.0.1:3000/api").replace(/\/+$/, "");

execFileSync(process.execPath, [cli, `${base}/openapi.json`, "-o", join(here, "../src/api/types.ts")], { stdio: "inherit" });
