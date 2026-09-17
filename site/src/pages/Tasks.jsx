// Tasks catalog page — Table view matching the Leaderboard design scheme:
// Container with rounded-2xl border, header banner, search/filter controls,
// and a clean per-task table where each row is clickable to /task/:taskName.

import { useState, useMemo } from "react";
import { Link } from "react-router-dom";
import curatedData from "../data/curated_tasks.json";
import { getTaskGithubUrl } from "../lib/taskGithub.js";

export function Tasks() {
    const [search, setSearch] = useState("");
    const [selectedCategory, setSelectedCategory] = useState("all");

    const allTasks = useMemo(() => {
        const list = Object.values(curatedData.tasks || {});
        return list.sort((a, b) => a.name.localeCompare(b.name));
    }, []);

    const categories = useMemo(() => {
        const set = new Set();
        for (const t of allTasks) {
            if (t.category) set.add(t.category);
        }
        return Array.from(set).sort();
    }, [allTasks]);

    const filteredTasks = useMemo(() => {
        const query = search.trim().toLowerCase();
        return allTasks.filter(task => {
            if (selectedCategory !== "all" && task.category !== selectedCategory) {
                return false;
            }
            if (!query) return true;
            return (
                (task.name && task.name.toLowerCase().includes(query)) ||
                (task.category && task.category.toLowerCase().includes(query)) ||
                (task.prompt && task.prompt.toLowerCase().includes(query))
            );
        });
    }, [allTasks, search, selectedCategory]);

    return (
        <main className="w-full max-w-6xl flex flex-col items-center gap-8">
            <div className="w-full bg-white dark:bg-slate-900 rounded-2xl border border-slate-200/80 dark:border-slate-800 shadow-xl shadow-slate-100 dark:shadow-none overflow-hidden">
                {/* Header banner — identical styling to Leaderboard header */}
                <header className="px-6 pt-6 pb-5 border-b border-slate-100 dark:border-slate-800 bg-slate-50/50 dark:bg-slate-800/30">
                    <h1 className="text-sm font-semibold text-slate-500 dark:text-slate-400 flex items-center gap-2 uppercase tracking-wider">
                        <svg className="w-4 h-4 text-indigo-500 dark:text-indigo-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-6 9l2 2 4-4" />
                        </svg>
                        DevOps Bench Tasks
                    </h1>
                    <p className="text-xs text-slate-500 dark:text-slate-400 mt-1">
                        Browse all {allTasks.length} benchmark tasks — scenario instructions, infrastructure specs, objective rubrics, and safeguards.
                    </p>
                </header>

                {/* Filter & search bar */}
                <div className="px-6 py-4 bg-white dark:bg-slate-900 border-b border-slate-100 dark:border-slate-800 flex flex-wrap items-center justify-between gap-4">
                    <div className="flex flex-wrap items-center gap-3 flex-1 max-w-xl">
                        <div className="relative flex-1 min-w-[240px]">
                            <input
                                type="text"
                                value={search}
                                onChange={e => setSearch(e.target.value)}
                                placeholder="Filter tasks by name, category…"
                                className="w-full px-3 py-1.5 text-xs rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-800 dark:text-slate-200 placeholder:text-slate-400 focus:outline-none focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-500"
                            />
                            {search && (
                                <button
                                    type="button"
                                    onClick={() => setSearch("")}
                                    className="absolute right-2.5 top-1.5 text-xs text-slate-400 hover:text-slate-600 dark:hover:text-slate-200"
                                >
                                    ✕
                                </button>
                            )}
                        </div>
                        <div className="flex items-center gap-1.5">
                            <span className="text-[10px] font-semibold text-slate-400 uppercase tracking-wider">Category:</span>
                            <select
                                value={selectedCategory}
                                onChange={e => setSelectedCategory(e.target.value)}
                                className="px-2.5 py-1.5 text-xs rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-700 dark:text-slate-300 focus:outline-none focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-500"
                            >
                                <option value="all">All ({allTasks.length})</option>
                                {categories.map(cat => (
                                    <option key={cat} value={cat}>
                                        {cat}
                                    </option>
                                ))}
                            </select>
                        </div>
                    </div>
                    <div className="text-xs font-mono text-slate-500 dark:text-slate-400">
                        {filteredTasks.length} of {allTasks.length} tasks
                    </div>
                </div>

                {/* Table column headers */}
                <div className="px-6 py-3 bg-white dark:bg-slate-900 border-b border-slate-100 dark:border-slate-800 hidden sm:grid grid-cols-12 gap-4 items-center font-semibold text-xs tracking-wider text-slate-500 dark:text-slate-400 select-none uppercase">
                    <div className="col-span-6">TASK</div>
                    <div className="col-span-2">CATEGORY</div>
                    <div className="col-span-2">RUBRIC CHECKS</div>
                    <div className="col-span-2 text-right">ENVIRONMENT</div>
                </div>

                {/* Table rows */}
                {filteredTasks.length === 0 ? (
                    <div className="px-6 py-12 text-center text-slate-400 text-xs font-mono">
                        No tasks match the filter &ldquo;{search}&rdquo;.
                    </div>
                ) : (
                    <div className="divide-y divide-slate-100 dark:divide-slate-800">
                        {filteredTasks.map(task => (
                            <Link
                                key={task.name}
                                to={`/task/${task.name}`}
                                className="px-6 py-4 flex flex-col sm:grid sm:grid-cols-12 gap-3 sm:gap-4 items-start sm:items-center hover:bg-slate-50/70 dark:hover:bg-slate-800/40 cursor-pointer transition-colors group select-none"
                            >
                                {/* Task name */}
                                <div className="col-span-6 flex items-center pr-4">
                                    <span className="font-semibold text-slate-900 dark:text-slate-100 text-sm font-mono group-hover:text-indigo-600 dark:group-hover:text-indigo-400 transition-colors">
                                        {task.name}
                                    </span>
                                    {getTaskGithubUrl(task.name) && (
                                        <span
                                            title="Source available on GitHub"
                                            className="ml-2.5 inline-flex items-center gap-1 text-[10px] font-mono px-1.5 py-0.5 rounded bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-400 border border-slate-200/60 dark:border-slate-700/60"
                                        >
                                            <svg className="w-2.5 h-2.5 fill-current" viewBox="0 0 24 24">
                                                <path fillRule="evenodd" clipRule="evenodd" d="M12 2C6.477 2 2 6.484 2 12.017c0 4.425 2.865 8.18 6.839 9.504.5.092.682-.217.682-.483 0-.237-.008-.868-.013-1.703-2.782.605-3.369-1.343-3.369-1.343-.454-1.158-1.11-1.466-1.11-1.466-.908-.62.069-.608.069-.608 1.003.07 1.53 1.032 1.53 1.032.892 1.53 2.341 1.088 2.91.832.092-.647.35-1.088.636-1.338-2.22-.253-4.555-1.113-4.555-4.951 0-1.093.39-1.988 1.029-2.688-.103-.253-.446-1.272.098-2.65 0 0 .84-.27 2.75 1.026A9.564 9.564 0 0112 6.844c.85.004 1.705.115 2.504.337 1.909-1.296 2.747-1.027 2.747-1.027.546 1.379.202 2.398.1 2.651.64.7 1.028 1.595 1.028 2.688 0 3.848-2.339 4.695-4.566 4.943.359.309.678.92.678 1.855 0 1.338-.012 2.419-.012 2.747 0 .268.18.58.688.482A10.019 10.019 0 0022 12.017C22 6.484 17.522 2 12 2z" />
                                            </svg>
                                            GitHub
                                        </span>
                                    )}
                                </div>

                                {/* Category badge */}
                                <div className="col-span-2">
                                    <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-semibold bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-300">
                                        {task.category || "General"}
                                    </span>
                                </div>

                                {/* Checks summary */}
                                <div className="col-span-2 flex flex-col gap-0.5 text-xs font-mono text-slate-600 dark:text-slate-300">
                                    <span>{task.objectives?.length || 0} objectives</span>
                                    <span className="text-[11px] text-slate-400 dark:text-slate-500">
                                        {(task.catastrophic?.length || 0) + (task.recoverable?.length || 0)} safeguards
                                    </span>
                                </div>

                                {/* Environment */}
                                <div className="col-span-2 text-right">
                                    <span className="inline-flex items-center px-2 py-0.5 rounded text-[11px] font-mono bg-indigo-50 dark:bg-indigo-950/40 text-indigo-700 dark:text-indigo-300 border border-indigo-200/60 dark:border-indigo-800/50">
                                        {task.environment?.type || "Kubernetes"}
                                    </span>
                                </div>
                            </Link>
                        ))}
                    </div>
                )}
            </div>
        </main>
    );
}
