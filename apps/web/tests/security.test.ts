import { describe, expect, it } from "vitest";
import { API_BASE_URL } from "../src/lib/api";

describe("web security defaults", () => {
  it("uses only the local API base URL by default", () => {
    expect(API_BASE_URL).toBe("http://127.0.0.1:8000");
  });
});
