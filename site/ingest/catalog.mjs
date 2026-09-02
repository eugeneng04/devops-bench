// =============================================================================
// Benchmark dimension catalog (Node ESM, ingest-side).
//
// The single source of truth for translating raw telemetry strings (from eval
// artifacts / metadata) into the curated `models` and `harnesses` identities
// written to Firestore.
//
//   resolveModel(raw)   -> curated model key (or fallback slug) + metadata
//   resolveHarness(raw) -> curated harness key (or fallback slug) + metadata
//
// Fallback policy: an unrecognized model or harness is NOT dropped (that would make a
// whole run vanish from the leaderboard). Instead it is slugified into a key and
// given minimal synthesized metadata, and the resolver flags it so the ingest
// can warn. Add a real alias + metadata entry here to give it a proper home.
// =============================================================================

// --- curated metadata (mirrors the `models` / `harnesses` collections) -------

/** @type {Record<string, {name: string, provider: string, license: string, logo: string}>} */
export const MODELS = {
    "alpha-pro":        { name: "Alpha Pro",        provider: "Acme",      license: "Proprietary", logo: "alpha" },
    "beta-sonic":       { name: "Beta Sonic",       provider: "Globex",    license: "Proprietary", logo: "beta" },
    "gamma-coder":      { name: "Gamma Coder",      provider: "Initech",   license: "Open Source", logo: "gamma" },
    "gemini-3.1-pro":   { name: "Gemini 3.1 Pro",   provider: "Google",    license: "Proprietary", logo: "gemini" },
    "gemini-3.5-flash": { name: "Gemini 3.5 Flash", provider: "Google",    license: "Proprietary", logo: "gemini" },
    "gemini-3.7-flash": { name: "Gemini 3.7 Flash", provider: "Google",    license: "Proprietary", logo: "gemini" },
    "claude-opus-5":    { name: "Claude Opus 5",    provider: "Anthropic", license: "Proprietary", logo: "claude" },
    "claude-opus-4-8":  { name: "Claude Opus 4.8",  provider: "Anthropic", license: "Proprietary", logo: "claude" },
    "claude-sonnet-5":  { name: "Claude Sonnet 5",  provider: "Anthropic", license: "Proprietary", logo: "claude" },
    "claude-haiku-4-5": { name: "Claude Haiku 4.5", provider: "Anthropic", license: "Proprietary", logo: "claude" },
    "claude-fable-5":   { name: "Claude Fable 5",   provider: "Anthropic", license: "Proprietary", logo: "claude" },
    "gpt-5.6-sol":      { name: "GPT-5.6 Sol",      provider: "OpenAI",    license: "Proprietary", logo: "openai" }
};

/** @type {Record<string, {name: string, type: "cli"|"api", accent: string, logo: string}>} */
export const HARNESSES = {
    "gemini-cli":  { name: "Gemini CLI",  type: "cli", accent: "#0ea5e9", logo: "terminal" },
    "kubeagents":  { name: "KubeAgents",  type: "cli", accent: "#326ce5", logo: "terminal" },
    "claude-code": { name: "Claude Code", type: "cli", accent: "#d97757", logo: "terminal" },
    "openclaw":    { name: "OpenClaw",    type: "cli", accent: "#f43f5e", logo: "claw" },
    "api-loop":    { name: "API Runner",  type: "api", accent: "#8b5cf6", logo: "braces" },
    "antigravity": { name: "Antigravity", type: "cli", accent: "#f59e0b", logo: "arrow-up" }
};

// --- raw identity -> curated id ----------------------------------------------

// Map a raw `agentModel` (as set via AGENT_MODEL) to a curated model id. Keys
// are matched case-insensitively as exact strings first, then as substrings, so
// "claude-opus-4-8" and "claude-opus-4-8-20260101" both resolve.
/** @type {Record<string, string>} */
export const MODEL_ALIASES = {
    "alpha-pro": "alpha-pro",
    "beta-sonic": "beta-sonic",
    "gamma-coder": "gamma-coder",
    // Preview shares the stable Gemini 3.1 Pro metadata. The bare key also lets
    // versioned ids (e.g. gemini-3.1-pro-001) resolve via substring matching.
    "gemini-3.1-pro": "gemini-3.1-pro",
    "gemini-3.1-pro-preview": "gemini-3.1-pro",
    "gemini-3.5-flash": "gemini-3.5-flash",
    "gemini-3.7-flash": "gemini-3.7-flash",
    // Anthropic. The bare keys cover dated snapshots and the `[1m]` long-context
    // suffix via substring matching; both bill at the same rate, so the suffix
    // needs no entry of its own.
    "claude-opus-5": "claude-opus-5",
    "claude-opus-4-8": "claude-opus-4-8",
    "claude-sonnet-5": "claude-sonnet-5",
    "claude-haiku-4-5": "claude-haiku-4-5",
    "claude-fable-5": "claude-fable-5",
    "gpt-5.6-sol": "gpt-5.6-sol",
    // Claude Code's tier shorthands, which is what AGENT_MODEL carries on a
    // subscription CLI run. They name a TIER, not a version — the CLI resolves
    // each to whatever is current — so they point at today's default. A run whose
    // harness reports `servedModel` is priced off that instead and never reaches
    // these (see pricing.priceFor).
    "opus": "claude-opus-5",
    "sonnet": "claude-sonnet-5",
    "haiku": "claude-haiku-4-5"
};

// Substring candidates, longest alias first. Order matters and insertion order
// is the wrong one: "opus" is a substring of "claude-opus-4-8[1m]", so scanning
// the object as written would resolve an Opus 4.8 run to the Opus 5 shorthand
// (and, once their prices diverge, bill it at the wrong rate). Longest-first
// makes the most specific alias win regardless of where it was declared.
const MODEL_ALIASES_BY_SPECIFICITY = Object.entries(MODEL_ALIASES)
    .sort((a, b) => b[0].length - a[0].length);

// Map a raw `agentType` (BENCH_AGENT_TYPE, incl. the harness's own aliases
// cli/binary -> gemini) to a curated harness id.
/** @type {Record<string, string>} */
export const HARNESS_ALIASES = {
    "gemini": "gemini-cli",
    "gemini-cli": "gemini-cli",
    "cli": "gemini-cli",
    "binary": "gemini-cli",
    "claude": "claude-code",
    "claude-code": "claude-code",
    "openclaw": "openclaw",
    "claw": "openclaw",
    "kubeagents": "kubeagents",
    "kube-agents": "kubeagents",
    "api": "api-loop",
    "api-loop": "api-loop",
    "antigravity": "antigravity"
};

// --- presentation ------------------------------------------------------------

// A stable palette of line/bar colors for setups. The derive step cycles
// through this list in order of appearance (so the first setup seen is blue,
// second is purple, etc.), giving every setup a distinguishable color in charts.
export const SETUP_PALETTE = [
    "#3b82f6", // blue
    "#8b5cf6", // purple
    "#ec4899", // pink
    "#f59e0b", // amber
    "#10b981", // emerald
    "#06b6d4", // cyan
    "#6366f1", // indigo
    "#f97316"  // orange
];

// --- helpers -----------------------------------------------------------------

/**
 * Turn an arbitrary raw string into a safe, predictable collection id.
 * Lowercases, replaces non-alphanumerics with hyphens, trims hyphens.
 */
export function slugify(str) {
    if (!str) return "unknown";
    return String(str)
        .toLowerCase()
        .trim()
        .replace(/[^a-z0-9]+/g, "-")
        .replace(/^-+|-+$/g, "") || "unknown";
}

/**
 * Clean a raw model string: strip whitespace, unquote, lowercase for lookup.
 */
function clean(str) {
    if (!str) return "";
    return String(str)
        .trim()
        .replace(/^["']|["']$/g, "")
        .toLowerCase();
}

/**
 * Title-case a slug for fallback display names: "gemini-2-5-pro" -> "Gemini 2 5 Pro".
 */
function humanize(slug) {
    return slug
        .split("-")
        .map(w => w.charAt(0).toUpperCase() + w.slice(1))
        .join(" ");
}

// --- resolvers ---------------------------------------------------------------

/**
 * Resolve a raw `agentModel` string (from metadata or run config) into a curated
 * model key and its metadata record.
 *
 * Matching order:
 *   1. Exact match against MODEL_ALIASES (case-insensitive).
 *   2. Substring match: find the first alias contained in the raw string.
 *      Allows "claude-opus-4-8-20260101" -> "claude-opus-4-8".
 *   3. Fallback: slugify the raw string, synthesize a minimal Model record,
 *      and mark `known: false` so ingest can log a warning.
 *
 * @param {string} raw
 * @returns {{ key: string, model: {name: string, provider: string, license: string, logo: string}, known: boolean }}
 */
export function resolveModel(raw) {
    const c = clean(raw);
    if (!c) {
        return {
            key: "unknown-model",
            model: { name: "Unknown Model", provider: "Unknown", license: "Proprietary", logo: "alpha" },
            known: false
        };
    }

    // 1. Exact alias match
    if (MODEL_ALIASES[c]) {
        const key = MODEL_ALIASES[c];
        return { key, model: { ...MODELS[key] }, known: true };
    }

    // 2. Substring match (most specific alias wins)
    for (const [alias, key] of MODEL_ALIASES_BY_SPECIFICITY) {
        if (c.includes(alias)) {
            return { key, model: { ...MODELS[key] }, known: true };
        }
    }

    // 3. Fallback: synthesize
    const key = slugify(raw);
    return {
        key,
        model: {
            name: humanize(key),
            provider: "Unknown",
            license: "Proprietary",
            logo: "alpha"
        },
        known: false
    };
}

/**
 * Resolve a raw `agentType` string (from metadata or run config) into a curated
 * harness key and its metadata record.
 *
 * Matching order:
 *   1. Exact alias match against HARNESS_ALIASES (case-insensitive).
 *   2. Substring match: find the first alias contained in the raw string.
 *      Allows "agent-runner-cli" -> "gemini-cli".
 *   3. Fallback: slugify the raw string, synthesize a minimal Harness record,
 *      and mark `known: false`.
 *
 * @param {string} raw
 * @returns {{ key: string, harness: {name: string, type: "cli"|"api", accent: string, logo: string}, known: boolean }}
 */
export function resolveHarness(raw) {
    const c = clean(raw);
    if (!c) {
        return {
            key: "unknown-harness",
            harness: { name: "Unknown Harness", type: "cli", accent: "#64748b", logo: "terminal" },
            known: false
        };
    }

    // 1. Exact match
    if (HARNESS_ALIASES[c]) {
        const key = HARNESS_ALIASES[c];
        return { key, harness: { ...HARNESSES[key] }, known: true };
    }

    // 2. Substring match
    for (const [alias, key] of Object.entries(HARNESS_ALIASES)) {
        if (c.includes(alias)) {
            return { key, harness: { ...HARNESSES[key] }, known: true };
        }
    }

    // 3. Fallback: synthesize
    const key = slugify(raw);
    return {
        key,
        harness: {
            name: humanize(key),
            type: "cli",
            accent: "#64748b",
            logo: "terminal"
        },
        known: false
    };
}
