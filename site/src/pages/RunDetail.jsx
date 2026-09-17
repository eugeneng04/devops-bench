// Page 2 — Run Detail
// Renders one run for a task × harness: telemetry header,
// Objectives/Safeguards with results & observed reasons, and score arithmetic.

import { useParams, Link } from "react-router-dom";
import curatedData from "../data/curated_tasks.json";
import { AssertsRenderer } from "../components/AssertsRenderer.jsx";
import { NotFound } from "../components/States.jsx";

export function RunDetail() {
    const { taskName, setupId } = useParams();

    const task = curatedData.tasks?.[taskName];
    if (!task) {
        return (
            <NotFound
                message={`Task "${taskName}" was not found in the curated benchmark dataset.`}
                backText="Back to Leaderboard"
            />
        );
    }

    // Match run either by setupId or arm
    const run = task.runs?.[setupId] || Object.values(task.runs || {}).find(r => r.setupId === setupId || r.arm === setupId);

    if (!run) {
        return (
            <NotFound
                message={`Run "${setupId}" for task "${taskName}" was not found.`}
                backText={`Back to Task ${taskName}`}
                backLink={`/task/${taskName}`}
            />
        );
    }

    const { model, harness, durationSec, tokens, toolCalls, checks, scores, arithmetic } = run;

    const objectives = checks.filter(c => c.role === "objective");
    const catastrophic = checks.filter(c => c.severity === "catastrophic");
    const recoverable = checks.filter(c => c.role === "safeguard" && c.severity !== "catastrophic");

    function renderCheckTable(title, checkList, isCatastrophic = false) {
        if (!checkList || checkList.length === 0) return null;

        const tableBorder = isCatastrophic
            ? "border-rose-200/70 dark:border-rose-950/40 bg-white dark:bg-slate-900"
            : "border-slate-200/80 dark:border-slate-800 bg-white dark:bg-slate-900";

        return (
            <div className={`rounded-2xl border ${tableBorder} shadow-sm p-6`}>
                <div className="flex items-center justify-between mb-4">
                    <h2 className={`text-sm font-bold uppercase tracking-wider ${
                        isCatastrophic ? "text-rose-800 dark:text-rose-300" : "text-slate-700 dark:text-slate-200"
                    }`}>
                        {title}
                    </h2>
                    <span className="text-xs font-mono text-slate-400 dark:text-slate-500">
                        {checkList.length} checks
                    </span>
                </div>
                <div className="overflow-x-auto">
                    <table className="w-full text-left border-collapse">
                        <thead>
                            <tr className="border-b border-slate-200 dark:border-slate-800 text-[10px] font-semibold uppercase tracking-wider text-slate-400 dark:text-slate-500">
                                <th className="pb-2.5 pr-4 w-1/5">Check</th>
                                <th className="pb-2.5 pr-4 w-1/3">Asserts</th>
                                <th className="pb-2.5 pr-4 w-20 text-center">Result</th>
                                <th className="pb-2.5 w-2/5">Observed</th>
                            </tr>
                        </thead>
                        <tbody className="divide-y divide-slate-100 dark:divide-slate-800 text-xs">
                            {checkList.map(c => {
                                const isPass = c.status === "pass";
                                const isFail = c.status === "fail";
                                const isErr = c.status === "error";

                                return (
                                    <tr key={c.name} className="hover:bg-slate-50/50 dark:hover:bg-slate-800/20">
                                        <td className="py-3 pr-4 align-top">
                                            <span className="font-semibold text-slate-900 dark:text-slate-100 block">
                                                {c.name}
                                            </span>
                                            <span className="text-[10px] text-slate-400 dark:text-slate-500 font-mono">
                                                {c.mode} {c.weight ? `· ${c.weight} pts` : ""}
                                            </span>
                                        </td>
                                        <td className="py-3 pr-4 align-top">
                                            <AssertsRenderer asserts={c.asserts} />
                                        </td>
                                        <td className="py-3 pr-4 align-top text-center">
                                            <span
                                                className={`inline-flex items-center px-2 py-0.5 rounded font-mono text-xs font-bold ${
                                                    isPass
                                                        ? "bg-emerald-50 dark:bg-emerald-950/60 text-emerald-700 dark:text-emerald-300 border border-emerald-200 dark:border-emerald-800/60"
                                                        : isFail
                                                        ? "bg-rose-50 dark:bg-rose-950/60 text-rose-700 dark:text-rose-300 border border-rose-200 dark:border-rose-800/60"
                                                        : isErr
                                                        ? "bg-amber-50 dark:bg-amber-950/60 text-amber-700 dark:text-amber-300 border border-amber-200 dark:border-amber-800/60"
                                                        : "text-slate-400"
                                                }`}
                                            >
                                                {isPass ? "PASS" : isFail ? "FAIL" : isErr ? "ERROR" : "–"}
                                            </span>
                                        </td>
                                        <td className="py-3 align-top font-mono text-[11px] text-slate-700 dark:text-slate-300 break-words leading-relaxed">
                                            {c.observed ? (
                                                <div className="bg-slate-50 dark:bg-slate-950/70 p-2 rounded-lg border border-slate-100 dark:border-slate-800/80">
                                                    {c.observed}
                                                </div>
                                            ) : (
                                                <span className="text-slate-400 dark:text-slate-500">—</span>
                                            )}
                                        </td>
                                    </tr>
                                );
                            })}
                        </tbody>
                    </table>
                </div>
            </div>
        );
    }

    return (
        <div className="w-full max-w-7xl flex flex-col gap-8 pb-16">
            {/* Breadcrumb & Header */}
            <div>
                <div className="flex items-center gap-2 mb-3 text-xs font-semibold">
                    <Link
                        to="/"
                        className="text-slate-500 hover:text-slate-700 dark:text-slate-400 dark:hover:text-slate-200 transition-colors"
                    >
                        Leaderboard
                    </Link>
                    <span className="text-slate-300 dark:text-slate-600">/</span>
                    <Link
                        to={`/task/${taskName}`}
                        className="text-indigo-600 hover:text-indigo-700 dark:text-indigo-400 dark:hover:text-indigo-300 transition-colors"
                    >
                        {taskName}
                    </Link>
                    <span className="text-slate-300 dark:text-slate-600">/</span>
                    <span className="text-slate-700 dark:text-slate-300 font-mono">{run.arm}</span>
                </div>

                <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-4 border-b border-slate-200 dark:border-slate-800 pb-5">
                    <div>
                        <div className="flex items-center gap-3">
                            <h1 className="text-2xl sm:text-3xl font-bold tracking-tight text-slate-900 dark:text-slate-50 font-mono">
                                {taskName}
                            </h1>
                            <span className="px-2.5 py-1 rounded-lg text-xs font-semibold bg-indigo-50 dark:bg-indigo-950/60 text-indigo-700 dark:text-indigo-300 border border-indigo-200 dark:border-indigo-800">
                                {harness} · {model}
                            </span>
                        </div>
                        <p className="mt-1 text-xs text-slate-500 dark:text-slate-400 font-mono">
                            Arm: {run.arm} · Setup: {run.setupId}
                        </p>
                    </div>

                    {/* Telemetry Stat Pills */}
                    <div className="flex flex-wrap items-center gap-2 font-mono text-xs">
                        <div className="bg-white dark:bg-slate-900 px-3 py-2 rounded-xl border border-slate-200/80 dark:border-slate-800 shadow-sm flex flex-col">
                            <span className="text-[10px] text-slate-400 uppercase font-semibold">Latency</span>
                            <span className="font-bold text-slate-800 dark:text-slate-200">
                                {durationSec ? `${Number(durationSec).toFixed(1)}s` : "—"}
                            </span>
                        </div>
                        <div className="bg-white dark:bg-slate-900 px-3 py-2 rounded-xl border border-slate-200/80 dark:border-slate-800 shadow-sm flex flex-col">
                            <span className="text-[10px] text-slate-400 uppercase font-semibold">Tokens</span>
                            <span className="font-bold text-slate-800 dark:text-slate-200" title={`In: ${tokens.input.toLocaleString()} | Out: ${tokens.output.toLocaleString()} | Cached: ${tokens.cached.toLocaleString()}`}>
                                {tokens.total ? `${tokens.total.toLocaleString()}` : "—"}
                            </span>
                        </div>
                        <div className="bg-white dark:bg-slate-900 px-3 py-2 rounded-xl border border-slate-200/80 dark:border-slate-800 shadow-sm flex flex-col">
                            <span className="text-[10px] text-slate-400 uppercase font-semibold">Tool Calls</span>
                            <span className="font-bold text-slate-800 dark:text-slate-200">
                                {toolCalls || 0}
                            </span>
                        </div>
                        <div className={`px-4 py-2 rounded-xl border shadow-sm flex flex-col ${
                            scores.catastrophic
                                ? "bg-rose-50 dark:bg-rose-950/40 border-rose-200 dark:border-rose-900/60"
                                : "bg-emerald-50 dark:bg-emerald-950/40 border-emerald-200 dark:border-emerald-900/60"
                        }`}>
                            <span className="text-[10px] uppercase font-semibold opacity-70">Outcome Score</span>
                            <span className="font-bold text-sm font-mono">
                                {scores.outcome != null ? `${Math.round(scores.outcome * 100)}%` : "—"}
                            </span>
                        </div>
                    </div>
                </div>
            </div>

            {/* Score Arithmetic Callout */}
            <div className={`rounded-2xl border p-5 ${
                scores.catastrophic
                    ? "bg-rose-50/50 dark:bg-rose-950/20 border-rose-200 dark:border-rose-900/60"
                    : "bg-slate-900 text-slate-100 border-slate-800 shadow-md"
            }`}>
                <div className="flex items-center justify-between mb-2">
                    <span className="text-xs font-bold uppercase tracking-wider opacity-80">
                        Score Arithmetic & Verdict
                    </span>
                    {scores.catastrophic && (
                        <span className="px-2 py-0.5 rounded text-[11px] font-bold bg-rose-500 text-white animate-pulse">
                            ⚠ CATASTROPHIC SAFEGUARD BREACHED
                        </span>
                    )}
                </div>
                <pre className="font-mono text-xs leading-relaxed overflow-x-auto whitespace-pre p-2 rounded-lg bg-black/20">
                    {arithmetic}
                </pre>
                <div className="mt-3 grid grid-cols-2 sm:grid-cols-3 gap-3 text-xs font-mono pt-2 border-t border-white/10">
                    <div>
                        <span className="opacity-60 block text-[10px]">Correctness (c):</span>
                        <span className="font-bold">{(scores.c ?? 0).toFixed(3)}</span>
                    </div>
                    <div>
                        <span className="opacity-60 block text-[10px]">Raw Safety Fraction:</span>
                        <span className="font-bold">{scores.raw_rec != null ? Number(scores.raw_rec).toFixed(3) : "1.000"}</span>
                    </div>
                    <div>
                        <span className="opacity-60 block text-[10px]">Rescaled Safety (rec_v):</span>
                        <span className="font-bold">{(scores.rec_v ?? 1.0).toFixed(3)}</span>
                    </div>
                </div>
            </div>

            {/* Tables 1-3 */}
            {renderCheckTable("Objectives", objectives)}
            {renderCheckTable("Catastrophic Safeguards", catastrophic, true)}
            {renderCheckTable("Recoverable Safeguards", recoverable)}
        </div>
    );
}
