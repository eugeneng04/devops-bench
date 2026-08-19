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
"""Turn a raw UsageSnapshot into classified metrics.

Pure functions over a snapshot file: no network, so the taxonomy can be revised
and re-run over every snapshot ever collected. That property is the reason this
is a separate step from collect.py, and the reason the tree facts this file
needs - which harness directories exist, which taxonomy prefixes still resolve -
are constants checked by a test rather than filesystem reads at runtime.

Undefined values stay null. A ratio with a zero denominator is null, not zero.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

from store import CLASSIFIED_FORMAT, SNAPSHOT_FORMAT

CANONICAL_REPOS = {"gke-labs/devops-bench", "kubernetes-sigs/devops-bench"}

# Path taxonomy. Ordered most specific first; the first matching prefix wins for
# a given file. Tier separates substantive work (1 and 2) from supporting work
# (3): tests and docs take the primary slot only when a branch has nothing else.
# Within substantive work, share decides - see pick_primary.
PATH_TAXONOMY: list[tuple[str, int, tuple[str, ...]]] = [
    ("addingTasks", 1, ("tasks/", "devops_bench/tasks/")),
    ("addingVerifiers", 1, ("devops_bench/verification/", "pkg/agents/verifier/")),
    ("addingProvider", 1, ("devops_bench/providers/", "devops_bench/models/")),
    ("changingGrading", 1, ("devops_bench/metrics/", "pkg/evaluator/")),
    ("addingChaos", 1, ("devops_bench/chaos/", "pkg/agents/chaos/")),
    ("addingSkills", 1, ("skills/", "devops_bench/skills/")),
    # Shared agent plumbing - base.py, config.py, capabilities/. Touching it is
    # not adding a harness; adding a harness is a directory that does not exist
    # upstream (see UPSTREAM_HARNESSES), which classify_file checks first.
    ("agentFramework", 2, ("devops_bench/agents/", "pkg/agents/runner/")),
    (
        "infrastructure",
        2,
        ("deployers/", "devops_bench/deployers/", "tf/", ".github/", "hack/", "scripts/"),
    ),
    (
        "core",
        2,
        (
            "devops_bench/core/",
            "devops_bench/evalharness/",
            "devops_bench/harness/",
            "devops_bench/k8s/",
            "devops_bench/results/",
            "devops_bench/cli.py",
            "devops_bench/run.py",
            "pkg/manager/",
            "pkg/runenv.py",
        ),
    ),
    ("tests", 3, ("tests/",)),
    ("docs", 3, ("docs/", "site/")),
]

# Prefixes that no longer exist in the tree but still appear in fork branches,
# which are cut from older upstream commits. Dropping them does not make the
# work go away, it makes it unclassified: `devops_bench/harness/` alone is
# 26,000 changed lines, 70% of everything the taxonomy could not place.
# test_classify.py asserts every other prefix still resolves, and that these
# genuinely do not - so a directory that comes back gets taken off this list.
HISTORICAL_PREFIXES = frozenset({"devops_bench/harness/"})

# Directories under one of these are candidate harnesses.
HARNESS_PARENTS = (
    "devops_bench/agents/cli/",
    "devops_bench/agents/api/",
    "pkg/agents/runner/",
)

# Harness directories that already exist upstream. Editing one is not adding
# one. Without this test, five branches that touch `openclaw/` read as new
# harnesses, and every branch touching `pkg/agents/runner/api/` - the parent
# directory model providers live in - reads the segment `api` as a harness name
# and reports a provider as a harness.
UPSTREAM_HARNESSES = frozenset(
    {
        "devops_bench/agents/cli/antigravity/",
        "devops_bench/agents/cli/gemini_cli/",
        "devops_bench/agents/cli/openclaw/",
        "pkg/agents/runner/api/",
    }
)

# A category takes the primary slot only if it holds at least this share of the
# branch's changed lines. Nothing clearing it means the branch really is spread
# across areas, and the honest answer is "mixed" - not the largest of the
# minorities, which is how a branch that is 88% documentation came to read as
# "adding a harness".
PRIMARY_SHARE_FLOOR = 0.20

MIXED = "mixed"
UNCLASSIFIED = "unclassified"
UNCLASSIFIED_TIER = 9

CLASS_LABELS = {
    "addingTasks": "Adding tasks",
    "addingHarness": "Adding a harness",
    "addingVerifiers": "Adding verifiers",
    "addingProvider": "Adding a model provider",
    "changingGrading": "Changing grading",
    "addingChaos": "Adding chaos scenarios",
    "addingSkills": "Adding skills",
    "agentFramework": "Agent framework",
    "infrastructure": "Infrastructure",
    "core": "Core changes",
    "tests": "Tests",
    "docs": "Documentation",
    MIXED: "Mixed",
    UNCLASSIFIED: "Unclassified",
}

# `config/jobs/` is prow, which is how the only pipeline outside this project
# that actually runs the benchmark refers to it. Without it that job read as a
# citation.
CI_PATH = re.compile(
    r"(^|/)(\.github/workflows/|config/jobs/|Makefile$|.*\.sh$|\.gitlab-ci\.yml$|Dockerfile)"
)
MANIFEST_PATH = re.compile(r"(^|/)(pyproject\.toml|requirements[^/]*\.txt|setup\.cfg|uv\.lock)$")
PROSE_PATH = re.compile(r"\.(md|rst|txt|adoc)$")
IMPORT_QUERIES = ('"import devops_bench"', '"from devops_bench"')


def classify_file(path: str) -> tuple[str, int]:
    for parent in HARNESS_PARENTS:
        rest = path[len(parent):] if path.startswith(parent) else ""
        if "/" in rest:
            directory = parent + rest.split("/", 1)[0] + "/"
            if directory not in UPSTREAM_HARNESSES:
                return "addingHarness", 1
            break
    for name, tier, prefixes in PATH_TAXONOMY:
        if any(path == p or path.startswith(p) for p in prefixes):
            return name, tier
    if path.endswith(".md"):
        return "docs", 3
    return UNCLASSIFIED, UNCLASSIFIED_TIER


def pick_primary(weight: dict[str, int], tiers: dict[str, int]) -> str:
    """Choose one primary category from the per-category changed-line weights.

    Share first, then tier. The previous order was strict tier then share, which
    let a first-tier category holding 20% of a branch beat a second-tier one
    holding 79%. Tier now only decides which categories get first refusal:
    substantive work is offered the slot before tests and documentation, but a
    substantive category still has to clear the floor to take it, and a branch
    that is 90% tests is called tests rather than mixed.
    """
    if not weight:
        return UNCLASSIFIED

    total = sum(weight.values())
    substantive = {n: w for n, w in weight.items() if tiers[n] <= 2}

    for candidates in (substantive, weight):
        clears = [n for n, w in candidates.items() if w / total >= PRIMARY_SHARE_FLOOR]
        if clears:
            return max(clears, key=lambda n: (weight[n], -tiers[n], n))
    return MIXED


def change_signature(files: list[dict[str, Any]], additions: int, deletions: int) -> str:
    """Identify a change by its content rather than its branch name.

    The path list is hashed into the signature. Added-plus-removed alone happens
    to separate every change in the current snapshot, but two integers is a
    collision waiting to happen and would silently merge unrelated work.
    """
    paths = "\n".join(sorted(f["path"] for f in files))
    material = f"{additions}/{deletions}\n{paths}"
    return hashlib.sha256(material.encode()).hexdigest()[:16]


def classify_branch(branch: dict[str, Any], outside: set[str], owner: str) -> dict[str, Any]:
    """Assign one primary category plus any others the branch touched.

    Affiliation is per branch, not per fork. One outside contributor wrote 11 of
    the several hundred commits on an org account's forks; making the fork the
    unit charged all 25 of its branches to the outside.
    """
    if branch.get("unavailable"):
        return {
            "name": branch["name"],
            "primary": None,
            "secondary": [],
            "authors": [],
            "external": None,
            "unavailable": branch["unavailable"],
        }

    authors = {a["login"] for a in branch.get("authors", [])}

    weight: dict[str, int] = {}
    tiers: dict[str, int] = {}
    for f in branch["files"]:
        name, tier = classify_file(f["path"])
        weight[name] = weight.get(name, 0) + max(f.get("changes", 0), 1)
        tiers[name] = tier

    primary = pick_primary(weight, tiers)
    additions = branch["additions"] or 0
    deletions = branch["deletions"] or 0

    return {
        "name": branch["name"],
        "primary": primary,
        "secondary": sorted(n for n in weight if n != primary),
        "authors": sorted(authors),
        # Ownership is the fallback only when there is no commit to read.
        "external": bool(authors & outside) or (not authors and owner in outside),
        "signature": change_signature(branch["files"], additions, deletions),
        # When the branch was last committed to, not when the work started. It
        # is what a date range on the page can honestly filter on: whether the
        # branch was still being worked on inside the window.
        "headCommittedAt": branch.get("headCommittedAt"),
        "changedFiles": len(branch["files"]),
        "additions": additions,
        "deletions": deletions,
        # Weighted by lines, because the health check is: how much work could
        # the taxonomy not place, not how many branches happened to contain a
        # file it could not place.
        "changedLines": sum(weight.values()),
        "unclassifiedLines": weight.get(UNCLASSIFIED, 0),
        "filesReturned": branch.get("filesReturned"),
        "unavailable": None,
    }


def classify_reference(hit: dict[str, Any], query: str) -> str | None:
    """Map one code-search hit to Depending / Running / Citing.

    Citing is the catch-all, which is only defensible because the tests above it
    run first. It used to be reached by two identical branches, one of them a
    `.md` test that changed nothing, which made a Python import look like a
    deliberate decision to call it a citation. An import inside prose is still
    prose, though - a README showing `import devops_bench` is a citation.
    """
    if hit["repo"] in CANONICAL_REPOS:
        return None  # self-reference, not adoption
    path = hit["path"]
    if MANIFEST_PATH.search(path):
        return "depending"
    if CI_PATH.search(path):
        return "running"
    if query in IMPORT_QUERIES and not PROSE_PATH.search(path):
        return "depending"
    return "citing"


def classify_references(block: dict[str, Any]) -> dict[str, Any]:
    """Classify code-search hits, but only if the control query stands up.

    The control asks a question whose answer cannot legitimately be zero. When
    it comes back empty the searches are not reporting an absence of references,
    they are not reporting - and the difference is the whole point.
    """
    control = block["control"]["value"]
    queries = []
    # One file matched by two queries is one reference. Keyed by repo and path,
    # keeping the strongest class, because the import queries overlap and a file
    # that both imports the package and declares it is depending on it.
    strongest = {"depending": 0, "running": 1, "citing": 2}
    best: dict[tuple[str, str], dict[str, Any]] = {}
    capped = False

    for result in block["queries"]:
        value = result["value"]
        total = value["totalCount"] if value else None
        returned = len(value["hits"]) if value else None
        query_capped = bool(value and total is not None and returned < total)
        capped = capped or query_capped
        queries.append(
            {
                "query": value["query"] if value else None,
                "totalCount": total,
                "hits": returned,
                # 249 matches behind 100 returned hits is not 100 references.
                "capped": query_capped,
                "unavailable": result["unavailable"],
            }
        )
        if not value:
            continue
        for hit in value["hits"]:
            cls = classify_reference(hit, value["query"])
            if cls is None:
                continue
            key = (hit["repo"], hit["path"])
            if key not in best or strongest[cls] < strongest[best[key]["class"]]:
                best[key] = {**hit, "class": cls}

    hits = [best[k] for k in sorted(best)]
    counts: dict[str, int | None] = {"depending": 0, "running": 0, "citing": 0}
    for hit in hits:
        counts[hit["class"]] += 1

    if not block.get("trustworthy") or not control:
        reason = block["control"]["unavailable"] or "the control query returned nothing"
        return {
            "references": dict.fromkeys(counts),
            "referencesUnavailable": f"code search is not answering: {reason}",
            "referenceHits": [],
            "referenceQueries": queries,
            "referenceHitsCapped": capped,
        }

    return {
        "references": counts,
        "referencesUnavailable": None,
        "referenceHits": hits,
        "referenceQueries": queries,
        "referenceHitsCapped": capped,
    }


def classify_repo(entry: dict[str, Any], outside: set[str]) -> dict[str, Any]:
    """Classify one repository's forks and branches.

    `outside` is the frozen affiliation from the snapshot, not a set recomputed
    from the contributors endpoint. Recomputing means that the day the first
    outside contributor merges something, every past outside signal turns inside
    and the milestone un-happens.
    """
    contributors = entry["contributors"]["value"]
    forks_raw = entry["forks"]["value"]

    out: dict[str, Any] = {
        "repo": entry["repo"]["value"],
        "traffic": entry["traffic"]["value"],
        "trafficUnavailable": entry["traffic"]["unavailable"],
        "contributorCount": len(contributors["humans"]) if contributors else None,
    }

    if forks_raw is None:
        out["forks"] = None
        out["forksUnavailable"] = entry["forks"]["unavailable"]
        out["forksSkippedByCap"] = None
        out["forksNotListed"] = None
        out["extensions"] = None
        return out

    extensions = {name: 0 for name in CLASS_LABELS}
    forks = []
    for fork in forks_raw["items"]:
        branches = [classify_branch(b, outside, fork["owner"]) for b in fork["branches"]]
        for b in branches:
            if b["primary"]:
                extensions[b["primary"]] += 1
        # Who wrote the work, not who holds the fork. Ownership was the signal
        # and it is the wrong one in both directions: an org account can hold a
        # contributor's branches, and a contributor's fork can carry commits
        # written by someone outside.
        forks.append(
            {
                "fullName": fork["fullName"],
                "owner": fork["owner"],
                "authors": sorted({a for b in branches for a in b["authors"]}),
                # A fork with no branches has nothing to read, so who holds it
                # is the only evidence there is.
                "external": any(b["external"] for b in branches)
                or (not branches and fork["owner"] in outside),
                # A fork nobody ever committed to is a bookmark, not adoption.
                "active": any(b["primary"] for b in branches),
                "divergentBranches": sum(1 for b in branches if b["primary"]),
                "branches": branches,
                "unavailable": fork["unavailable"],
            }
        )

    out["forks"] = forks
    out["forksUnavailable"] = None
    out["forksSkippedByCap"] = forks_raw["skippedByCap"]
    # GitHub's own fork counter against the forks it will actually list.
    out["forksNotListed"] = forks_raw["countReported"] - forks_raw["countListed"]
    out["extensions"] = extensions
    return out


def ratio(numerator: int, denominator: int) -> float | None:
    """Null, never zero, when the denominator is zero."""
    return None if denominator == 0 else numerator / denominator


def classify(snapshot: dict[str, Any]) -> dict[str, Any]:
    affiliation = snapshot["affiliation"]
    outside = set(affiliation["outsideLogins"])

    repos = {
        name: classify_repo(entry, outside)
        for name, entry in snapshot["repos"].items()
    }

    all_forks = [f for r in repos.values() for f in (r["forks"] or [])]
    external_forks = [f for f in all_forks if f["external"]]
    active_forks = [f for f in all_forks if f["active"]]

    # A person who forked both repositories is one adopter, not two. Counting
    # repositories inflates the denominator with insiders - who fork twice -
    # while every outside owner is counted once, pushing the headline down.
    owners = {f["owner"] for f in all_forks}
    active_owners = {f["owner"] for f in active_forks}
    external_owners = {f["owner"] for f in external_forks}
    active_external_owners = {f["owner"] for f in active_forks if f["external"]}

    branches = [b for f in all_forks for b in f["branches"] if b["primary"]]
    external_branches = [b for b in branches if b["external"]]

    # Deduplicate within an affiliation group, never across it. Fourteen outside
    # branches are byte-identical to branches on an insider's fork; merging them
    # across the boundary makes the outside share depend on a tie-break nobody
    # chose.
    inside_signatures = {b["signature"] for b in branches if not b["external"]}
    external_signatures = {b["signature"] for b in external_branches}

    changed_lines = sum(b["changedLines"] for b in branches)
    unclassified_lines = sum(b["unclassifiedLines"] for b in branches)

    return {
        "formatVersion": CLASSIFIED_FORMAT,
        "collectedAt": snapshot["collectedAt"],
        "windowDays": snapshot["windowDays"],
        "provenance": snapshot.get("provenance"),
        "snapshotPartial": snapshot.get("partial", False),
        "snapshotSkipped": snapshot.get("skipped", []),
        "classLabels": CLASS_LABELS,
        "repos": repos,
        **classify_references(snapshot["references"]),
        "affiliation": {
            "inside": len(affiliation["insideLogins"]),
            "outside": len(affiliation["outsideLogins"]),
            "frozenAt": affiliation.get("frozenAt"),
        },
        "totals": {
            "forks": len(all_forks),
            "activeForks": len(active_forks),
            "externalForks": len(external_forks),
            "owners": len(owners),
            "activeOwners": len(active_owners),
            "externalOwners": len(external_owners),
            "activeExternalOwners": len(active_external_owners),
            "divergentBranches": len(branches),
            "externalDivergentBranches": len(external_branches),
            "distinctChanges": len(inside_signatures) + len(external_signatures),
            "externalDistinctChanges": len(external_signatures),
            "changedLines": changed_lines,
            "unclassifiedLines": unclassified_lines,
            # Unique visitors and cloners are per repository and do not add up;
            # only the per-repo figures under `repos` are meaningful.
            "trafficRepos": [n for n, r in repos.items() if r["traffic"]],
        },
        "derived": {
            "externalOwnerRatio": ratio(len(external_owners), len(owners)),
            "activeExternalOwnerRatio": ratio(
                len(active_external_owners), len(active_owners)
            ),
            "externalBranchRatio": ratio(len(external_branches), len(branches)),
            "externalChangeRatio": ratio(
                len(external_signatures),
                len(inside_signatures) + len(external_signatures),
            ),
            "unclassifiedLineRate": ratio(unclassified_lines, changed_lines),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("snapshot", type=Path, help="raw snapshot JSON from collect.py")
    parser.add_argument("--out", type=Path, help="write classified JSON here (default stdout)")
    args = parser.parse_args()

    snapshot = json.loads(args.snapshot.read_text())
    version = snapshot.get("formatVersion")
    if version != SNAPSHOT_FORMAT:
        print(
            f"{args.snapshot}: snapshot format {version}, expected {SNAPSHOT_FORMAT}.",
            file=sys.stderr,
        )
        return 2

    result = classify(snapshot)
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
