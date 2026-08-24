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
"""Tests for the time series.

Every test here is named after a way a trend chart lies: a gap drawn as a
collapse, a quiet day drawn as a gap, uniques added up into a number GitHub
never reported, or a history that stops at the oldest record this program
happens not to read.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

import series
import store

REPO = "gke-labs/devops-bench"


def traffic(daily: dict[str, tuple[int, int]], window: tuple[int, int] = (100, 20)) -> dict:
    """`daily` maps a date to (total, unique) views; clones mirror them."""
    entries = [
        {"date": d, "total": total, "unique": unique} for d, (total, unique) in sorted(daily.items())
    ]
    return {
        "views": {"total": window[0], "unique": window[1], "daily": entries},
        "clones": {"total": window[0], "unique": window[1], "daily": entries},
        "referrers": [],
        "popularPaths": [],
    }


def classified(collected: str, repos: dict[str, dict | None], window_days: int = 14) -> dict:
    return {
        "formatVersion": store.CLASSIFIED_FORMAT,
        "collectedAt": f"{collected}T12:00:00Z",
        "windowDays": window_days,
        "repos": {name: {"traffic": value} for name, value in repos.items()},
        "totals": {"forks": 27, "trafficRepos": [n for n, v in repos.items() if v]},
        "derived": {"externalOwnerRatio": 0.22},
        "affiliation": {"inside": 19, "outside": 8, "frozenAt": collected},
        "references": {"depending": 2, "running": 1, "citing": 11},
        "referencesUnavailable": None,
        "snapshotPartial": False,
        "snapshotSkipped": [],
        "provenance": None,
    }


def days(start: str, count: int, total: int = 5, unique: int = 2) -> dict[str, tuple[int, int]]:
    first = date.fromisoformat(start)
    return {(first + timedelta(days=i)).isoformat(): (total, unique) for i in range(count)}


# --- the window ------------------------------------------------------------


def test_the_window_ends_yesterday_and_never_includes_today():
    # Measured across two observations: traffic covers day -14 through day -1 in
    # UTC and today is absent entirely. A window that included today would claim
    # coverage of a day GitHub has not reported, and a real zero would be
    # written for it on every run.
    start, end = series.covered_window("2026-08-18T16:45:08Z", 14)
    assert (start, end) == (date(2026, 8, 4), date(2026, 8, 17))
    assert (end - start).days + 1 == 14


def test_coverage_comes_from_the_run_date_not_from_the_array_bounds():
    # A quiet day at the edge is omitted from the array. Deriving the window
    # from the array would shrink it and turn that real zero into a gap.
    record = classified("2026-08-18", {REPO: traffic({"2026-08-10": (5, 2)})})
    daily = series.daily_traffic({"2026-08-18": record})
    assert daily[REPO]["covered"] == [["2026-08-04", "2026-08-17"]]
    assert len(daily[REPO]["points"]) == 14


# --- stitching -------------------------------------------------------------


def test_overlapping_runs_stitch_past_the_fourteen_days_github_retains():
    # The whole payoff of keeping every snapshot. Two runs six days apart cover
    # twenty days between them; GitHub will only ever answer for fourteen.
    records = {
        "2026-08-12": classified("2026-08-12", {REPO: traffic(days("2026-07-29", 14))}),
        "2026-08-18": classified("2026-08-18", {REPO: traffic(days("2026-08-04", 14))}),
    }
    daily = series.daily_traffic(records)
    assert daily[REPO]["covered"] == [["2026-07-29", "2026-08-17"]]
    assert len(daily[REPO]["points"]) == 20
    assert daily[REPO]["gaps"] == []


def test_a_fortnight_nobody_ran_is_a_gap_not_a_run_of_zeroes():
    # Two runs far enough apart that their windows do not touch. Filling the
    # middle with zeroes draws a collapse in traffic that never happened.
    records = {
        "2026-06-01": classified("2026-06-01", {REPO: traffic(days("2026-05-18", 14))}),
        "2026-08-18": classified("2026-08-18", {REPO: traffic(days("2026-08-04", 14))}),
    }
    daily = series.daily_traffic(records)
    assert daily[REPO]["covered"] == [
        ["2026-05-18", "2026-05-31"],
        ["2026-08-04", "2026-08-17"],
    ]
    assert daily[REPO]["gaps"] == [["2026-06-01", "2026-08-03"]]
    assert len(daily[REPO]["points"]) == 28
    assert not [p for p in daily[REPO]["points"] if "2026-06-01" <= p["date"] <= "2026-08-03"]


def test_a_quiet_day_inside_a_covered_window_is_zero_not_a_gap():
    # GitHub omits a day with no traffic from the array entirely. Inside a
    # window some run covered, absent is a measurement of zero.
    record = classified("2026-08-18", {REPO: traffic({"2026-08-04": (5, 2), "2026-08-17": (5, 2)})})
    daily = series.daily_traffic({"2026-08-18": record})
    quiet = [p for p in daily[REPO]["points"] if p["date"] == "2026-08-10"]
    assert quiet == [{"date": "2026-08-10", "views": 0, "uniqueVisitors": 0, "clones": 0, "uniqueCloners": 0}]


def test_a_later_run_wins_for_a_day_both_runs_saw():
    records = {
        "2026-08-12": classified("2026-08-12", {REPO: traffic({"2026-08-10": (5, 2)})}),
        "2026-08-18": classified("2026-08-18", {REPO: traffic({"2026-08-10": (9, 4)})}),
    }
    daily = series.daily_traffic(records)
    overlap = next(p for p in daily[REPO]["points"] if p["date"] == "2026-08-10")
    assert (overlap["views"], overlap["uniqueVisitors"]) == (9, 4)


# --- what must never be added up -------------------------------------------


def test_the_window_unique_figure_is_kept_whole_and_never_derived_from_the_days():
    # Measured: fourteen daily uniques sum to 89 against a reported window
    # figure of 37. GitHub deduplicates within whatever window it is asked
    # about, so the daily array cannot reassemble the window number.
    record = classified(
        "2026-08-18", {REPO: traffic(days("2026-08-04", 14, total=10, unique=7), window=(505, 35))}
    )
    point = series.run_point("2026-08-18", record)
    daily = series.daily_traffic({"2026-08-18": record})
    # The reported window figure, kept whole.
    assert point["traffic"][REPO]["uniqueVisitors"] == 35
    # What adding the days up would have produced instead. The two disagree by
    # design, which is why the series keeps them in separate places.
    assert sum(p["uniqueVisitors"] for p in daily[REPO]["points"]) == 98


def test_traffic_that_never_worked_is_null_and_contributes_no_days():
    # kubernetes-sigs returns 403 without Administration:read. Null, never zero,
    # and it must not create a covered window full of zeroes.
    other = "kubernetes-sigs/devops-bench"
    record = classified("2026-08-18", {REPO: traffic(days("2026-08-04", 14)), other: None})
    point = series.run_point("2026-08-18", record)
    assert point["traffic"][other] is None
    assert other not in series.daily_traffic({"2026-08-18": record})


def test_a_repository_whose_traffic_starts_working_is_visible_as_coverage():
    # The series steps up for a reason that is instrumentation, not usage.
    other = "kubernetes-sigs/devops-bench"
    records = {
        "2026-08-12": classified("2026-08-12", {REPO: traffic(days("2026-07-29", 14)), other: None}),
        "2026-08-18": classified(
            "2026-08-18",
            {REPO: traffic(days("2026-08-04", 14)), other: traffic(days("2026-08-04", 14))},
        ),
    }
    result = series.build(records)
    assert result["runs"][0]["coverage"]["trafficRepos"] == [REPO]
    assert result["runs"][1]["coverage"]["trafficRepos"] == [REPO, other]


# --- one bad record must not cost the history ------------------------------


def test_a_record_older_than_the_format_field_does_not_kill_the_walk(tmp_path):
    # The first snapshot ever taken predates the store. A walk that raises on it
    # can never get past the oldest date there is, so the failure is permanent
    # and it lands on the history rather than on the one record.
    s = store.FileStore(tmp_path)
    (tmp_path / "classified").mkdir()
    (tmp_path / "classified" / "2026-08-11.json").write_text('{"noFormatVersion": true}')
    s.put("classified", "2026-08-18", classified("2026-08-18", {REPO: traffic(days("2026-08-04", 14))}))

    records, unreadable = series.read_all(s, "classified")
    assert list(records) == ["2026-08-18"]
    assert "2026-08-11" in unreadable

    result = series.build(records, unreadable)
    assert [r["date"] for r in result["runs"]] == ["2026-08-18"]
    # And it is reported, not dropped. A chart missing a date it could not read
    # looks complete and is not.
    assert result["unreadable"][0]["date"] == "2026-08-11"


def test_reclassify_rewrites_every_snapshot_it_can_read(tmp_path, monkeypatch):
    s = store.FileStore(tmp_path)
    for run_date in ("2026-08-12", "2026-08-18"):
        s.put("snapshot", run_date, {"formatVersion": store.SNAPSHOT_FORMAT, "date": run_date})
    (tmp_path / "snapshots" / "2026-08-11.json").write_text("{}")

    monkeypatch.setattr(
        series.classify,
        "classify",
        lambda snap: {"formatVersion": store.CLASSIFIED_FORMAT, "from": snap["date"]},
    )
    written, unreadable = series.reclassify(s)

    assert written == ["2026-08-12", "2026-08-18"]
    assert list(unreadable) == ["2026-08-11"]
    assert s.get("classified", "2026-08-18")["from"] == "2026-08-18"


def test_a_store_with_nothing_readable_is_an_error_not_an_empty_chart(tmp_path, monkeypatch):
    # Rendering an empty series publishes a page of blanks that looks like a
    # project nobody uses.
    (tmp_path / "classified").mkdir()
    (tmp_path / "classified" / "2026-08-11.json").write_text("{}")
    monkeypatch.setattr("sys.argv", ["series.py", "--store", f"file:{tmp_path}"])
    assert series.main() == 2


# --- what changed between two runs -----------------------------------------


def branch(name: str, signature: str | None = "sig", **over) -> dict:
    record = {
        "name": name,
        "primary": "agentFramework",
        "secondary": [],
        "external": False,
        "authors": [],
        "changedLines": 10,
        "headCommittedAt": "2026-08-14T00:00:00Z",
        "signature": signature,
        "unavailable": None,
    }
    return {**record, **over}


def forked(collected: str, forks: list[dict] | None, **over) -> dict:
    entry = {
        "repo": REPO,
        "forks": forks,
        "forksUnavailable": None if forks is not None else "listing failed",
        "forksNotListed": 0,
        "forksSkippedByCap": 0,
        "traffic": None,
        **over,
    }
    record = classified(collected, {})
    record["repos"] = {REPO: entry}
    return record


def fork(full_name: str, branches: list[dict]) -> dict:
    return {
        "fullName": full_name,
        "owner": full_name.split("/")[0],
        "external": True,
        "active": True,
        "divergentBranches": len(branches),
        "branches": branches,
        "unavailable": None,
    }


def only(before, after):
    return series.run_changes(before, after)["repos"][REPO]


def test_a_fork_the_previous_run_did_not_have_is_new():
    out = only(
        forked("2026-08-12", [fork("a/f", [branch("main")])]),
        forked("2026-08-18", [fork("a/f", [branch("main")]), fork("b/f", [branch("main")])]),
    )
    assert [f["fullName"] for f in out["newForks"]] == ["b/f"]
    assert [b["branch"] for b in out["newBranches"]] == ["main"]
    assert out["newBranches"][0]["fork"] == "b/f"


def test_a_branch_whose_head_moved_is_updated_not_new():
    out = only(
        forked("2026-08-12", [fork("a/f", [branch("work", "one", changedLines=10)])]),
        forked("2026-08-18", [fork("a/f", [branch("work", "two", changedLines=40)])]),
    )
    assert out["newBranches"] == []
    assert [b["branch"] for b in out["updatedBranches"]] == ["work"]
    assert out["updatedBranches"][0]["changedLinesBefore"] == 10
    assert out["updatedBranches"][0]["changedLines"] == 40


def test_a_branch_that_stood_still_is_not_reported():
    out = only(
        forked("2026-08-12", [fork("a/f", [branch("work", "one")])]),
        forked("2026-08-18", [fork("a/f", [branch("work", "one")])]),
    )
    assert out["newBranches"] == [] and out["updatedBranches"] == []


def test_a_branch_that_could_not_be_read_is_not_called_updated():
    # No signature means no comparison ran. Calling that a change reports the
    # failure of the collector as work somebody did.
    unread = branch("work", None, unavailable="compare failed", changedLines=None)
    out = only(
        forked("2026-08-12", [fork("a/f", [branch("work", "one")])]),
        forked("2026-08-18", [fork("a/f", [unread])]),
    )
    assert out["updatedBranches"] == []


def test_a_run_that_could_not_list_forks_reports_no_changes_at_all():
    # Every fork would otherwise look new the moment listing recovers.
    out = only(forked("2026-08-12", None), forked("2026-08-18", [fork("a/f", [branch("main")])]))
    assert out["comparable"] is False
    assert "earlier run" in out["reason"]


def test_a_capped_listing_never_publishes_a_deletion():
    # A fork missing from a sample was not necessarily deleted.
    out = only(
        forked("2026-08-12", [fork("a/f", [branch("main")]), fork("b/f", [branch("main")])]),
        forked("2026-08-18", [fork("a/f", [branch("main")])], forksSkippedByCap=3),
    )
    assert out["goneForks"] is None and out["goneBranches"] is None


def test_an_uncapped_run_does_report_what_disappeared():
    out = only(
        forked("2026-08-12", [fork("a/f", [branch("main"), branch("work")])]),
        forked("2026-08-18", [fork("a/f", [branch("main")])]),
    )
    assert out["goneForks"] == []
    assert [(b["fork"], b["branch"]) for b in out["goneBranches"]] == [("a/f", "work")]
    # Described from its last sighting: it has no current state to report.
    assert out["goneBranches"][0]["primary"] == "agentFramework"


def test_the_first_run_has_nothing_to_compare_against():
    runs = series.build({"2026-08-12": forked("2026-08-12", [fork("a/f", [branch("main")])])})["runs"]
    assert "changes" not in runs[0]


def test_older_runs_keep_the_counts_and_drop_the_rows():
    records = {
        f"2026-06-{day:02d}": forked(
            f"2026-06-{day:02d}", [fork("a/f", [branch(f"work-{n}") for n in range(day)])]
        )
        for day in range(1, 12)
    }
    runs = series.build(records)["runs"]

    assert [r["date"] for r in runs if r.get("changeDetail")] == sorted(records)[-series.DETAIL_RUNS:]
    dropped = next(r for r in runs if "changes" in r and not r["changeDetail"])
    assert dropped["changes"]["repos"][REPO]["newBranches"] == 1
    assert "newForks" in dropped["changes"]["repos"][REPO]
    assert runs[-1]["changes"]["repos"][REPO]["newBranches"][0]["branch"] == "work-10"
