# Usage metrics

A mockup of the collection, classification, and reporting layers described in
`PROPOSAL_usage-metrics.md` §2. Three steps, run in order:

```bash
python3 hack/usage-metrics/collect.py                      # -> snapshots/<date>.json
python3 hack/usage-metrics/classify.py snapshots/<date>.json --out /tmp/classified.json
python3 hack/usage-metrics/render.py /tmp/classified.json  # -> dashboard.html
```

`dashboard.html` is self-contained: no network requests, no CDN, no build step.
Open it from `file://`, attach it as a CI artifact, or publish it to GitHub Pages
unchanged.

## Why three steps

| Step | Does | Needs network |
|---|---|---|
| `collect.py` | Reads public GitHub signals, writes one dated snapshot | Yes |
| `classify.py` | Applies the path and reference taxonomies | No |
| `render.py` | Inlines a classified snapshot into the dashboard template | No |

Classification is separated from collection so the taxonomy can be revised and
re-run over every snapshot ever taken. If the split were collapsed, a taxonomy
change would only affect data collected after it.

## Requirements

The `gh` CLI, authenticated. Everything else is Python standard library.

The traffic endpoints (views, clones, referrers, popular paths) require **push
access to the repository being measured** — GitHub returns
`403 Must have push access to repository` otherwise. That is recorded as `null`
with the reason attached, and the dashboard shows it as a dash and a banner
rather than folding it into a zero. Running this against `kubernetes-sigs` will
produce traffic data only when the job runs inside that repository.

## Rules the code enforces

- **A missing measurement is `null`, never `0`.** A failed API call and a
  measurement of zero must never look the same.
- **A ratio with a zero denominator is `null`,** not 0%.
- **Code search runs on exact, qualified strings only.** A loose
  `"devops-bench"` search returns hundreds of hits from unrelated projects that
  carry the string as a tag. The queries used are recorded in the snapshot.
- **Contributor affiliation is unioned across repositories.** The two repos are
  the same project, so a contributor upstream is not an external adopter for
  having forked the mirror.
- **Affiliation is stored as a boolean.** No list of names is persisted.

## Editing the dashboard

Edit `dashboard.template.html` and re-run `render.py`. Do not edit the generated
`dashboard.html` — it is overwritten on every render.

Chart colors come from a validated categorical palette; slots 1–3 clear the
colorblind-separation and contrast gates in both light and dark mode. If you
change a series color, re-validate the set rather than eyeballing it.

## Rate limits

- Core API: 5,000 requests/hour. A full run with fork-branch comparison costs
  roughly 300 requests against the two repositories.
- Code search: **10 requests/minute** — the binding constraint. `collect.py`
  sleeps between queries. Adding queries is not free.
