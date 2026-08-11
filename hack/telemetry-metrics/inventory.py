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
"""What the repository currently defines: tasks and harnesses.

Read at aggregation time, not baked into the event stream. A task added today
must show as present when yesterday's stream is re-aggregated, otherwise the
catalog in an old snapshot silently contradicts the repository.
"""

from __future__ import annotations

import re
from pathlib import Path

REGISTER_RE = re.compile(r'AGENTS\.register\(\s*"([^"]+)"')

# Recorded in the checked-in manifests under results/ but registered on a branch
# not merged here. A real key in use that the source scan cannot see yet.
EXTRA_HARNESS_KEYS = {"claude"}


def discover_tasks(root: Path) -> list[str]:
    """Catalog task ids, as ``<folder>/<name>``."""
    return sorted(
        f"{p.parent.parent.name}/{p.parent.name}" for p in (root / "tasks").rglob("task.yaml")
    )


def discover_harnesses(root: Path) -> list[str]:
    """Canonical harness keys, from the registration decorators."""
    keys = set(EXTRA_HARNESS_KEYS)
    for path in (root / "devops_bench").rglob("*.py"):
        keys.update(REGISTER_RE.findall(path.read_text(encoding="utf-8", errors="ignore")))
    return sorted(keys)
