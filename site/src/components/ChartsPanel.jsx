// The charts below the leaderboard table.
//
// Laid out the way Artificial Analysis lays out its models page: one scrolling
// column, banded into groups by what is being measured — Harness, Token Usage,
// Cost, Speed, Consistency — with each chart carrying a one-line italic
// subtitle. No tabs. A tab hides the comparison a reader did not know to look
// for — the cost story only lands next to the token story, and both only land
// next to the score. Groups are waypoints in that scroll, not walls.
//
// Subtitles follow Artificial Analysis's house style: a noun phrase naming what
// is measured and in what unit, then " · " separated qualifiers, ending in the
// direction. Not sentences, and not an argument for why the chart exists — that
// reasoning belongs in the header comment of the component that draws it.
//
// A spend metric gets a ranked bar for "how much" and a scatter against the
// outcome score for "did the spend buy anything". Sections whose metric is
// unmeasured are omitted rather than drawn empty.
//
// Every chart reads the FILTERED setups, so the filter bar at the top of the
// page drives the plots as well as the table.

import { useMemo, useState } from "react";
import { EfficiencyScatter } from "./EfficiencyScatter.jsx";
import { RankedBarChart } from "./RankedBarChart.jsx";
import { TokenBreakdownChart } from "./TokenBreakdownChart.jsx";
import { ConsistencyChart } from "./ConsistencyChart.jsx";
import { HarnessSavingsChart } from "./HarnessSavingsChart.jsx";
import { scatterPoints, canUseLogScale, taskOptions } from "../lib/charts.js";
import {
    CHART_METRICS,
    METRIC_GROUPS,
    METRIC_LABELS,
    availableMetrics,
    isLowerBetter,
    metricDescription
} from "../lib/vocab.js";

// The spend axes paired with the outcome score, in the order a reader meets
// them: what it cost in money, then in wall clock. Tokens come first and are
// handled on their own, because their "how much" view is the bucket breakdown
// rather than a single ranked total.
// A bar section earns its place over the table's own column only because of the
// view picker: the table ranks the per-task mean and nothing else, so the total
// and the single-task views are rankings a reader cannot get upstairs.
const SPEND_SECTIONS = [
    {
        metric: "cost",
        group: "Cost",
        barTitle: "Cost per Task",
        totalTitle: "Total Cost",
        subject: "API cost (USD)",
        qualifier: "Priced from each run's own token buckets at published rates",
        scatterTitle: "Outcome Index vs. Cost per Task"
    },
    {
        metric: "latency",
        group: "Speed",
        barTitle: "Time per Task",
        totalTitle: "Total Time",
        subject: "agent wall-clock time (seconds)",
        qualifier: "Excluding scoring and harness startup",
        scatterTitle: "Outcome Index vs. Execution Time"
    }
];

// Taller than the bar charts on purpose. A scatter's dots carry a name label
// each, and the placement algorithm can only push a label so far before it runs
// out of plot; the extra height is what stops the labels stacking up in the
// crowded low-cost corner. One constant so the two scatters keep the same shape.
//
// This is the real height of the plot, not of a box the plot sits in — the
// scatter has to fill it. See the note on EfficiencyScatter's root element.
const SCATTER_H = "h-[30rem]";

const TOKEN_SECTION = {
    metric: "tokens",
    group: "Token Usage",
    barTitle: "Token Usage per Task",
    totalTitle: "Total Token Usage",
    subject: "tokens",
    qualifier: "Stacked by billed bucket: input, cache read, cache write, reasoning, output"
};

const SCATTER_SUBTITLE =
    "One dot per model × harness pairing · Dashed line is the Pareto frontier · Up and to the left is better";

const taskName = (tasks, folder) => tasks.find(t => t.folder === folder)?.name ?? folder;
const cap = text => text.charAt(0).toUpperCase() + text.slice(1);

// What a section is currently showing, phrased so the subtitle and the
// screen-reader label say it rather than leaving the reader to infer it from a
// control they may not have touched.
function viewSubject(view, subject, tasks) {
    if (view === "total") return `Total ${subject} across all tasks`;
    if (view === "mean") return `Mean ${subject} per task`;
    return `${cap(subject)} on ${taskName(tasks, view)}`;
}

// The section heading follows the view: "per Task" would misread a sum.
const viewTitle = (view, section) => (view === "total" ? section.totalTitle : section.barTitle);

/** "· Higher is better" / "· Lower is better", from the metric vocabulary. */
function withDirection(text, metric) {
    return `${text} · ${isLowerBetter(metric) ? "Lower" : "Higher"} is better`;
}

// --- small shared controls ---------------------------------------------------

function Segmented({ value, onChange, options, ariaLabel }) {
    return (
        <div role="group" aria-label={ariaLabel} className="inline-flex flex-wrap p-0.5 bg-slate-100 dark:bg-slate-800 rounded-lg text-[11px]">
            {options.map(opt => {
                const active = opt.key === value;
                return (
                    <button
                        key={opt.key}
                        type="button"
                        onClick={() => !opt.disabled && onChange(opt.key)}
                        disabled={opt.disabled}
                        aria-pressed={active}
                        title={opt.title}
                        className={`px-2.5 py-1 font-medium rounded-md whitespace-nowrap transition-all duration-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 disabled:cursor-not-allowed ${
                            active
                                ? "bg-white dark:bg-slate-700 text-slate-800 dark:text-slate-100 shadow-sm"
                                : opt.disabled
                                    ? "text-slate-300 dark:text-slate-600"
                                    : "text-slate-600 dark:text-slate-300 hover:text-slate-800 dark:hover:text-slate-100"
                        }`}
                    >
                        {opt.label}
                    </button>
                );
            })}
        </div>
    );
}

// Grouped metric dropdown. A <select> rather than more pill buttons: the custom
// section offers every metric in the vocabulary, and seventeen pills is a wall.
function MetricSelect({ id, label, value, onChange, available }) {
    return (
        <label htmlFor={id} className="flex items-center gap-1.5 text-[11px] font-medium text-slate-500 dark:text-slate-400">
            {label}
            <select
                id={id}
                value={value}
                onChange={e => onChange(e.target.value)}
                title={metricDescription(value)}
                className="px-2 py-1 rounded-md bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-200 text-[11px] font-medium border-0 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500"
            >
                {METRIC_GROUPS.map(group => {
                    const options = group.metrics.filter(m => available.includes(m));
                    if (!options.length) return null;
                    return (
                        <optgroup key={group.key} label={group.label}>
                            {options.map(m => <option key={m} value={m}>{METRIC_LABELS[m]}</option>)}
                        </optgroup>
                    );
                })}
            </select>
        </label>
    );
}

// Task picker. One control, three kinds of answer: the per-task mean (the
// default, so the chart reads as it always did), the suite total, or a single
// task. Mean and total are grouped apart from the task list because they are a
// different question, not a different task.
//
// The caller hides this entirely when there is only one task, where all three
// answers are the same number.
function TaskSelect({ id, value, onChange, tasks }) {
    return (
        <label htmlFor={id} className="flex items-center gap-1.5 text-[11px] font-medium text-slate-500 dark:text-slate-400">
            Show
            <select
                id={id}
                value={value}
                onChange={e => onChange(e.target.value)}
                className="px-2 py-1 rounded-md bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-200 text-[11px] font-medium border-0 max-w-[16rem] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500"
            >
                <optgroup label="All tasks">
                    <option value="mean">Mean per task</option>
                    <option value="total">Total across tasks</option>
                </optgroup>
                {tasks.length ? (
                    <optgroup label="Single task">
                        {tasks.map(t => <option key={t.folder} value={t.folder}>{t.name}</option>)}
                    </optgroup>
                ) : null}
            </select>
        </label>
    );
}

function Checkbox({ id, label, checked, onChange, disabled, title }) {
    return (
        <label
            htmlFor={id}
            title={title}
            className={`flex items-center gap-1.5 text-[11px] font-medium ${disabled ? "text-slate-300 dark:text-slate-600 cursor-not-allowed" : "text-slate-500 dark:text-slate-400"}`}
        >
            <input
                id={id}
                type="checkbox"
                checked={checked}
                disabled={disabled}
                onChange={e => onChange(e.target.checked)}
                className="rounded border-slate-300 dark:border-slate-600 text-indigo-500 focus-visible:ring-indigo-500 disabled:cursor-not-allowed"
            />
            {label}
        </label>
    );
}

// One titled chart. The subtitle is not decoration: without it a reader has to
// infer from the axis whether a long bar is good news.
function Section({ title, subtitle, controls, children }) {
    return (
        <section className="mt-10 first:mt-0 pt-10 first:pt-0 border-t first:border-t-0 border-slate-100 dark:border-slate-800">
            <div className="flex flex-wrap items-start justify-between gap-3 mb-4">
                <div className="min-w-0">
                    <h3 className="text-sm font-semibold text-slate-800 dark:text-slate-100">{title}</h3>
                    <p className="text-[11px] italic text-slate-500 dark:text-slate-400 mt-0.5 max-w-3xl">{subtitle}</p>
                </div>
                {controls}
            </div>
            {children}
        </section>
    );
}

// One icon and accent per group, so the headers are distinguishable at a glance
// while scrolling and not just five identical grey lines.
const GROUPS = {
    "Cost": {
        accent: "text-emerald-500 dark:text-emerald-400",
        d: "M12 8c-1.657 0-3 .895-3 2s1.343 2 3 2 3 .895 3 2-1.343 2-3 2m0-8c1.11 0 2.08.402 2.599 1M12 8V7m0 9v1m0-1c-1.11 0-2.08-.402-2.599-1M21 12a9 9 0 11-18 0 9 9 0 0118 0z"
    },
    "Speed": {
        accent: "text-amber-500 dark:text-amber-400",
        d: "M13 10V3L4 14h7v7l9-11h-7z"
    },
    "Token Usage": {
        accent: "text-violet-500 dark:text-violet-400",
        d: "M9 3v2m6-2v2M9 19v2m6-2v2M5 9H3m2 6H3m18-6h-2m2 6h-2M7 19h10a2 2 0 002-2V7a2 2 0 00-2-2H7a2 2 0 00-2 2v10a2 2 0 002 2zM9 9h6v6H9V9z"
    },
    "Consistency": {
        accent: "text-sky-500 dark:text-sky-400",
        d: "M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z"
    },
    "Harness": {
        accent: "text-rose-500 dark:text-rose-400",
        d: "M12 6V4m0 2a2 2 0 100 4m0-4a2 2 0 110 4m-6 8a2 2 0 100-4m0 4a2 2 0 110-4m0 4v2m0-6V4m6 6v10m6-2a2 2 0 100-4m0 4a2 2 0 110-4m0 4v2m0-6V4"
    }
};

// A band of related charts under one heading. One heading over all eight
// sections was a heading that said nothing: a reader scrolling for the cost
// charts had no waypoint to scroll to. The sections inside a group are wrapped
// so the first of them keeps its `first:` rules and drops its top rule — the
// group heading is already the separator there.
function Group({ title, children }) {
    const { accent, d } = GROUPS[title];
    return (
        <section className="mt-14 first:mt-0">
            <h2 className={`text-xs font-semibold uppercase tracking-wider flex items-center gap-2 mb-8 ${accent}`}>
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d={d} />
                </svg>
                {title}
            </h2>
            <div>{children}</div>
        </section>
    );
}

// --- panel -------------------------------------------------------------------

export function ChartsPanel({ setups, models, harnesses }) {
    const [colorBy, setColorBy] = useState("model");
    const [harnessMetric, setHarnessMetric] = useState("cost");
    const [spreadMetric, setSpreadMetric] = useState("composite");
    const [customX, setCustomX] = useState("tokens");
    const [customY, setCustomY] = useState("composite");
    const [logX, setLogX] = useState(false);
    const [logY, setLogY] = useState(false);
    // One view per bar section, keyed by metric. Separate rather than shared:
    // narrowing the cost chart to one task is a question about cost, and
    // silently re-pointing the token chart with it would be a surprise.
    const [views, setViews] = useState({});

    const available = useMemo(() => availableMetrics(setups, CHART_METRICS), [setups]);
    const tasks = useMemo(() => taskOptions(setups), [setups]);

    // A task the filter bar has since excluded must not keep narrowing a chart
    // from a control that no longer offers it — fall back to the mean.
    const viewFor = metric => {
        const view = views[metric] ?? "mean";
        return view === "mean" || view === "total" || tasks.some(t => t.folder === view) ? view : "mean";
    };
    const setView = (metric, view) => setViews(prev => ({ ...prev, [metric]: view }));

    // The props a bar chart needs to honour a view. `task` is null for the two
    // whole-suite views, where `aggregate` is what distinguishes them.
    const viewProps = view => ({
        task: view === "mean" || view === "total" ? null : view,
        aggregate: view === "total" ? "total" : "mean"
    });

    // Log scales cannot draw a zero or a negative, and Chart.js drops such points
    // without comment. Offer the toggle only when every plotted value survives.
    const customPoints = useMemo(
        () => scatterPoints(setups, customX, customY),
        [setups, customX, customY]
    );
    const logXOk = canUseLogScale(customPoints.map(p => p.x));
    const logYOk = canUseLogScale(customPoints.map(p => p.y));

    const activeSpreadMetric = available.includes(spreadMetric) ? spreadMetric : (available[0] ?? spreadMetric);
    const activeHarnessMetric = available.includes(harnessMetric) ? harnessMetric : (available[0] ?? harnessMetric);

    // The colour toggle is a LEGEND ENCODING, not a ranking: it groups the dots
    // so a cluster is visible. It applies to every scatter at once, because a
    // reader comparing two charts should not have to re-set it on each.
    const colorControl = (
        <Segmented
            value={colorBy}
            onChange={setColorBy}
            ariaLabel="Color dots by"
            options={[
                { key: "model", label: "Color: model", title: "Color the dots by model. Each dot is still one model × harness pairing — this only groups them." },
                { key: "harness", label: "Color: harness", title: "Color the dots by harness. Each dot is still one model × harness pairing — this only groups them." }
            ]}
        />
    );

    const scatterAgainstOutcome = metric => (
        <div className={SCATTER_H}>
            <EfficiencyScatter
                setups={setups}
                xMetric={metric}
                yMetric="composite"
                models={models}
                harnesses={harnesses}
                colorBy={colorBy}
                ariaLabel={`Outcome score against ${METRIC_LABELS[metric].toLowerCase()} for each setup, with the Pareto frontier`}
                caption={`Outcome score versus ${METRIC_LABELS[metric].toLowerCase()} per setup`}
            />
        </div>
    );

    return (
        <section
            aria-label="Performance and efficiency charts"
            className="w-full bg-white dark:bg-slate-900 rounded-2xl border border-slate-200/80 dark:border-slate-800 shadow-xl shadow-slate-100 dark:shadow-none p-6 flex flex-col"
        >
            <Group title="Harness">
                <Section
                    title="Harness Comparison"
                    subtitle={withDirection(`${METRIC_LABELS[activeHarnessMetric]} for one model across harnesses, augmentation held constant · Single-harness models omitted`, activeHarnessMetric)}
                    controls={
                        <MetricSelect
                            id="harness-metric"
                            label="Metric"
                            value={activeHarnessMetric}
                            onChange={setHarnessMetric}
                            available={available}
                        />
                    }
                >
                    <HarnessSavingsChart
                        setups={setups}
                        metric={activeHarnessMetric}
                        models={models}
                        harnesses={harnesses}
                        ariaLabel={`${METRIC_LABELS[activeHarnessMetric]} per harness, with the model and augmentation held constant`}
                        caption={`${METRIC_LABELS[activeHarnessMetric]} by harness for each model`}
                    />
                </Section>
            </Group>

            {available.includes("tokens") && (
                <Group title={TOKEN_SECTION.group}>
                    {/* Scatter first here, bar second — the reverse of the spend
                        bands. "Did the tokens buy anything" is the question a
                        reader brings to token usage; the bucket breakdown is
                        the follow-up that explains a dot's position. */}
                    <Section title="Outcome Index vs. Total Tokens" subtitle={SCATTER_SUBTITLE}>
                        {scatterAgainstOutcome("tokens")}
                    </Section>

                    <Section
                        title={viewTitle(viewFor("tokens"), TOKEN_SECTION)}
                        subtitle={withDirection(`${viewSubject(viewFor("tokens"), TOKEN_SECTION.subject, tasks)} · ${TOKEN_SECTION.qualifier}`, "tokens")}
                        controls={tasks.length > 1 ? <TaskSelect id="token-task" value={viewFor("tokens")} onChange={v => setView("tokens", v)} tasks={tasks} /> : undefined}
                    >
                        <TokenBreakdownChart
                            setups={setups}
                            models={models}
                            harnesses={harnesses}
                            {...viewProps(viewFor("tokens"))}
                            ariaLabel={`${viewSubject(viewFor("tokens"), TOKEN_SECTION.subject, tasks)} per setup, stacked by billed bucket`}
                            caption={`Token usage by bucket per setup — ${viewSubject(viewFor("tokens"), TOKEN_SECTION.subject, tasks).toLowerCase()}`}
                        />
                    </Section>
                </Group>
            )}

            {SPEND_SECTIONS.filter(s => available.includes(s.metric)).map(section => (
                <Group key={section.metric} title={section.group}>
                    <Section
                        title={viewTitle(viewFor(section.metric), section)}
                        subtitle={withDirection(`${viewSubject(viewFor(section.metric), section.subject, tasks)} · ${section.qualifier}`, section.metric)}
                        controls={tasks.length > 1 ? <TaskSelect id={`${section.metric}-task`} value={viewFor(section.metric)} onChange={v => setView(section.metric, v)} tasks={tasks} /> : undefined}
                    >
                        <RankedBarChart
                            setups={setups}
                            metric={section.metric}
                            models={models}
                            harnesses={harnesses}
                            {...viewProps(viewFor(section.metric))}
                            ariaLabel={`${viewSubject(viewFor(section.metric), section.subject, tasks)} per setup, ranked`}
                            caption={`${viewSubject(viewFor(section.metric), section.subject, tasks)} by setup`}
                        />
                    </Section>
                    <Section
                        title={section.scatterTitle}
                        subtitle={SCATTER_SUBTITLE}
                        controls={section.metric === SPEND_SECTIONS[0].metric ? colorControl : undefined}
                    >
                        {scatterAgainstOutcome(section.metric)}
                    </Section>
                </Group>
            ))}

            <Group title="Consistency">
                <Section
                    title="Consistency Across Tasks"
                    subtitle={`Spread of ${METRIC_LABELS[activeSpreadMetric].toLowerCase()} across tasks · Box is the middle half, line the median, whiskers the best and worst task · Ranked by spread, tightest first`}
                    controls={
                        <MetricSelect
                            id="spread-metric"
                            label="Metric"
                            value={activeSpreadMetric}
                            onChange={setSpreadMetric}
                            available={available}
                        />
                    }
                >
                    <ConsistencyChart
                        setups={setups}
                        metric={activeSpreadMetric}
                        models={models}
                        harnesses={harnesses}
                        ariaLabel={`Box plot of ${METRIC_LABELS[activeSpreadMetric].toLowerCase()} across tasks for each setup, tightest first`}
                        caption={`Best task, quartiles, median and worst task ${METRIC_LABELS[activeSpreadMetric].toLowerCase()} by setup`}
                    />
                </Section>
            </Group>

            {/* Folded away, unlike everything above it. Any two of ~17 metrics is
                270-odd plots and almost none of them mean anything — "cache write
                tokens versus pass@1" is a question nobody has — but the long tail
                should still be reachable. */}
            <details className="mt-14 pt-10 border-t border-slate-100 dark:border-slate-800 group">
                <summary className="text-sm font-semibold text-slate-800 dark:text-slate-100 cursor-pointer marker:text-slate-400 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 rounded">
                    Plot any two metrics
                </summary>
                <p className="text-[11px] italic text-slate-500 dark:text-slate-400 mt-1 mb-4 max-w-3xl">
                    One dot per setup · No frontier line: an arbitrary metric pair has no agreed better direction · Log scales unavailable on an axis where a plotted value is zero
                </p>
                <div className="flex flex-wrap items-center gap-x-4 gap-y-2 mb-4">
                    <MetricSelect id="custom-x" label="X" value={customX} onChange={setCustomX} available={available} />
                    <Checkbox
                        id="custom-log-x"
                        label="log X"
                        checked={logX && logXOk}
                        disabled={!logXOk}
                        onChange={setLogX}
                        title={logXOk ? "Logarithmic x-axis" : "A plotted value is zero or negative, which a log axis cannot show"}
                    />
                    <MetricSelect id="custom-y" label="Y" value={customY} onChange={setCustomY} available={available} />
                    <Checkbox
                        id="custom-log-y"
                        label="log Y"
                        checked={logY && logYOk}
                        disabled={!logYOk}
                        onChange={setLogY}
                        title={logYOk ? "Logarithmic y-axis" : "A plotted value is zero or negative, which a log axis cannot show"}
                    />
                </div>
                <div className={SCATTER_H}>
                    <EfficiencyScatter
                        setups={setups}
                        xMetric={customX}
                        yMetric={customY}
                        models={models}
                        harnesses={harnesses}
                        colorBy={colorBy}
                        showFrontier={false}
                        logX={logX && logXOk}
                        logY={logY && logYOk}
                        ariaLabel={`${METRIC_LABELS[customY]} against ${METRIC_LABELS[customX]} for each setup`}
                        caption={`${METRIC_LABELS[customY]} versus ${METRIC_LABELS[customX]} per setup`}
                    />
                </div>
            </details>
        </section>
    );
}
