export type CopyResult = "copied" | "failed";

/** Wraps the browser Clipboard API with graceful failure — never throws. */
export async function copyToClipboard(value: string): Promise<CopyResult> {
  try {
    if (typeof navigator === "undefined" || !navigator.clipboard?.writeText) {
      return "failed";
    }
    await navigator.clipboard.writeText(value);
    return "copied";
  } catch {
    return "failed";
  }
}
