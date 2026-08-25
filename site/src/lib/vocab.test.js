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

    it("scales an absolute metric as a ratio to the best value on screen", () => {
        // Best (fastest) is 10s: it earns a full bar, and twice as slow is half.
        expect(metricBarFraction("latency", 10, 10)).toBeCloseTo(1);
        expect(metricBarFraction("latency", 20, 10)).toBeCloseTo(0.5);
        expect(metricBarFraction("latency", 100, 10)).toBeCloseTo(0.1);
    });

    it("gives the only visible setup a full bar, not a sliver", () => {
        // Regression: filtering down to one row made value === the scale, which
        // previously floored the bar at 2% for the fastest setup on screen.
        expect(metricBarFraction("latency", 42, 42)).toBeCloseTo(1);
        expect(metricBarFraction("tokens", 38412, 38412)).toBeCloseTo(1);
    });

    it("keeps near-equal values near-equal instead of full vs empty", () => {
        // Regression: min..max normalization would render these 1.0 and 0.0,
        // turning a 1% gap into the whole bar width.
        expect(metricBarFraction("latency", 99, 99)).toBeCloseTo(1);
        expect(metricBarFraction("latency", 100, 99)).toBeCloseTo(0.99, 2);
    });

    it("is empty for a missing value or an unusable scale", () => {
        expect(metricBarFraction("latency", null, 100)).toBe(0);
        expect(metricBarFraction("latency", 10, null)).toBe(0);
        // 0 is the unmeasured sentinel, not an instant run — no bar for it.
        expect(metricBarFraction("latency", 0, 10)).toBe(0);
        expect(metricBarFraction("latency", 10, 0)).toBe(0);
    });
});
