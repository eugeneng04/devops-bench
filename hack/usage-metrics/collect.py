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
"""Ask GitHub for everything, once, and write one dated snapshot.

The only program here that touches the network. It records what GitHub said and
nothing more; every judgement about what the numbers mean lives in classify.py,
so a revised taxonomy can be re-run over every snapshot ever taken.

Three rules it will not break:

  A measurement that could not be taken is null plus a reason, never zero.
  One broken fork loses that fork, not the run.
  A run that dies half way leaves a file marked partial, and never overwrites
  a complete one from the same day.

The snapshot contains contributor and author logins. It is raw input, not a
published artifact — see PRODUCTION_PLAN.md 7.3.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.parse
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

from ghclient import GitHub, Unavailable
from store import SNAPSHOT_FORMAT, FileStore, open_store, provenance

REPOS = ["gke-labs/devops-bench", "kubernetes-sigs/devops-bench"]

# Forking is unrestricted, and the per-fork branch comparison is the expensive
# part of the run. A cap keeps one popular week from exhausting the hourly
# budget; whatever it skips is recorded so a capped run never reads as full
# coverage.
MAX_FORKS_PER_RUN = 120

# Code search is capped at 10 requests/minute, two orders of magnitude tighter
# than the core API. Every query added here spends part of that budget.
CODE_SEARCH_INTERVAL_SECONDS = 7

# Accounts that are automation. __typename == "Bot" and a trailing [bot] catch
# most of them; these are the ones that look like ordinary users. Filtering by
# all three matters most for time-to-first-response, where prow answers every
# pull request within seconds.
KNOWN_BOTS = {
    "devops-bench-sync-bot",
    "k8s-ci-robot",
    "k8s-triage-robot",
    "github-actions",
    "dependabot",
    "coderabbitai",
    "easycla",
    "linux-foundation-easycla",
    # A shared account that signs commits written through Claude Code. It is
    # type User with no [bot] suffix, so nothing else here catches it, and four
    # commits on a fork made it read as an outside adopter.
    "claude",
}

# Hand-maintained overrides for the inside/outside decision, kept out of the
# code so changing one is an edit to a list rather than a patch. See the file's
# own comment: it is an override list, not a roster. Affiliation is derived from
# the contributors API and from who authored each commit; this names only the
# people those rules get wrong.
AFFILIATION_FILE = Path(__file__).parent / "affiliation.json"

SEARCH_QUERIES = [
    '"import devops_bench"',
    '"from devops_bench"',
    '"gke-labs/devops-bench"',
    '"kubernetes-sigs/devops-bench"',
]

# A query whose answer is known and cannot be zero. If it comes back empty the
# search index or the token is the problem, and every reference figure in the
# run is unavailable rather than zero. Without this, "nobody references us" and
# "search is broken" were the same output — which is what happened.
CONTROL_QUERY = '"devops_bench" repo:gke-labs/devops-bench'

PULL_REQUESTS_QUERY = """
query($owner:String!, $name:String!, $cursor:String) {
  repository(owner:$owner, name:$name) {
    pullRequests(first:25, after:$cursor, orderBy:{field:CREATED_AT, direction:ASC}) {
      totalCount
      pageInfo { hasNextPage endCursor }
      nodes {
        number state merged isDraft createdAt mergedAt closedAt
        additions deletions changedFiles
        author { login __typename }
        files(first:100) {
          totalCount
          pageInfo { hasNextPage endCursor }
          nodes { path additions deletions }
        }
        reviews(first:100) {
          totalCount
          nodes { state submittedAt author { login __typename } }
        }
        comments(first:50) {
          totalCount
          nodes { createdAt author { login __typename } }
        }
      }
    }
  }
}
"""

PULL_REQUEST_FILES_QUERY = """
query($owner:String!, $name:String!, $number:Int!, $cursor:String) {
  repository(owner:$owner, name:$name) {
    pullRequest(number:$number) {
      files(first:100, after:$cursor) {
        pageInfo { hasNextPage endCursor }
        nodes { path additions deletions }
      }
    }
  }
}
"""

ISSUES_QUERY = """
query($owner:String!, $name:String!, $cursor:String) {
  repository(owner:$owner, name:$name) {
    issues(first:50, after:$cursor, orderBy:{field:CREATED_AT, direction:ASC}) {
      totalCount
      pageInfo { hasNextPage endCursor }
      nodes {
        number state createdAt closedAt
        author { login __typename }
        comments(first:50) {
          totalCount
          nodes { createdAt author { login __typename } }
        }
      }
    }
  }
}
"""


def measure(fn: Callable[[], Any]) -> dict[str, Any]:
    """Run a collection step, capturing failure as a reason rather than a zero.

    Catches everything, not just Unavailable. A response that arrives in an
    unexpected shape is a failed measurement like any other; letting the
    KeyError propagate discards the whole run, including every step that
    already succeeded.
    """
    try:
        return {"value": fn(), "unavailable": None}
    except Unavailable as exc:
        return {"value": None, "unavailable": str(exc)}
    except Exception as exc:  # noqa: BLE001 - see docstring
        return {"value": None, "unavailable": f"unexpected {type(exc).__name__}: {exc}"}


def actor(node: dict[str, Any] | None) -> dict[str, Any] | None:
    """A GraphQL author, normalised. None when the account has been deleted."""
    if not node or not node.get("login"):
        return None
    login = node["login"].lower()
    return {
        "login": login,
        "type": node.get("__typename", "User"),
        "isBot": is_bot(login, node.get("__typename")),
    }


def is_bot(login: str, typename: str | None = None) -> bool:
    login = login.lower()
    return (
        typename == "Bot"
        or login.endswith("[bot]")
        or login.removesuffix("[bot]") in KNOWN_BOTS
    )


def collect_repo(gh: GitHub, repo: str) -> dict[str, Any]:
    r = gh.rest(f"repos/{repo}")
    return {
        "stars": r["stargazers_count"],
        "forks": r["forks_count"],
        "watchers": r["subscribers_count"],
        # GitHub's open_issues_count is issues plus pull requests. The old name
        # said "issues" and the dashboard read it as issues.
        "openIssuesAndPulls": r["open_issues_count"],
        "defaultBranch": r["default_branch"],
        "createdAt": r["created_at"],
        "pushedAt": r["pushed_at"],
    }


def collect_traffic(gh: GitHub, repo: str) -> dict[str, Any]:
    views = gh.rest(f"repos/{repo}/traffic/views")
    clones = gh.rest(f"repos/{repo}/traffic/clones")
    referrers = gh.rest(f"repos/{repo}/traffic/popular/referrers")
    paths = gh.rest(f"repos/{repo}/traffic/popular/paths")
    return {
        "views": {
            "total": views["count"],
            # Non-additive: this is unique visitors over the whole 14 days, not
            # a figure that can be summed with any other window's.
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


def collect_contributors(gh: GitHub, repo: str) -> dict[str, Any]:
    people = gh.paginate(f"repos/{repo}/contributors")
    logins = {p["login"].lower() for p in people if p.get("type") == "User"}
    return {
        "humans": sorted(login for login in logins if not is_bot(login)),
        "bots": sorted(login for login in logins if is_bot(login)),
    }


def head_sha(gh: GitHub, repo: str, branch: str) -> str | None:
    return gh.rest(f"repos/{repo}/branches/{_escape(branch)}")["commit"]["sha"]


def _escape(ref: str) -> str:
    """Make a git ref safe in a URL path.

    A `#` is legal in a ref name and truncates the request as a fragment, so the
    comparison silently runs against something else. Slashes stay literal —
    branch names contain them and the compare endpoint expects them raw.
    """
    return urllib.parse.quote(ref, safe="/")


def compare_branch(gh: GitHub, repo: str, base: str, owner: str, branch: str) -> dict[str, Any]:
    path = f"repos/{repo}/compare/{_escape(base)}...{_escape(owner)}:{_escape(branch)}"
    cmp = gh.rest(path)
    commits = cmp.get("commits", [])
    files = cmp.get("files", [])
    complete = len(commits) == cmp.get("total_commits", len(commits))
    # Who wrote the work, not who holds the fork. Already in this response, so
    # it costs nothing. A commit whose email matches no account has author null
    # and contributes no evidence rather than a login nobody can check.
    authors: dict[str, int] = {}
    for c in commits:
        who = c.get("author")
        if who and not is_bot(who["login"], who.get("type")):
            login = who["login"].lower()
            authors[login] = authors.get(login, 0) + 1
    return {
        "aheadBy": cmp["ahead_by"],
        "behindBy": cmp.get("behind_by", 0),
        # Raw counts, not a derived boolean. GitHub caps the file list at 300
        # for the whole comparison and there is no way to page past it, so a
        # stored "truncated: false" tells you nothing about how close it came.
        # These let classification refuse to report a share it cannot support.
        "totalCommits": cmp.get("total_commits"),
        "commitsReturned": len(commits),
        "filesReturned": len(files),
        "authors": [{"login": l, "commits": n} for l, n in sorted(authors.items())],
        "authorsComplete": complete,
        "commitsUnattributed": sum(1 for c in commits if not c.get("author")),
        "baseSha": cmp.get("base_commit", {}).get("sha"),
        "mergeBaseSha": cmp.get("merge_base_commit", {}).get("sha"),
        # The head commit's date, for divergence age. Only trustworthy when the
        # commit list came back whole; past 250 commits the last one returned is
        # not the head.
        "headCommittedAt": (
            commits[-1]["commit"]["committer"]["date"] if commits and complete else None
        ),
        "additions": sum(f.get("additions", 0) for f in files),
        "deletions": sum(f.get("deletions", 0) for f in files),
        "files": [{"path": f["filename"], "changes": f.get("changes", 0)} for f in files],
    }


def collect_fork(
    gh: GitHub, repo: str, base: str, base_sha: str | None, fork: dict[str, Any]
) -> dict[str, Any]:
    """One fork and the branches on it that have diverged from upstream.

    Everything is caught per branch and per fork. The old version let one bad
    comparison escape the whole loop, throwing away every fork already
    collected in that pass and replacing all of them with a single null.
    """
    owner = fork["owner"]["login"].lower()
    entry: dict[str, Any] = {
        "fullName": fork["full_name"],
        "owner": owner,
        "createdAt": fork["created_at"],
        "pushedAt": fork["pushed_at"],
        # Already in the listing response, so the size of the forks-of-forks
        # blind spot costs nothing to record.
        "forksOfThisFork": fork.get("forks_count", 0),
        "branches": [],
        "unavailable": None,
    }
    try:
        branches = gh.paginate(f"repos/{fork['full_name']}/branches")
    except Unavailable as exc:
        entry["unavailable"] = str(exc)
        return entry

    for branch in branches:
        name = branch["name"]
        # A branch whose head is upstream's head is a stale copy. This is a
        # same-run equality test, not a cached result from last week: the
        # comparison is three-dot, so it depends on both ends and upstream
        # moves every week.
        if base_sha and branch.get("commit", {}).get("sha") == base_sha:
            continue
        record: dict[str, Any] = {"name": name, "headSha": branch.get("commit", {}).get("sha")}
        try:
            record.update(compare_branch(gh, repo, base, owner, name))
            record["unavailable"] = None
        except Unavailable as exc:
            # Keep the branch. Dropping it made a throttled request and a branch
            # that shares no history produce the same output: nothing.
            record["unavailable"] = str(exc)
            entry["branches"].append(record)
            continue
        if record["aheadBy"] == 0:
            continue
        entry["branches"].append(record)
    return entry


def list_forks(gh: GitHub, repo: str) -> list[dict[str, Any]]:
    """Oldest first. The listing default is newest first, so a fork created
    mid-pagination shifts every later page boundary and silently duplicates or
    drops entries. Oldest-first is append-only."""
    return gh.paginate(f"repos/{repo}/forks", {"sort": "oldest"})


def collect_pull_requests(gh: GitHub, repo: str) -> dict[str, Any]:
    """Every pull request, with its reviews, comments and changed files.

    GraphQL because the REST equivalent is roughly one request per pull request
    plus one per review page; this is four requests for two hundred.
    """
    owner, name = repo.split("/")
    out: list[dict[str, Any]] = []
    cursor, total = None, None
    while True:
        page = gh.graphql(PULL_REQUESTS_QUERY, owner=owner, name=name, cursor=cursor)[
            "repository"
        ]["pullRequests"]
        total = page["totalCount"]
        for node in page["nodes"]:
            out.append(_pull_request(gh, owner, name, node))
        if not page["pageInfo"]["hasNextPage"]:
            break
        cursor = page["pageInfo"]["endCursor"]
    return {"totalCount": total, "collected": len(out), "items": out}


def _pull_request(gh: GitHub, owner: str, name: str, node: dict[str, Any]) -> dict[str, Any]:
    files = [dict(f) for f in node["files"]["nodes"]]
    if node["files"]["pageInfo"]["hasNextPage"]:
        files += _all_files(gh, owner, name, node["number"], node["files"]["pageInfo"]["endCursor"])
    return {
        "number": node["number"],
        "state": node["state"],
        "merged": node["merged"],
        "isDraft": node["isDraft"],
        "createdAt": node["createdAt"],
        "mergedAt": node["mergedAt"],
        "closedAt": node["closedAt"],
        "author": actor(node["author"]),
        "additions": node["additions"],
        "deletions": node["deletions"],
        "changedFiles": node["changedFiles"],
        "files": files,
        "reviews": [
            {"state": r["state"], "submittedAt": r["submittedAt"], "author": actor(r["author"])}
            for r in node["reviews"]["nodes"]
        ],
        "reviewCount": node["reviews"]["totalCount"],
        # Recorded rather than assumed away: if every comment on the page is a
        # bot and there are more, first-human-response is unknown for this pull
        # request and has to be reported as such.
        "comments": [
            {"createdAt": c["createdAt"], "author": actor(c["author"])}
            for c in node["comments"]["nodes"]
        ],
        "commentCount": node["comments"]["totalCount"],
    }


def _all_files(gh: GitHub, owner: str, name: str, number: int, cursor: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    while cursor:
        page = gh.graphql(
            PULL_REQUEST_FILES_QUERY, owner=owner, name=name, number=number, cursor=cursor
        )["repository"]["pullRequest"]["files"]
        out += [dict(f) for f in page["nodes"]]
        cursor = page["pageInfo"]["endCursor"] if page["pageInfo"]["hasNextPage"] else None
    return out


def collect_issues(gh: GitHub, repo: str) -> dict[str, Any]:
    owner, name = repo.split("/")
    out: list[dict[str, Any]] = []
    cursor, total = None, None
    while True:
        page = gh.graphql(ISSUES_QUERY, owner=owner, name=name, cursor=cursor)["repository"][
            "issues"
        ]
        total = page["totalCount"]
        for node in page["nodes"]:
            out.append(
                {
                    "number": node["number"],
                    "state": node["state"],
                    "createdAt": node["createdAt"],
                    "closedAt": node["closedAt"],
                    "author": actor(node["author"]),
                    "comments": [
                        {"createdAt": c["createdAt"], "author": actor(c["author"])}
                        for c in node["comments"]["nodes"]
                    ],
                    "commentCount": node["comments"]["totalCount"],
                }
            )
        if not page["pageInfo"]["hasNextPage"]:
            break
        cursor = page["pageInfo"]["endCursor"]
    return {"totalCount": total, "collected": len(out), "items": out}


def code_search(gh: GitHub, query: str) -> dict[str, Any]:
    """The REST endpoint, not `gh search code`.

    The CLI re-quotes its argument, so a quoted phrase became a literal search
    token and matched nothing — then the empty result was recorded as a
    successful measurement of zero.
    """
    result = gh.rest("search/code", {"q": query, "per_page": 100})
    return {
        "query": query,
        "totalCount": result["total_count"],
        "incomplete": result.get("incomplete_results", False),
        "hits": [
            {"repo": item["repository"]["full_name"], "path": item["path"]}
            for item in result.get("items", [])
        ],
    }


def collect_references(gh: GitHub, sleep: Callable[[float], None] = time.sleep) -> dict[str, Any]:
    control = measure(lambda: code_search(gh, CONTROL_QUERY))
    trustworthy = bool(control["value"]) and control["value"]["totalCount"] > 0
    queries = []
    for query in SEARCH_QUERIES:
        if not trustworthy:
            queries.append(
                {
                    "value": {"query": query},
                    "unavailable": "control query returned nothing; search is not trustworthy this run",
                }
            )
            continue
        sleep(CODE_SEARCH_INTERVAL_SECONDS)
        queries.append(measure(lambda q=query: code_search(gh, q)))
    return {"control": control, "trustworthy": trustworthy, "queries": queries}


def read_overrides(path: Path) -> tuple[set[str], set[str]]:
    """The hand-maintained inside/outside overrides.

    A login in both lists is an error rather than a tie-break. Silently letting
    one win is the shape of the bug this file replaced: a login could sit in
    both published lists, and since only one of them is read, correcting an
    affiliation by hand did nothing and reported nothing.
    """
    if not path.exists():
        return set(), set()
    data = json.loads(path.read_text())
    inside = {login.lower() for login in data.get("inside", [])}
    outside = {login.lower() for login in data.get("outside", [])}
    both = inside & outside
    if both:
        raise SystemExit(f"{path}: {', '.join(sorted(both))} listed as both inside and outside")
    return inside, outside


def freeze_affiliation(
    previous: dict[str, Any],
    contributors: set[str],
    seen: set[str],
    overrides: tuple[set[str], set[str]] = (frozenset(), frozenset()),
) -> dict[str, Any]:
    """Decide inside-or-outside now, and never revisit it.

    Recomputing affiliation against today's contributor list means that the day
    the one genuine outside contributor lands a pull request, re-classifying
    history converts every past outside signal into an inside one: the trend
    rewrites itself and the milestone un-happens. So anyone ever seen as outside
    stays outside, even after they contribute.

    `seen` is who wrote and said things, not who holds repositories - see the
    caller. Holding a fork is not adopting a project.

    `overrides` beats everything here, the freeze included. The freeze exists so
    a derived answer cannot be recomputed away; a human saying "this account is
    ours" is not a derived answer, and leaving it unable to correct the record
    is how a wrong label becomes permanent.
    """
    forced_inside, forced_outside = overrides
    was_inside = set(previous.get("insideLogins", []))
    was_outside = set(previous.get("outsideLogins", []))
    derived_inside = was_inside | {c for c in contributors if c not in was_outside}
    inside = (derived_inside | forced_inside) - forced_outside
    # `- inside` because a login must never land in both lists: naming a frozen
    # outsider as an inside org used to add it to inside and leave it in
    # outside, and classification reads outside, so the change did nothing.
    outside = (was_outside | forced_outside | {s for s in seen if not is_bot(s)}) - inside
    return {
        "insideLogins": sorted(inside),
        "outsideLogins": sorted(outside),
        "overrides": {"inside": sorted(forced_inside), "outside": sorted(forced_outside)},
        "source": "contributors API and commit authorship, overridden by affiliation.json, frozen at first sighting",
        "carriedFrom": previous.get("frozenAt"),
        "frozenAt": datetime.now(UTC).date().isoformat(),
    }


def covers_less_than_stored(store: FileStore, date: str, skipped: list[str]) -> str | None:
    """Would writing this run lose signals a snapshot already on disk has?

    A run with --skip-forks finishes cleanly and is not partial, but it knows
    strictly less than a full run from the same morning. Overwriting silently
    turns a complete day into a thin one, which reads downstream as a week where
    nobody forked anything.
    """
    try:
        stored = set(store.get("snapshot", date).get("skipped", []))
    except Exception:  # noqa: BLE001 - nothing there, or unreadable: nothing to lose
        return None
    return ", ".join(sorted(set(skipped) - stored)) if stored < set(skipped) else None


def previous_affiliation(store: FileStore) -> dict[str, Any]:
    for date in reversed(store.list("snapshot")):
        try:
            return store.get("snapshot", date).get("affiliation") or {}
        except Exception as exc:  # noqa: BLE001 - an unreadable old snapshot is not fatal
            print(f"  ignoring snapshot {date}: {exc}", file=sys.stderr)
    return {}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--store",
        default=f"file:{Path(__file__).parent}",
        help="where records live; file:<path>, which in production is the data repository",
    )
    parser.add_argument("--skip-forks", action="store_true", help="skip the branch comparison")
    parser.add_argument("--skip-pulls", action="store_true", help="skip pull requests and issues")
    parser.add_argument("--skip-search", action="store_true", help="skip code search")
    parser.add_argument("--max-forks", type=int, default=MAX_FORKS_PER_RUN)
    parser.add_argument(
        "--force", action="store_true", help="overwrite a fuller snapshot from the same day"
    )
    # The freeze protects a measurement from being recomputed away. It does not
    # protect a rule that was wrong: affiliation used to come from who held a
    # fork, and the logins that produced misread this way carry forward forever
    # on their own. Discarding the carried affiliation is a deliberate, visible
    # act — the snapshot records carriedFrom as null.
    parser.add_argument(
        "--affiliation",
        default=str(AFFILIATION_FILE),
        help="hand-maintained inside/outside overrides",
    )
    parser.add_argument(
        "--refreeze",
        action="store_true",
        help="ignore the carried affiliation and decide it from this run alone",
    )
    args = parser.parse_args()

    store = open_store(args.store)
    gh = GitHub()
    collected_at = datetime.now(UTC).replace(microsecond=0)
    date = collected_at.date().isoformat()
    skipped = [
        name
        for name, flag in (
            ("forks", args.skip_forks),
            ("pulls", args.skip_pulls),
            ("search", args.skip_search),
        )
        if flag
    ]
    lost = covers_less_than_stored(store, date, skipped)
    if lost and not args.force:
        print(
            f"{date} already has a snapshot that collected {lost}. Re-run without "
            f"the skip flags, or pass --force to replace it with this thinner one.",
            file=sys.stderr,
        )
        return 2

    snapshot: dict[str, Any] = {
        "apiVersion": "devops-bench.k8s.io/v1alpha1",
        "kind": "UsageSnapshot",
        "formatVersion": SNAPSHOT_FORMAT,
        "collectedAt": collected_at.isoformat().replace("+00:00", "Z"),
        "windowDays": 14,
        "partial": True,
        # Which signals this run did not even ask for. A skipped signal is not
        # an unavailable one, and neither is a zero.
        "skipped": skipped,
        "provenance": provenance(),
        "repos": {},
    }

    def checkpoint() -> None:
        """A run killed by the job time limit leaves a partial file rather than
        nothing, and it is written under its own key so it can never be mistaken
        for, or overwrite, a complete snapshot from the same day."""
        snapshot["budget"] = gh.budget
        snapshot["apiCalls"] = gh.calls
        store.put("snapshot", f"{date}.partial", snapshot)

    seen_logins: set[str] = set()
    contributors: set[str] = set()

    for repo in REPOS:
        print(f"collecting {repo}", file=sys.stderr)
        facts = measure(lambda r=repo: collect_repo(gh, r))
        base = (facts["value"] or {}).get("defaultBranch", "main")
        people = measure(lambda r=repo: collect_contributors(gh, r))
        contributors |= set((people["value"] or {}).get("humans", []))

        entry: dict[str, Any] = {
            "repo": facts,
            "traffic": measure(lambda r=repo: collect_traffic(gh, r)),
            "contributors": people,
        }
        snapshot["repos"][repo] = entry
        checkpoint()

        if args.skip_pulls:
            entry["pullRequests"] = {"value": None, "unavailable": "skipped by flag"}
            entry["issues"] = {"value": None, "unavailable": "skipped by flag"}
        else:
            print("  pull requests", file=sys.stderr)
            entry["pullRequests"] = measure(lambda r=repo: collect_pull_requests(gh, r))
            print("  issues", file=sys.stderr)
            entry["issues"] = measure(lambda r=repo: collect_issues(gh, r))
            for kind in ("pullRequests", "issues"):
                for item in (entry[kind]["value"] or {}).get("items", []):
                    # Reviewers and commenters too. Four people who have only
                    # ever reviewed or commented were in neither list.
                    people = [item["author"]]
                    people += [r["author"] for r in item.get("reviews", [])]
                    people += [c["author"] for c in item.get("comments", [])]
                    for who in people:
                        if who and not is_bot(who["login"], who.get("type")):
                            seen_logins.add(who["login"].lower())
        checkpoint()

        if args.skip_forks:
            entry["forks"] = {"value": None, "unavailable": "skipped by flag"}
            continue

        print("  forks", file=sys.stderr)
        listing = measure(lambda r=repo: list_forks(gh, r))
        forks = listing["value"] or []
        upstream_head = measure(lambda r=repo, b=base: head_sha(gh, r, b))
        collected: list[dict[str, Any]] = []
        entry["forks"] = {
            "value": {
                # GitHub's fork counter and the forks it will actually list do
                # not agree — private forks, blocked accounts, a counter that is
                # not always decremented. Persistent, not a race, so it is
                # recorded rather than gated on.
                "countReported": (facts["value"] or {}).get("forks"),
                "countListed": len(forks),
                "skippedByCap": max(0, len(forks) - args.max_forks),
                "upstreamHeadSha": upstream_head["value"],
                "items": collected,
            },
            "unavailable": listing["unavailable"],
        }
        for fork in forks[: args.max_forks]:
            record = collect_fork(gh, repo, base, upstream_head["value"], fork)
            collected.append(record)
            # Who wrote the work, not who holds the fork. Ownership was the
            # signal and it is wrong in both directions: an org account can hold
            # a contributor's branches, and a contributor's fork can carry
            # commits written by someone outside. Ownership is evidence only
            # when there are no commits to read - a fork nobody has touched.
            # .get because a branch whose comparison failed is kept with a
            # reason and nothing else; it is not evidence either way.
            wrote = {a["login"] for b in record["branches"] for a in b.get("authors", [])}
            seen_logins |= wrote or {record["owner"]}
            checkpoint()
        if len(forks) > args.max_forks:
            print(f"  capped at {args.max_forks} of {len(forks)} forks", file=sys.stderr)

    if args.skip_search:
        snapshot["references"] = {"control": None, "trustworthy": False, "queries": []}
    else:
        print("collecting code-search references", file=sys.stderr)
        snapshot["references"] = collect_references(gh)

    snapshot["affiliation"] = freeze_affiliation(
        {} if args.refreeze else previous_affiliation(store),
        contributors,
        seen_logins,
        read_overrides(Path(args.affiliation)),
    )
    snapshot["partial"] = False
    snapshot["budget"] = gh.budget
    snapshot["apiCalls"] = gh.calls

    path = store.put("snapshot", date, snapshot)
    store.delete("snapshot", f"{date}.partial")
    print(f"{path}  ({gh.calls} API calls)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
