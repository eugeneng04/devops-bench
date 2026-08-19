# Usage metrics

Collection, classification, and reporting for the signals described in
`PROPOSAL_usage-metrics.md` §2. `PRODUCTION_PLAN.md` is the build plan and
`METRICS_PLAN.md` is the velocity, engagement and hotspot work that sits on top
of it.

```bash
python3 hack/usage-metrics/collect.py                              # -> snapshots/<date>.json
python3 hack/usage-metrics/series.py --reclassify --out series/latest.json
python3 hack/usage-metrics/render.py classified/<date>.json --series series/latest.json
```

`series.py --reclassify` runs `classify.py` over every snapshot in the store
first, so those three commands are the whole pipeline. `classify.py` on its own
is for looking at one record.

`dashboard.html` is self-contained: no network requests, no CDN, no build step.

## The four steps and the store

| Step | Does | Needs network |
|---|---|---|
| `collect.py` | Asks GitHub for everything, writes one dated snapshot | Yes |
| `classify.py` | Applies the path and reference taxonomies | No |
| `series.py` | Walks every record ever stored into a history | No |
| `render.py` | Inlines a classified record and the history into the template | No |

They only ever meet through stored records, so `store.py` is the real interface
between them:

```python
put(kind, date, record)      # kind: snapshot | classified | series
get(kind, date) -> record
list(kind) -> [date, ...]    # ascending
```

Local files are the default, and production is the same files committed to a git
repository of their own, so none of this needs a cloud account — by hand or on a
schedule. Consecutive snapshots are near-identical, so git deltas them to ~12 KB
each against 2.4 MB on disk. Cloud Storage slots in behind the same three calls
if it ever outgrows that; `PRODUCTION_PLAN.md` 7.2 has the reasoning and the
three limits that would force the move.

Classification is separate from collection so the taxonomy can be revised and
re-run over every snapshot ever taken. That only holds if raw snapshots are kept
forever, which is why nothing here has an expiry.

## Requirements

The `gh` CLI, authenticated. Everything else is Python standard library.

The traffic endpoints (views, clones, referrers, popular paths) need
**Administration: read** on the repository being measured. GitHub returns
`403 Must have push access to repository` otherwise, which is recorded as `null`
with the reason attached — running against `kubernetes-sigs` produces traffic
data only from inside that repository.

## Rules the code enforces

- **A missing measurement is `null`, never `0`.** A failed call and a
  measurement of zero must never look the same.
- **Failure is caught per fork and per branch.** One bad comparison used to
  escape the whole loop and replace every fork already collected with a single
  null. A comparison that fails now keeps the branch and stores the reason —
  a throttled request and a branch with no shared history are different
  findings, and nine branches are currently the second kind.
- **Retry only what is retryable.** Two unrelated things return 403. A
  `Retry-After`, an exhausted budget, or a secondary limit is worth waiting for;
  a permission error never is, and retrying it costs four requests and thirty
  seconds on every run forever. 5xx is not retried either — GitHub returns one
  when a diff is too large to compute, which is a property of the branch.
- **A rate limit that outlasts the run is recorded, not slept through.** The
  primary limit can be 59 minutes away.
- **Pagination is by hand.** `gh api --paginate` emits nothing at all if any
  page fails, so a retry re-fetches every page and a throttled run amplifies its
  own load. Here a retry costs one page.
- **Every code search carries a control query** whose answer cannot be zero. If
  the control comes back empty, every reference figure in that run is
  unavailable rather than zero. Search had never worked: `gh search code`
  re-quotes its argument, so quoted phrases matched nothing and three of the
  four queries in the committed snapshot read `0` with no reason attached. It
  now calls the REST endpoint and stores `total_count` and `incomplete_results`.
- **A fork's default branch is compared like any other.** Forking and committing
  straight to `main` is the most common outside pattern; skipping those branches
  by name made that contributor indistinguishable from an untouched fork. Three
  such divergences exist today and were invisible.
- **Raw counts, not derived booleans.** `totalCommits`, commits returned, files
  returned, the base and merge-base SHAs. GitHub caps a comparison's file list
  at 300 with no way to page past it, so a stored `truncated: false` says
  nothing about how close it came.
- **Branch names are escaped into the URL.** `#` is legal in a ref and truncates
  the request as a fragment; slashes stay literal because the compare endpoint
  expects them.
- **Forks are listed oldest-first.** Newest-first means a fork created
  mid-pagination shifts every later page boundary and silently duplicates or
  drops entries.
- **The blind spots are numbers.** GitHub's fork counter against the forks it
  will actually list (13 against 12 for kubernetes-sigs, persistently), and how
  many forks the per-run cap skipped.
- **Affiliation is frozen at first sighting.** Anyone ever seen outside the
  contributor list stays outside. Recomputing it means that the day the first
  outside contributor merges something, re-classifying history turns every past
  outside signal into an inside one and the milestone un-happens.
- **Who wrote the commits decides, not who holds the fork.** The compare
  response names the author of every commit and the collector used to throw it
  away, so an org account holding branches a contributor wrote read as the
  largest outside adopter on the dashboard. Ownership is now evidence only for a
  fork with no commits to read, which is what keeps the hand-maintained org list
  short: it is the fallback, not the mechanism. A commit whose email matches no
  account contributes no evidence rather than an outsider, and a bot's commits
  are not a person's — including `claude`, a shared account with a user type and
  no `[bot]` suffix.
- **A login is never in both lists.** Naming a frozen outsider as an inside org
  used to add it to inside and leave it in outside; classification reads
  outside, so the change did nothing and reported nothing.
- **Reviewers and commenters are people too.** Only pull request and issue
  authors reached the affiliation pass, so four people who have only ever
  reviewed or commented were in neither list.
- **The judgement calls live in `affiliation.json`, not in the code.** It is an
  override list, not a roster: name someone only when the derived answer is
  wrong. An entry beats everything, including the freeze — a person saying "this
  account is ours" is not a derived answer, and leaving it unable to correct the
  record is how a wrong label becomes permanent. A login in both lists is an
  error at startup rather than a tie-break.
- **The freeze protects a measurement, not a rule.** Logins misread by the old
  ownership rule would otherwise carry forward forever, so `--refreeze` decides
  affiliation from one run alone. It is a deliberate act and the snapshot says
  so: `carriedFrom` is null.
- **A run that dies leaves a partial file, never a corrupt one.** The collector
  checkpoints after every fork under a key that `list()` does not return, so a
  partial run can never be mistaken for or overwrite a complete snapshot from
  the same day.
- **A thinner run does not replace a fuller one from the same day.** A
  `--skip-forks` run finishes cleanly and is not partial, but it knows strictly
  less; overwriting turns a complete day into a thin one, which reads downstream
  as a week when nobody forked anything. `--force` if you mean it.
- **A record carries its format version, and a reader refuses one it does not
  know** rather than failing three functions later.

## Rules the history enforces

`series.py` turns the stored records into two different kinds of thing, and
confusing them is how a trend chart lies.

- **A run point is discrete and never summed.** Fork counts and reference counts
  are whatever the world looked like the moment a run took them. Runs are
  irregular, so the chart plots them where they were taken and draws nothing
  between two of them.
- **A daily point accumulates.** Each run's fourteen-day traffic window overlaps
  the last one's, so the windows stitch into a history longer than the fourteen
  days GitHub retains. Two runs six days apart give twenty consecutive days.
- **The window ends yesterday and never includes today**, and coverage comes
  from the run's date, not from the first and last entry in its array. GitHub
  omits a day with no traffic entirely, so deriving the window from the array
  would shrink it at a quiet edge and turn a real zero into a gap.
- **Absent inside a covered window is zero; absent outside every window is a
  gap.** The gap is drawn as a break in the line. Filling it with zeroes draws a
  collapse in traffic that never happened.
- **Unique visitors are never added up.** GitHub deduplicates within whatever
  window it is asked about: fourteen daily uniques here sum to 89 against a
  reported window figure of 37. The window figure is kept whole, and the page
  never sums uniques across days or across repositories.
- **A record this version cannot read is named on the page**, not dropped. The
  first snapshot ever taken predates the store and has no format version; a walk
  that raised on it could never get past the oldest date there is. A chart
  missing a date it could not read looks complete and is not.

## Rules classification enforces

- **A category takes the primary slot only above a 20% share of the branch's
  changed lines.** The floor existed before but was bypassed by its own
  fallback, which took the largest remaining area with no floor at all — one
  branch that is 88% documentation read as "adding a harness". Substantive work
  gets first refusal over tests and documentation, but it still has to clear the
  floor; nothing clearing it is `mixed`.
- **Share is compared before tier.** Strict tier order let a specific category
  holding 20% of a branch beat a general one holding 79%.
- **Adding a harness means a directory that does not exist upstream.** Matching
  any file under a harness directory counted editing one as adding one, and read
  the `api` in `pkg/agents/runner/api/` — the directory model providers live in
  — as a harness name. Nine branches reported a provider as a harness.
- **A change is identified by its content, not its branch name.** The signature
  hashes the sorted path list together with additions and deletions. 242
  branches are 225 distinct changes. Every count on the page follows this,
  extension hotspots included: people fork a fork and carry every branch with
  them, so a change sitting on four forks is one extension of the benchmark and
  the bar that counted four was counting the copying.
- **Deduplicate within an affiliation group, never across it.** Fourteen outside
  branches are byte-identical to branches on a contributor's fork; merging them
  across the boundary makes the outside share depend on an arbitrary tie-break.
- **Affiliation is read from the snapshot, never recomputed.**
- **Nothing is published from code search until the control query passes**, and
  a query that matched more files than GitHub will return is marked capped — 249
  matches behind 100 returned hits is not 100 references. One file matched by two
  queries is one reference.
- **Affiliation is per branch, not per fork.** One outside contributor wrote 11
  commits on an org account that holds 25 branches; charging the fork charged
  all 25 to the outside. 3 of 19 and 2 of 6 actually are, which moves the
  outside branch share from 11.8% to 3.7%.
- **Outside share counts owners, not repositories.** Contributors fork both
  repositories and are counted twice while every outside owner is counted once,
  so a per-repository denominator is inflated with insiders and pushes the
  headline down: 18.5% by repository, 22.2% by owner. A fork nobody ever
  committed to is reported separately — 2 of the 4 outside owners are inactive.
- **The unclassified share is weighted by changed lines**, because a branch gets
  a category from whatever else it touched. 26,000 lines under a directory that
  has since been deleted upstream were hiding behind a 2.4% branch-level figure.
- **The conversion ratio and clones-per-cloner are gone.** The first divided
  four months of forks across both repositories by fourteen days of visitors to
  one; the second is 39 clones per cloner against 511 page views, which is
  continuous integration, not people.

`PATH_TAXONOMY` and `UPSTREAM_HARNESSES` are constants rather than filesystem
reads, so classification stays pure and re-runnable over old snapshots.
`test_classify.py` asserts they still match the checkout — a prefix pointing at
a directory that no longer exists silently stops classifying anything, and
nothing fails. `HISTORICAL_PREFIXES` is the exception list for directories that
are gone upstream but still appear in fork branches.

## What a snapshot contains

Repository facts, traffic, contributors, every fork and its diverged branches,
code-search references — and, new, every pull request and issue with its
reviews, comments and changed files, from GraphQL.

GraphQL because the cost is not close: **26 requests** for 296 pull requests and
30 issues across both repositories, where the REST equivalent is roughly one
call per pull request plus one per review page.

Per pull request: author (with whether the account is a bot), created, merged
and closed times, state, additions and deletions, the full changed-file list
(paginated past the 100-node limit — two pull requests need it), every review
with its author and time, and the first fifty comments with `commentCount` so a
truncated list is visible rather than assumed away.

> Snapshots carry contributor, author and fork-owner logins. They are raw input,
> not a published artifact, and `.gitignore` keeps them out of git. The
> classified record and the dashboard carry aggregates only —
> `PRODUCTION_PLAN.md` 7.3.

## Cost, measured

| Run | Requests | Wall clock |
|---|---|---|
| `--skip-forks --skip-search` | 26 | 33s |
| `--skip-pulls` (forks and search) | 353 | 4m45s |

- Core API: 5,000 requests/hour. Fork-branch comparison is essentially all of
  the cost — one request per fork, one per fork's branch listing, one per
  diverged branch.
- Code search: **10 requests/minute** — the binding constraint. The collector
  sleeps between queries, and the control query spends one of them.
- `--max-forks` caps the expensive part. Whatever it skips is recorded, so a
  capped run never reads as full coverage.

The per-run budget left over is stored in the snapshot, per resource, so a thin
run can be explained after the fact rather than guessed at.

**Not implemented, deliberately:** skipping a fork whose `pushed_at` has not
moved since the last run. The comparison is three-dot against upstream `main`,
so its result depends on both ends — every branch on one fork currently reports
`behindBy: 308`, which is a fact about upstream, not the branch. Carrying a
stale result forward freezes that number, and the merge base shifts exactly when
a branch's work lands upstream, which is the case the metric most cares about.

## Tests

```bash
pytest hack/usage-metrics/
```

No network: the client takes a fake runner. What is worth testing is not that a
request succeeds but what happens when one fails, because every one of those
cases has silently corrupted a published number. Every classification test is
named after a number that was published wrong.

## Editing the dashboard

Edit `dashboard.template.html` and re-run `render.py`. Do not edit the generated
`dashboard.html` — it is overwritten on every render.

Chart colors come from a validated categorical palette; slots 1–3 clear the
colorblind-separation and contrast gates in both light and dark mode. If you
change a series color, re-validate the set rather than eyeballing it.

Extension hotspots opens on the last 14 days, the same window the traffic cards
use. The range filters on a branch's **last commit**, so it means "still being
worked on in the window", not "started in it", and a `main` branch that took one
commit yesterday brings its whole divergence with it. Copies are collapsed after
the range, never before — collapsing first can keep the copy that falls outside
the window and drop the ones inside. A branch with no commit date is held out of
a bounded range and counted under **All**, with a line under the chart saying
how many; every snapshot from format 2 on carries the date.
