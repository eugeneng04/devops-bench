import { describe, it, expect, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";

// Stub the canvases; what is under test is the section logic and the sr-only
// tables the charts render beside them.
vi.mock("react-chartjs-2", () => ({ Scatter: () => null, Bar: () => null }));

import { ChartsPanel } from "./ChartsPanel.jsx";

const models = { "alpha-pro": { name: "Alpha Pro" }, "beta-sonic": { name: "Beta Sonic" } };
const harnesses = {
    "gemini-cli": { name: "Gemini CLI", accent: "#0ea5e9" },
    "openclaw": { name: "OpenClaw", accent: "#f43f5e" }
};

const setup = (id, model, harness, scores, tasks) => ({
    id,
    model,
    harness,
    augmentation: [],
    color: "#3b82f6",
    tasks: tasks ?? [{ folder: "t1", name: "Task 1", scores }],
    history: [{ t: "2026-02-15T00:00:00Z", scores }]
});

const withTokens = {
    composite: 82, latency: 30,
    inputTokens: 10000, outputTokens: 1000, cachedTokens: 25000
};
const cheaper = {
    composite: 74, latency: 18,
    inputTokens: 8000, outputTokens: 500, cachedTokens: null
};

const sectionTitles = () =>
    screen.getAllByRole("heading", { level: 3 }).map(h => h.textContent);

describe("ChartsPanel layout", () => {
    it("renders the token sections when any setup carries a token bucket", () => {
        const setups = [
            setup("a", "alpha-pro", "gemini-cli", withTokens),
            setup("b", "beta-sonic", "openclaw", cheaper)
        ];
        render(<ChartsPanel setups={setups} models={models} harnesses={harnesses} />);
        expect(sectionTitles()).toEqual([
            "Outcome Index",
            "Harness Comparison",
            "Token Usage per Task",
            "Outcome Index vs. Total Tokens",
            "Time per Task",
            "Outcome Index vs. Execution Time",
            "Consistency Across Tasks"
        ]);
    });

    // Regression: the token sections used to be gated on a `tokens` score key
    // that Firestore never writes (only inputTokens/outputTokens/cachedTokens
    // are stored), so they were always omitted even with full bucket data.
    it("still shows Token Usage when only inputTokens is reported", () => {
        const setups = [setup("a", "alpha-pro", "gemini-cli", { composite: 80, inputTokens: 500 })];
        render(<ChartsPanel setups={setups} models={models} harnesses={harnesses} />);
        expect(sectionTitles()).toContain("Token Usage per Task");
        expect(sectionTitles()).toContain("Outcome Index vs. Total Tokens");
    });

    it("omits the token sections when no setup reports any bucket", () => {
        const setups = [setup("a", "alpha-pro", "gemini-cli", { composite: 80, latency: 10 })];
        render(<ChartsPanel setups={setups} models={models} harnesses={harnesses} />);
        expect(sectionTitles()).not.toContain("Token Usage per Task");
        expect(sectionTitles()).not.toContain("Outcome Index vs. Total Tokens");
        expect(sectionTitles()).toContain("Time per Task");
    });

    it("plots the Outcome-vs-Tokens scatter from the sum of the real buckets", () => {
        const setups = [
            setup("a", "alpha-pro", "gemini-cli", withTokens),
            setup("b", "beta-sonic", "openclaw", cheaper)
        ];
        render(<ChartsPanel setups={setups} models={models} harnesses={harnesses} />);
        const table = screen.getByRole("heading", { level: 3, name: "Outcome Index vs. Total Tokens" })
            .closest("section")
            .querySelector("table");
        // 10000 + 1000 + 25000, formatted as a compact count
        expect(within(table).getByText("36.0k")).toBeInTheDocument();
    });

    it("says which direction is good, so a long bar is never ambiguous", () => {
        const setups = [setup("a", "alpha-pro", "gemini-cli", withTokens)];
        render(<ChartsPanel setups={setups} models={models} harnesses={harnesses} />);
        expect(
            screen.getByRole("heading", { level: 3, name: "Outcome Index" }).parentElement
        ).toHaveTextContent("Higher is better");
        expect(
            screen.getByRole("heading", { level: 3, name: "Time per Task" }).parentElement
        ).toHaveTextContent("Lower is better");
    });

    it("shows the token stack per bucket, with 'not reported' for a missing bucket", () => {
        const setups = [
            setup("a", "alpha-pro", "gemini-cli", withTokens),
            setup("b", "beta-sonic", "openclaw", cheaper)
        ];
        render(<ChartsPanel setups={setups} models={models} harnesses={harnesses} />);
        const table = screen.getByRole("heading", { level: 3, name: "Token Usage per Task" })
            .closest("section")
            .querySelector("table");
        for (const label of ["Input Tokens", "Output Tokens", "Cached Tokens"]) {
            expect(within(table).getByRole("columnheader", { name: label })).toBeInTheDocument();
        }
        const row = within(table).getByRole("rowheader", { name: /Beta Sonic/ }).closest("tr");
        expect(within(row).getAllByRole("cell").at(-1)).toHaveTextContent("—");
    });
});

describe("ChartsPanel custom explorer", () => {
    it("is folded away rather than competing with the curated sections", () => {
        const setups = [setup("a", "alpha-pro", "gemini-cli", withTokens)];
        render(<ChartsPanel setups={setups} models={models} harnesses={harnesses} />);
        const summary = screen.getByText("Plot any two metrics");
        expect(summary.closest("details")).not.toHaveAttribute("open");
    });
});
