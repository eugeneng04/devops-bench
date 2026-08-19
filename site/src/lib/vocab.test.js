import { describe, it, expect } from "vitest";
import { formatMetric, isLowerBetter, metricBarFraction, metricMeta } from "./vocab.js";

describe("metric presentation rules", () => {
    it("treats quality metrics as higher-is-better percentages", () => {
        for (const m of ["composite", "correctness", "recoverableSafety", "pass1"]) {
            expect(metricMeta(m).percentage).toBe(true);
            expect(isLowerBetter(m)).toBe(false);
        }
    });

    it("treats efficiency metrics as lower-is-better magnitudes", () => {
        for (const m of ["latency", "tokens"]) {
            expect(metricMeta(m).percentage).toBe(false);
            expect(isLowerBetter(m)).toBe(true);
        }
    });

    it("defaults an unknown metric to the percentage rules", () => {
        expect(metricMeta("nope").percentage).toBe(true);
    });
});

describe("formatMetric", () => {
    it("keeps one decimal on percentages so the column width is stable", () => {
        expect(formatMetric("composite", 90)).toBe("90.0%");
        expect(formatMetric("composite", 85.44)).toBe("85.4%");
    });

    it("renders latency in seconds and compacts large token counts", () => {
        expect(formatMetric("latency", 42.66)).toBe("42.7s");
        expect(formatMetric("latency", 8)).toBe("8.0s");
        expect(formatMetric("tokens", 38412)).toBe("38.4k");
        expect(formatMetric("tokens", 850)).toBe("850");
    });

    it("renders a missing value as an em dash, never as zero", () => {
        expect(formatMetric("latency", null)).toBe("—");
        expect(formatMetric("composite", undefined)).toBe("—");
        expect(formatMetric("tokens", NaN)).toBe("—");
    });
});

describe("metricBarFraction", () => {
    it("maps a percentage straight onto the bar", () => {
        expect(metricBarFraction("composite", 75, null)).toBeCloseTo(0.75);
    });

    it("inverts an absolute metric so the fastest setup gets the fullest bar", () => {
        // Scaled against the slowest (100s): 10s is nearly full, 100s is minimal.
        expect(metricBarFraction("latency", 10, 100)).toBeCloseTo(0.9);
        expect(metricBarFraction("latency", 100, 100)).toBeCloseTo(0.02);
    });

    it("is empty for a missing value or an unusable scale", () => {
        expect(metricBarFraction("latency", null, 100)).toBe(0);
        expect(metricBarFraction("latency", 10, null)).toBe(0);
    });
});
