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
"""Tests for the classification taxonomy.

Most of these are a published number that was wrong. The name of each says which
one.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import classify
from classify import (
    HARNESS_PARENTS,
    HISTORICAL_PREFIXES,
    PATH_TAXONOMY,
    UPSTREAM_HARNESSES,
    change_signature,
    classify_branch,
    classify_file,
    classify_reference,
    classify_references,
    pick_primary,
)

CHECKOUT = Path(__file__).resolve().parents[2]


def branch(name, files, additions=0, deletions=0, **kwargs):
    return {
        "name": name,
        "files": [{"path": p, "changes": c} for p, c in files],
        "additions": additions or sum(c for _, c in files),
        "deletions": deletions,
        "filesReturned": len(files),
        "unavailable": None,
        **kwargs,
    }


@pytest.fixture
def snapshot_like():
    """Two forks held by one contributor, one held by an outsider, all three
    carrying byte-identical work. That is the shape the real snapshot has."""

    def fork(full_name, owner, branches):
        return {"fullName": full_name, "owner": owner, "branches": branches, "unavailable": None}

    work = [("devops_bench/tasks/a.py", 10)]
    return {
        "formatVersion": 2,
        "collectedAt": "2026-08-12T00:00:00Z",
        "windowDays": 14,
        "partial": False,
        "skipped": [],
        "provenance": {},
        "affiliation": {"insideLogins": ["dev"], "outsideLogins": ["out"], "frozenAt": "2026-08-12"},
        "references": {
            "control": {"value": {"totalCount": 5, "hits": []}, "unavailable": None},
            "trustworthy": True,
            "queries": [],
        },
        "repos": {
            "a/b": {
                "repo": {"value": {"stars": 1}, "unavailable": None},
                "traffic": {"value": None, "unavailable": "needs push access"},
                "contributors": {"value": {"humans": ["dev"], "bots": []}, "unavailable": None},
                "pullRequests": {"value": {"totalCount": 0, "collected": 0, "items": []}, "unavailable": None},
                "issues": {"value": {"totalCount": 0, "collected": 0, "items": []}, "unavailable": None},
                "forks": {
                    "value": {
                        "countReported": 3,
                        "countListed": 3,
                        "skippedByCap": 0,
                        "upstreamHeadSha": "abc",
                        "items": [
                            fork("dev/b", "dev", [branch("main", work)]),
                            fork("dev/b-2", "dev", [branch("main", work)]),
                            fork("out/b", "out", [branch("main", work)]),
                        ],
                    },
                    "unavailable": None,
                },
            }
        },
    }


# --- the drift detector the health check was supposed to be -------------------


def test_every_taxonomy_prefix_still_resolves():
    """A prefix pointing at a directory that no longer exists silently stops
    classifying anything, and nothing fails."""
    prefixes = [p for _, _, ps in PATH_TAXONOMY for p in ps]
    missing = [p for p in prefixes if p not in HISTORICAL_PREFIXES and not (CHECKOUT / p).exists()]
    assert missing == [], f"taxonomy prefixes gone from the tree: {missing}"


def test_historical_prefixes_are_actually_historical():
    """When a directory comes back, it comes off the list rather than being
    described forever as removed."""
    resurrected = [p for p in HISTORICAL_PREFIXES if (CHECKOUT / p).exists()]
    assert resurrected == [], f"back in the tree, drop from HISTORICAL_PREFIXES: {resurrected}"


def test_harness_parents_and_upstream_harnesses_match_the_tree():
    found = {
        f"{parent}{d.name}/"
        for parent in HARNESS_PARENTS
        if (CHECKOUT / parent).is_dir()
        for d in (CHECKOUT / parent).iterdir()
        if d.is_dir() and d.name != "__pycache__"
    }
    assert found == set(UPSTREAM_HARNESSES)


# --- 3.1 what kind of change is this ------------------------------------------


def test_editing_an_existing_harness_is_not_adding_one():
    assert classify_file("devops_bench/agents/cli/openclaw/runner.py") == ("agentFramework", 2)
    assert classify_file("devops_bench/agents/cli/hermes/runner.py") == ("addingHarness", 1)


def test_a_model_provider_is_not_a_harness():
    """`pkg/agents/runner/api/` is the directory providers live in, not a
    harness named `api`. Nine branches were reported as adding a harness."""
    assert classify_file("pkg/agents/runner/api/ollama.py") == ("agentFramework", 2)


def test_the_floor_applies_to_the_fallback():
    """A branch that is 88% documentation read as 'adding a harness' because the
    fallback took the largest substantive area with no floor at all."""
    weight = {"docs": 880, "addingHarness": 60, "core": 60}
    tiers = {"docs": 3, "addingHarness": 1, "core": 2}
    assert pick_primary(weight, tiers) == "docs"


def test_a_branch_spread_across_everything_is_mixed():
    """Nothing holds a fifth of it, so naming one area is a guess."""
    tiers = {"addingTasks": 1, "changingGrading": 1, "core": 2, "infrastructure": 2,
             "tests": 3, "docs": 3}
    assert pick_primary(
        {"addingTasks": 10, "core": 15, "infrastructure": 15, "tests": 60}, tiers
    ) == "tests"
    assert pick_primary(dict.fromkeys(tiers, 17), tiers) == classify.MIXED


def test_share_beats_tier():
    """A first-tier category at 20% used to beat a second-tier one at 79%."""
    weight = {"addingTasks": 20, "core": 79}
    tiers = {"addingTasks": 1, "core": 2}
    assert pick_primary(weight, tiers) == "core"


def test_substantive_work_gets_first_refusal_over_supporting_work():
    """Test files are verbose, so a feature branch has more of them than
    feature. A substantive category that clears the floor takes the slot even
    when tests are larger; below the floor, tests are what the branch is."""
    tiers = {"tests": 3, "addingVerifiers": 1}
    assert pick_primary({"tests": 700, "addingVerifiers": 300}, tiers) == "addingVerifiers"
    assert pick_primary({"tests": 900, "addingVerifiers": 100}, tiers) == "tests"
    assert pick_primary({"tests": 900}, {"tests": 3}) == "tests"


def test_a_branch_of_nothing_but_unplaced_files_says_so():
    result = classify_branch(branch("x", [("migrated.bara.sky", 40)]), set(), "dev")
    assert result["primary"] == classify.UNCLASSIFIED
    assert result["unclassifiedLines"] == 40


def test_an_unavailable_branch_is_not_classified_as_anything():
    b = {"name": "x", "unavailable": "no common ancestor"}
    assert classify_branch(b, set(), "dev") == {
        "name": "x",
        "primary": None,
        "secondary": [],
        "authors": [],
        # Not False. A comparison that failed says nothing about who wrote it.
        "external": None,
        "unavailable": "no common ancestor",
    }


# --- 3.2 count distinct changes, not branches ---------------------------------


def test_the_signature_uses_the_path_list():
    """Added plus removed alone separates everything in today's snapshot, which
    is luck, not a property of the rule."""
    files_a = [{"path": "a.py"}]
    files_b = [{"path": "b.py"}]
    assert change_signature(files_a, 10, 2) != change_signature(files_b, 10, 2)
    assert change_signature(files_a, 10, 2) == change_signature(list(files_a), 10, 2)


def test_the_same_work_on_two_branch_names_is_one_change():
    one = classify_branch(branch("feature/x", [("devops_bench/tasks/a.py", 10)], 10, 2), set(), "dev")
    two = classify_branch(
        branch("worktree-feature-x", [("devops_bench/tasks/a.py", 10)], 10, 2), set(), "dev"
    )
    assert one["signature"] == two["signature"]


def test_deduplication_never_crosses_the_affiliation_boundary(snapshot_like):
    """One organisation account mirrors a contributor's fork branch for branch.
    Merged across the boundary the outside share collapses."""
    result = classify.classify(snapshot_like)
    assert result["totals"]["externalDistinctChanges"] == 1
    assert result["totals"]["distinctChanges"] == 2


# --- 3.3 who is outside the team ----------------------------------------------


def test_affiliation_is_read_from_the_snapshot_not_recomputed(snapshot_like):
    """The contributors endpoint lists commit authors of merged commits only, so
    recomputing turns a reviewer into an outsider and un-happens the milestone
    the day their first commit merges."""
    snapshot_like["affiliation"]["outsideLogins"] = []
    result = classify.classify(snapshot_like)
    assert result["totals"]["externalOwners"] == 0


# --- 3.4 references elsewhere -------------------------------------------------


def test_a_failed_control_query_makes_references_unavailable_not_zero():
    block = {
        "control": {"value": None, "unavailable": "search returned nothing"},
        "trustworthy": False,
        "queries": [
            {
                "value": {"query": '"import devops_bench"', "totalCount": 0, "hits": []},
                "unavailable": None,
            }
        ],
    }
    out = classify_references(block)
    assert out["references"] == {"depending": None, "running": None, "citing": None}
    assert "search returned nothing" in out["referencesUnavailable"]


def test_a_capped_query_is_marked_against_its_real_total():
    block = {
        "control": {"value": {"totalCount": 5, "hits": []}, "unavailable": None},
        "trustworthy": True,
        "queries": [
            {
                "value": {
                    "query": '"from devops_bench"',
                    "totalCount": 249,
                    "hits": [{"repo": "someone/else", "path": f"a{i}.py"} for i in range(100)],
                },
                "unavailable": None,
            }
        ],
    }
    out = classify_references(block)
    assert out["referenceQueries"][0] == {
        "query": '"from devops_bench"',
        "totalCount": 249,
        "hits": 100,
        "capped": True,
        "unavailable": None,
    }
    assert out["referenceHitsCapped"] is True


def test_one_file_matched_by_two_queries_is_one_reference():
    hit = {"repo": "someone/else", "path": "app/main.py"}
    block = {
        "control": {"value": {"totalCount": 5, "hits": []}, "unavailable": None},
        "trustworthy": True,
        "queries": [
            {"value": {"query": q, "totalCount": 1, "hits": [hit]}, "unavailable": None}
            for q in classify.IMPORT_QUERIES
        ],
    }
    out = classify_references(block)
    assert out["references"]["depending"] == 1


def test_a_prow_job_runs_the_benchmark_rather_than_citing_it():
    hit = {"repo": "kubernetes/test-infra", "path": "config/jobs/x/devops-bench-presubmits.yaml"}
    assert classify_reference(hit, '"kubernetes-sigs/devops-bench"') == "running"


def test_an_import_shown_in_a_readme_is_a_citation():
    hit = {"repo": "someone/else", "path": "docs/README.md"}
    assert classify_reference(hit, '"import devops_bench"') == "citing"
    assert classify_reference({**hit, "path": "app/main.py"}, '"import devops_bench"') == "depending"


def test_our_own_repositories_are_not_adoption():
    hit = {"repo": "gke-labs/devops-bench", "path": "devops_bench/run.py"}
    assert classify_reference(hit, '"import devops_bench"') is None


def _reference_block(*queries):
    return {
        "control": {"value": {"totalCount": 5, "hits": []}, "unavailable": None},
        "trustworthy": True,
        "queries": [
            {"value": {"query": q, "totalCount": len(hits), "hits": hits}, "unavailable": None}
            for q, hits in queries
        ],
    }


def test_a_reference_is_attributed_to_the_repository_it_names():
    out = classify_references(
        _reference_block(
            ('"gke-labs/devops-bench"', [{"repo": "someone/else", "path": "docs/a.md"}]),
            ('"kubernetes-sigs/devops-bench"', [{"repo": "other/repo", "path": "docs/b.md"}]),
        )
    )
    assert {h["path"]: h["targets"] for h in out["referenceHits"]} == {
        "docs/a.md": ["gke-labs/devops-bench"],
        "docs/b.md": ["kubernetes-sigs/devops-bench"],
    }


def test_a_package_import_takes_the_repository_the_rest_of_its_project_names():
    """The package is byte-identical in both repositories, so the import itself
    says nothing. The project around it does."""
    out = classify_references(
        _reference_block(
            ('"from devops_bench"', [{"repo": "someone/else", "path": "app/main.py"}]),
            ('"kubernetes-sigs/devops-bench"', [{"repo": "someone/else", "path": "README.md"}]),
        )
    )
    assert {h["path"]: h["targets"] for h in out["referenceHits"]} == {
        "app/main.py": ["kubernetes-sigs/devops-bench"],
        "README.md": ["kubernetes-sigs/devops-bench"],
    }


def test_a_project_naming_no_repository_leaves_its_references_unattributed():
    out = classify_references(
        _reference_block(
            ('"from devops_bench"', [{"repo": "someone/else", "path": "app/main.py"}]),
        )
    )
    assert out["referenceHits"][0]["targets"] == []
    assert out["references"]["depending"] == 1


# --- 3.5 ratios ----------------------------------------------------------------


def test_external_share_counts_owners_not_repositories(snapshot_like):
    """Contributors fork both repositories and are counted twice; every outside
    owner is counted once. The per-repository denominator is inflated with
    insiders, which pushes the headline down."""
    result = classify.classify(snapshot_like)
    assert result["totals"]["forks"] == 3
    assert result["totals"]["owners"] == 2
    assert result["derived"]["externalOwnerRatio"] == 0.5


def test_a_fork_nobody_committed_to_is_not_adoption(snapshot_like):
    snapshot_like["repos"]["a/b"]["forks"]["value"]["items"].append(
        {"fullName": "watcher/b", "owner": "watcher", "branches": [], "unavailable": None}
    )
    snapshot_like["affiliation"]["outsideLogins"].append("watcher")
    result = classify.classify(snapshot_like)
    assert result["derived"]["externalOwnerRatio"] == 2 / 3
    assert result["derived"]["activeExternalOwnerRatio"] == 0.5


def test_dropped_ratios_are_gone(snapshot_like):
    """Conversion divided four months of forks by fourteen days of visitors to
    one repository; clones per cloner measured continuous integration."""
    derived = classify.classify(snapshot_like)["derived"]
    assert "conversionRate" not in derived
    assert "clonesPerUniqueCloner" not in derived


def test_a_ratio_with_an_empty_denominator_is_null():
    assert classify.ratio(0, 0) is None
    assert classify.ratio(0, 4) == 0.0


# --- 3.6 the health check ------------------------------------------------------


def test_the_unclassified_share_is_weighted_by_lines(snapshot_like):
    """Per branch it is a rounding error: a branch gets a category from whatever
    else it touched, so 26,000 unplaced lines hid behind a 2% figure."""
    forks = snapshot_like["repos"]["a/b"]["forks"]["value"]
    forks["items"] = forks["items"][:1]
    forks["items"][0]["branches"] = [
        branch("big", [("devops_bench/tasks/a.py", 100), ("migrated.bara.sky", 300)])
    ]
    result = classify.classify(snapshot_like)
    assert result["totals"]["unclassifiedLines"] == 300
    assert result["derived"]["unclassifiedLineRate"] == 300 / 400


def test_a_fork_is_external_by_who_wrote_it_not_who_holds_it(snapshot_like):
    # An org account held 24 branches a contributor wrote. Owner matching called
    # that outside adoption; the compare response says every commit is inside.
    forks = snapshot_like["repos"]["a/b"]["forks"]["value"]["items"]
    forks[2]["branches"][0]["authors"] = [{"login": "dev", "commits": 126}]
    result = classify.classify(snapshot_like)

    held = next(f for f in result["repos"]["a/b"]["forks"] if f["owner"] == "out")
    assert held["authors"] == ["dev"]
    assert held["external"] is False
    assert result["totals"]["externalOwners"] == 0


def test_outside_commits_on_an_insiders_fork_still_count(snapshot_like):
    # The mirror case in reverse: ownership misses it in both directions.
    forks = snapshot_like["repos"]["a/b"]["forks"]["value"]["items"]
    forks[0]["branches"][0]["authors"] = [{"login": "out", "commits": 3}]
    result = classify.classify(snapshot_like)

    owned = next(f for f in result["repos"]["a/b"]["forks"] if f["fullName"] == "dev/b")
    assert owned["external"] is True
    assert result["totals"]["externalOwners"] == 2


def test_a_fork_with_no_commits_to_read_falls_back_to_its_owner(snapshot_like):
    result = classify.classify(snapshot_like)
    held = next(f for f in result["repos"]["a/b"]["forks"] if f["owner"] == "out")
    assert held["authors"] == []
    assert held["external"] is True


def test_one_outside_commit_does_not_charge_the_whole_fork(snapshot_like):
    # An org account holds 25 branches; an outsider wrote 11 commits on one of
    # them. Making the fork the unit charged all 25 branches to the outside.
    fork = snapshot_like["repos"]["a/b"]["forks"]["value"]["items"][0]
    fork["branches"].append(branch("second", [("devops_bench/tasks/b.py", 10)]))
    fork["branches"][0]["authors"] = [{"login": "dev", "commits": 5}]
    fork["branches"][1]["authors"] = [{"login": "out", "commits": 1}]
    result = classify.classify(snapshot_like)

    held = next(f for f in result["repos"]["a/b"]["forks"] if f["fullName"] == "dev/b")
    assert held["external"] is True
    assert [b["external"] for b in held["branches"]] == [False, True]
    assert result["totals"]["externalDivergentBranches"] == 2  # not 3


# --- 3.6 contributions ---------------------------------------------------------


def pull_request(number, author, created, merged=None, closed=None, reviews=(), comments=()):
    return {
        "number": number,
        "state": "MERGED" if merged else ("CLOSED" if closed else "OPEN"),
        "merged": bool(merged),
        "isDraft": False,
        "createdAt": created,
        "mergedAt": merged,
        "closedAt": merged or closed,
        "author": {"login": author, "type": "User", "isBot": author.endswith("[bot]")},
        "additions": 1,
        "deletions": 0,
        "changedFiles": 1,
        "files": [],
        "reviews": [
            {"state": state, "submittedAt": at, "author": {"login": who, "isBot": who.endswith("[bot]")}}
            for who, state, at in reviews
        ],
        "reviewCount": len(reviews),
        "comments": [
            {"createdAt": at, "author": {"login": who, "isBot": who.endswith("[bot]")}}
            for who, at in comments
        ],
        "commentCount": len(comments),
    }


def contributions(items, first_merge=None, collected="2026-08-18T00:00:00Z"):
    entry = {"pullRequests": {"value": {"totalCount": len(items), "collected": len(items), "items": items}, "unavailable": None}}
    return classify.classify_contributions(entry, first_merge or {}, collected)


def month(result, key):
    return next(m for m in result["months"] if m["month"] == key)


def test_a_merge_is_counted_in_the_month_it_merged_not_the_month_it_opened():
    """Bucketing a duration by the month the pull request opened makes the
    newest month look fast: its slow pull requests have not merged yet."""
    out = contributions([pull_request(1, "dev", "2026-06-30T00:00:00Z", merged="2026-07-02T00:00:00Z")])
    assert month(out, "2026-06")["opened"] == 1
    assert month(out, "2026-06")["merged"] == 0
    assert month(out, "2026-07")["merged"] == 1
    assert month(out, "2026-07")["mergeHours"] == [48.0]


def test_a_new_contributor_is_a_first_merge_not_a_first_pull_request():
    opened_never_merged = pull_request(1, "newcomer", "2026-06-01T00:00:00Z", closed="2026-06-02T00:00:00Z")
    landed = pull_request(2, "newcomer", "2026-07-01T00:00:00Z", merged="2026-07-02T00:00:00Z")
    out = contributions(
        [opened_never_merged, landed], first_merge={"newcomer": "2026-07-02T00:00:00Z"}
    )
    assert month(out, "2026-06")["newContributors"] == []
    assert month(out, "2026-07")["newContributors"] == ["newcomer"]


def test_a_second_repository_does_not_make_an_existing_contributor_new_again():
    """The first merge is project-wide. Somebody whose work landed upstream is
    not a newcomer the day they merge into the donated copy."""
    snapshot = {
        "repos": {
            "a/b": {"pullRequests": {"value": {"items": [
                pull_request(1, "dev", "2026-05-01T00:00:00Z", merged="2026-05-02T00:00:00Z")]}, "unavailable": None}},
            "c/d": {"pullRequests": {"value": {"items": [
                pull_request(1, "dev", "2026-07-01T00:00:00Z", merged="2026-07-02T00:00:00Z")]}, "unavailable": None}},
        }
    }
    first = classify.first_merge_by_author(snapshot)
    assert first == {"dev": "2026-05-02T00:00:00Z"}
    later = contributions(snapshot["repos"]["c/d"]["pullRequests"]["value"]["items"], first_merge=first)
    assert month(later, "2026-07")["newContributors"] == []


def test_a_bot_is_not_engagement_and_neither_is_the_author():
    pr = pull_request(
        1, "dev", "2026-07-01T00:00:00Z",
        comments=[("dev", "2026-07-01T01:00:00Z"), ("ci[bot]", "2026-07-01T02:00:00Z"), ("reviewer", "2026-07-01T05:00:00Z")],
    )
    assert classify.first_response(pr) == "2026-07-01T05:00:00Z"
    out = contributions([pr])
    assert month(out, "2026-07")["engageHours"] == [5.0]


def test_a_pull_request_nobody_answered_is_absent_rather_than_zero():
    out = contributions([pull_request(1, "dev", "2026-07-01T00:00:00Z")])
    assert month(out, "2026-07")["engageHours"] == []
    assert out["openPRAgeHours"] == [1152.0]


def test_a_merge_with_no_approval_is_counted_separately():
    approved = pull_request(
        1, "dev", "2026-07-01T00:00:00Z", merged="2026-07-03T00:00:00Z",
        reviews=[("reviewer", "APPROVED", "2026-07-02T00:00:00Z")],
    )
    out = contributions([approved, pull_request(2, "dev", "2026-07-01T00:00:00Z", merged="2026-07-01T12:00:00Z")])
    assert out["openToApprovalHours"] == [24.0]
    assert out["approvalToMergeHours"] == [24.0]
    assert out["mergedWithoutApproval"] == 1


def test_the_month_the_collection_ran_is_marked_partial():
    out = contributions(
        [pull_request(1, "dev", "2026-07-01T00:00:00Z"), pull_request(2, "dev", "2026-08-02T00:00:00Z")],
        collected="2026-08-18T00:00:00Z",
    )
    assert [m["partial"] for m in out["months"]] == [False, True]


def test_pull_requests_that_were_not_collected_are_unavailable_not_empty():
    entry = {"pullRequests": {"value": None, "unavailable": "GraphQL rate limit"}}
    assert classify.classify_contributions(entry, {}, "2026-08-18T00:00:00Z") == {
        "unavailable": "GraphQL rate limit"
    }


def test_a_thread_that_hit_the_collection_cap_is_counted():
    """Reviews are collected 100 at a time and comments 50. A cut-off thread can
    only push a first response later than it was."""
    pr = pull_request(1, "dev", "2026-07-01T00:00:00Z", comments=[("reviewer", "2026-07-01T05:00:00Z")])
    pr["commentCount"] = 80
    out = contributions([pr])
    assert (out["collectedPRs"], out["truncatedThreads"]) == (1, 1)
