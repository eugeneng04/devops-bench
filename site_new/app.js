// =============================================================================
// devops-bench leaderboard — data + rendering for the static results page.
//
// FILE MAP (top -> bottom):
//   1. DATA MODEL ......... the structures the whole UI is built on (READ FIRST)
//   2. MOCK DATA .......... generates a fake `setups` so the page renders today
//   3. DERIVED ACCESSORS .. pure functions the render layer calls (score/label/…)
//   4. RENDERING .......... leaderboard rows + expandable task breakdown
//   5. TREND CHART ........ Chart.js line chart of score-over-time
//
// [MOCK] markers flag anything fabricated that MUST be replaced when real eval
// data is wired in. (For the real loader pattern, see the old site/app.js
// loadData(), which fetches eval_results/eval-results-N.jsonl.)
// =============================================================================

// --- 1. DATA MODEL -----------------------------------------------------------
//
// `setups` is THE load-bearing structure: a flat array where each element is
// ONE leaderboard row. Every render function reads from this shape, so keeping
// it stable is what lets real data drop in without touching the rendering code.
//
// Shape of a single setup:
//   {
//     id:           "alpha-pro-gemini-cli-gca-mcp", // stable, slugified DOM id
//     model:        "alpha-pro",              // key into `models`     (1st-class axis)
//     harness:      "gemini-cli",             // key into `harnesses`  (1st-class axis)
//     mcp:          true | false,             // BENCH_USE_MCP         (modifier)
//     augmentation: "baseline" | "gca",       // GCA + skills + rules  (modifier)
//     color:        "#3b82f6",                // line/bar color for this row
//     tasks: [                                // one entry per benchmark task
//       {
//         folder: "create-deployment",        // real tasks/<folder>
//         name:   "Deploy vLLM Server: …",    // display name
//         scores: { pass1: 96, pass5: 98, passMax: 100 }  // accuracy % per metric
//       }, …
//     ]
//   }
//
// A "setup" is the benchmark ENTITY = a (model × harness) PAIRING run in a
// specific config. Model and harness are the two CO-EQUAL first-class axes:
// we are benchmarking the combined capability of an LLM and the agent runner
// driving it (BENCH_AGENT_TYPE + AGENT_TARGET — e.g. Gemini CLI vs OpenClaw
// vs the internal API loop). `augmentation` (GCA + skills + rules) and `mcp`
// are SECONDARY modifiers layered on top of a pairing. Because every field is
// an independent tag, any one can become the row axis, a filter, or a group-by
// without restructuring the data.
//
// The headline number per row is DERIVED from `tasks` (see setupScore) — it is
// intentionally NOT stored, to avoid a second source of truth that can drift.
//
// NOTE: latency / token-count stats are intentionally NOT surfaced yet — the
// harness capture for those is still inconsistent (harness-dependent token shapes,
// last-turn-only token usage vs cumulative latency, missing-data cases). Add
// them once that's normalized.

// Dimension vocabularies (display labels for the harness values).
const HARNESS_TYPES = { cli: "CLI", api: "API" };                    // BENCH_AGENT_TYPE family
const AUGMENTATIONS = { baseline: "Baseline", gca: "GCA + Skills" };  // secondary modifier layer
// mcp is a boolean (BENCH_USE_MCP) — also a secondary modifier.

// `models` — stable metadata per base LLM, keyed by model id and referenced
// from each setup via `setup.model` (one model fans out to several setups).
// [MOCK] fictional placeholders; replace with real AGENT_MODEL / AGENT_PROVIDER.
const models = {
    "alpha-pro":   { name: "Alpha Pro",   provider: "Acme",    license: "Proprietary", logo: "alpha" },
    "beta-sonic":  { name: "Beta Sonic",  provider: "Globex",  license: "Proprietary", logo: "beta" },
    "gamma-coder": { name: "Gamma Coder", provider: "Initech", license: "Open Source", logo: "gamma" }
};

// `harnesses` — the agent RUNNER under test, a first-class axis CO-EQUAL with
// `models`. Maps to BENCH_AGENT_TYPE + AGENT_TARGET in pkg/evaluator: `cli`
// dispatches on the AGENT_TARGET binary (gemini / openclaw), `api` is the
// internal Python tool-calling loop. `type` is the cli/api family; `accent`
// tints the harness chip so it reads as its own entity class (distinct from the
// model brand). `logo` keys into harnessIcon().
// [MOCK] names/accents are illustrative; wire real AGENT_TARGET values later.
const harnesses = {
    "gemini-cli": { name: "Gemini CLI", type: "cli", accent: "#0ea5e9", logo: "terminal" },
    "openclaw":   { name: "OpenClaw",   type: "cli", accent: "#f43f5e", logo: "claw" },
    "api-loop":   { name: "API Runner", type: "api", accent: "#8b5cf6", logo: "braces" }
};

// `TASK_CATALOG` — the benchmark tasks, shared by every setup (index-aligned
// with the BASE_PROFILE arrays below). `folder` values are REAL (they match the
// tasks/<folder> dirs); `name` is a display label.
const TASK_CATALOG = [
    { folder: "get-app-architecture",          name: "Summarize Application Architecture" },
    { folder: "create-deployment",             name: "Deploy vLLM Server: Gemma 3, GPU, GCS Fuse" },
    { folder: "deploy-config",                 name: "Deploy Kubernetes Configuration Manifests" },
    { folder: "modify-deployment",             name: "Update App Config: Gemini to Local vLLM" },
    { folder: "fix-config",                    name: "Fix & Apply Frontend Deployment Manifest" },
    { folder: "deploy-hello-app",              name: "Productionize & Deploy Hello World App" },
    { folder: "computeclass-spot-fallback",    name: "ComputeClass Spot VMs with N2 Fallback" },
    { folder: "computeclass-active-migration", name: "ComputeClass Active Workload Migration" },
    { folder: "gateway-cloud-armor",           name: "Gateway Cloud Armor Security Policy" },
    { folder: "gateway-https-redirect",        name: "Gateway HTTP-to-HTTPS redirect" },
    { folder: "hpa-metric-filtering",          name: "Prometheus AutoscalingMetric Filter" },
    { folder: "hpa-renamed-metric",            name: "HPA Custom Export-Name Metric Mapping" }
];

// --- 2. MOCK DATA ------------------------------------------------------------
//
// [MOCK] Everything in this section is fabricated so the page renders before
// real results exist. To wire real data: DELETE BASE_PROFILE, SETUP_DEFS, and
// the `setups` generator, then build `setups` (shape documented in section 1)
// from eval_results/*.jsonl instead — aggregating Outcome Validity across the
// per-task `Run #`s to get real pass@1 / pass@5 / pass@max.

// [MOCK] Baseline per-task accuracy per model (index aligns with TASK_CATALOG).
const BASE_PROFILE = {
    "alpha-pro":   [92, 93, 94, 95, 94, 93, 90, 89, 86, 88, 88, 87],
    "beta-sonic":  [90, 91, 92, 93, 92, 91, 85, 84, 80, 82, 83, 81],
    "gamma-coder": [84, 86, 88, 89, 88, 87, 70, 69, 65, 68, 69, 67]
};

// [MOCK] Curated (model × harness) pairings. Not a full cross product
// (model x harness x augmentation x mcp); a representative subset that pairs
// several models with different agent runners and shows each as a baseline-vs-
// GCA pair, so the model AND harness axes are both exercised.
const SETUP_DEFS = [
    { model: "alpha-pro",   harness: "gemini-cli", mcp: false, augmentation: "baseline" },
    { model: "alpha-pro",   harness: "gemini-cli", mcp: true,  augmentation: "gca" },
    { model: "alpha-pro",   harness: "api-loop",   mcp: false, augmentation: "baseline" },
    { model: "alpha-pro",   harness: "api-loop",   mcp: true,  augmentation: "gca" },
    { model: "beta-sonic",  harness: "openclaw",   mcp: false, augmentation: "baseline" },
    { model: "beta-sonic",  harness: "openclaw",   mcp: true,  augmentation: "gca" },
    { model: "gamma-coder", harness: "gemini-cli", mcp: false, augmentation: "baseline" },
    { model: "gamma-coder", harness: "api-loop",   mcp: true,  augmentation: "gca" }
];

// One distinct line/bar color per setup (model brand color drives the logo only).
const PALETTE = ["#3b82f6", "#1d4ed8", "#10b981", "#059669", "#f59e0b", "#d97706", "#8b5cf6", "#ec4899"];

function clampPct(v) {
    return Math.max(0, Math.min(100, v));
}

// [MOCK] Expands the compact source above into the real `setups` shape that the
// render layer consumes (section 1). The accuracy numbers here are SYNTHESIZED:
// a baseline profile plus deltas for augmentation/harness, and pass5/passMax as
// fixed offsets above pass1. Real data replaces this whole block.
const setups = SETUP_DEFS.map((def, i) => {
    const base = BASE_PROFILE[def.model];
    const augDelta = def.augmentation === "gca" ? 5 : 0;            // [MOCK] GCA + skills + rules lift
    const harnessDelta = harnesses[def.harness].type === "cli" ? 1 : 0;  // [MOCK] runner lift
    const delta = augDelta + harnessDelta;
    return {
        id: `${def.model}-${def.harness}-${def.augmentation}${def.mcp ? "-mcp" : ""}`.replace(/[^a-z0-9-]/gi, ""),
        model: def.model,
        harness: def.harness,
        mcp: def.mcp,
        augmentation: def.augmentation,
        color: PALETTE[i % PALETTE.length],
        tasks: TASK_CATALOG.map((task, t) => {
            const pass1 = clampPct(base[t] + delta);
            return {
                folder: task.folder,
                name: task.name,
                // best-of-N ordering: pass@1 <= pass@5 <= pass@max
                scores: { pass1: pass1, pass5: clampPct(pass1 + 2), passMax: clampPct(pass1 + 4) }
            };
        })
    };
});

// Iteration labels for the trend chart (shared time axis).
const ITERATIONS = ["Iteration 1", "Iteration 2", "Iteration 3", "Iteration 4", "Iteration 5", "Current Run"];

// --- 3. DERIVED ACCESSORS ----------------------------------------------------
//
// Pure read-only functions over a `setup`. The render layer (section 4/5) only
// ever reaches the data THROUGH these, so real data only has to match the
// `setups` shape — not the rendering code.

// Full label distinguishing a setup. Leads with the first-class pairing
// (model × harness), then the secondary modifiers. Used by the chart legend.
function setupLabel(setup) {
    const parts = [`${models[setup.model].name} × ${harnesses[setup.harness].name}`];
    parts.push(AUGMENTATIONS[setup.augmentation]);
    if (setup.mcp) parts.push("MCP");
    return parts.join(" · ");
}

// Secondary modifier chips shown on the row (augmentation + mcp only — the
// harness now has its own first-class column, so its type lives there).
function setupTags(setup) {
    const tags = [
        {
            text: AUGMENTATIONS[setup.augmentation],
            cls: setup.augmentation === "gca"
                ? "bg-indigo-50 text-indigo-700 ring-1 ring-indigo-100"
                : "bg-slate-100 text-slate-500"
        }
    ];
    if (setup.mcp) tags.push({ text: "MCP", cls: "bg-emerald-50 text-emerald-700 ring-1 ring-emerald-100" });
    return tags;
}

// Aggregated headline score for a setup under the selected metric.
// Placeholder rule = mean over tasks; swap in the real aggregation here later.
function setupScore(setup, metric) {
    const vals = setup.tasks.map(t => t.scores[metric]);
    return vals.reduce((sum, v) => sum + v, 0) / vals.length;
}

// [MOCK] Synthesizes a plausible upward trend ending at the setup's current
// score. There is NO real history wired in — real data must supply actual
// per-iteration values (one point per past eval run).
function setupHistory(setup, metric) {
    const target = setupScore(setup, metric);
    return ITERATIONS.map((_, i) => {
        const t = i / (ITERATIONS.length - 1);
        return Math.round((target - (1 - t) * 8) * 10) / 10;
    });
}

// --- 4. APPLICATION STATE & RENDERING ----------------------------------------
let currentMetric = 'pass1';
const openRows = new Set();
let trendChartInstance = null;

// --- FILTERING ---------------------------------------------------------------
//
// Faceted multi-select filter over the setup dimensions. Each group holds a Set
// of selected values; WITHIN a group the selected values are OR'd, ACROSS groups
// they are AND'd (standard faceted behavior). An empty group means "no filter"
// for that dimension. getFilteredSetups() is the single source the leaderboard
// AND the trend chart both read from, so any selection change is reflected
// everywhere via filterAndRender() + updateTrendChart().

const filterState = {
    model: new Set(),
    harness: new Set(),
    augmentation: new Set(),
    mcp: new Set()        // values: "mcp" | "nomcp"
};

// Group definitions, including how to read the matching value off a setup and a
// `tier`: "primary" facets are the co-equal first-class axes (model, harness);
// "secondary" facets are the modifier layer (augmentation, mcp), rendered more
// quietly. `options()` is derived from the live `setups` so it stays correct
// when real data drops in (e.g. an unused harness simply won't show a chip).
const FILTER_GROUPS = [
    {
        key: "model", label: "Model", tier: "primary",
        valueOf: s => s.model,
        options: () => Object.keys(models)
            .filter(id => setups.some(s => s.model === id))
            .map(id => ({ value: id, text: models[id].name }))
    },
    {
        key: "harness", label: "Harness", tier: "primary",
        valueOf: s => s.harness,
        options: () => Object.keys(harnesses)
            .filter(id => setups.some(s => s.harness === id))
            .map(id => ({ value: id, text: harnesses[id].name }))
    },
    {
        key: "augmentation", label: "Augment", tier: "secondary",
        valueOf: s => s.augmentation,
        options: () => Object.keys(AUGMENTATIONS)
            .filter(a => setups.some(s => s.augmentation === a))
            .map(a => ({ value: a, text: AUGMENTATIONS[a] }))
    },
    {
        key: "mcp", label: "MCP", tier: "secondary",
        valueOf: s => (s.mcp ? "mcp" : "nomcp"),
        options: () => {
            const opts = [];
            if (setups.some(s => s.mcp)) opts.push({ value: "mcp", text: "MCP" });
            if (setups.some(s => !s.mcp)) opts.push({ value: "nomcp", text: "No MCP" });
            return opts;
        }
    }
];

// The setups passing every active facet. Empty facet = match all.
function getFilteredSetups() {
    return setups.filter(setup =>
        FILTER_GROUPS.every(group => {
            const selected = filterState[group.key];
            return selected.size === 0 || selected.has(group.valueOf(setup));
        })
    );
}

function anyFilterActive() {
    return FILTER_GROUPS.some(g => filterState[g.key].size > 0);
}

function toggleFilter(groupKey, value) {
    const set = filterState[groupKey];
    if (set.has(value)) set.delete(value);
    else set.add(value);
    renderFilters();
    filterAndRender();
    updateTrendChart();
}

function clearFilters() {
    FILTER_GROUPS.forEach(g => filterState[g.key].clear());
    renderFilters();
    filterAndRender();
    updateTrendChart();
}

// Renders one filter group (label + chips). `tier` controls weight: primary
// facets (model/harness) get bolder labels and indigo active chips; secondary
// facets (modifiers) get quieter labels and a softer slate active state.
function renderFilterGroup(group) {
    const opts = group.options();
    if (opts.length === 0) return '';
    const primary = group.tier === 'primary';
    const chips = opts.map(opt => {
        const active = filterState[group.key].has(opt.value);
        let cls;
        if (active) {
            cls = primary
                ? 'bg-indigo-600 text-white border-indigo-600 shadow-sm'
                : 'bg-slate-700 text-white border-slate-700 shadow-sm';
        } else {
            cls = 'bg-white text-slate-600 border-slate-200 hover:border-slate-300 hover:bg-slate-50';
        }
        const size = primary ? 'px-3 py-1 text-xs' : 'px-2.5 py-0.5 text-[11px]';
        return `<button type="button"
                    onclick="toggleFilter('${group.key}', '${opt.value}')"
                    aria-pressed="${active}"
                    class="${size} rounded-full border font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 focus-visible:ring-offset-1 ${cls}">
                    ${opt.text}
                </button>`;
    }).join('');
    const labelCls = primary
        ? 'text-[11px] font-bold tracking-wide uppercase text-slate-600'
        : 'text-[10px] font-semibold tracking-wider uppercase text-slate-400';
    return `
        <div class="flex flex-wrap items-center gap-1.5">
            <span class="${labelCls} w-16 shrink-0">${group.label}</span>
            ${chips}
        </div>`;
}

// Renders the two-tier filter bar: the first-class axes (Model × Harness) up
// top, then a divider, then the secondary modifier facets.
function renderFilters() {
    const bar = document.getElementById('filter-bar');
    if (!bar) return;

    const primaryHtml = FILTER_GROUPS.filter(g => g.tier === 'primary')
        .map(renderFilterGroup).join('');
    const secondaryHtml = FILTER_GROUPS.filter(g => g.tier === 'secondary')
        .map(renderFilterGroup).join('');

    const total = setups.length;
    const shown = getFilteredSetups().length;
    const clearBtn = anyFilterActive()
        ? `<button type="button" onclick="clearFilters()"
               class="text-[11px] font-medium text-indigo-600 hover:text-indigo-800 underline-offset-2 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 rounded">
               Clear all
           </button>`
        : '';

    bar.innerHTML = `
        <div class="flex items-start justify-between gap-4">
            <div class="flex flex-col gap-2 flex-grow">${primaryHtml}</div>
            <div class="flex items-center gap-3 shrink-0 pt-0.5">
                <span class="text-[11px] text-slate-400 whitespace-nowrap">${shown} of ${total}</span>
                ${clearBtn}
            </div>
        </div>
        <div class="flex items-center gap-2 pt-1 mt-1 border-t border-slate-100">
            <span class="text-[9px] font-semibold tracking-wider uppercase text-slate-300 shrink-0">Modifiers</span>
            <div class="flex flex-col sm:flex-row sm:flex-wrap gap-x-4 gap-y-1 flex-grow pl-1">${secondaryHtml}</div>
        </div>`;
}

const brandLogos = {
    alpha: `<svg aria-hidden="true" focusable="false" class="w-4 h-4 min-w-[16px]" viewBox="0 0 24 24" fill="none"><rect x="2" y="2" width="20" height="20" rx="6" fill="#6366f1"/><text x="12" y="16" fill="white" font-size="12" font-family="system-ui, sans-serif" font-weight="bold" text-anchor="middle">A</text></svg>`,
    beta: `<svg aria-hidden="true" focusable="false" class="w-4 h-4 min-w-[16px]" viewBox="0 0 24 24" fill="none"><rect x="2" y="2" width="20" height="20" rx="6" fill="#0ea5e9"/><text x="12" y="16" fill="white" font-size="12" font-family="system-ui, sans-serif" font-weight="bold" text-anchor="middle">B</text></svg>`,
    gamma: `<svg aria-hidden="true" focusable="false" class="w-4 h-4 min-w-[16px]" viewBox="0 0 24 24" fill="none"><rect x="2" y="2" width="20" height="20" rx="6" fill="#f97316"/><text x="12" y="16" fill="white" font-size="12" font-family="system-ui, sans-serif" font-weight="bold" text-anchor="middle">C</text></svg>`
};

// Harness glyphs — line icons tinted with the harness accent so the runner
// reads as its own entity class (vs the filled-square model logos).
function harnessIcon(harness) {
    const c = harness.accent;
    const glyph = {
        terminal: `<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M7 8l3 3-3 3m5 1h4"/>`,
        claw:     `<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 7l8-4 8 4-8 4-8-4z"/><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 12l8 4 8-4M4 17l8 4 8-4"/>`,
        braces:   `<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 5c-2 0-2 2-2 3.5S6 12 4 12c2 0 2 2.5 2 4s0 3 2 3m8-14c2 0 2 2 2 3.5S18 12 20 12c-2 0-2 2.5-2 4s0 3-2 3"/>`
    }[harness.logo] || '';
    return `<svg aria-hidden="true" focusable="false" class="w-4 h-4 min-w-[16px]" fill="none" stroke="${c}" viewBox="0 0 24 24">${glyph}</svg>`;
}

function switchMetric(metric) {
    currentMetric = metric;
    ['pass1', 'pass5', 'passMax'].forEach(m => {
        const btn = document.getElementById(`btn-${m}`);
        if (btn) {
            if (m === metric) {
                btn.classList.add('bg-white', 'text-slate-800', 'shadow-sm');
                btn.classList.remove('text-slate-600', 'hover:text-slate-800');
                btn.setAttribute('aria-pressed', 'true');
            } else {
                btn.classList.remove('bg-white', 'text-slate-800', 'shadow-sm');
                btn.classList.add('text-slate-600', 'hover:text-slate-800');
                btn.setAttribute('aria-pressed', 'false');
            }
        }
    });
    filterAndRender();
    updateTrendChart();
}

function handleRowKeyDown(event, setupId) {
    if (event.key === 'Enter' || event.key === ' ') {
        event.preventDefault(); // Prevent page scrolling
        toggleRow(setupId);
    }
}

function toggleRow(setupId) {
    const panel = document.getElementById(`panel-${setupId}`);
    const chevron = document.getElementById(`chevron-${setupId}`);
    const rowTrigger = document.getElementById(`row-trigger-${setupId}`);

    if (openRows.has(setupId)) {
        openRows.delete(setupId);
        if (panel) panel.classList.remove('expanded');
        if (chevron) chevron.classList.remove('rotate-180');
        if (rowTrigger) rowTrigger.setAttribute('aria-expanded', 'false');
    } else {
        openRows.add(setupId);
        if (panel) panel.classList.add('expanded');
        if (chevron) chevron.classList.add('rotate-180');
        if (rowTrigger) rowTrigger.setAttribute('aria-expanded', 'true');
    }
}

function filterAndRender() {
    const container = document.getElementById('leaderboard-rows');
    const activeId = document.activeElement ? document.activeElement.id : null;

    // Sort the FILTERED setups by their aggregated score under the selected metric.
    const sortedData = getFilteredSetups()
        .sort((a, b) => setupScore(b, currentMetric) - setupScore(a, currentMetric));

    if (sortedData.length === 0) {
        container.innerHTML = `
            <div class="px-6 py-12 flex flex-col items-center justify-center text-center gap-2">
                <svg class="w-8 h-8 text-slate-300" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"></path>
                </svg>
                <p class="text-sm font-medium text-slate-500">No setups match the selected filters.</p>
                <button type="button" onclick="clearFilters()" class="text-xs font-medium text-indigo-600 hover:text-indigo-800 hover:underline">Clear all filters</button>
            </div>`;
        return;
    }

    container.innerHTML = sortedData.map(setup => {
        const model = models[setup.model];
        const harness = harnesses[setup.harness];
        const color = setup.color;
        const scoreValue = setupScore(setup, currentMetric);
        const isExpanded = openRows.has(setup.id);

        // The harness configures these — render them nested UNDER the harness:
        // the CLI/API type chip (accent-tinted) followed by the augmentation + MCP modifiers.
        const tagsHtml = setupTags(setup).map(tag =>
            `<span class="inline-flex items-center px-2 py-0.5 rounded text-[10px] font-medium ${tag.cls}">${tag.text}</span>`
        ).join('');
        const typeChip = `<span class="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-semibold uppercase tracking-wide" style="color: ${harness.accent}; background-color: ${harness.accent}1a;">${HARNESS_TYPES[harness.type]}</span>`;
        const harnessConfigHtml = typeChip + tagsHtml;

        const tasksBreakdownHtml = `
            <div class="accordion-wrapper ${isExpanded ? 'expanded' : ''}" id="panel-${setup.id}">
                <div class="accordion-content">
                    <div class="px-6 py-4 bg-slate-50 border-t border-slate-100 text-xs">
                        <div class="mb-3 font-semibold text-slate-500 tracking-wider uppercase">Granular Task Breakdown</div>
                        <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-x-8 gap-y-3">
                            ${setup.tasks.map(task => {
                                const taskScore = task.scores[currentMetric];
                                return `
                                    <div class="flex flex-col gap-1 h-full">
                                        <div class="flex justify-between text-slate-600 font-medium gap-2">
                                            <div class="flex flex-col">
                                                <span class="font-semibold text-slate-700">${task.name}</span>
                                                <span class="text-[10px] font-mono text-slate-400 mt-0.5">${task.folder}/</span>
                                            </div>
                                            <span class="font-semibold text-slate-700 mt-0.5 shrink-0 whitespace-nowrap">${taskScore}%</span>
                                        </div>
                                        <div class="w-full bg-slate-200 h-1.5 rounded-full overflow-hidden mt-auto">
                                            <div class="progress-bar-fill h-full rounded-full subtask-progress-bar" style="--target-width: ${taskScore}; background-color: ${color};"></div>
                                        </div>
                                    </div>
                                `;
                            }).join('')}
                        </div>
                    </div>
                </div>
            </div>
        `;

        return `
            <div class="flex flex-col">
                <!-- Main Clickable Header Row -->
                <div id="row-trigger-${setup.id}"
                     onclick="toggleRow('${setup.id}')"
                     onkeydown="handleRowKeyDown(event, '${setup.id}')"
                     role="button"
                     tabindex="0"
                     aria-expanded="${isExpanded}"
                     aria-controls="panel-${setup.id}"
                     aria-label="${setupLabel(setup)}"
                     class="relative px-6 py-4 flex flex-col sm:grid sm:grid-cols-12 gap-3 sm:gap-4 items-start sm:items-center hover:bg-slate-50/70 cursor-pointer transition-colors group select-none focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 focus-visible:ring-inset">

                    <!-- Benchmark subject: model × harness pairing (co-equal first-class).
                         Fixed 1fr_auto_1fr sub-grid so the operator and harness align across rows.
                         Harness config (type + augmentation + MCP) nests beneath the harness. -->
                    <div class="col-span-7 sm:col-span-7 grid grid-cols-[1fr_auto_1fr] items-center gap-1 sm:gap-2 w-full sm:w-auto pr-6 sm:pr-0">
                        <!-- Model entity -->
                        <div class="flex items-center gap-2 min-w-0">
                            <div class="p-1 bg-white rounded-md shadow-sm border border-slate-100 flex-shrink-0 group-hover:scale-105 transition-transform">
                                ${brandLogos[model.logo] || ''}
                            </div>
                            <div class="flex flex-col gap-0.5 min-w-0">
                                <span class="text-slate-900 font-semibold text-sm truncate">${model.name}</span>
                                <span class="text-[10px] text-slate-400 font-normal truncate">${model.provider}</span>
                            </div>
                        </div>

                        <!-- Pairing connector: hairlines + a multiplication glyph reading "model combined with harness" -->
                        <div aria-hidden="true" class="flex items-center justify-center gap-1 px-0.5 sm:px-1 select-none shrink-0">
                            <span class="hidden sm:block h-px w-2.5 bg-gradient-to-r from-transparent to-slate-300"></span>
                            <span class="flex items-center justify-center w-5 h-5 rounded-md text-slate-400 text-sm font-medium leading-none ring-1 ring-slate-200/70 bg-slate-50 group-hover:text-indigo-500 group-hover:ring-indigo-200 transition-colors">×</span>
                            <span class="hidden sm:block h-px w-2.5 bg-gradient-to-l from-transparent to-slate-300"></span>
                        </div>

                        <!-- Harness entity -->
                        <div class="flex items-center gap-2 min-w-0">
                            <div class="p-1 rounded-md shadow-sm flex-shrink-0 group-hover:scale-105 transition-transform" style="background-color: ${harness.accent}1a; border: 1px solid ${harness.accent}33;">
                                ${harnessIcon(harness)}
                            </div>
                            <div class="flex flex-col gap-1 min-w-0">
                                <span class="text-slate-900 font-semibold text-sm truncate">${harness.name}</span>
                                <div class="flex flex-wrap items-center gap-1">${harnessConfigHtml}</div>
                            </div>
                        </div>
                    </div>

                    <!-- Interactive Score progression meters -->
                    <div class="col-span-4 sm:col-span-4 flex items-center gap-3 w-full sm:w-auto mt-2 sm:mt-0">
                        <span class="text-sm font-semibold text-slate-900 w-12 min-w-[48px]">
                            ${scoreValue.toFixed(1)}%
                        </span>
                        <div class="w-full bg-slate-100 h-2 rounded-full overflow-hidden relative">
                            <div class="progress-bar-fill h-full rounded-full"
                                 style="width: ${scoreValue}%; background-color: ${color};">
                            </div>
                        </div>
                    </div>

                    <!-- Chevron Column (Mobile: Absolute, Desktop: Relative Grid Span 1) -->
                    <div class="absolute right-6 top-5 sm:relative sm:right-auto sm:top-auto col-span-1 sm:col-span-1 flex items-center justify-end">
                        <svg aria-hidden="true" id="chevron-${setup.id}" class="w-4 h-4 text-slate-500 transition-transform duration-200 ${isExpanded ? 'rotate-180' : ''}" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7"></path>
                        </svg>
                    </div>

                </div>
                ${tasksBreakdownHtml}
            </div>
        `;
    }).join('');

    if (activeId) {
        const elementToFocus = document.getElementById(activeId);
        if (elementToFocus) {
            elementToFocus.focus();
        }
    }
}

function setupTooltip() {
    const trigger = document.getElementById('tooltip-trigger');
    if (trigger) {
        trigger.addEventListener('keydown', function(event) {
            if (event.key === 'Escape') {
                trigger.blur(); // Dismisses tooltip
            }
        });
    }
}

// --- 5. TREND CHART ----------------------------------------------------------
// Score-over-time line chart: one line per setup, x = iterations, y = score for
// the selected metric. Data comes from setupHistory() (currently [MOCK]).
function initTrendChart() {
    const canvas = document.getElementById('trendChart');
    if (!canvas) return;
    const ctx = canvas.getContext('2d');

    // Set custom Chart.js defaults matching Inter font and Slate styling
    Chart.defaults.font.family = "'Inter', sans-serif";
    Chart.defaults.color = "#64748b"; // slate-500
    Chart.defaults.plugins.tooltip.backgroundColor = "#0f172a"; // slate-900
    Chart.defaults.plugins.tooltip.titleColor = "#f8fafc";
    Chart.defaults.plugins.tooltip.bodyColor = "#cbd5e1";
    Chart.defaults.plugins.tooltip.padding = 12;
    Chart.defaults.plugins.tooltip.cornerRadius = 8;
    Chart.defaults.plugins.tooltip.borderWidth = 1;
    Chart.defaults.plugins.tooltip.borderColor = "#334155"; // slate-700

    trendChartInstance = new Chart(ctx, {
        type: 'line',
        data: {
            labels: ITERATIONS,
            datasets: []
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: {
                mode: 'index',
                intersect: false,
            },
            plugins: {
                legend: {
                    display: true,
                    position: 'bottom',
                    labels: {
                        usePointStyle: true,
                        boxWidth: 8,
                        padding: 20,
                        font: {
                            size: 11,
                            weight: '500'
                        }
                    }
                },
                tooltip: {
                    callbacks: {
                        label: function(context) {
                            return ` ${context.dataset.label}: ${context.parsed.y.toFixed(1)}%`;
                        }
                    }
                }
            },
            scales: {
                x: {
                    grid: {
                        display: false
                    },
                    ticks: {
                        padding: 8
                    }
                },
                y: {
                    min: 60,
                    max: 100,
                    border: {
                        display: false
                    },
                    grid: {
                        color: "#f1f5f9"
                    },
                    ticks: {
                        callback: function(value) {
                            return value + '%';
                        },
                        stepSize: 10,
                        padding: 8
                    }
                }
            },
            elements: {
                line: {
                    tension: 0.35,
                    borderWidth: 3
                },
                point: {
                    radius: 3,
                    hitRadius: 12,
                    hoverRadius: 6,
                    hoverBackgroundColor: '#ffffff',
                    hoverBorderWidth: 3
                }
            }
        }
    });

    updateTrendChart();
}

function updateTrendChart() {
    if (!trendChartInstance) return;

    // One line per FILTERED setup, colored by the setup's own color.
    const visibleSetups = getFilteredSetups();
    const datasets = visibleSetups.map(setup => ({
        label: setupLabel(setup),
        data: setupHistory(setup, currentMetric),
        borderColor: setup.color,
        backgroundColor: `${setup.color}1a`, // 10% opacity shading (1a = 10%)
        pointBorderColor: setup.color,
        pointBackgroundColor: setup.color,
        fill: false
    }));

    trendChartInstance.data.datasets = datasets;
    trendChartInstance.update();

    // Dynamically build accessibility data table representation
    const table = document.getElementById('trend-chart-table');
    if (table) {
        let tableHtml = `
            <caption>Accuracy Performance Trend Over Time data summary (selected metric: ${currentMetric})</caption>
            <thead>
                <tr>
                    <th scope="col">Setup</th>
                    ${ITERATIONS.map(iter => `<th scope="col">${iter}</th>`).join('')}
                </tr>
            </thead>
            <tbody>
                ${visibleSetups.map(setup => {
                    const historyData = setupHistory(setup, currentMetric);
                    return `
                        <tr>
                            <th scope="row">${setupLabel(setup)}</th>
                            ${historyData.map(val => `<td>${val.toFixed(1)}%</td>`).join('')}
                        </tr>
                    `;
                }).join('')}
            </tbody>
        `;
        table.innerHTML = tableHtml;
    }
}

// Initialize layout
window.onload = function() {
    renderFilters();
    filterAndRender();
    initTrendChart();
    setupTooltip();
};
