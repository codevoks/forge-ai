import { spawn } from "node:child_process";
import process from "node:process";

const env = {
  ...process.env,
  FORGE_EXTERNAL_INTEGRATIONS: "disabled",
  FORGE_DATABASE_URL:
    process.env.FORGE_DATABASE_URL ??
    "postgresql://forge_runtime:forge_runtime@localhost:55432/forge",
  FORGE_MIGRATION_DATABASE_URL:
    process.env.FORGE_MIGRATION_DATABASE_URL ?? "postgresql://forge:forge@localhost:55432/forge",
  FORGE_OIDC_ISSUER: process.env.FORGE_OIDC_ISSUER ?? "http://forge.local/oidc",
  FORGE_OIDC_AUDIENCE: process.env.FORGE_OIDC_AUDIENCE ?? "forge-local",
  FORGE_OIDC_JWKS_PATH: process.env.FORGE_OIDC_JWKS_PATH ?? "local/jwks.json",
  NEXT_PUBLIC_FORGE_API_BASE_URL:
    process.env.NEXT_PUBLIC_FORGE_API_BASE_URL ?? "http://127.0.0.1:8000"
};

function run(command, args, options = {}) {
  return new Promise((resolve, reject) => {
    const child = spawn(command, args, {
      stdio: "inherit",
      shell: false,
      env,
      ...options
    });
    child.on("exit", (code) => {
      if (code === 0) {
        resolve();
      } else {
        reject(new Error(`${command} ${args.join(" ")} exited with ${code}`));
      }
    });
  });
}

async function main() {
  if (env.FORGE_EXTERNAL_INTEGRATIONS !== "disabled") {
    throw new Error("pnpm demo requires FORGE_EXTERNAL_INTEGRATIONS=disabled.");
  }

  await run("docker", ["compose", "up", "-d", "postgres"]);
  await run("docker", ["compose", "up", "-d", "redis"]);
  await run("pnpm", ["--filter", "@forge/api", "db:migrate"]);
  await run("pnpm", ["--filter", "@forge/api", "db:seed"]);

  console.log("");
  console.log("Forge demo is starting with external integrations disabled.");
  console.log("Web:    http://127.0.0.1:3000");
  console.log("API:    http://127.0.0.1:8000/health/ready");
  console.log("Demo:   choose Alice Admin, create a run, then refresh to watch worker execution.");
  console.log("Worker: local Redis queue, leases, checkpoints, recovery, and dead letters are active.");
  console.log("");

  const api = spawn("pnpm", ["--filter", "@forge/api", "dev"], {
    stdio: "inherit",
    env
  });
  const web = spawn("pnpm", ["--filter", "@forge/web", "dev"], {
    stdio: "inherit",
    env
  });
  const worker = spawn("pnpm", ["--filter", "@forge/worker", "dev"], {
    stdio: "inherit",
    env
  });

  const shutdown = () => {
    api.kill("SIGTERM");
    web.kill("SIGTERM");
    worker.kill("SIGTERM");
  };

  process.on("SIGINT", shutdown);
  process.on("SIGTERM", shutdown);
}

main().catch((error) => {
  console.error(error.message);
  process.exit(1);
});
