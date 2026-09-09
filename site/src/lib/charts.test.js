import { describe, it, expect } from "vitest";

import {
    canUseLogScale,
    colorSeries,
    harnessComparisons,
    paretoFrontier,
    placeLabels,
    rankedBars,
    scatterPoints,
    taskValues
} from "./charts.js";

const setup = (id, scores, over = {}) => ({
    id,
    model: "alpha-pro",
    harness: "gemini-cli",
    augmentation: [],
    color: "#3b82f6",
    tasks: [{ folder: "t1", name: "Task 1", scores }],
    history: [],
    ...over
});

describe("scatterPoints", () => {
    it("drops a setup missing either axis rather than pinning it to zero", () => {
        // A setup with no latency data is not an instant setup, and plotting it
        // on the axis would put it on the frontier.
        const setups = [
            setup("a", { composite: 80, latency: 20 }),
            setup("b", { composite: 90, latency: null }),
            setup("c", { composite: null, latency: 10 })
        ];
        expect(scatterPoints(setups, "latency", "composite").map(p => p.setup.id)).toEqual(["a"]);
    });
});

describe("paretoFrontier", () => {
    // Latency is lower-is-better, composite higher-is-better, so the frontier
    // runs up and to the right from the fastest point.
    const pt = (id, latency, composite) => ({
        x: latency,
        y: composite,
        setup: setup(id, { latency, composite })
    });

    it("keeps only the non-dominated points", () => {
        const points = [
            pt("fast-weak", 5, 60),
            pt("mid", 20, 85),
            pt("dominated", 25, 80),   // slower than mid AND scores less
            pt("slow-best", 60, 92)
        ];
        expect(paretoFrontier(points, "latency", "composite").map(p => p.setup.id))
            .toEqual(["fast-weak", "mid", "slow-best"]);
    });

    it("reads the better direction from the metric, not from the axis", () => {
        // Both axes lower-is-better: now only the bottom-left corner survives.
        const points = [
            { x: 10, y: 100, setup: setup("a", { latency: 10, inputTokens: 100 }) },
            { x: 20, y: 200, setup: setup("b", { latency: 20, inputTokens: 200 }) }
        ];
        expect(paretoFrontier(points, "latency", "inputTokens").map(p => p.setup.id)).toEqual(["a"]);
    });

    it("keeps exact ties, since neither dominates the other", () => {
        const points = [pt("a", 10, 80), pt("b", 10, 80)];
        expect(paretoFrontier(points, "latency", "composite")).toHaveLength(2);
    });
});

describe("colorSeries", () => {
    const models = { "alpha-pro": { name: "Alpha Pro" }, "beta-sonic": { name: "Beta Sonic" } };
    const harnesses = {
        "gemini-cli": { name: "Gemini CLI", accent: "#0ea5e9" },
        "openclaw": { name: "OpenClaw", accent: "#f43f5e" }
    };

    it("groups by model, sorted by key so colors stay stable under filtering", () => {
        const setups = [
            setup("a", {}, { model: "beta-sonic" }),
            setup("b", {}, { model: "alpha-pro" })
        ];
        const series = colorSeries(setups, "model", models, harnesses);
        expect(series.map(s => s.key)).toEqual(["alpha-pro", "beta-sonic"]);
    });

    it("uses the harness's own accent color when grouping by harness", () => {
        const setups = [setup("a", {}, { harness: "openclaw" })];
        const series = colorSeries(setups, "harness", models, harnesses);
        expect(series[0].color).toBe("#f43f5e");
    });
});

describe("rankedBars", () => {
    const models = { "alpha-pro": { name: "Alpha Pro" }, "beta-sonic": { name: "Beta Sonic" } };
    const harnesses = { "gemini-cli": { name: "Gemini CLI" }, "openclaw": { name: "OpenClaw" } };

    it("ranks best-first per the metric's direction", () => {
        const setups = [
            setup("a", { latency: 30 }, { model: "alpha-pro", harness: "gemini-cli" }),
            setup("b", { latency: 10 }, { model: "beta-sonic", harness: "openclaw" })
        ];
        expect(rankedBars(setups, "latency", models, harnesses).map(b => b.setup.id)).toEqual(["b", "a"]);
    });

    it("drops a setup with no value for the metric rather than ranking it last", () => {
        const setups = [
            setup("a", { latency: 10 }, { model: "alpha-pro", harness: "gemini-cli" }),
            setup("b", { latency: null }, { model: "beta-sonic", harness: "openclaw" })
        ];
        expect(rankedBars(setups, "latency", models, harnesses).map(b => b.setup.id)).toEqual(["a"]);
    });
});

describe("harnessComparisons", () => {
    const models = { "alpha-pro": { name: "Alpha Pro" } };
    const harnesses = {
        "gemini-cli": { name: "Gemini CLI", accent: "#0ea5e9" },
        "openclaw": { name: "OpenClaw", accent: "#f43f5e" }
    };

    it("drops a model that ran on only one harness", () => {
        const setups = [setup("a", { latency: 10 }, { model: "alpha-pro", harness: "gemini-cli" })];
        expect(harnessComparisons(setups, "latency", models, harnesses)).toEqual([]);
    });

    it("groups the same model across harnesses and ranks by best first", () => {
        const setups = [
            setup("a", { latency: 30 }, { model: "alpha-pro", harness: "gemini-cli" }),
            setup("b", { latency: 10 }, { model: "alpha-pro", harness: "openclaw" })
        ];
        const [group] = harnessComparisons(setups, "latency", models, harnesses);
        expect(group.entries.map(e => e.harness)).toEqual(["openclaw", "gemini-cli"]);
        expect(group.entries[0].pctVsBest).toBeCloseTo(0);
        expect(group.entries[1].pctVsBest).toBeCloseTo(200);
    });
});

describe("taskValues", () => {
    it("drops tasks with no value for the metric", () => {
        const s = setup("a", {}, {
            tasks: [
                { folder: "t1", name: "Task 1", scores: { latency: 10 } },
                { folder: "t2", name: "Task 2", scores: { latency: null } }
            ]
        });
        expect(taskValues(s, "latency")).toEqual([{ value: 10, task: "Task 1" }]);
    });
});

describe("canUseLogScale", () => {
    it("is false when any plotted value is zero or negative", () => {
        expect(canUseLogScale([1, 2, 3])).toBe(true);
        expect(canUseLogScale([1, 0, 3])).toBe(false);
        expect(canUseLogScale([])).toBe(false);
    });
});

describe("placeLabels", () => {
    it("keeps every label inside the plot area", () => {
        const area = { left: 0, right: 200, top: 0, bottom: 200 };
        const dots = [{ x: 100, y: 100, r: 4, w: 30, h: 12 }];
        const [spot] = placeLabels(dots, area);
        expect(spot.x - 15).toBeGreaterThanOrEqual(area.left);
        expect(spot.x + 15).toBeLessThanOrEqual(area.right);
    });
});
