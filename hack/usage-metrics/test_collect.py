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
"""Tests for collection. No network: the GitHub client takes a fake runner.

What is worth testing here is not that a request succeeds — it is what happens
when one fails, because every one of these cases has silently corrupted a
published number before.
"""

from __future__ import annotations

import json

import pytest

import collect
import store
from ghclient import GitHub, Unavailable, parse_response, wait_seconds

PERMISSION_403 = """HTTP/2.0 403 Forbidden
X-Ratelimit-Limit: 5000
X-Ratelimit-Remaining: 4998
X-Ratelimit-Reset: 1786577782
X-Ratelimit-Resource: core

{"message":"Must have push access to repository","status":"403"}"""

SECONDARY_403 = """HTTP/2.0 403 Forbidden
X-Ratelimit-Remaining: 4998
X-Ratelimit-Resource: core

{"message":"You have exceeded a secondary rate limit."}"""

EXHAUSTED_403 = """HTTP/2.0 403 Forbidden
X-Ratelimit-Remaining: 0
X-Ratelimit-Reset: 1000060
X-Ratelimit-Resource: core

{"message":"API rate limit exceeded"}"""

SERVER_500 = """HTTP/2.0 500 Internal Server Error
X-Ratelimit-Resource: core

{"message":"Server Error"}"""


def ok(body: object, headers: str = "X-Ratelimit-Remaining: 4900\nX-Ratelimit-Resource: core") -> str:
    return f"HTTP/2.0 200 OK\n{headers}\n\n{json.dumps(body)}"


def client(responses: list[str], **kwargs) -> tuple[GitHub, list]:
    """A client whose next response is scripted, and the args it was called with."""
    seen: list[list[str]] = []

    def runner(args, timeout):
        seen.append(args)
        text = responses.pop(0)
        return (0 if text.startswith("HTTP/2.0 2") else 1, text, "")

    return GitHub(runner=runner, sleep=lambda _: None, clock=lambda: 1000000.0, **kwargs), seen


# --- parsing and the retry decision ---------------------------------------


def test_parse_response_splits_status_headers_and_body():
    response = parse_response(ok({"a": 1}))
    assert response.status == 200
    assert response.headers["x-ratelimit-remaining"] == "4900"
    assert response.json() == {"a": 1}


def test_parse_response_keeps_the_last_header_block_after_a_redirect():
    response = parse_response("HTTP/2.0 301 Moved\nLocation: /x\n\n" + ok({"a": 1}))
    assert response.status == 200
    assert response.json() == {"a": 1}


def test_a_permission_403_is_permanent():
    # The kubernetes-sigs traffic endpoint, on every run, forever. Retrying it
    # spends four requests and thirty seconds to learn the same thing.
    assert wait_seconds(parse_response(PERMISSION_403), now=1000000.0) is None


def test_a_secondary_limit_403_is_worth_waiting_for():
    assert wait_seconds(parse_response(SECONDARY_403), now=1000000.0) == 60.0


def test_an_exhausted_budget_waits_until_the_reset():
    assert wait_seconds(parse_response(EXHAUSTED_403), now=1000000.0) == 60.0


def test_a_5xx_is_not_retried():
    # A comparison too large to compute returns one, which is a property of the
    # branch. Retrying spends the most effort on the branches that fail again.
    assert wait_seconds(parse_response(SERVER_500), now=1000000.0) is None


def test_permission_failure_costs_exactly_one_request():
    gh, seen = client([PERMISSION_403])
    with pytest.raises(Unavailable, match="push access"):
        gh.rest("repos/x/y/traffic/views")
    assert len(seen) == 1


def test_a_throttled_request_is_retried_and_then_succeeds():
    gh, seen = client([SECONDARY_403, ok({"ok": True})])
    assert gh.rest("repos/x/y") == {"ok": True}
    assert len(seen) == 2


def test_a_limit_that_outlasts_the_run_is_recorded_rather_than_slept_through():
    far = EXHAUSTED_403.replace("1000060", "1003000")
    gh, _ = client([far])
    with pytest.raises(Unavailable, match="longer than this run will wait"):
        gh.rest("repos/x/y")


def test_the_remaining_budget_is_recorded():
    gh, _ = client([ok({}, "X-Ratelimit-Remaining: 17\nX-Ratelimit-Resource: search")])
    gh.rest("search/code")
    assert gh.budget["search"]["remaining"] == 17


# --- pagination ------------------------------------------------------------


def test_pagination_retries_one_page_not_all_of_them():
    # gh api --paginate emits nothing at all when any page fails, so a retry
    # re-fetches every page and a throttled run amplifies its own load.
    pages = [ok([{"n": i} for i in range(100)]), SECONDARY_403, ok([{"n": 100}])]
    gh, seen = client(pages)
    assert len(gh.paginate("repos/x/y/forks")) == 101
    assert [a[0].split("&page=")[1] for a in seen] == ["1", "2", "2"]


def test_pagination_stops_on_a_short_page():
    gh, seen = client([ok([{"n": 1}])])
    assert gh.paginate("repos/x/y/forks") == [{"n": 1}]
    assert len(seen) == 1


# --- failure is a value ----------------------------------------------------


def test_measure_survives_an_unexpected_response_shape():
    # A missing field used to propagate out of measure() and kill the run
    # before anything was written.
    result = collect.measure(lambda: {"a": 1}["missing"])
    assert result["value"] is None
    assert "KeyError" in result["unavailable"]


def test_a_failed_comparison_keeps_the_branch_with_a_reason():
    fork = {
        "full_name": "someone/devops-bench",
        "owner": {"login": "Someone"},
        "created_at": "2026-01-01T00:00:00Z",
        "pushed_at": "2026-01-02T00:00:00Z",
        "forks_count": 0,
    }
    gh, _ = client([ok([{"name": "wip", "commit": {"sha": "aaa"}}]), SERVER_500])
    entry = collect.collect_fork(gh, "gke-labs/devops-bench", "main", "upstream", fork)
    assert entry["branches"][0]["name"] == "wip"
    assert entry["branches"][0]["unavailable"]
    assert "aheadBy" not in entry["branches"][0]


def test_one_unlistable_fork_does_not_lose_the_others():
    fork = {
        "full_name": "someone/devops-bench",
        "owner": {"login": "someone"},
        "created_at": "2026-01-01T00:00:00Z",
        "pushed_at": "2026-01-02T00:00:00Z",
        "forks_count": 0,
    }
    gh, _ = client([PERMISSION_403])
    entry = collect.collect_fork(gh, "gke-labs/devops-bench", "main", None, fork)
    assert entry["branches"] == []
    assert "push access" in entry["unavailable"]


def test_a_branch_matching_upstream_head_is_not_compared():
    fork = {
        "full_name": "someone/devops-bench",
        "owner": {"login": "someone"},
        "created_at": "2026-01-01T00:00:00Z",
        "pushed_at": "2026-01-02T00:00:00Z",
        "forks_count": 0,
    }
    gh, seen = client([ok([{"name": "main", "commit": {"sha": "same"}}])])
    entry = collect.collect_fork(gh, "gke-labs/devops-bench", "main", "same", fork)
    assert entry["branches"] == []
    assert len(seen) == 1


def test_a_forks_default_branch_is_compared_rather_than_skipped():
    # The most common outside pattern is forking and committing straight to
    # main. Skipping it by name made that contributor look like an untouched
    # fork — identical to the population being measured against.
    fork = {
        "full_name": "someone/devops-bench",
        "owner": {"login": "someone"},
        "created_at": "2026-01-01T00:00:00Z",
        "pushed_at": "2026-01-02T00:00:00Z",
        "forks_count": 0,
    }
    compare = {
        "ahead_by": 2,
        "behind_by": 0,
        "total_commits": 2,
        "commits": [{"sha": "c1", "commit": {"committer": {"date": "2026-08-07T06:18:26Z"}}}] * 2,
        "files": [{"filename": "README.md", "changes": 3, "additions": 3, "deletions": 0}],
        "base_commit": {"sha": "b"},
        "merge_base_commit": {"sha": "m"},
    }
    gh, _ = client([ok([{"name": "main", "commit": {"sha": "theirs"}}]), ok(compare)])
    entry = collect.collect_fork(gh, "gke-labs/devops-bench", "main", "ours", fork)
    assert [b["name"] for b in entry["branches"]] == ["main"]
    assert entry["branches"][0]["headCommittedAt"] == "2026-08-07T06:18:26Z"


def test_a_truncated_commit_list_reports_no_head_date():
    fork = {
        "full_name": "someone/devops-bench",
        "owner": {"login": "someone"},
        "created_at": "2026-01-01T00:00:00Z",
        "pushed_at": "2026-01-02T00:00:00Z",
        "forks_count": 0,
    }
    compare = {
        "ahead_by": 400,
        "behind_by": 0,
        "total_commits": 400,
        "commits": [{"sha": "c", "commit": {"committer": {"date": "2026-01-01T00:00:00Z"}}}],
        "files": [],
        "base_commit": {"sha": "b"},
        "merge_base_commit": {"sha": "m"},
    }
    gh, _ = client([ok([{"name": "big", "commit": {"sha": "x"}}]), ok(compare)])
    entry = collect.collect_fork(gh, "gke-labs/devops-bench", "main", None, fork)
    assert entry["branches"][0]["headCommittedAt"] is None
    assert entry["branches"][0]["commitsReturned"] == 1
    assert entry["branches"][0]["totalCommits"] == 400


# --- branch names ----------------------------------------------------------


def test_a_hash_in_a_branch_name_is_escaped():
    # A legal ref name. Unescaped it truncates the request as a URL fragment,
    # and the comparison silently runs against something else.
    assert collect._escape("<!--<script#x") == "%3C%21--%3Cscript%23x"


def test_a_slash_in_a_branch_name_is_left_alone():
    assert collect._escape("feature/thing") == "feature/thing"


# --- code search -----------------------------------------------------------


def test_a_dead_control_query_makes_every_reference_unavailable():
    # "Nobody references us" and "search is broken" were the same output. Three
    # of the four queries in the committed snapshot read 0 with no reason.
    gh, _ = client([ok({"total_count": 0, "incomplete_results": False, "items": []})])
    result = collect.collect_references(gh, sleep=lambda _: None)
    assert result["trustworthy"] is False
    assert all(q["value"] is None or q["unavailable"] for q in result["queries"])


def test_a_live_control_query_lets_the_searches_through():
    hit = {
        "total_count": 249,
        "incomplete_results": False,
        "items": [{"repository": {"full_name": "a/b"}, "path": "x.py"}],
    }
    gh, _ = client([ok(hit)] * (len(collect.SEARCH_QUERIES) + 1))
    result = collect.collect_references(gh, sleep=lambda _: None)
    assert result["trustworthy"] is True
    assert result["queries"][0]["value"]["totalCount"] == 249


# --- affiliation -----------------------------------------------------------


def test_someone_seen_outside_stays_outside_after_they_contribute():
    # Otherwise the day the first outside contributor merges anything, every
    # past outside signal retroactively becomes an inside one and the milestone
    # un-happens.
    first = collect.freeze_affiliation({}, {"teammate"}, {"stranger"})
    assert first["outsideLogins"] == ["stranger"]

    later = collect.freeze_affiliation(first, {"teammate", "stranger"}, set())
    assert "stranger" in later["outsideLogins"]
    assert "stranger" not in later["insideLogins"]


def test_bots_are_neither_inside_nor_outside():
    result = collect.freeze_affiliation({}, {"teammate"}, {"devops-bench-sync-bot", "x[bot]"})
    assert result["outsideLogins"] == []


def test_an_organisation_holding_a_fork_is_not_an_adopter():
    result = collect.freeze_affiliation({}, set(), {"gke-labs"}, ({"gke-labs"}, set()))
    assert result["outsideLogins"] == []


# --- the store -------------------------------------------------------------


def test_a_record_round_trips(tmp_path):
    s = store.FileStore(tmp_path)
    s.put("snapshot", "2026-08-12", {"formatVersion": store.SNAPSHOT_FORMAT, "a": 1})
    assert s.get("snapshot", "2026-08-12")["a"] == 1
    assert s.list("snapshot") == ["2026-08-12"]


def test_an_unknown_format_version_is_refused_rather_than_half_read(tmp_path):
    s = store.FileStore(tmp_path)
    s.put("snapshot", "2026-08-12", {"formatVersion": 99})
    with pytest.raises(store.FormatError, match="99"):
        s.get("snapshot", "2026-08-12")


def test_a_snapshot_from_before_the_store_existed_is_refused(tmp_path):
    s = store.FileStore(tmp_path)
    s.put("snapshot", "2026-08-11", {"apiVersion": "devops-bench.k8s.io/v1alpha1"})
    with pytest.raises(store.FormatError, match="no formatVersion"):
        s.get("snapshot", "2026-08-11")


def test_a_checkpoint_is_not_part_of_the_history(tmp_path):
    # A partial run has to survive on disk without ever being mistaken for, or
    # overwriting, a complete snapshot from the same day.
    s = store.FileStore(tmp_path)
    s.put("snapshot", "2026-08-12", {"formatVersion": store.SNAPSHOT_FORMAT})
    s.put("snapshot", "2026-08-12.partial", {"formatVersion": store.SNAPSHOT_FORMAT})
    assert s.list("snapshot") == ["2026-08-12"]


def test_a_thinner_run_does_not_replace_a_fuller_one_from_the_same_day(tmp_path):
    # A --skip-forks run finishes cleanly and is not partial, but it knows less.
    # Overwriting turns a complete day into a thin one, which reads downstream
    # as a week where nobody forked anything.
    s = store.FileStore(tmp_path)
    s.put("snapshot", "2026-08-12", {"formatVersion": store.SNAPSHOT_FORMAT, "skipped": []})
    assert collect.covers_less_than_stored(s, "2026-08-12", ["forks"]) == "forks"
    assert collect.covers_less_than_stored(s, "2026-08-12", []) is None
    assert collect.covers_less_than_stored(s, "2026-08-11", ["forks"]) is None


def test_a_fuller_run_may_replace_a_thinner_one(tmp_path):
    s = store.FileStore(tmp_path)
    s.put("snapshot", "2026-08-12", {"formatVersion": store.SNAPSHOT_FORMAT, "skipped": ["forks"]})
    assert collect.covers_less_than_stored(s, "2026-08-12", []) is None


def test_cloud_storage_is_named_but_not_pretended_to_exist():
    with pytest.raises(NotImplementedError, match="not built"):
        store.open_store("gcs:some-bucket/prefix")


def test_a_backend_nobody_named_is_rejected_by_name():
    with pytest.raises(ValueError, match="firestore"):
        store.open_store("firestore:some-project")


def test_a_login_is_never_in_both_lists():
    # Naming a frozen outsider as inside used to add it to inside and leave it
    # in outside; classification reads outside, so the change did nothing.
    previous = {"insideLogins": [], "outsideLogins": ["gke-labs"]}
    result = collect.freeze_affiliation(previous, set(), set(), ({"gke-labs"}, set()))
    assert "gke-labs" in result["insideLogins"]
    assert "gke-labs" not in result["outsideLogins"]


# --- the affiliation override file -------------------------------------------


def test_an_override_beats_the_contributors_api():
    # A reviewer from another project who landed one fix is a contributor by the
    # API's definition, and counting them inside pushes the outside share down.
    result = collect.freeze_affiliation(
        {}, {"teammate", "visitor"}, set(), (set(), {"visitor"})
    )
    assert result["insideLogins"] == ["teammate"]
    assert result["outsideLogins"] == ["visitor"]


def test_an_override_beats_the_freeze():
    # The freeze stops a derived answer being recomputed away. A person saying
    # "this account is ours" is not a derived answer, and leaving it unable to
    # correct the record is how a wrong label becomes permanent.
    previous = {"insideLogins": [], "outsideLogins": ["holdingorg"]}
    result = collect.freeze_affiliation(previous, set(), set(), ({"holdingorg"}, set()))
    assert result["outsideLogins"] == []
    assert result["overrides"] == {"inside": ["holdingorg"], "outside": []}


def test_an_override_file_is_read_and_lowercased(tmp_path):
    path = tmp_path / "affiliation.json"
    path.write_text(json.dumps({"inside": ["GKE-Labs"], "outside": ["Visitor"]}))
    assert collect.read_overrides(path) == ({"gke-labs"}, {"visitor"})


def test_a_missing_override_file_is_not_an_error(tmp_path):
    assert collect.read_overrides(tmp_path / "nope.json") == (set(), set())


def test_a_login_in_both_override_lists_is_an_error(tmp_path):
    # Letting one list win silently is the bug this file replaced.
    path = tmp_path / "affiliation.json"
    path.write_text(json.dumps({"inside": ["x"], "outside": ["x"]}))
    with pytest.raises(SystemExit, match="both inside and outside"):
        collect.read_overrides(path)


def test_the_shipped_override_file_parses():
    inside, outside = collect.read_overrides(collect.AFFILIATION_FILE)
    assert "kubernetes-sigs" in inside
    assert not (inside & outside)


def test_a_commit_author_is_read_off_the_comparison():
    def by(login):
        return {
            "author": None if login is None else {"login": login, "type": "User"},
            "commit": {"committer": {"date": "2026-01-01T00:00:00Z"}},
        }

    gh, _ = client(
        [
            ok(
                {
                    "ahead_by": 3,
                    "total_commits": 3,
                    "commits": [by("Writer"), by("claude"), by(None)],
                    "files": [],
                }
            )
        ]
    )
    result = collect.compare_branch(gh, "a/b", "main", "c", "x")
    # Lowercased like every other login. The Claude Code account is automation
    # wearing a user account, and a commit whose email matches no account is no
    # evidence rather than an outsider.
    assert result["authors"] == [{"login": "writer", "commits": 1}]
    assert result["commitsUnattributed"] == 1


def test_a_branch_whose_comparison_failed_is_not_evidence(monkeypatch):
    # The record kept for a failed comparison carries a reason and nothing else.
    # Reading authors off it unconditionally killed a seven-minute run at the
    # last step, after every request had already been spent.
    gh, _ = client([ok([{"name": "x", "commit": {"sha": "s"}}]), SERVER_500])
    entry = collect.collect_fork(
        gh, "a/b", "main", "head", {"full_name": "c/b", "owner": {"login": "C"},
                                    "created_at": "", "pushed_at": "", "forks_count": 0}
    )
    branch = entry["branches"][0]
    assert branch["unavailable"]
    assert branch.get("authors", []) == []
