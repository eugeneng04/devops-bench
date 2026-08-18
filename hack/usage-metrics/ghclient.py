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
"""The one way in and out of the GitHub API.

Every request goes through here so the safety rules live in one place: a time
limit on every call, retries only where retrying helps, and a running record of
how much of the hourly budget is left.

Two failure kinds, and telling them apart matters more than the retry logic:

  throttled    the server asked us to wait. Waiting works, so this retries.
  Unavailable  permission, a bad path, a comparison too large to compute.
               Waiting never works, and retrying it five times costs five
               requests and thirty seconds on every run, forever.

Both 403s look identical until you read the headers, which is why this shells
out to `gh api -i` and parses the status line rather than reading stderr. The
kubernetes-sigs traffic endpoint is a permanent 403 with an untouched budget;
a secondary rate limit is a 403 with a Retry-After.

Pagination is by hand. `gh api --paginate` emits nothing at all when any page
fails, so one throttled page throws away every page already fetched and the
retry re-requests all of them — a run that is being throttled amplifies its own
load. Here a retry costs one page.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
import urllib.parse
from dataclasses import dataclass, field
from typing import Any, Callable

TIMEOUT_SECONDS = 90
MAX_RETRIES = 3

# Past this, waiting out a limit costs more than the measurement is worth. The
# primary limit resets on the hour, so a fresh 5,000-request exhaustion can be
# 59 minutes away; the job records a gap instead of sleeping through it.
MAX_WAIT_SECONDS = 120

# A page count no legitimate listing here reaches. A guard against paging
# forever on an endpoint that ignores `page`.
MAX_PAGES = 20

SECONDARY_LIMIT_MARKERS = ("secondary rate limit", "abuse detection")


class Unavailable(Exception):
    """A measurement could not be taken. Recorded as null plus this reason."""


@dataclass(frozen=True)
class Response:
    status: int
    headers: dict[str, str]
    body: str

    def json(self) -> Any:
        try:
            return json.loads(self.body or "null")
        except json.JSONDecodeError as exc:
            raise Unavailable(f"unparseable response: {exc}") from exc

    def message(self) -> str:
        try:
            payload = json.loads(self.body)
            return payload.get("message") or self.body[:200]
        except (json.JSONDecodeError, AttributeError):
            return self.body[:200] or f"HTTP {self.status}"


def parse_response(text: str) -> Response:
    """Split `gh api -i` output into a status, headers, and a body.

    A redirect leaves more than one header block; the last one is the response
    that actually answered.
    """
    text = text.replace("\r\n", "\n")
    status, headers = 0, {}
    while text.startswith("HTTP/"):
        block, _, text = text.partition("\n\n")
        lines = block.split("\n")
        parts = lines[0].split(None, 2)
        status = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0
        headers = {}
        for line in lines[1:]:
            name, sep, value = line.partition(":")
            if sep:
                headers[name.strip().lower()] = value.strip()
    return Response(status=status, headers=headers, body=text)


def wait_seconds(response: Response, now: float) -> float | None:
    """How long to wait before retrying, or None if the failure is permanent.

    Nothing else here is allowed to decide that a request is worth repeating.
    """
    if response.status not in (403, 429):
        # 5xx included deliberately. GitHub returns one when a diff comparison
        # is too large to compute, which is a property of the branch and not a
        # blip — retrying spends the most effort on exactly the branches that
        # will fail again.
        return None
    retry_after = response.headers.get("retry-after")
    if retry_after:
        try:
            return max(0.0, float(retry_after))
        except ValueError:
            pass
    if any(marker in response.body.lower() for marker in SECONDARY_LIMIT_MARKERS):
        return 60.0
    if response.headers.get("x-ratelimit-remaining") == "0":
        try:
            return max(0.0, float(response.headers["x-ratelimit-reset"]) - now)
        except (KeyError, ValueError):
            return 60.0
    # A 403 with the budget untouched is a permission error. "Must have push
    # access to repository" is the one this project hits on every single run.
    return None


def _run(args: list[str], timeout: int) -> tuple[int, str, str]:
    process = subprocess.run(
        ["gh", "api", "-i", *args], capture_output=True, text=True, timeout=timeout
    )
    return process.returncode, process.stdout, process.stderr


@dataclass
class GitHub:
    timeout: int = TIMEOUT_SECONDS
    max_retries: int = MAX_RETRIES
    max_wait: float = MAX_WAIT_SECONDS
    sleep: Callable[[float], None] = time.sleep
    clock: Callable[[], float] = time.time
    runner: Callable[[list[str], int], tuple[int, str, str]] = _run
    # Whatever the last response said was left, per resource: core, search,
    # graphql. Stored in the snapshot so a thin run can be explained later.
    budget: dict[str, dict[str, Any]] = field(default_factory=dict)
    calls: int = 0

    def _once(self, args: list[str]) -> Response:
        self.calls += 1
        try:
            _, out, err = self.runner(args, self.timeout)
        except subprocess.TimeoutExpired as exc:
            raise Unavailable(f"timed out after {self.timeout}s") from exc
        except OSError as exc:
            raise Unavailable(f"could not run gh: {exc}") from exc
        response = parse_response(out)
        if response.status == 0:
            raise Unavailable(err.strip().splitlines()[-1] if err.strip() else "no response from gh")
        resource = response.headers.get("x-ratelimit-resource")
        if resource:
            self.budget[resource] = {
                "remaining": _as_int(response.headers.get("x-ratelimit-remaining")),
                "limit": _as_int(response.headers.get("x-ratelimit-limit")),
                "reset": _as_int(response.headers.get("x-ratelimit-reset")),
            }
        return response

    def _request(self, args: list[str], what: str) -> Response:
        for attempt in range(self.max_retries + 1):
            response = self._once(args)
            if 200 <= response.status < 300:
                return response
            pause = wait_seconds(response, self.clock())
            if pause is None:
                raise Unavailable(f"{what}: {response.message()} (HTTP {response.status})")
            if pause > self.max_wait:
                raise Unavailable(
                    f"{what}: rate limited for another {pause:.0f}s, longer than this run will wait"
                )
            if attempt == self.max_retries:
                raise Unavailable(f"{what}: still rate limited after {attempt + 1} attempts")
            print(f"  throttled on {what}, waiting {pause:.0f}s", file=sys.stderr)
            self.sleep(pause)
        raise AssertionError("unreachable")

    def rest(self, path: str, params: dict[str, Any] | None = None) -> Any:
        if params:
            path = f"{path}?{urllib.parse.urlencode(params)}"
        return self._request([path], path).json()

    def paginate(
        self, path: str, params: dict[str, Any] | None = None, per_page: int = 100
    ) -> list[Any]:
        """Page by page, so a retry costs one page rather than all of them."""
        items: list[Any] = []
        for page in range(1, MAX_PAGES + 1):
            batch = self.rest(path, {**(params or {}), "per_page": per_page, "page": page})
            if not isinstance(batch, list):
                raise Unavailable(f"{path}: expected a list of results")
            items += batch
            if len(batch) < per_page:
                return items
        print(f"  {path}: stopped at {MAX_PAGES} pages", file=sys.stderr)
        return items

    def graphql(self, query: str, **variables: Any) -> dict[str, Any]:
        args = ["graphql", "-f", f"query={query}"]
        for name, value in variables.items():
            if value is None:
                continue
            # -f sends a string, -F sends a literal. A GraphQL Int! variable is
            # rejected if it arrives quoted.
            args += ["-f" if isinstance(value, str) else "-F", f"{name}={value}"]
        for attempt in range(self.max_retries + 1):
            payload = self._request(args, "graphql").json()
            errors = payload.get("errors") if isinstance(payload, dict) else None
            if not errors:
                return payload.get("data") or {}
            message = "; ".join(e.get("message", "?") for e in errors)
            # A GraphQL rate limit arrives as HTTP 200 with an error in the body,
            # so it never reaches the status-code path above.
            if "rate limit" not in message.lower() or attempt == self.max_retries:
                raise Unavailable(f"graphql: {message}")
            print("  graphql rate limited, waiting 60s", file=sys.stderr)
            self.sleep(60.0)
        raise AssertionError("unreachable")


def _as_int(value: str | None) -> int | None:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
