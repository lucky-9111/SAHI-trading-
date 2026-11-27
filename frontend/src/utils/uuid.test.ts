import { afterEach, describe, expect, it, vi } from "vitest";
import { uuid } from "./uuid";

describe("uuid", () => {
  afterEach(() => vi.unstubAllGlobals());
  it("works when crypto.randomUUID is missing (plain HTTP)", () => {
    vi.stubGlobal("crypto", { getRandomValues: (a: Uint8Array) => a.fill(7) });
    expect(uuid()).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
  });
  it("works with no crypto at all", () => {
    vi.stubGlobal("crypto", undefined);
    expect(uuid()).toHaveLength(36);
  });
});
