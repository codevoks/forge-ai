import { existsSync } from "node:fs";
import { spawnSync } from "node:child_process";

const privateRuntimePaths = [
  ".env",
  ".env.local",
  ".env.development",
  ".local-learning",
  "apps/api/local/jwks.json",
  "apps/api/local/private-key.pem"
];

if (!existsSync(".git")) {
  const unsafePresent = privateRuntimePaths.filter((path) => existsSync(path) && path.startsWith(".env"));
  if (unsafePresent.length > 0) {
    console.error(`Private environment files are present before Git ignore validation: ${unsafePresent.join(", ")}`);
    process.exit(1);
  }
  console.log("Public-file guard skipped Git exposure check because Git is not initialized yet.");
  process.exit(0);
}

const result = spawnSync("git", ["status", "--short", "--", ...privateRuntimePaths], {
  encoding: "utf8"
});

if (result.status !== 0) {
  console.error(result.stderr.trim() || "Unable to inspect Git status for private runtime paths.");
  process.exit(result.status ?? 1);
}

const exposed = result.stdout.trim();
if (exposed.length > 0) {
  console.error(`Private runtime files are visible to Git:\n${exposed}`);
  process.exit(1);
}

console.log("Public-file guard passed: private runtime artifacts are not visible to Git.");
