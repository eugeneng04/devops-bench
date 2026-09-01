import { describe, it, expect, vi } from "vitest";
import { render, screen, within, fireEvent } from "@testing-library/react";

// Stub the canvases; what is under test is the section logic and the sr-only
// tables the charts render beside them.
vi.mock("react-chartjs-2", () => ({ Scatter: () => null, Bar: () => null }));

import { ChartsPanel } from "./ChartsPanel.jsx";

const models = { "alpha-pro": { name: "Alpha Pro" }, "beta-sonic": { name: "Beta Sonic" } };
const harnesses = {
    "gemini-cli": { name: "Gemini CLI", accent: "#0ea5e9", logo: "terminal" },
    "openclaw": { name: "OpenClaw", accent: "#f43f5e", logo: "claw" }
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

const full = {
    composite: 82, cost: 0.4, tokens: 40000, latency: 30,
    tokensInput: 10000, tokensCached: 25000, tokensCacheWrite: 3000,
    tokensReasoning: 1000, tokensOutput: 1000,
    turns: 14, toolCalls: 31
};
const cheaper = {
    composite: 74, cost: 0.1, tokens: 12000, latency: 18,
    tokensInput: 8000, tokensCached: 3000, tokensCacheWrite: 500,
    tokensReasoning: null, tokensOutput: 500,
    turns: 8, toolCalls: 12
};

const setups = [
    setup("a", "alpha-pro", "gemini-cli", full),
    setup("b", "beta-sonic", "openclaw", cheaper)
];

function renderPanel(props = {}) {
    return render(<ChartsPanel setups={setups} models={models} harnesses={harnesses} {...props} />);
}

const sectionTitles = () =>
    screen.getAllByRole("heading", { level: 3 }).map(h => h.textContent);

describe("ChartsPanel layout", () => {
    it("stacks every section on one page, ranked bars beside the matching scatter", () => {
        renderPanel();
        expect(sectionTitles()).toEqual([
            "Harness Comparison",
            // Tokens lead with the scatter; the spend bands lead with the bar.
            "Outcome Index vs. Total Tokens",
            "Token Usage per Task",
            "Cost per Task",
            "Outcome Index vs. Cost per Task",
            "Time per Task",
            "Outcome Index vs. Execution Time",
            "Consistency Across Tasks"
        ]);
    });

    it("bands the sections into groups, so cost has a heading to scroll to", () => {
        renderPanel();
        expect(screen.getAllByRole("heading", { level: 2 }).map(h => h.textContent)).toEqual([
            "Harness", "Token Usage", "Cost", "Speed", "Consistency"
        ]);
        // A group is the parent of its own sections and nobody else's: one
        // heading over all eight would be a heading that says nothing.
        const cost = screen.getByRole("heading", { level: 2, name: "Cost" }).closest("section");
        expect(within(cost).getAllByRole("heading", { level: 3 }).map(h => h.textContent))
            .toEqual(["Cost per Task", "Outcome Index vs. Cost per Task"]);
    });

    it("drops the group along with the sections when its metric is unmeasured", () => {
        const noCost = [setup("a", "alpha-pro", "gemini-cli", { ...full, cost: null })];
        render(<ChartsPanel setups={noCost} models={models} harnesses={harnesses} />);
        // An empty "Cost" band would promise charts that are not there.
        expect(screen.getAllByRole("heading", { level: 2 }).map(h => h.textContent)).not.toContain("Cost");
        expect(screen.getAllByRole("heading", { level: 2 }).map(h => h.textContent)).toContain("Speed");
    });

    it("says which direction is good, so a long bar is never ambiguous", () => {
        renderPanel();
        const heading = screen.getByRole("heading", { level: 3, name: "Time per Task" });
        expect(heading.parentElement).toHaveTextContent("Lower is better");
        // ...and the other way round on a metric where more is good.
        fireEvent.change(screen.getByLabelText("Metric", { selector: "#harness-metric" }), {
            target: { value: "composite" }
        });
        expect(
            screen.getByRole("heading", { level: 3, name: "Harness Comparison" }).parentElement
        ).toHaveTextContent("Higher is better");
    });

    it("omits a section whose metric nothing measured, rather than drawing it empty", () => {
        const noCost = [setup("a", "alpha-pro", "gemini-cli", { ...full, cost: null })];
        render(<ChartsPanel setups={noCost} models={models} harnesses={harnesses} />);
        expect(sectionTitles()).not.toContain("Cost per Task");
        expect(sectionTitles()).not.toContain("Outcome Index vs. Cost per Task");
        // The metrics that ARE measured still get their sections.
        expect(sectionTitles()).toContain("Time per Task");
    });

    it("ranks each bar chart best-first, which is not the same direction on every metric", () => {
        renderPanel();
        const rank = title => {
            const table = screen.getByRole("heading", { level: 3, name: title })
                .closest("section")
                .querySelector("table");
            return within(table).getAllByRole("rowheader").map(th => th.textContent);
        };
        // Fastest first...
        expect(rank("Time per Task")[0]).toMatch(/Beta Sonic/);
        // ...but highest outcome first on the scatter's accessible table.
        expect(rank("Outcome Index vs. Cost per Task")[0]).toMatch(/Alpha Pro/);
    });

    it("orders every chart best-first, not by whatever order the setups arrived in", () => {
        // Input order is deliberately the ranking of no metric — Gamma is first
        // in the array and best at nothing — so each assertion below fails if
        // its chart just renders the setups as they arrived.
        const middle = {
            composite: 78, cost: 0.25, tokens: 23000, latency: 24,
            tokensInput: 6000, tokensCached: 15000, tokensCacheWrite: 1000,
            tokensReasoning: 500, tokensOutput: 700,
            turns: 11, toolCalls: 20
        };
        render(
            <ChartsPanel
                setups={[
                    setup("c", "alpha-pro", "openclaw", middle),
                    setup("a", "alpha-pro", "gemini-cli", full),
                    setup("b", "beta-sonic", "openclaw", cheaper)
                ]}
                models={models}
                harnesses={harnesses}
            />
        );
        const firstRow = title => {
            const table = screen.getByRole("heading", { level: 3, name: title })
                .closest("section")
                .querySelector("table");
            return within(table).getAllByRole("rowheader")[0].textContent;
        };
        // Exact labels, not /Alpha Pro/: two of the three setups are Alpha Pro,
        // so a model-name match would pass on an unsorted chart.
        const best = "Alpha Pro × Gemini CLI · Baseline";
        const cheapest = "Beta Sonic × OpenClaw · Baseline";
        expect(firstRow("Time per Task")).toBe(cheapest);          // fastest
        expect(firstRow("Token Usage per Task")).toBe(cheapest);   // shortest stack
        // The scatter has no reading order, but its accessible table does:
        // ranked on the y metric, so a screen reader gets the same ranking the
        // dot positions give a sighted reader.
        expect(firstRow("Outcome Index vs. Cost per Task")).toBe(best);
    });

    it("marks the non-dominated setups on the outcome scatters", () => {
        renderPanel();
        const table = screen.getByRole("heading", { level: 3, name: "Outcome Index vs. Cost per Task" })
            .closest("section")
            .querySelector("table");
        // Neither beats the other on both axes: b is cheaper, a scores higher.
        expect(within(table).getByRole("columnheader", { name: "On Pareto frontier" })).toBeInTheDocument();
        for (const name of [/Alpha Pro/, /Beta Sonic/]) {
            const row = within(table).getByRole("rowheader", { name }).closest("tr");
            expect(within(row).getAllByRole("cell").at(-1)).toHaveTextContent("yes");
        }
    });

    it("shows the token stack per bucket, with an em dash for an unreported bucket", () => {
        renderPanel();
        const table = screen.getByRole("heading", { level: 3, name: "Token Usage per Task" })
            .closest("section")
            .querySelector("table");
        for (const label of ["Input Tokens", "Cached Tokens", "Cache Write Tokens", "Reasoning Tokens", "Output Tokens"]) {
            expect(within(table).getByRole("columnheader", { name: label })).toBeInTheDocument();
        }
        const row = within(table).getByRole("rowheader", { name: /Beta Sonic/ }).closest("tr");
        expect(within(row).getAllByRole("cell")[3]).toHaveTextContent("—");
    });

    it("narrows the token breakdown to one task, and back to the mean", () => {
        // Two tasks whose input tokens differ, so the mean is neither of them.
        const twoTasks = [setup("a", "alpha-pro", "gemini-cli", full, [
            { folder: "t1", name: "Task 1", scores: { ...full, tokensInput: 1000 } },
            { folder: "t2", name: "Task 2", scores: { ...full, tokensInput: 3000 } }
        ])];
        render(<ChartsPanel setups={twoTasks} models={models} harnesses={harnesses} />);
        const inputCell = () => {
            const table = screen.getByRole("heading", { level: 3, name: "Token Usage per Task" })
                .closest("section")
                .querySelector("table");
            return within(table).getAllByRole("cell")[0].textContent;
        };
        const picker = screen.getByLabelText("Show", { selector: "#token-task" });
        expect(inputCell()).toBe("2.0k");              // the mean of the two

        fireEvent.change(picker, { target: { value: "t2" } });
        expect(inputCell()).toBe("3.0k");              // that task alone

        fireEvent.change(picker, { target: { value: "mean" } });
        expect(inputCell()).toBe("2.0k");
    });

    it("totals the buckets across tasks, which is not the mean", () => {
        const twoTasks = [setup("a", "alpha-pro", "gemini-cli", full, [
            { folder: "t1", name: "Task 1", scores: { ...full, tokensInput: 1000 } },
            { folder: "t2", name: "Task 2", scores: { ...full, tokensInput: 3000 } }
        ])];
        render(<ChartsPanel setups={twoTasks} models={models} harnesses={harnesses} />);
        fireEvent.change(screen.getByLabelText("Show", { selector: "#token-task" }), { target: { value: "total" } });
        const section = screen.getByRole("heading", { level: 3, name: "Total Token Usage" }).closest("section");
        expect(within(section.querySelector("table")).getAllByRole("cell")[0]).toHaveTextContent("4.0k");
        // The heading has to change with it: "per Task" would misread a sum.
        expect(sectionTitles()).not.toContain("Token Usage per Task");
    });

    it("ranks setups differently on total than on mean, when coverage differs", () => {
        // b spends more per task but ran half as many, so it totals less. A
        // chart that quietly reused the mean would order these the same way.
        const wide = setup("a", "alpha-pro", "gemini-cli", full, [
            { folder: "t1", name: "Task 1", scores: { ...full, tokensInput: 1000 } },
            { folder: "t2", name: "Task 2", scores: { ...full, tokensInput: 1000 } }
        ]);
        const deep = setup("b", "beta-sonic", "openclaw", full, [
            { folder: "t1", name: "Task 1", scores: { ...full, tokensInput: 1500 } }
        ]);
        render(<ChartsPanel setups={[wide, deep]} models={models} harnesses={harnesses} />);
        const firstBar = title => within(
            screen.getByRole("heading", { level: 3, name: title }).closest("section").querySelector("table")
        ).getAllByRole("rowheader")[0].textContent;

        expect(firstBar("Token Usage per Task")).toMatch(/Alpha Pro/);   // 1.0k mean beats 1.5k
        fireEvent.change(screen.getByLabelText("Show", { selector: "#token-task" }), { target: { value: "total" } });
        expect(firstBar("Total Token Usage")).toMatch(/Beta Sonic/);     // 1.5k total beats 2.0k
    });

    it("drops a setup that never ran the selected task, rather than drawing it empty", () => {
        const mixed = [
            setup("a", "alpha-pro", "gemini-cli", full, [{ folder: "t1", name: "Task 1", scores: full }]),
            setup("b", "beta-sonic", "openclaw", cheaper, [{ folder: "t2", name: "Task 2", scores: cheaper }])
        ];
        render(<ChartsPanel setups={mixed} models={models} harnesses={harnesses} />);
        fireEvent.change(screen.getByLabelText("Show", { selector: "#token-task" }), { target: { value: "t1" } });
        const table = screen.getByRole("heading", { level: 3, name: "Token Usage per Task" })
            .closest("section")
            .querySelector("table");
        expect(within(table).getByRole("rowheader", { name: /Alpha Pro/ })).toBeInTheDocument();
        expect(within(table).queryByRole("rowheader", { name: /Beta Sonic/ })).not.toBeInTheDocument();
    });

    it("gives the spend bars their own view, one picker per metric", () => {
        // Cost duplicates the table's own column at the mean, so the bar only
        // earns its place if it can show the total and a single task too.
        const twoTasks = [setup("a", "alpha-pro", "gemini-cli", full, [
            { folder: "t1", name: "Task 1", scores: { ...full, cost: 0.2, latency: 10 } },
            { folder: "t2", name: "Task 2", scores: { ...full, cost: 0.6, latency: 30 } }
        ])];
        render(<ChartsPanel setups={twoTasks} models={models} harnesses={harnesses} />);
        const value = title => within(
            screen.getByRole("heading", { level: 3, name: title }).closest("section").querySelector("table")
        ).getAllByRole("cell")[1].textContent;

        expect(value("Cost per Task")).toBe("$0.400");   // the mean
        fireEvent.change(screen.getByLabelText("Show", { selector: "#cost-task" }), { target: { value: "total" } });
        expect(value("Total Cost")).toBe("$0.800");
        fireEvent.change(screen.getByLabelText("Show", { selector: "#cost-task" }), { target: { value: "t1" } });
        expect(value("Cost per Task")).toBe("$0.200");

        // ...and the time picker moves independently of it.
        expect(value("Time per Task")).toBe("20.0s");
        fireEvent.change(screen.getByLabelText("Show", { selector: "#latency-task" }), { target: { value: "total" } });
        expect(value("Total Time")).toBe("40.0s");
        expect(value("Cost per Task")).toBe("$0.200");
    });

    it("hides the task picker when there is only one task to pick", () => {
        renderPanel();   // the default fixture gives every setup a single task
        expect(screen.queryByLabelText("Show")).not.toBeInTheDocument();
    });

    it("compares harnesses with the model held constant", () => {
        const paired = [
            setup("a", "alpha-pro", "gemini-cli", { ...cheaper, cost: 0.2 }),
            setup("b", "alpha-pro", "openclaw", { ...full, cost: 0.5 })
        ];
        render(<ChartsPanel setups={paired} models={models} harnesses={harnesses} />);
        const row = screen.getByRole("rowheader", { name: "Alpha Pro · Baseline" }).closest("tr");
        expect(within(row).getAllByRole("cell")[0]).toHaveTextContent("Gemini CLI");
        expect(screen.getByRole("cell", { name: "150% worse than best" })).toBeInTheDocument();
    });

    it("keys the harness bars with a glyph, not colour alone", () => {
        // The y-axis names the MODEL, so without a legend nothing on the chart
        // says which bar is which runner.
        const paired = [
            setup("a", "alpha-pro", "gemini-cli", { ...cheaper, cost: 0.2 }),
            setup("b", "alpha-pro", "openclaw", { ...full, cost: 0.5 })
        ];
        render(<ChartsPanel setups={paired} models={models} harnesses={harnesses} />);
        const legend = screen.getByRole("heading", { level: 3, name: "Harness Comparison" })
            .closest("section")
            .querySelector("ul[aria-hidden]");
        for (const name of ["Gemini CLI", "OpenClaw"]) {
            expect(within(legend).getByText(name)).toBeInTheDocument();
        }
        // One glyph per harness, tinted with that harness's accent.
        const strokes = [...legend.querySelectorAll("svg")].map(el => el.getAttribute("stroke"));
        expect(strokes).toEqual(["#0ea5e9", "#f43f5e"]);
    });

    it("falls back to colour when the catalog carries no glyph for a harness", () => {
        const paired = [
            setup("a", "alpha-pro", "gemini-cli", { ...cheaper, cost: 0.2 }),
            setup("b", "alpha-pro", "openclaw", { ...full, cost: 0.5 })
        ];
        // A harness the catalog does not know must not borrow another's mark.
        const partial = { ...harnesses, openclaw: { name: "OpenClaw", accent: "#f43f5e" } };
        render(<ChartsPanel setups={paired} models={models} harnesses={partial} />);
        const legend = screen.getByRole("heading", { level: 3, name: "Harness Comparison" })
            .closest("section")
            .querySelector("ul[aria-hidden]");
        expect(within(legend).getByText("OpenClaw")).toBeInTheDocument();
        expect(legend.querySelectorAll("svg path")).toHaveLength(1);   // only Gemini CLI's
    });

    it("says nothing to compare when no model ran on two harnesses", () => {
        // The default fixture pairs each model with one harness, so a bar chart
        // here would compare models while claiming to compare harnesses.
        renderPanel();
        expect(screen.getByText(/ran on more than one harness/)).toBeInTheDocument();
    });

    it("switches the metric the harness section compares", () => {
        const paired = [
            setup("a", "alpha-pro", "gemini-cli", { ...cheaper, latency: 10 }),
            setup("b", "alpha-pro", "openclaw", { ...full, latency: 30 })
        ];
        render(<ChartsPanel setups={paired} models={models} harnesses={harnesses} />);
        fireEvent.change(screen.getByLabelText("Metric", { selector: "#harness-metric" }), {
            target: { value: "latency" }
        });
        expect(screen.getByRole("cell", { name: "200% worse than best" })).toBeInTheDocument();
    });

    it("ranks the consistency section by spread, not by score", () => {
        // `steady` scores WORSE on average than `erratic` but never varies, so a
        // section that reused the mean ranking would put it second.
        const tasks = (a, b) => [
            { folder: "t1", name: "Task 1", scores: { ...full, composite: a } },
            { folder: "t2", name: "Task 2", scores: { ...full, composite: b } }
        ];
        render(
            <ChartsPanel
                setups={[
                    setup("a", "alpha-pro", "gemini-cli", full, tasks(95, 35)),   // mean 65, wild
                    setup("b", "beta-sonic", "openclaw", full, tasks(60, 58))     // mean 59, steady
                ]}
                models={models}
                harnesses={harnesses}
            />
        );
        const table = screen.getByRole("heading", { level: 3, name: "Consistency Across Tasks" })
            .closest("section")
            .querySelector("table");
        expect(within(table).getAllByRole("rowheader").map(th => th.textContent))
            .toEqual([expect.stringMatching(/Beta Sonic/), expect.stringMatching(/Alpha Pro/)]);
        // The task at the bad end is named, which is the row's whole point.
        expect(within(table).getAllByRole("row")[2]).toHaveTextContent("Task 2");
    });
});

describe("ChartsPanel custom explorer", () => {
    it("is folded away rather than competing with the curated sections", () => {
        renderPanel();
        const summary = screen.getByText("Plot any two metrics");
        expect(summary.closest("details")).not.toHaveAttribute("open");
    });

    it("drops the frontier, where 'non-dominated' has no meaning", () => {
        renderPanel();
        const details = screen.getByText("Plot any two metrics").closest("details");
        expect(within(details).queryByRole("columnheader", { name: "On Pareto frontier" })).not.toBeInTheDocument();
        expect(within(details).getByLabelText("X")).toBeInTheDocument();
        expect(within(details).getByLabelText("Y")).toBeInTheDocument();
    });

    it("offers chart-only axes in the pickers, grouped", () => {
        renderPanel();
        const options = within(screen.getByLabelText("X")).getAllByRole("option").map(o => o.textContent);
        // Token buckets are not leaderboard columns; this is the only place they
        // can be plotted.
        expect(options).toContain("Cached Tokens");
        expect(options).toContain("Tool Calls");
    });

    it("disables a log toggle when a plotted value is zero, which the axis cannot draw", () => {
        const withZero = [
            setup("a", "alpha-pro", "gemini-cli", { ...full, toolCalls: 0, tokens: 40000 }),
            setup("b", "beta-sonic", "openclaw", { ...cheaper, toolCalls: 12, tokens: 12000 })
        ];
        render(<ChartsPanel setups={withZero} models={models} harnesses={harnesses} />);
        expect(screen.getByLabelText("log X")).toBeEnabled();   // tokens, all positive

        fireEvent.change(screen.getByLabelText("X"), { target: { value: "toolCalls" } });
        expect(screen.getByLabelText("log X")).toBeDisabled();
        expect(screen.getByLabelText("log X").checked).toBe(false);
    });
});
