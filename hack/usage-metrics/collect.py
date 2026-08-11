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
"""Collect public usage signals for devops-bench into a dated snapshot.

Reads only public GitHub data plus the traffic API (which needs push access on
the repository being measured). Writes raw observations; classification lives in
classify.py so the taxonomy can be re-run over old snapshots when it changes.

A measurement that could not be taken is recorded as null with a reason, never
as zero.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPOS = ["gke-labs/devops-bench", "kubernetes-sigs/devops-bench"]

# Code search is capped at 10 requests/minute, two orders of magnitude tighter
# than the core API. Every query added here spends part of that budget.
CODE_SEARCH_INTERVAL_SECONDS = 7

# Branches on a fork that are just a stale copy of upstream are noise.
BORING_BRANCHES = {"main", "master", "gh-pages"}


class Unavailable(Exception):
    """A measurement could not be taken. Recorded as null plus this reason."""


def gh_api(path: str, paginate: bool = False) -> Any:
    cmd = ["gh", "api", path]
    if paginate:
        cmd += ["--paginate", "--slurp"]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise Unavailable(result.stderr.strip().splitlines()[-1] if result.stderr else "gh api failed")
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise Unavailable(f"unparseable response: {exc}") from exc
    if paginate and isinstance(payload, list):
        return [item for page in payload for item in page]
    return payload


def measure(fn) -> dict[str, Any]:
    """Run a collection step, capturing failure as a reason rather than a zero."""
    try:
        return {"value": fn(), "unavailable": None}
    except Unavailable as exc:
        return {"value": None, "unavailable": str(exc)}


def collect_repo(repo: str) -> dict[str, Any]:
    r = gh_api(f"repos/{repo}")
    return {
        "stars": r["stargazers_count"],
        "forks": r["forks_count"],
        "watchers": r["subscribers_count"],
        "openIssues": r["open_issues_count"],
        "defaultBranch": r["default_branch"],
        "createdAt": r["created_at"],
        "pushedAt": r["pushed_at"],
    }


def collect_traffic(repo: str) -> dict[str, Any]:
    views = gh_api(f"repos/{repo}/traffic/views")
    clones = gh_api(f"repos/{repo}/traffic/clones")
    referrers = gh_api(f"repos/{repo}/traffic/popular/referrers")
    paths = gh_api(f"repos/{repo}/traffic/popular/paths")
    return {
        "views": {
            "total": views["count"],
            "unique": views["uniques"],
            "daily": [
                {"date": d["timestamp"][:10], "total": d["count"], "unique": d["uniques"]}
                for d in views["views"]
            ],
        },
        "clones": {
            "total": clones["count"],
            "unique": clones["uniques"],
            "daily": [
                {"date": d["timestamp"][:10], "total": d["count"], "unique": d["uniques"]}
                for d in clones["clones"]
            ],
        },
        "referrers": [
            {"source": r["referrer"], "total": r["count"], "unique": r["uniques"]}
            for r in referrers
        ],
        "popularPaths": [
            {"path": p["path"], "title": p["title"], "total": p["count"], "unique": p["uniques"]}
            for p in paths
        ],
    }


def collect_contributors(repo: str) -> list[str]:
    people = gh_api(f"repos/{repo}/contributors?per_page=100", paginate=True)
    return sorted({p["login"].lower() for p in people if p.get("type") == "User"})


def collect_forks(repo: str, base_branch: str) -> list[dict[str, Any]]:
    """List forks and, for each, the branches that have diverged from upstream."""
    forks = gh_api(f"repos/{repo}/forks?per_page=100&sort=newest", paginate=True)
    out = []
    for fork in forks:
        entry: dict[str, Any] = {
            "fullName": fork["full_name"],
            "owner": fork["owner"]["login"].lower(),
            "createdAt": fork["created_at"],
            "pushedAt": fork["pushed_at"],
            "branches": [],
            "unavailable": None,
        }
        try:
            branches = gh_api(f"repos/{fork['full_name']}/branches?per_page=100", paginate=True)
        except Unavailable as exc:
            entry["unavailable"] = str(exc)
            out.append(entry)
            continue

        for branch in branches:
            name = branch["name"]
            if name in BORING_BRANCHES:
                continue
            try:
                cmp = gh_api(f"repos/{repo}/compare/{base_branch}...{entry['owner']}:{name}")
            except Unavailable:
                # Comparison across a fork fails when the branch shares no history.
                continue
            if cmp.get("ahead_by", 0) == 0:
                continue
            entry["branches"].append(
                {
                    "name": name,
                    "aheadBy": cmp["ahead_by"],
                    "behindBy": cmp.get("behind_by", 0),
                    "additions": sum(f.get("additions", 0) for f in cmp.get("files", [])),
                    "deletions": sum(f.get("deletions", 0) for f in cmp.get("files", [])),
                    # The compare API caps its file list at 300; past that the
                    # path taxonomy is working from a partial view.
                    "fileListTruncated": len(cmp.get("files", [])) >= 300,
                    "files": [
                        {"path": f["filename"], "changes": f.get("changes", 0)}
                        for f in cmp.get("files", [])
                    ],
                }
            )
        out.append(entry)
    return out


def code_search(query: str) -> dict[str, Any]:
    result = subprocess.run(
        ["gh", "search", "code", query, "--json", "repository,path", "--limit", "100"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise Unavailable(result.stderr.strip().splitlines()[-1] if result.stderr else "search failed")
    try:
        hits = json.loads(result.stdout or "[]")
    except json.JSONDecodeError as exc:
        raise Unavailable(f"unparseable search response: {exc}") from exc
    return {
        "query": query,
        "hits": [
            {"repo": h["repository"]["nameWithOwner"], "path": h["path"]}
            for h in hits
        ],
    }


# Exact, qualified queries only. A loose "devops-bench" search returns hundreds
# of hits from unrelated projects that merely carry the string as a tag.
SEARCH_QUERIES = [
    '"import devops_bench"',
    '"from devops_bench"',
    '"gke-labs/devops-bench"',
    '"kubernetes-sigs/devops-bench"',
]


def collect_references() -> list[dict[str, Any]]:
    results = []
    for i, query in enumerate(SEARCH_QUERIES):
        if i:
            time.sleep(CODE_SEARCH_INTERVAL_SECONDS)
        results.append(measure(lambda q=query: code_search(q)))
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out",
        type=Path,
        default=Path(__file__).parent / "snapshots",
        help="directory to write the dated snapshot into",
    )
    parser.add_argument(
        "--skip-forks",
        action="store_true",
        help="skip the per-fork branch comparison (the slowest step)",
    )
    args = parser.parse_args()

    collected_at = datetime.now(UTC).replace(microsecond=0)
    snapshot: dict[str, Any] = {
        "apiVersion": "devops-bench.k8s.io/v1alpha1",
        "kind": "UsageSnapshot",
        "collectedAt": collected_at.isoformat().replace("+00:00", "Z"),
        "windowDays": 14,
        "repos": {},
    }

    for repo in REPOS:
        print(f"collecting {repo}", file=sys.stderr)
        repo_data = measure(lambda r=repo: collect_repo(r))
        base = (repo_data["value"] or {}).get("defaultBranch", "main")
        entry: dict[str, Any] = {
            "repo": repo_data,
            "traffic": measure(lambda r=repo: collect_traffic(r)),
            "contributors": measure(lambda r=repo: collect_contributors(r)),
        }
        if args.skip_forks:
            entry["forks"] = {"value": None, "unavailable": "skipped by flag"}
        else:
            entry["forks"] = measure(lambda r=repo, b=base: collect_forks(r, b))
        snapshot["repos"][repo] = entry

    print("collecting code-search references", file=sys.stderr)
    snapshot["references"] = collect_references()

    args.out.mkdir(parents=True, exist_ok=True)
    path = args.out / f"{collected_at.date()}.json"
    path.write_text(json.dumps(snapshot, indent=2) + "\n")
    print(path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
