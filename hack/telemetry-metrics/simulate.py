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
"""Generate a synthetic telemetry event stream for the dashboard mockup.

No telemetry has ever been collected, so the event volume on this page is
invented. Everything else is read out of the repository:

  - task names come from tasks/**/task.yaml
  - harness keys come from the @AGENTS.register("...") decorators
  - the event schema is the real ResultRow contract (devops_bench/results/row.py)
    plus the fields the telemetry proposal adds

Deterministic: same seed and same repository produce the same stream.
"""

from __future__ import annotations

import argparse
import json
import math
import random
import re
import sys
import uuid
import zlib
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

REGISTER_RE = re.compile(r'AGENTS\.register\(\s*"([^"]+)"')

# Observed in the checked-in runs under results/. Used as the centre of the
# per-task latency and token distributions so the magnitudes are not invented.
OBSERVED_LATENCY_SEC = 164.0
OBSERVED_INPUT_TOKENS = 2748
OBSERVED_OUTPUT_TOKENS = 11267

# Multiplier on a task's base failure rate. A dashboard where every harness
# fails identically shows nothing; the point of the chart is the gap.
HARNESS_DIFFICULTY = {
    "claude": 0.75,
    "gemini": 0.85,
    "antigravity": 1.0,
    "api": 1.25,
    "openclaw": 1.45,
}

MODELS_BY_HARNESS = {
    "claude": ["claude-opus-4-8[1m]", "claude-sonnet-4-5"],
    "gemini": ["gemini-3.1-pro-preview", "gemini-3.5-flash", "gemini-2.5-pro"],
    "antigravity": ["gemini-3.1-pro-preview"],
    "openclaw": ["claude-opus-4-8[1m]", "gpt-5"],
    "api": ["gemini-3.1-pro-preview", "claude-sonnet-4-5"],
}

# Task names an install ran that are not in the upstream catalog: the signal
# that someone authored a task locally.
LOCAL_TASK_NAMES = [
    "istio-mtls-rollout",
    "argocd-drift-detect",
    "karpenter-consolidation",
    "vpa-recommendation",
    "internal-slo-burn",
]


def discover_tasks(root: Path) -> list[tuple[str, str]]:
    return sorted(
        (p.parent.parent.name, p.parent.name) for p in (root / "tasks").rglob("task.yaml")
    )


def discover_harnesses(root: Path) -> list[str]:
    keys = set()
    for path in (root / "devops_bench").rglob("*.py"):
        keys.update(REGISTER_RE.findall(path.read_text(encoding="utf-8", errors="ignore")))
    # The checked-in manifests record a "claude" harness that lives on a branch
    # not yet merged here; it is a real key in use.
    keys.add("claude")
    return sorted(keys)


def build_population(rng: random.Random, harnesses: list[str], installs: int) -> list[dict]:
    """One record per opted-in install, with a stable pseudonymous UUID."""
    out = []
    for i in range(installs):
        harness = rng.choices(harnesses, weights=[6, 5, 3, 2, 1][: len(harnesses)])[0]
        out.append(
            {
                "uuid": str(uuid.UUID(int=rng.getrandbits(128), version=4)),
                "harness": harness,
                "model": rng.choice(MODELS_BY_HARNESS.get(harness, ["gemini-3.1-pro-preview"])),
                # A few installs drive most of the volume; most run once or twice.
                "intensity": rng.paretovariate(1.3),
                "firstDay": rng.randrange(0, 60) if i > installs // 3 else 0,
                "consentSource": rng.choices(["env", "flag"], weights=[3, 2])[0],
                "clientVersion": rng.choices(["0.4.1", "0.4.0", "0.3.7"], weights=[6, 3, 1])[0],
                "authorsLocalTasks": rng.random() < 0.12,
            }
        )
    return out


def poisson(rng: random.Random, mean: float) -> int:
    """Knuth's sampler. random.Random has no Poisson and the counts here are small."""
    limit, k, p = math.exp(-min(mean, 20.0)), 0, 1.0
    while True:
        p *= rng.random()
        if p <= limit:
            return k
        k += 1


def task_difficulty(folder: str, name: str) -> float:
    """Base failure rate. Cloud and recovery tasks fail more than no-op ones."""
    base = {"noop": 0.06, "kind": 0.22, "common": 0.28, "gcp": 0.34}.get(folder, 0.25)
    # crc32, not hash(): str hashing is salted per process, which would make the
    # same seed produce a different stream on every run.
    jitter = zlib.crc32(f"{folder}/{name}".encode()) % 17
    return min(0.85, base + jitter / 100.0)


def generate(root: Path, days: int, installs: int, seed: int) -> dict[str, Any]:
    rng = random.Random(seed)
    tasks = discover_tasks(root)
    harnesses = discover_harnesses(root)
    if not tasks or not harnesses:
        raise SystemExit(f"no tasks or harnesses found under {root}")

    population = build_population(rng, harnesses, installs)
    # Task popularity is heavily skewed: the first task in the catalog a user
    # meets gets run far more than the last.
    weights = [1 / (i + 1) ** 0.7 for i in range(len(tasks))]

    end = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    events: list[dict[str, Any]] = []

    for person in population:
        for day in range(person["firstDay"], days):
            # Weekday-heavy, and adoption ramps over the window.
            weekday = (end - timedelta(days=days - day)).weekday()
            rate = person["intensity"] * (0.3 if weekday >= 5 else 1.0) * (0.4 + day / days)
            for _ in range(min(poisson(rng, rate), 40)):
                events.append(make_event(rng, person, tasks, weights, end, days, day))

    events.sort(key=lambda e: e["t"])
    return {
        "apiVersion": "devops-bench.k8s.io/v1alpha1",
        "kind": "TelemetryEventStream",
        "synthetic": True,
        "generatedAt": end.isoformat().replace("+00:00", "Z"),
        "seed": seed,
        "windowDays": days,
        "catalog": [f"{f}/{n}" for f, n in tasks],
        "harnesses": harnesses,
        "events": events,
    }


def make_event(rng, person, tasks, weights, end, days, day) -> dict[str, Any]:
    folder, name = rng.choices(tasks, weights=weights)[0]
    if person["authorsLocalTasks"] and rng.random() < 0.35:
        folder, name = "local", rng.choice(LOCAL_TASK_NAMES)

    when = end - timedelta(days=days - day, seconds=rng.randrange(0, 86400))
    failed = rng.random() < task_difficulty(folder, name) * HARNESS_DIFFICULTY.get(
        person["harness"], 1.0
    )
    # Parallel fan-out: most runs are serial, a tail runs the catalog at once.
    parallel = rng.choices([1, 2, 4, 8, 16], weights=[60, 18, 12, 7, 3])[0]
    latency = OBSERVED_LATENCY_SEC * rng.lognormvariate(0, 0.55) * (1.6 if failed else 1.0)
    turns = max(1, int(rng.lognormvariate(2.4, 0.5)))

    return {
        "schemaVersion": 2,
        "userUuid": person["uuid"],
        "runId": f"run_{when.strftime('%Y%m%d_%H%M%S')}",
        "t": when.isoformat().replace("+00:00", "Z"),
        "setupId": f"{person['model']}-{person['harness']}",
        "model": person["model"],
        "harness": person["harness"],
        "augmentation": ["mcp"] if rng.random() < 0.4 else [],
        "taskFolder": folder,
        "taskName": name,
        "iteration": 0,
        "outcomeScore": 0.0 if failed else round(rng.uniform(0.5, 1.0), 2),
        "toolScore": round(rng.uniform(0.0, 1.0), 2),
        "latencySec": round(latency, 2),
        "inputTokens": int(OBSERVED_INPUT_TOKENS * turns * rng.lognormvariate(0, 0.3)),
        "outputTokens": int(OBSERVED_OUTPUT_TOKENS * rng.lognormvariate(0, 0.4)),
        "status": "failure" if failed else "success",
        "exitCode": 1 if failed else 0,
        "turnCount": turns,
        "parallelExecutionCount": parallel,
        "clientVersion": person["clientVersion"],
        "consentSource": person["consentSource"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--days", type=int, default=90)
    parser.add_argument("--installs", type=int, default=140)
    parser.add_argument("--seed", type=int, default=20260811)
    parser.add_argument("--out", type=Path, default=Path(__file__).parent / "events.json")
    args = parser.parse_args()

    stream = generate(args.repo_root, args.days, args.installs, args.seed)
    args.out.write_text(json.dumps(stream, indent=2) + "\n")
    print(f"{args.out} ({len(stream['events'])} events)", file=sys.stderr)
    print(args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
