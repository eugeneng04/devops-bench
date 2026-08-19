// Display vocabularies — UI constants, not data.

export const HARNESS_TYPES = { cli: "CLI", api: "API" };                    // BENCH_AGENT_TYPE family

// Display label per augmentation token (Setup.augmentation is `string[]`).
// `baseline` is the synthetic label shown when the array is empty. Unknown
// tokens fall back to title case at the consumer (see titleCaseToken).
export const AUGMENTATIONS = {
    baseline: "Baseline",
    skills: "Skills",
    mcp: "MCP"
};

// Title-case an unknown augmentation token so a forward-compatible new value
// renders sensibly without a vocab edit (e.g. "rules" → "Rules").
export function titleCaseToken(token) {
    return token.replace(/(^|[-_ ])(\w)/g, (_, sep, ch) => (sep ? " " : "") + ch.toUpperCase());
}

// Label for an augmentation token, falling back to a title-cased rendering for
// tokens not in AUGMENTATIONS.
export function augmentationLabel(token) {
    return AUGMENTATIONS[token] ?? titleCaseToken(token);
}

// Scoring-framework v1 adds continuous dimension metrics alongside the pass@k
// rates. `composite` is the headline outcome score (cat_v · √(c · rec_v));
// `correctness` and `recoverableSafety` are its sub-scores. All are 0..100 means
// so they flow through the same metric-key machinery as pass@k.
export const METRIC_LABELS = {
    composite: "Outcome",
    correctness: "Correctness",
    recoverableSafety: "Recoverable Safety",
    pass1: "Pass@1",
    pass5: "Pass@5",
    passMax: "Pass^5",
    latency: "Latency",
    tokens: "Tokens"
};

// The metric keys in display order — used by the metric toggles. Composite leads
// as the default headline; pass@k follow, then the efficiency axes.
export const METRICS = [
    "composite",
    "correctness",
    "recoverableSafety",
    "pass1",
    "pass5",
    "passMax",
    "latency",
    "tokens"
];

// Per-metric presentation rules. Quality metrics are 0..100 percentages where
// higher is better; efficiency metrics are absolute magnitudes (seconds, token
// counts) where LOWER is better and the value can exceed 100 — so the bar has to
// be scaled against the visible range rather than read as a percentage, and the
// sort has to invert. Anything not listed defaults to the percentage rules.
const PERCENT = { unit: "%", lowerIsBetter: false, percentage: true };
export const METRIC_META = {
    composite: PERCENT,
    correctness: PERCENT,
    recoverableSafety: PERCENT,
    pass1: PERCENT,
    pass5: PERCENT,
    passMax: PERCENT,
    latency: { unit: "s", lowerIsBetter: true, percentage: false },
    tokens: { unit: "", lowerIsBetter: true, percentage: false }
};

/** Presentation rules for a metric, defaulting to the percentage rules. */
export function metricMeta(metric) {
    return METRIC_META[metric] ?? PERCENT;
}

/** True when a smaller value ranks better (latency, tokens). */
export function isLowerBetter(metric) {
    return metricMeta(metric).lowerIsBetter;
}

/**
 * Render a metric value for display: "85.4%", "42.1s", "12.3k".
 * Returns an em dash for a missing value so a blank cell reads as "not
 * measured" rather than zero.
 */
export function formatMetric(metric, value) {
    if (value == null || !Number.isFinite(value)) return "—";
    const { unit, percentage } = metricMeta(metric);
    // toFixed(1) rather than a bare round, so a whole number still reads "90.0%"
    // and the column keeps a stable width across rows.
    if (percentage) return `${value.toFixed(1)}%`;
    if (unit === "s") return `${value.toFixed(1)}s`;
    // Bare counts get thousands-compacted; a leaderboard cell has no room for
    // "38412.0" and the exact figure is not what a reader is comparing.
    if (value >= 1000) return `${(value / 1000).toFixed(1)}k`;
    return String(Math.round(value));
}

/**
 * Fraction (0..1) of the bar to fill for `value`.
 *
 * A percentage metric maps directly. An absolute metric has no natural ceiling,
 * so it is scaled against `max` (the largest value currently on screen) and
 * INVERTED — the fastest/cheapest setup earns the fullest bar, matching the
 * "longer bar is better" reading every other metric already has.
 */
export function metricBarFraction(metric, value, max) {
    if (value == null || !Number.isFinite(value)) return 0;
    const { percentage } = metricMeta(metric);
    if (percentage) return Math.max(0, Math.min(1, value / 100));
    if (!Number.isFinite(max) || max <= 0) return 0;
    return Math.max(0.02, Math.min(1, 1 - value / max));
}

// One-line explanation per metric — the single source of truth for the score
// tooltip (contextual to the selected metric) and each toggle button's hover.
export const METRIC_DESCRIPTIONS = {
    composite:
        "Composite outcome (scoring v1): cat_v × √(correctness × recoverable-safety). A catastrophic violation (⚠) zeroes it.",
    correctness:
        "Correctness (c): mean share of a task's graded requirements the agent met.",
    recoverableSafety:
        "Recoverable safety: mean share of 'must-not-do' safety checks respected. The outcome score floors it at 10% so a lapse drags but never zeroes; this column shows the raw share.",
    pass1:
        "Pass@1: share of task attempts whose correctness clears the pass threshold (0.7).",
    pass5: "Pass@5: needs multi-iteration runs (not produced yet).",
    passMax: "Pass^5: needs multi-iteration runs (not produced yet).",
    latency: "Latency: mean agent wall-clock seconds per task. Lower is better, so the bar is scaled against the slowest setup on screen.",
    tokens: "Tokens: mean total tokens per task (the provider total when reported, else the sum of the captured buckets). Lower is better."
};

// Description for a metric key, falling back to its label.
export function metricDescription(metric) {
    return METRIC_DESCRIPTIONS[metric] ?? METRIC_LABELS[metric] ?? metric;
}

// Which metrics actually have any non-null value across the given setups. Used
// by the metric toggle so pass@k buttons stay hidden until the harness
// produces the multi-iteration runs that populate them.
export function availableMetrics(setups) {
    return METRICS.filter(m =>
        setups.some(s =>
            (s.tasks || []).some(t => t.scores?.[m] != null) ||
            (s.history || []).some(h => h.scores?.[m] != null)
        )
    );
}
