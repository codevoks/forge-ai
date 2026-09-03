import { afterEach, describe, expect, it, vi } from "vitest";
import { copyToClipboard } from "../src/lib/clipboard";

describe("copyToClipboard", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("resolves 'copied' when the Clipboard API succeeds", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    vi.stubGlobal("navigator", { clipboard: { writeText } });

    const result = await copyToClipboard("run-123");

    expect(result).toBe("copied");
    expect(writeText).toHaveBeenCalledWith("run-123");
  });

  it("resolves 'failed' instead of throwing when the Clipboard API rejects", async () => {
    const writeText = vi.fn().mockRejectedValue(new Error("denied"));
    vi.stubGlobal("navigator", { clipboard: { writeText } });

    await expect(copyToClipboard("secret-looking-value")).resolves.toBe("failed");
  });

  it("resolves 'failed' when the Clipboard API is unavailable (insecure context)", async () => {
    vi.stubGlobal("navigator", {});

    await expect(copyToClipboard("value")).resolves.toBe("failed");
  });
});
