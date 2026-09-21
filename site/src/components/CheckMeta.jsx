import { Link } from "react-router-dom";

export function modeTooltip(mode) {
    if (mode === "converge") return "Converge: polled repeatedly until true within timeout budget";
    if (mode === "assert") return "Assert: evaluated once instantaneously at the end of the run";
    if (mode === "hold") return "Hold: sampled continuously in background — must stay true throughout";
    if (mode === "judge") return "Judge: evaluated by LLM judge against prompt criteria";
    if (mode === "audit") return "Audit: deterministic scan of shell commands and tool calls";
    return mode;
}

export function CheckMeta({ id, role, group, mode, weight, isCatastrophic = false }) {
    const pillBase = isCatastrophic
        ? "bg-rose-50/70 dark:bg-rose-950/40 text-rose-700 dark:text-rose-300 border border-rose-200/50 dark:border-rose-900/40"
        : "bg-slate-100/80 dark:bg-slate-800/70 text-slate-600 dark:text-slate-300 border border-slate-200/40 dark:border-slate-700/50";

    const keyLabel = isCatastrophic
        ? "text-rose-400 dark:text-rose-500 font-medium"
        : "text-slate-400 dark:text-slate-500 font-medium";

    const hasAny = id || role || group || mode || (weight != null && weight !== "");
    if (!hasAny) return null;

    return (
        <div className="flex flex-wrap items-center gap-1.5 mt-1 font-mono text-[10px]">
            {id && (
                <span className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded ${pillBase}`}>
                    <span className={keyLabel}>id:</span>
                    <span>{id}</span>
                </span>
            )}
            {role && (
                <span className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded ${pillBase}`}>
                    <span className={keyLabel}>role:</span>
                    <span>{role}</span>
                </span>
            )}
            {mode && (
                <span className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded ${pillBase}`}>
                    <span className={keyLabel}>mode:</span>
                    <Link
                        to="/methodology#modes"
                        className="hover:text-indigo-600 dark:hover:text-indigo-400 underline decoration-dotted underline-offset-2 cursor-help"
                        title={modeTooltip(mode)}
                    >
                        {mode}
                    </Link>
                </span>
            )}
            {weight != null && weight !== "" && (
                <span className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded ${pillBase}`}>
                    <span className={keyLabel}>weight:</span>
                    <span>{typeof weight === "number" ? `${weight} pts` : weight}</span>
                </span>
            )}
            {group && (
                <span className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded ${pillBase}`}>
                    <span className={keyLabel}>group:</span>
                    <span>{group}</span>
                </span>
            )}
        </div>
    );
}
