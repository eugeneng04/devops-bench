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
"""Where the three record kinds live.

The four programs in this directory only ever meet through stored records, so
this interface is the real one between them. Three operations, keyed by kind and
date:

    put(kind, date, record)
    get(kind, date) -> record
    list(kind) -> [date, ...]        ascending

Local files are the backend everywhere, by hand and in production, because the
production store is a git repository of files - PRODUCTION_PLAN.md 7.2. Nothing
here needs a cloud account. Cloud Storage slots in behind the same three calls
if the history ever outgrows git.

Every record carries a format version, and a reader refuses a version it does
not know rather than half-reading it into a KeyError three functions later.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SNAPSHOT_FORMAT = 2
CLASSIFIED_FORMAT = 2
SERIES_FORMAT = 1

# What each program will accept when reading. Add a version here only once a
# reader can actually handle it.
SUPPORTED = {
    "snapshot": {SNAPSHOT_FORMAT},
    "classified": {CLASSIFIED_FORMAT},
    "series": {SERIES_FORMAT},
}

DIRECTORIES = {"snapshot": "snapshots", "classified": "classified", "series": "series"}

DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class FormatError(Exception):
    """A stored record is a version, or a shape, this program cannot read."""


def check_version(record: dict[str, Any], kind: str) -> dict[str, Any]:
    """Reject an unreadable record here, where the message can still say why."""
    if not isinstance(record, dict):
        raise FormatError(f"{kind}: expected an object, got {type(record).__name__}")
    version = record.get("formatVersion")
    if version is None:
        raise FormatError(
            f"{kind}: no formatVersion. Snapshots written before the store existed "
            f"are format 1 and are not readable by this program."
        )
    if version not in SUPPORTED[kind]:
        raise FormatError(
            f"{kind}: formatVersion {version} is not one this program reads "
            f"({sorted(SUPPORTED[kind])}). Upgrade the reader or re-collect."
        )
    return record


def provenance() -> dict[str, Any]:
    """Where a number came from. The only audit trail once records leave git."""
    run = os.environ.get("GITHUB_RUN_ID")
    repo = os.environ.get("GITHUB_REPOSITORY")
    return {
        "collectorSha": _git_sha(),
        "workflowRunUrl": (
            f"{os.environ.get('GITHUB_SERVER_URL', 'https://github.com')}/{repo}/actions/runs/{run}"
            if run and repo
            else None
        ),
        "writtenAt": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
    }


def _git_sha() -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(Path(__file__).parent), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout.strip() or None if result.returncode == 0 else None


class FileStore:
    """Records as JSON files under one directory. The default everywhere."""

    def __init__(self, root: Path):
        self.root = Path(root)

    def _path(self, kind: str, date: str) -> Path:
        if kind not in DIRECTORIES:
            raise ValueError(f"unknown kind {kind!r}")
        return self.root / DIRECTORIES[kind] / f"{date}.json"

    def put(self, kind: str, date: str, record: dict[str, Any]) -> str:
        path = self._path(kind, date)
        path.parent.mkdir(parents=True, exist_ok=True)
        # Write beside the target and move, so a run killed mid-write leaves the
        # previous record intact rather than a truncated one.
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(record, indent=2) + "\n")
        temporary.replace(path)
        return str(path)

    def get(self, kind: str, date: str) -> dict[str, Any]:
        path = self._path(kind, date)
        if not path.exists():
            raise FileNotFoundError(path)
        return check_version(json.loads(path.read_text()), kind)

    def list(self, kind: str) -> list[str]:
        directory = self.root / DIRECTORIES[kind]
        if not directory.is_dir():
            return []
        # Only well-formed dates. Checkpoints are written under a suffixed key
        # so that a partial run is on disk without being part of the history.
        return sorted(p.stem for p in directory.glob("*.json") if DATE.match(p.stem))

    def delete(self, kind: str, date: str) -> None:
        self._path(kind, date).unlink(missing_ok=True)


def open_store(uri: str) -> FileStore:
    """`file:<path>`, which in production is a checkout of the data repository.

    `gcs:<bucket>/<prefix>` is named and not built. It is the escalation from
    git, and 7.2 lists the three things that would force it: a deletion that has
    to be honoured cleanly, a need to query the history in BigQuery, or readers
    who must see the dashboard without seeing raw snapshots. Naming it here
    means asking for it fails with that sentence rather than obscurely.
    """
    scheme, _, rest = uri.partition(":")
    if scheme == "file":
        return FileStore(Path(rest))
    if scheme == "gcs":
        raise NotImplementedError(
            "the Cloud Storage backend is not built; git is the store today "
            "(PRODUCTION_PLAN.md 7.2). Use file:<path> against the data repository."
        )
    raise ValueError(f"unknown store {uri!r}; expected file:<path>")
