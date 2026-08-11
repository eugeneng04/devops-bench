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
is a separate step from collect.py.

Undefined values stay null. A ratio with a zero denominator is null, not zero.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

CANONICAL_REPOS = {"gke-labs/devops-bench", "kubernetes-sigs/devops-bench"}

# Path taxonomy. Ordered most specific first; the first matching prefix wins for
# a given file. Tier decides which class becomes a branch's primary when a
# change touches several areas - a change touching both a harness and tests is
# "adding a harness", not "tests".
#
# Every prefix below exists in the tree today. `pkg/` is the pre-migration
# layout and is kept because fork branches still carry it.
PATH_TAXONOMY: list[tuple[str, int, tuple[str, ...]]] = [
    ("addingTasks", 1, ("tasks/", "devops_bench/tasks/")),
    ("addingHarness", 1, ("devops_bench/agents/", "pkg/agents/runner/")),
    ("addingVerifiers", 1, ("devops_bench/verification/", "pkg/agents/verifier/")),
    ("addingProvider", 1, ("devops_bench/providers/", "devops_bench/models/")),
    ("changingGrading", 1, ("devops_bench/metrics/", "pkg/evaluator/")),
    ("addingChaos", 1, ("devops_bench/chaos/", "pkg/agents/chaos/")),
    ("addingSkills", 1, ("skills/", "devops_bench/skills/")),
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

CLASS_LABELS = {
    "addingTasks": "Adding tasks",
    "addingHarness": "Adding a harness",
    "addingVerifiers": "Adding verifiers",
    "addingProvider": "Adding a model provider",
    "changingGrading": "Changing grading",
    "addingChaos": "Adding chaos scenarios",
    "addingSkills": "Adding skills",
    "infrastructure": "Infrastructure",
    "core": "Core changes",
    "tests": "Tests",
    "docs": "Documentation",
    "unclassified": "Unclassified",
}

UNCLASSIFIED_TIER = 9

CI_PATH = re.compile(r"(^|/)(\.github/workflows/|Makefile$|.*\.sh$|\.gitlab-ci\.yml$|Dockerfile)")
MANIFEST_PATH = re.compile(r"(^|/)(pyproject\.toml|requirements[^/]*\.txt|setup\.cfg|uv\.lock)$")
IMPORT_QUERIES = ('"import devops_bench"', '"from devops_bench"')


def classify_file(path: str) -> tuple[str, int]:
    for name, tier, prefixes in PATH_TAXONOMY:
        if any(path == p or path.startswith(p) for p in prefixes):
            return name, tier
    if path.endswith(".md"):
        return "docs", 3
    return "unclassified", UNCLASSIFIED_TIER


def classify_branch(branch: dict[str, Any]) -> dict[str, Any]:
    """Assign one primary class plus any number of secondary classes."""
    weight: dict[str, int] = {}
    tiers: dict[str, int] = {}
    for f in branch["files"]:
        name, tier = classify_file(f["path"])
        weight[name] = weight.get(name, 0) + max(f.get("changes", 0), 1)
        tiers[name] = tier

    # Lowest tier wins; more changed lines breaks a tie inside a tier.
    primary = (
        min(weight, key=lambda n: (tiers[n], -weight[n], n)) if weight else "unclassified"
    )

    return {
        "name": branch["name"],
        "primary": primary,
        "secondary": sorted(n for n in weight if n != primary),
        "changedFiles": len(branch["files"]),
        "additions": branch["additions"],
        "deletions": branch["deletions"],
        "fileListTruncated": branch.get("fileListTruncated", False),
    }


def classify_reference(hit: dict[str, Any], query: str) -> str | None:
    """Map one code-search hit to Depending / Running / Citing."""
    if hit["repo"] in CANONICAL_REPOS:
        return None  # self-reference, not adoption
    path = hit["path"]
    if query in IMPORT_QUERIES:
        return "depending"
    if MANIFEST_PATH.search(path):
        return "depending"
    if CI_PATH.search(path):
        return "running"
    if path.endswith(".md"):
        return "citing"
    return "citing"


def classify_repo(entry: dict[str, Any], contributors: set[str]) -> dict[str, Any]:
    """Classify one repository's forks and branches.

    `contributors` is the union across every repository in the snapshot: the two
    repos are the same project, so someone who contributed upstream is not an
    external adopter just because they forked the mirror.
    """
    forks_raw = entry["forks"]["value"]

    out: dict[str, Any] = {
        "repo": entry["repo"]["value"],
        "traffic": entry["traffic"]["value"],
        "trafficUnavailable": entry["traffic"]["unavailable"],
        "contributorCount": (
            len(entry["contributors"]["value"]) if entry["contributors"]["value"] else None
        ),
    }

    if forks_raw is None:
        out["forks"] = None
        out["forksUnavailable"] = entry["forks"]["unavailable"]
        out["extensions"] = None
        return out

    extensions = {name: 0 for name in CLASS_LABELS}
    forks = []
    for fork in forks_raw:
        external = fork["owner"] not in contributors
        branches = [classify_branch(b) for b in fork["branches"]]
        for b in branches:
            extensions[b["primary"]] += 1
        forks.append(
            {
                "fullName": fork["fullName"],
                "external": external,
                "divergentBranches": len(branches),
                "branches": branches,
                "unavailable": fork["unavailable"],
            }
        )

    out["forks"] = forks
    out["forksUnavailable"] = None
    out["extensions"] = extensions
    return out


def ratio(numerator: int, denominator: int) -> float | None:
    """Null, never zero, when the denominator is zero."""
    return None if denominator == 0 else numerator / denominator


def classify(snapshot: dict[str, Any]) -> dict[str, Any]:
    contributors: set[str] = set()
    for entry in snapshot["repos"].values():
        contributors |= set(entry["contributors"]["value"] or [])

    repos = {
        name: classify_repo(entry, contributors)
        for name, entry in snapshot["repos"].items()
    }

    references = {"depending": 0, "running": 0, "citing": 0}
    reference_hits: list[dict[str, Any]] = []
    queries = []
    for result in snapshot["references"]:
        value = result["value"]
        queries.append(
            {
                "query": value["query"] if value else None,
                "unavailable": result["unavailable"],
                "hits": len(value["hits"]) if value else None,
            }
        )
        if not value:
            continue
        for hit in value["hits"]:
            cls = classify_reference(hit, value["query"])
            if cls is None:
                continue
            references[cls] += 1
            reference_hits.append({**hit, "class": cls})

    all_forks = [f for r in repos.values() for f in (r["forks"] or [])]
    all_branches = [b for f in all_forks for b in f["branches"]]
    external_forks = [f for f in all_forks if f["external"]]
    external_branches = [b for f in external_forks for b in f["branches"]]

    unique_visitors = 0
    unique_cloners = 0
    traffic_partial = False
    for r in repos.values():
        if r["traffic"]:
            unique_visitors += r["traffic"]["views"]["unique"]
            unique_cloners += r["traffic"]["clones"]["unique"]
        else:
            traffic_partial = True

    unclassified = sum(
        (r["extensions"] or {}).get("unclassified", 0) for r in repos.values()
    )

    engaged = len(external_forks) + sum(references.values())

    return {
        "collectedAt": snapshot["collectedAt"],
        "windowDays": snapshot["windowDays"],
        "classLabels": CLASS_LABELS,
        "repos": repos,
        "references": references,
        "referenceHits": reference_hits,
        "referenceQueries": queries,
        "totals": {
            "forks": len(all_forks),
            "externalForks": len(external_forks),
            # A person who forked both repos is one adopter, not two.
            "externalOwners": len({f["fullName"].split("/")[0].lower() for f in external_forks}),
            "contributors": len(contributors),
            "divergentBranches": len(all_branches),
            "externalDivergentBranches": len(external_branches),
            "uniqueVisitors": unique_visitors,
            "uniqueCloners": unique_cloners,
            "trafficPartial": traffic_partial,
        },
        "derived": {
            "externalForkRatio": ratio(len(external_forks), len(all_forks)),
            "externalBranchRatio": ratio(len(external_branches), len(all_branches)),
            "unclassifiedRate": ratio(unclassified, len(all_branches)),
            "conversionRate": ratio(engaged, unique_visitors),
            "clonesPerUniqueCloner": ratio(
                sum(
                    r["traffic"]["clones"]["total"] for r in repos.values() if r["traffic"]
                ),
                unique_cloners,
            ),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("snapshot", type=Path, help="raw snapshot JSON from collect.py")
    parser.add_argument("--out", type=Path, help="write classified JSON here (default stdout)")
    args = parser.parse_args()

    result = classify(json.loads(args.snapshot.read_text()))
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
