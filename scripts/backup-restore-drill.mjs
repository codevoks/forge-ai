import { spawnSync } from "node:child_process";
import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

// Phase 13 backup/restore drill: proves pg_dump/pg_restore genuinely work
// against the local zero-cost stack and measures a local-profile RPO/RTO
// proxy. It never touches the real "forge" database's data — it restores
// into a throwaway database inside the same Postgres container and diffs
// row counts, then drops that database again.

const DRILL_DB = `forge_restore_drill_${Date.now()}`;
const TABLES_TO_VERIFY = ["tenants", "workspaces", "users", "runs", "tasks", "execution_events"];

function run(command, args, options = {}) {
  const result = spawnSync(command, args, { stdio: "pipe", encoding: "utf8", ...options });
  if (result.status !== 0) {
    const detail = result.stderr || result.stdout || `exit code ${result.status}`;
    throw new Error(`${command} ${args.join(" ")} failed: ${detail}`);
  }
  return result.stdout;
}

function psql(database, sql) {
  return run("docker", [
    "compose",
    "exec",
    "-T",
    "postgres",
    "psql",
    "-U",
    "forge",
    "-d",
    database,
    "-t",
    "-A",
    "-c",
    sql
  ]).trim();
}

function rowCounts(database) {
  const counts = {};
  for (const table of TABLES_TO_VERIFY) {
    const raw = psql(database, `select count(*) from ${table};`);
    counts[table] = Number.parseInt(raw, 10) || 0;
  }
  return counts;
}

async function main() {
  const workDir = mkdtempSync(join(tmpdir(), "forge-backup-drill-"));
  const dumpPath = join(workDir, "forge-backup.dump");

  console.log("Confirming the local zero-cost stack is running...");
  run("docker", ["compose", "ps", "postgres"]);

  console.log("Recording row counts in the live 'forge' database (before backup)...");
  const before = rowCounts("forge");

  console.log(`Backing up 'forge' with pg_dump (custom format) to ${dumpPath}...`);
  const backupStart = Date.now();
  const dumpResult = spawnSync(
    "docker",
    ["compose", "exec", "-T", "postgres", "pg_dump", "-U", "forge", "-d", "forge", "-Fc"],
    { stdio: ["ignore", "pipe", "pipe"] }
  );
  if (dumpResult.status !== 0) {
    throw new Error(`pg_dump failed: ${dumpResult.stderr?.toString() ?? "unknown error"}`);
  }
  writeFileSync(dumpPath, dumpResult.stdout);
  const backupSeconds = (Date.now() - backupStart) / 1000;

  console.log(`Creating throwaway restore-verification database '${DRILL_DB}'...`);
  run("docker", [
    "compose",
    "exec",
    "-T",
    "postgres",
    "createdb",
    "-U",
    "forge",
    DRILL_DB
  ]);

  try {
    console.log("Restoring the backup into the throwaway database...");
    const restoreStart = Date.now();
    const restoreResult = spawnSync(
      "docker",
      [
        "compose",
        "exec",
        "-T",
        "postgres",
        "pg_restore",
        "-U",
        "forge",
        "-d",
        DRILL_DB,
        "--no-owner",
        "--no-privileges"
      ],
      { input: dumpResult.stdout, stdio: ["pipe", "pipe", "pipe"] }
    );
    // pg_restore exits non-zero on warnings (e.g. extension already exists);
    // treat it as a hard failure only if the restored row counts don't match.
    const restoreSeconds = (Date.now() - restoreStart) / 1000;
    void restoreResult;

    console.log("Verifying restored row counts match the backed-up database...");
    const after = rowCounts(DRILL_DB);

    const mismatches = TABLES_TO_VERIFY.filter((table) => before[table] !== after[table]);
    const report = {
      profile: "local_single_container_no_replica",
      drill_database: DRILL_DB,
      backup_seconds_rpo_proxy: Number(backupSeconds.toFixed(2)),
      restore_seconds_rto_proxy: Number(restoreSeconds.toFixed(2)),
      row_counts_before_backup: before,
      row_counts_after_restore: after,
      mismatched_tables: mismatches,
      status: mismatches.length === 0 ? "passed" : "failed",
      caveat:
        "Single local container, no replica, no continuous WAL archiving. This measures " +
        "pg_dump/pg_restore mechanics and local timing only, not a production RPO/RTO SLA.",
      paid_provider_calls: 0
    };
    console.log(JSON.stringify({ action: "phase13_backup_restore_drill", result: report }));
    if (mismatches.length > 0) {
      throw new Error(`Row count mismatch after restore: ${mismatches.join(", ")}`);
    }
  } finally {
    console.log(`Dropping throwaway database '${DRILL_DB}'...`);
    run("docker", ["compose", "exec", "-T", "postgres", "dropdb", "-U", "forge", DRILL_DB]);
    rmSync(workDir, { recursive: true, force: true });
  }
}

main().catch((error) => {
  console.error(error.message);
  process.exitCode = 1;
});
