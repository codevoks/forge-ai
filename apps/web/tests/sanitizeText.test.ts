import { describe, expect, it } from "vitest";
import { buildReportFilename, sanitizeReportText } from "../src/lib/sanitizeText";

describe("sanitizeReportText", () => {
  it("strips control characters from untrusted content", () => {
    const hostile = "line one\x00\x07\x1Bline two";
    expect(sanitizeReportText(hostile)).toBe("line oneline two");
  });

  it("caps very long content and marks it truncated", () => {
    const long = "a".repeat(1000);
    const result = sanitizeReportText(long, 50);
    expect(result.length).toBe(51); // 50 chars + ellipsis
    expect(result.endsWith("…")).toBe(true);
  });

  it("leaves ordinary tool/evidence text untouched", () => {
    expect(sanitizeReportText("Simulated ticket creation")).toBe("Simulated ticket creation");
  });

  it("renders non-string values as JSON rather than throwing", () => {
    expect(sanitizeReportText({ a: 1 })).toBe('{"a":1}');
  });

  it("returns an empty string for null/undefined instead of the literal text", () => {
    expect(sanitizeReportText(null)).toBe("");
    expect(sanitizeReportText(undefined)).toBe("");
  });
});

describe("buildReportFilename", () => {
  it("produces a safe filename from a UUID run id", () => {
    expect(buildReportFilename("01a06109-1234-7abc-9def-000000000000")).toBe(
      "forge-execution-report-01a06109-1234-7abc-9def-000000000000.pdf"
    );
  });

  it("strips path traversal and shell-hostile characters from a malicious run id", () => {
    const hostile = "../../etc/passwd; rm -rf ~ `whoami`";
    const filename = buildReportFilename(hostile);
    expect(filename.startsWith("forge-execution-report-")).toBe(true);
    expect(filename.endsWith(".pdf")).toBe(true);
    const idPortion = filename.slice("forge-execution-report-".length, -".pdf".length);
    expect(idPortion).not.toMatch(/[./~`;\s]/);
  });

  it("falls back to a generic name if the id sanitizes to nothing", () => {
    expect(buildReportFilename("../../../")).toBe("forge-execution-report-run.pdf");
  });
});
