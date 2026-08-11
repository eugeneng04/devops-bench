# CLI telemetry dashboard (mockup)

A mockup of the reporting surface for the in-product telemetry proposal — what a
maintainer would actually look at once opt-in events are being ingested.

```bash
cd hack/telemetry-metrics
python3 simulate.py                              # -> events.json
python3 aggregate.py events.json --out report.json
python3 render.py report.json                    # -> dashboard.html
```

`dashboard.html` is self-contained: no network requests, no CDN, no build step.

## What is real and what is not

**Not real: the event volume.** No telemetry has ever been collected, so
`simulate.py` invents the stream. It is deterministic — same seed, same output.

**Real: everything the stream is built from.**

| Thing | Source |
|---|---|
| Task names | `tasks/**/task.yaml`, via `inventory.py` |
| Harness keys | the `@AGENTS.register("...")` decorators, via `inventory.py` |
| Event schema | the `ResultRow` contract, plus the proposal's added fields |
| Latency and token magnitudes | the runs checked in under `results/` |

Once a real endpoint exists, `simulate.py` is deleted and `aggregate.py` reads
the ingested stream unchanged.

## The event is a ResultRow, not a manifest

The proposal says it extends `manifest.json`. That file is run-level only:

```json
{"schemaVersion": 1, "runId": "...", "t": "...", "setupId": "...",
 "model": "...", "harness": "...", "augmentation": ["mcp"]}
```

The per-task fields the proposal wants — `task_id`, `latency_ms`, `exit_code`,
`token_consumption` — already exist one level down, in the `ResultRow` written
to `rows.json` by `devops_bench/evalharness/reporter.py`. The telemetry event is
that row plus `userUuid`, `turnCount`, `parallelExecutionCount`, `clientVersion`
and `consentSource`. Hook the row writer, not the manifest writer.

## Spans, not metrics

`task_id` × `model` × `harness` × `userUuid` is unbounded cardinality. As
OpenTelemetry *metric* attributes that will be dropped or throttled at ingest.
One span per task execution carrying those as span attributes is the right
shape; keep `MeterProvider` for genuinely low-cardinality counters only.

## Rules the code enforces

- **The denominator is unknown and the page says so.** Opt-in telemetry cannot
  measure the population that did not opt in. Nothing here is presented as a
  share of all users, and the banner is not dismissable.
- **A ratio with a zero denominator is `null`, not 0%.** A task nobody ran has
  no failure rate.
- **A per-task failure rate below `MIN_RUNS_FOR_RATE` executions is suppressed.**
  The dashboard ranks tasks on that rate; ranking on a 3-run sample is ranking
  on noise.
- **Aggregation is separate from collection** so it can be revised and re-run
  over every stream ever ingested.
- **The catalog is read from the repository at aggregation time,** never taken
  from the stream. A task added today has to show as present when a stream from
  last month is re-aggregated, or old snapshots silently contradict the repo.
- **A catalog task nobody executed gets a row of zeros, not an omission.** So
  does a registered harness nobody ran. Absent and zero are different findings,
  and only one of them is actionable.
- **Catalog drift is computed over every event, never per harness.** Scoped, a
  task looks new merely because the harness that ran it is new.
- **"New" needs a grace period.** A rarely-run task can take days to appear at
  all, so first-seen-after-the-window-opened on its own flags a third of the
  catalog. `NEW_GRACE_DAYS` is the guard.
- **No PII.** The install identifier is a locally generated UUID. Affiliation,
  hostnames, paths, and prompts are never in the event.

## Editing the dashboard

Edit `dashboard.template.html` and re-run `render.py`. Do not edit the generated
`dashboard.html` — it is overwritten on every render. It shares its palette with
`hack/usage-metrics/`; if you change a series color, re-validate the set in both.
