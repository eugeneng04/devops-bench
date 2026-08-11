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
from collections import defaultdict
from pathlib import Path
from typing import Any

# Below this, a per-task failure rate is noise rather than a signal.
MIN_RUNS_FOR_RATE = 20


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


def scope(events: list[dict], catalog: set[str]) -> dict[str, Any]:
    """Every figure the dashboard draws, over one slice of the event stream."""
    daily = [
        {"date": date, "runs": len(day), "installs": len({e["userUuid"] for e in day})}
        for date, day in sorted(group(events, lambda e: e["t"][:10]).items())
    ]

    by_task = []
    for (folder, name), rows in group(events, lambda e: (e["taskFolder"], e["taskName"])).items():
        summary = summarize(rows)
        by_task.append(
            {
                "task": f"{folder}/{name}",
                "name": name,
                "folder": folder,
                "inCatalog": f"{folder}/{name}" in catalog,
                # A rate over a handful of runs swings wildly; the dashboard
                # ranks on it, so suppress it rather than rank on noise.
                "rateIsStable": summary["runs"] >= MIN_RUNS_FOR_RATE,
                **summary,
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
    overall = summarize(events)

    return {
        "totals": {
            **overall,
            "localTaskRuns": sum(t["runs"] for t in local),
            "localTaskNames": len(local),
            "localTaskShare": ratio(sum(t["runs"] for t in local), overall["runs"]),
            "catalogCoverage": ratio(
                len({t["task"] for t in by_task if t["inCatalog"]}), len(catalog)
            ),
        },
        "daily": daily,
        "byTask": by_task,
        "byModel": by_model,
        "fanout": fanout,
        "consentSource": consent,
        "clientVersion": versions,
    }


def aggregate(stream: dict) -> dict[str, Any]:
    """Pre-slice by harness. The browser filters by picking a scope rather than
    re-aggregating, so the page never has to carry the raw event stream."""
    events = stream["events"]
    catalog = set(stream["catalog"])
    by_harness = group(events, lambda e: e["harness"])

    return {
        "apiVersion": "devops-bench.k8s.io/v1alpha1",
        "kind": "TelemetryReport",
        "synthetic": stream.get("synthetic", False),
        "generatedAt": stream["generatedAt"],
        "windowDays": stream["windowDays"],
        "catalogSize": len(catalog),
        "minRunsForRate": MIN_RUNS_FOR_RATE,
        "harnessSummary": sorted(
            ({"harness": h, **summarize(rows)} for h, rows in by_harness.items()),
            key=lambda h: -h["runs"],
        ),
        "scopes": {
            "all": scope(events, catalog),
            **{h: scope(rows, catalog) for h, rows in by_harness.items()},
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stream", type=Path, help="event stream JSON from simulate.py")
    parser.add_argument("--out", type=Path, default=Path("-"))
    args = parser.parse_args()

    report = aggregate(json.loads(args.stream.read_text()))
    text = json.dumps(report, indent=2) + "\n"
    if str(args.out) == "-":
        sys.stdout.write(text)
    else:
        args.out.write_text(text)
        print(args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
