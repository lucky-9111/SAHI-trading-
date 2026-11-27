import { describe, expect, it } from "vitest";
import { inr, pnlClass } from "./format";

describe("format", () => {
  it("formats rupees in Indian grouping", () => {
    expect(inr("1000000")).toBe("₹10,00,000.00");
    expect(inr(-40, true)).toBe("-₹40.00");
    expect(inr(4000, true)).toBe("+₹4,000.00");
  });
  it("colours P&L", () => {
    expect(pnlClass(5)).toBe("text-up");
    expect(pnlClass(-5)).toBe("text-down");
    expect(pnlClass(0)).toBe("text-slate-500");
  });
});
