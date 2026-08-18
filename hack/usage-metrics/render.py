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
"""Inline a classified snapshot into the dashboard template.

Produces one self-contained HTML file with no network dependencies, so it works
from a file:// URL, as a CI artifact, or on GitHub Pages unchanged.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

TEMPLATE = Path(__file__).parent / "dashboard.template.html"
PLACEHOLDER = "__DATA__"

# Escaping "</" is not enough. Inside a script element "<!--<script>" opens the
# double-escaped state, where the next "</script>" is text rather than the end
# of the block, and the rest of the page is swallowed into the JSON. The string
# contains no "</" and is a legal branch name, so a fork can push it. Escaping
# every "<", ">" and "&" leaves no sequence the HTML tokenizer reacts to; the
# JSON value is unchanged because < and "<" decode identically.
UNSAFE = {"<": "\\u003c", ">": "\\u003e", "&": "\\u0026"}


def render(classified: dict, series: dict | None = None) -> str:
    template = TEMPLATE.read_text()
    if PLACEHOLDER not in template:
        raise SystemExit(f"{TEMPLATE} is missing the {PLACEHOLDER} placeholder")
    # The page still renders without a series - it says it has no history rather
    # than drawing an empty chart - so a first run has something to show.
    payload = json.dumps({**classified, "series": series}, separators=(",", ":"))
    for char, escape in UNSAFE.items():
        payload = payload.replace(char, escape)
    return template.replace(PLACEHOLDER, payload)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("classified", type=Path, help="classified JSON from classify.py")
    parser.add_argument("--series", type=Path, help="time series JSON from series.py")
    parser.add_argument(
        "--out", type=Path, default=Path(__file__).parent / "dashboard.html"
    )
    args = parser.parse_args()

    args.out.write_text(
        render(
            json.loads(args.classified.read_text()),
            json.loads(args.series.read_text()) if args.series else None,
        )
    )
    print(args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
