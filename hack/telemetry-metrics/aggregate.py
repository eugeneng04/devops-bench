#!/usr/bin/env python3
# Copyright 2026 The Kubernetes Authors.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Aggregate a telemetry event stream into the dashboard payload.

Pure: no network, no clock. Kept separate from event collection so the
aggregation can be revised and re-run over every stream ever ingested.

Two rules the numbers obey:

  - A ratio with a zero denominator is null, not 0%. A task nobody ran has no
    failure rate.
  - Every figure is over opted-in installs only. The size of the population
    that did not opt in is unknowable by construction, so no figure here is
    ever presented as a share of all users.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from inventory import discover_harnesses, discover_tasks

# Below this, a per-task failure rate is noise rather than a signal.
MIN_RUNS_FOR_RATE = 20

# A rarely-run task can take a few days to show up at all, so "first seen after
# the window opened" on its own flags half the catalog as new. Only a first
# execution this far past the window start means the task did not exist before.
NEW_GRACE_DAYS = 7


def ratio(numerator: int, denominator: int) -> float | None:
    return None if denominator == 0 else numerator / denominator


def percentile(values: list[float], q: float) -> float | None:
    """Nearest-rank percentile. None for an empty sample."""
    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, min(len(ordered), int(round(q * len(ordered) + 0.5))))
    return ordered[rank - 1]


def group(events: list[dict], key) -> dict[Any, list[dict]]:
    out: dict[Any, list[dict]] = defaultdict(list)
    for e in events:
        out[key(e)].append(e)
    return out


def summarize(events: list[dict]) -> dict[str, Any]:
    latencies = [e["latencySec"] for e in events]
    failures = sum(1 for e in events if e["status"] != "success")
    return {
        "runs": len(events),
        "installs": len({e["userUuid"] for e in events}),
        "failures": failures,
        "failureRate": ratio(failures, len(events)),
        "p50LatencySec": percentile(latencies, 0.50),
        "p95LatencySec": percentile(latencies, 0.95),
        "inputTokens": sum(e["inputTokens"] for e in events),
        "outputTokens": sum(e["outputTokens"] for e in events),
        "turns": sum(e["turnCount"] for e in events),
    }


def new_threshold(window_start: str) -> str:
    """First-seen dates after this are genuinely new, not just slow to appear."""
    return (date.fromisoformat(window_start) + timedelta(days=NEW_GRACE_DAYS)).isoformat()


def daily_runs(events: list[dict], start: str, end: str) -> list[dict]:
    """Zero-filled executions per day. A day with no runs is a measured zero, so
    it has to be a point on the line rather than a missing one."""
    counts = Counter(e["t"][:10] for e in events)
    first, last = date.fromisoformat(start), date.fromisoformat(end)
    out = []
    for i in range((last - first).days + 1):
        day = (first + timedelta(days=i)).isoformat()
        out.append({"date": day, "runs": counts[day]})
    return out


def scope(events: list[dict], catalog: set[str], window_start: str) -> dict[str, Any]:
    """Every figure the dashboard draws, over one slice of the event stream."""
    daily = [
        {"date": date, "runs": len(day), "installs": len({e["userUuid"] for e in day})}
        for date, day in sorted(group(events, lambda e: e["t"][:10]).items())
    ]

    by_task = []
    for (folder, name), rows in group(events, lambda e: (e["taskFolder"], e["taskName"])).items():
        summary = summarize(rows)
        first_seen = min(e["t"][:10] for e in rows)
        by_task.append(
            {
                "task": f"{folder}/{name}",
                "name": name,
                "folder": folder,
                "inCatalog": f"{folder}/{name}" in catalog,
                "firstSeen": first_seen,
                # A rate over a handful of runs swings wildly; the dashboard
                # ranks on it, so suppress it rather than rank on noise.
                "rateIsStable": summary["runs"] >= MIN_RUNS_FOR_RATE,
                **summary,
            }
        )
    # A catalog task nobody ran is a measured zero. Omitting it makes it look
    # like it does not exist, when what it means is that nobody uses it.
    executed = {t["task"] for t in by_task}
    for task in sorted(catalog - executed):
        folder, _, name = task.partition("/")
        by_task.append(
            {
                "task": task, "name": name, "folder": folder,
                "inCatalog": True, "firstSeen": None,
                "rateIsStable": False, "runs": 0, "installs": 0, "failures": 0,
                "failureRate": None, "p50LatencySec": None, "p95LatencySec": None,
                "inputTokens": 0, "outputTokens": 0, "turns": 0,
            }
        )
    by_task.sort(key=lambda t: -t["runs"])

    by_model = [
        {"model": m, **summarize(rows)}
        for m, rows in group(events, lambda e: e["model"]).items()
    ]
    by_model.sort(key=lambda m: -m["runs"])

    fanout = [
        {"parallel": n, "runs": len(rows)}
        for n, rows in sorted(group(events, lambda e: e["parallelExecutionCount"]).items())
    ]

    consent = {k: len({e["userUuid"] for e in rows})
               for k, rows in group(events, lambda e: e["consentSource"]).items()}
    versions = {k: len({e["userUuid"] for e in rows})
                for k, rows in group(events, lambda e: e["clientVersion"]).items()}

    local = [t for t in by_task if not t["inCatalog"]]
    never = [t for t in by_task if t["inCatalog"] and t["runs"] == 0]
    overall = summarize(events)

    return {
        "totals": {
            **overall,
            "localTaskRuns": sum(t["runs"] for t in local),
            "localTaskNames": len(local),
            "localTaskShare": ratio(sum(t["runs"] for t in local), overall["runs"]),
            "neverExecuted": len(never),
            "catalogCoverage": ratio(len(catalog) - len(never), len(catalog)),
        },
        "daily": daily,
        "byTask": by_task,
        "byModel": by_model,
        "fanout": fanout,
        "consentSource": consent,
        "clientVersion": versions,
    }


def aggregate(stream: dict, catalog: list[str], harnesses: list[str]) -> dict[str, Any]:
    """Pre-slice by harness. The browser filters by picking a scope rather than
    re-aggregating, so the page never has to carry the raw event stream."""
    events = stream["events"]
    catalog_set = set(catalog)
    by_harness = group(events, lambda e: e["harness"])
    window_start = min((e["t"][:10] for e in events), default="")
    window_end = max((e["t"][:10] for e in events), default="")

    harness_summary = [
        {
            "harness": h,
            "registered": h in harnesses,
            "firstSeen": min(e["t"][:10] for e in rows),
            "isNew": min(e["t"][:10] for e in rows) > new_threshold(window_start),
            **summarize(rows),
        }
        for h, rows in by_harness.items()
    ]
    # A registered harness nobody ran gets a row of zeros rather than vanishing.
    for h in sorted(set(harnesses) - set(by_harness)):
        harness_summary.append(
            {
                "harness": h, "registered": True, "firstSeen": None, "isNew": False,
                "runs": 0, "installs": 0, "failures": 0, "failureRate": None,
                "p50LatencySec": None, "p95LatencySec": None,
                "inputTokens": 0, "outputTokens": 0, "turns": 0,
            }
        )
    harness_summary.sort(key=lambda h: -h["runs"])

    all_tasks = scope(events, catalog_set, window_start)["byTask"]
    threshold = new_threshold(window_start) if window_start else None
    drift = []
    for t in all_tasks:
        if not t["inCatalog"]:
            state = "outsideCatalog"
        elif t["runs"] == 0:
            state = "neverExecuted"
        elif threshold and t["firstSeen"] > threshold:
            state = "new"
        else:
            continue
        drift.append({**{k: t[k] for k in ("task", "firstSeen", "runs", "installs")}, "state": state})

    # Every task and harness that appeared after the window opened, with the
    # executions it has accumulated since. The dashboard narrows this to a
    # reader-chosen lookback; the grace period is the floor it cannot go below.
    adoption = []
    for t in all_tasks:
        if t["inCatalog"] and t["firstSeen"] and threshold and t["firstSeen"] > threshold:
            rows = [e for e in events if f"{e['taskFolder']}/{e['taskName']}" == t["task"]]
            adoption.append(
                {
                    "kind": "task", "id": t["task"], "firstSeen": t["firstSeen"],
                    "runs": t["runs"], "installs": t["installs"],
                    "daily": daily_runs(rows, t["firstSeen"], window_end),
                }
            )
    for h in harness_summary:
        if h["isNew"]:
            adoption.append(
                {
                    "kind": "harness", "id": h["harness"], "firstSeen": h["firstSeen"],
                    "runs": h["runs"], "installs": h["installs"],
                    "daily": daily_runs(by_harness[h["harness"]], h["firstSeen"], window_end),
                }
            )
    adoption.sort(key=lambda a: -a["runs"])

    return {
        "apiVersion": "devops-bench.k8s.io/v1alpha1",
        "kind": "TelemetryReport",
        "synthetic": stream.get("synthetic", False),
        "generatedAt": stream["generatedAt"],
        "windowDays": stream["windowDays"],
        "windowStart": window_start,
        "windowEnd": window_end,
        "newSince": new_threshold(window_start) if window_start else None,
        "catalogSize": len(catalog_set),
        "minRunsForRate": MIN_RUNS_FOR_RATE,
        "harnessSummary": harness_summary,
        # Drift describes the catalog, so it is computed once over every event
        # rather than per harness. Scoping it would make a task look new merely
        # because the harness filtering it is itself new.
        "drift": drift,
        "adoption": adoption,
        "scopes": {
            "all": scope(events, catalog_set, window_start),
            **{h: scope(rows, catalog_set, window_start) for h, rows in by_harness.items()},
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stream", type=Path, help="event stream JSON from simulate.py")
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parents[2],
        help="repository to read the task catalog and harness registry from",
    )
    parser.add_argument("--out", type=Path, default=Path("-"))
    args = parser.parse_args()

    report = aggregate(
        json.loads(args.stream.read_text()),
        discover_tasks(args.repo_root),
        discover_harnesses(args.repo_root),
    )
    text = json.dumps(report, indent=2) + "\n"
    if str(args.out) == "-":
        sys.stdout.write(text)
    else:
        args.out.write_text(text)
        print(args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
