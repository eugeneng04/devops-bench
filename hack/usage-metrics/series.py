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
"""Walk every classified record ever stored into one time series.

Pure functions over stored records: no network. This is the program that makes
keeping every snapshot worth anything, and it is also the only one that reads
more than one.

Two kinds of number live here and they must never be mixed:

  A **run point** is what one collection saw on the day it ran - fork counts,
  branch counts, ratios, and GitHub's own fourteen-day traffic totals. Runs are
  irregular, so these are discrete points on a date axis. Nothing is
  interpolated between them and no run figure is ever added to another.

  A **daily point** is one day of traffic. Consecutive runs overlap by design,
  so their fourteen-day arrays stitch into a continuous history far longer than
  the fourteen days GitHub retains. This is the one figure that genuinely
  accumulates.

Unique visitors are the trap. GitHub deduplicates within whatever window it is
asked about, so fourteen daily uniques do not sum to the window figure - 89
against a reported 37, measured. Daily uniques stitch into a line because each
is a distinct question about a distinct day; window uniques stay discrete.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import classify
from store import SERIES_FORMAT, FormatError, open_store, provenance

TRAFFIC_KINDS = (("views", "views", "uniqueVisitors"), ("clones", "clones", "uniqueCloners"))


def covered_window(collected_at: str, window_days: int) -> tuple[date, date]:
    """The days a run's traffic arrays actually speak for.

    Measured across observations: the window runs from day -N through day -1 in
    UTC and today is absent entirely. Deriving this from the array's own first
    and last entry instead would be wrong in the case that matters - GitHub
    omits a day with no traffic from the array, so a quiet day at either edge
    would shrink the window and turn a real zero into a gap.
    """
    day = date.fromisoformat(collected_at[:10])
    return day - timedelta(days=window_days), day - timedelta(days=1)


def merge_ranges(ranges: list[tuple[date, date]]) -> list[tuple[date, date]]:
    """Collapse overlapping or touching windows into the days actually covered."""
    merged: list[list[date]] = []
    for start, end in sorted(ranges):
        if merged and start <= merged[-1][1] + timedelta(days=1):
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return [(s, e) for s, e in merged]


def daily_traffic(records: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Stitch every run's fourteen-day arrays into one history per repository.

    A later run wins for a day two runs both saw. The figures agree in practice
    once a day is over, and preferring the newer one is the rule that stays
    right if they ever do not.

    Absent from the array is zero **only inside a window some run covered**.
    Outside every window it is a gap, and the difference is the whole point: a
    fortnight nobody ran must not render as a fortnight of no visitors.
    """
    windows: dict[str, list[tuple[date, date]]] = {}
    values: dict[str, dict[date, dict[str, int]]] = {}

    for run_date in sorted(records):
        record = records[run_date]
        window_days = record["windowDays"]
        for name, repo in record["repos"].items():
            traffic = repo.get("traffic")
            if not traffic:
                continue
            windows.setdefault(name, []).append(
                covered_window(record["collectedAt"], window_days)
            )
            by_day = values.setdefault(name, {})
            for key, total_field, unique_field in TRAFFIC_KINDS:
                for entry in traffic[key]["daily"]:
                    day = by_day.setdefault(date.fromisoformat(entry["date"][:10]), {})
                    day[total_field] = entry["total"]
                    day[unique_field] = entry["unique"]

    out: dict[str, Any] = {}
    for name, ranges in windows.items():
        covered = merge_ranges(ranges)
        by_day = values.get(name, {})
        points = []
        for start, end in covered:
            day = start
            while day <= end:
                seen = by_day.get(day, {})
                points.append(
                    {
                        "date": day.isoformat(),
                        # Inside a covered window, a day GitHub did not list had
                        # no traffic. This is the only place a zero is written
                        # for something that was not measured as zero, and the
                        # covered ranges beside it are what justifies it.
                        "views": seen.get("views", 0),
                        "uniqueVisitors": seen.get("uniqueVisitors", 0),
                        "clones": seen.get("clones", 0),
                        "uniqueCloners": seen.get("uniqueCloners", 0),
                    }
                )
                day += timedelta(days=1)
        out[name] = {
            "covered": [[s.isoformat(), e.isoformat()] for s, e in covered],
            "gaps": [
                [
                    (covered[i][1] + timedelta(days=1)).isoformat(),
                    (covered[i + 1][0] - timedelta(days=1)).isoformat(),
                ]
                for i in range(len(covered) - 1)
            ],
            "points": points,
        }
    return out


def run_point(run_date: str, record: dict[str, Any]) -> dict[str, Any]:
    """One collection, as one point.

    Coverage travels with the point. A repository whose traffic starts working
    steps the series up for a reason that is instrumentation, not usage, and a
    chart that cannot see that renders it as growth.
    """
    traffic = {}
    for name, repo in record["repos"].items():
        value = repo.get("traffic")
        traffic[name] = (
            None
            if not value
            else {
                "views": value["views"]["total"],
                "uniqueVisitors": value["views"]["unique"],
                "clones": value["clones"]["total"],
                "uniqueCloners": value["clones"]["unique"],
            }
        )
    return {
        "date": run_date,
        "collectedAt": record["collectedAt"],
        "windowDays": record["windowDays"],
        "totals": record["totals"],
        "derived": record["derived"],
        "affiliation": record["affiliation"],
        "references": record["references"],
        "referencesUnavailable": record["referencesUnavailable"],
        # Window totals. Discrete points; never summed, never stitched.
        "traffic": traffic,
        "coverage": {
            "partial": record.get("snapshotPartial", False),
            "skipped": record.get("snapshotSkipped", []),
            "trafficRepos": record["totals"]["trafficRepos"],
            "forksUnavailable": sorted(
                name for name, r in record["repos"].items() if r.get("forksUnavailable")
            ),
        },
        "provenance": record.get("provenance"),
    }


def build(
    records: dict[str, dict[str, Any]], unreadable: dict[str, str] | None = None
) -> dict[str, Any]:
    return {
        "apiVersion": "usage-metrics/v1",
        "kind": "UsageSeries",
        "formatVersion": SERIES_FORMAT,
        "generatedAt": provenance()["writtenAt"],
        "provenance": provenance(),
        # A date this program could not read is a hole in the history and says
        # so. Dropping it leaves a chart that looks complete and is not.
        "unreadable": [
            {"date": d, "reason": r} for d, r in sorted((unreadable or {}).items())
        ],
        "runs": [run_point(d, records[d]) for d in sorted(records)],
        "daily": daily_traffic(records),
    }


def read_all(store: Any, kind: str) -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
    """Every record of one kind, and the reason for each one that would not read.

    One unreadable record must not cost the whole history. The first snapshot
    ever taken predates the format field, so a walk that raises on it can never
    get past the oldest date in the store - the failure is permanent and it
    lands on the walk, not on the record.
    """
    records: dict[str, dict[str, Any]] = {}
    unreadable: dict[str, str] = {}
    for run_date in store.list(kind):
        try:
            records[run_date] = store.get(kind, run_date)
        except (FormatError, ValueError, KeyError) as error:
            unreadable[run_date] = str(error)
    return records, unreadable


def reclassify(store: Any) -> tuple[list[str], dict[str, str]]:
    """Re-run the current taxonomy over every snapshot ever stored.

    The stated reason collect and classify are separate programs is that the
    taxonomy can be revised and re-applied to history. Until this existed that
    was a promise with no program behind it - classify.py takes exactly one file
    and nothing walked the directory.
    """
    snapshots, unreadable = read_all(store, "snapshot")
    written = []
    for run_date, snapshot in sorted(snapshots.items()):
        try:
            store.put("classified", run_date, classify.classify(snapshot))
        except (KeyError, TypeError) as error:
            unreadable[run_date] = f"classification failed: {error!r}"
            continue
        written.append(run_date)
    return written, unreadable


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store", default="file:.", help="where records live")
    parser.add_argument(
        "--reclassify",
        action="store_true",
        help="re-run the taxonomy over every snapshot before building the series",
    )
    parser.add_argument("--out", type=Path, help="write the series here (default stdout)")
    args = parser.parse_args()

    store = open_store(args.store)
    skipped: dict[str, str] = {}

    if args.reclassify:
        written, skipped = reclassify(store)
        for run_date in written:
            print(f"reclassified {run_date}", file=sys.stderr)

    records, unreadable = read_all(store, "classified")
    skipped.update(unreadable)
    for run_date, reason in sorted(skipped.items()):
        print(f"skipped {run_date}: {reason}", file=sys.stderr)

    if not records:
        print(
            f"{args.store}: no classified records this program can read. Run "
            f"classify.py, or series.py --reclassify to build them from snapshots.",
            file=sys.stderr,
        )
        return 2

    result = build(records, skipped)
    text = json.dumps(result, indent=2) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text)
        print(args.out)
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
