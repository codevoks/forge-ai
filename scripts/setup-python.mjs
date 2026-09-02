import { existsSync } from "node:fs";
import { spawnSync } from "node:child_process";

function run(command, args) {
  const result = spawnSync(command, args, { stdio: "inherit" });
  if (result.status !== 0) {
    process.exit(result.status ?? 1);
  }
}

if (!existsSync(".venv/bin/python")) {
  run("python3", ["-m", "venv", ".venv"]);
}

const python = ".venv/bin/python";

run(python, ["-m", "pip", "install", "--upgrade", "pip", "setuptools"]);
run(python, [
  "-m",
  "pip",
  "install",
  "-e",
  "apps/api",
  "-e",
  "apps/worker",
  "mypy==1.17.1",
  "pytest==9.1.1",
  "pytest-cov==7.1.0",
  "redis==5.2.1",
  "ruff==0.12.9"
]);
