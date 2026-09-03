/**
 * Strips control characters and caps length before any untrusted string
 * (model/tool/MCP output, evidence summaries, tool arguments) is drawn into
 * a PDF. jsPDF only ever renders these as glyphs — never interprets them —
 * but this keeps garbled control bytes and runaway payloads out of the
 * report regardless.
 */
export function sanitizeReportText(value: unknown, maxLength = 400): string {
  if (value === null || value === undefined) return "";
  const raw = typeof value === "string" ? value : JSON.stringify(value);
  const stripped = raw.replace(/[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]/g, "");
  return stripped.length > maxLength ? `${stripped.slice(0, maxLength)}…` : stripped;
}

/** Builds a filesystem-safe filename from a run id and objective. */
export function buildReportFilename(runId: string): string {
  const safeId = runId.replace(/[^a-zA-Z0-9-]/g, "").slice(0, 64) || "run";
  return `forge-execution-report-${safeId}.pdf`;
}
