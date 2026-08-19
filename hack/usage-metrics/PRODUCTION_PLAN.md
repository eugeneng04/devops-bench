# Usage metrics — full implementation plan

The complete build, from nothing, in the order it should be built. Roughly half of
it exists as a working prototype; each stage says what is there and what is
missing, so nothing gets rebuilt for no reason.

This revision follows an adversarial review of the previous one. Several numbers
the earlier plan published turned out to be wrong; they are withdrawn in Stage 8
and corrected where they appear.

## The question this answers

Does anyone outside the team use devops-bench, and is that growing?

Everything below exists to answer that from public GitHub data alone, on a
schedule, with numbers nobody has to caveat.

## Shape of the system

```
GitHub  ──►  collect.py  ──────►  snapshot   (raw, one per run)
                                     │  ▲
                                     ▼  │
                              classify.py   (pure: no network)
                                     │  ▲
                                     ▼  │
                                 classified  (categories + ratios, one per run)
                                     │  ▲
                                     ▼  │
                               series.py     (reads every run ever stored)
                                     │  ▲
                                     ▼  │
                                  series     (figures per date)
                                     │
                                     ▼
                              render.py  ──►  dashboard.html  (self-contained page)

                        ┌──────────────────────────┐
       every ▲ ▼ above  │  the store               │  files, in a git repo
       goes through ────►  put · get · list        │  (Stage 7)
                        └──────────────────────────┘
```

Four programs, three kinds of record between them, and one storage interface
they all go through. No program knows where the records live.

Collection and classification are separate because the categories will be wrong
at first and will be revised — and a revision has to be re-applicable to every
run ever saved. That promise is what makes the store's retention policy
load-bearing rather than an implementation detail.

---

# Stage −1 — Three things that are broken right now

Not future work. These are live defects in code that has already produced a
committed dashboard. Fix them before anything else, because two of them are
silently corrupting the data and the third is a public-facing hazard.

**Code search has never worked.** *(Fixed in Stage 1.)* The collector shelled
out to `gh search code`,
which re-quotes its argument, so the quoted phrases become literal search tokens
and the query matches nothing. It then records the empty result as a successful
measurement of zero.

```
gh search code '"from devops_bench"'          ->  []
gh api search/code q='"from devops_bench"'    ->  249
```

Three of the four reference queries in the saved snapshot read `0` with
`unavailable: null`. Every statement about outside references rests on this.
Fix: call the REST endpoint directly, store `total_count` and
`incomplete_results`, and never publish a search figure without the control
query in Stage 1.3.

**A branch name can blank the dashboard.** *(Fixed.)* `render.py` escaped only
`</`, reasoning that a literal `</script>` is the only way out of the JSON
block. It is not — a string containing `<!--<script>` drives the HTML tokenizer
into the double-escaped state, where the real closing tag stops closing, and
everything after it is swallowed into the JSON. Confirmed in Chrome: the rest of
the page never parses and no script after the block runs, so the page renders
empty. The `>` matters; `<!--<script` without a terminator is inert.
`git check-ref-format 'refs/heads/<!--<script>'` accepts that name, so anyone
can push it to a fork. Not script execution — the template uses `textContent`
throughout — but remote defacement of a published page. Fixed by escaping `<`,
`>`, and `&` as `<`, `>`, `&`, which leaves no sequence the
tokenizer reacts to and decodes to the same JSON.

**A throttled comparison deletes a branch.** *(Fixed in Stage 1.2.)*
`collect_forks` wrapped the compare call in `except Unavailable: continue`, so a
rate-limited request and a branch that genuinely shares no history produced the
same result: nothing.

---

# Stage 0 — Freeze the three record formats, and the store they go in

**Why first.** The four programs only meet through stored records. Those
formats, plus the interface that reads and writes them, are the real interface —
and changing one later means rewriting the programs on both sides of it.

**Build.**
- **Snapshot** — what GitHub said, unprocessed. Every measurement is wrapped as
  either a value or a reason it is missing. No bare numbers.
- **Classified** — categories, counts, and ratios for one snapshot.
- **Series** — the same figures per date, across every snapshot.

## 0.1 The store

Three operations, keyed by kind and date. Nothing else, and no program imports a
database library directly:

```
put(kind, date, record)      # kind: snapshot | classified | series
get(kind, date) -> record
list(kind) -> [date, ...]    # ascending; how series.py and re-classify walk history
```

One implementation, used everywhere. **Local files** is the default, and
production is the same files in a git repository of their own — Stage 7.2. No
cloud account is needed to run any of this, by hand or on a schedule. Cloud
Storage sits behind the same three calls if it ever outgrows git.

The abstraction is worth it for exactly one reason: it is the difference between
deciding where data lives now and deciding it later. It is three functions;
resist making it more.

Four things every file carries, none of which exist today:

- **A format version, and a program that reads it.** The current classified
  output has no version field at all, and `classify.py` never looks at the
  snapshot's. The first format change turns every historical snapshot into a
  `KeyError` in classify, and a stale-shaped payload into a dashboard of blanks
  in render. Reading the version and refusing an unknown one is the whole
  requirement; migration can wait until there is a second version.
- **A taxonomy version** on classified output. Without it, revising the category
  rules produces a step change in the trend chart that is indistinguishable from
  a change in the codebase — which destroys the only thing a heuristic
  classifier is good for.
- **Provenance.** The collector's git SHA, the source snapshot filename, and the
  workflow run URL. When someone disputes a number there has to be a path from
  the dashboard cell back to the rows that produced it.
- **Per-date coverage** on the series: which repos had traffic, which signals
  were unavailable. A metric whose coverage changes over time produces trend
  movement that is pure instrumentation.

**Status.** Built. All three formats carry a version, provenance and coverage,
and `series.py` writes the third.

**Done when.** The three formats are written down in the README; a hand-written
example of each is accepted by the program that consumes it; and a file carrying
an unknown version is rejected with a clear message rather than half-read.

---

# Stage 1 — Collection

One program that asks GitHub for everything and writes one dated file. It is the
only part that touches the network.

## 1.1 The call wrapper

Every GitHub request goes through one function so the safety rules live in one
place: a time limit on every call, retries where retrying helps, and a record of
how much of the hourly budget was left at the end.

**Retry only what is retryable.** A blanket "retry on 403" is worse than no
retry. Two completely different things return 403:

| Response | Meaning | What to do |
|---|---|---|
| 403, `Retry-After` present, or remaining budget 0, or body says secondary limit | Throttled | Wait as asked, retry |
| 403, budget untouched, "Must have push access" | Permission, permanent | Record the reason, move on |

The kubernetes-sigs traffic endpoint is permanently in the second row. Retrying
it with backoff adds four useless requests and about thirty seconds to every
single run, forever. The same applies to 5xx: GitHub documents that a large diff
comparison times out with a 5xx, which is a property of that branch, not a blip
— retrying it five times wastes the most on the biggest branches.

**This is impossible with the current design.** `gh_api` shells out to `gh api`
and reduces every failure to the last line of stderr, discarding the status code
and all headers. The wrapper needs the status line — either `gh api -i` with
parsing, or a real HTTP client.

**Paginate by hand.** `gh api --paginate` emits nothing at all if any page
fails, so a retry re-fetches every page from the start — a run that is already
being throttled amplifies its own load. Request pages explicitly so a retry is
per-page and completed pages survive.

**Drop the SHA-cache idea.** The earlier plan proposed skipping any branch whose
head SHA had not moved. That is unsound. The comparison is three-dot against
upstream `main`, so its result depends on both ends, and `main` moves every
week. Every branch on one fork currently reports `behindBy: 175` — that number
is a property of upstream, not the branch. Caching on head SHA alone freezes it
at last week's value, and the merge base shifts precisely when a branch's work
lands upstream, which is the case the metric cares about most. If caching is
ever revisited, the key is *both* SHAs, and the hit rate is then near zero.

The honest cost reductions available: skip a fork whose `pushed_at` has not
moved since the previous run, and skip a fork's `main` when its SHA equals
upstream's (a same-run equality test, not cross-run reuse).

*Missing today.* No retries, no backoff, no timeout, no budget recording.

## 1.2 Failure is a value

Every measurement is recorded as either a number or a reason it is absent. A
measurement that failed and a measurement of zero must never look the same.

Three holes today:

- **An unexpected response shape kills the run** before anything is saved.
  `measure()` catches only its own exception type, so a missing field propagates
  out.
- **One bad fork loses all of them.** That same propagation escapes the whole
  fork loop, so every fork already collected in that pass is discarded and
  replaced by a single null. Accumulate per fork, and catch per fork.
- **A failed comparison deletes the branch** (see Stage −1).

## 1.3 What gets collected

| Signal | What it tells you | Notes |
|---|---|---|
| Repo facts | stars, forks, watchers, open issues | One request each. `open_issues_count` includes pull requests — rename the field or subtract them |
| Traffic | visitors, clones, referrers, popular pages | **Only 14 days exist.** Needs an Administration-read token, not push access — see Stage 6 |
| Contributors | who is on the team | Frozen into the snapshot, see 1.6 |
| Forks and their branches | what people changed after forking | The expensive part |
| Code search | who mentions or imports the project elsewhere | REST endpoint, with a control query |

**Every code search carries a control.** Run one query per batch whose expected
result is known and non-zero — a phrase that must match inside our own
repositories. If the control returns nothing, mark every reference measurement
in that run unavailable. Without it, "nobody references us" and "search is
broken or the token can't see anything" are the same output, which is exactly
what happened.

Two structural limits to record in the README rather than discover later: code
search only indexes the default branch of non-fork public repositories, so none
of the forks are searchable at all; and results are capped at 100 with
`incomplete_results` as the only signal that more exist.

## 1.4 Fork comparison, the expensive part

For each fork, list its branches and compare each against upstream to get the
changed files.

**Stop skipping `main`.** The collector unconditionally skips `main`, `master`
and `gh-pages`. A casual adopter who forks and commits straight to their default
branch — the single most common outside pattern, and the exact population being
measured — therefore contributes nothing and looks identical to an untouched
fork. Compare `main` too and let the existing "not ahead of us" filter drop it.
Cost: one extra request per fork.

**Record the raw counts, not derived booleans.** Store `total_commits`, the
number of commits returned, the number of files returned, and the base SHA the
comparison ran against. GitHub caps the file list at 300 for the entire
comparison and there is no way to page past it — pagination applies to commits,
not files. A stored `fileListTruncated: false` tells you nothing when the cap
was never approached; the real counts let classification refuse to report a
category share it cannot support.

**Encode branch names into the URL.** `#` is a legal character in a git ref and
truncates the request path as a fragment, producing a malformed comparison that
currently vanishes silently.

**Paginate forks in a stable order.** The listing is sorted newest-first, so a
fork created mid-pagination shifts every later page boundary and silently
duplicates or drops entries. Sort by oldest, which is append-only.

**Record the blind spots as numbers, not prose.** The forks GitHub says exist
minus the forks it will list (private forks, blocked accounts, a counter that is
not always decremented). And the sum of `forks_count` across the forks
themselves, which is already in the listing response at zero extra cost, so the
size of the forks-of-forks gap is visible rather than assumed.

## 1.5 Writing the file

Checkpoint to disk after each fork, so a run killed by the job time limit is a
partial file rather than nothing. Mark it partial. Never let a partial run
overwrite a good file from the same day — the current code writes
`snapshots/<date>.json` unconditionally at the very end.

Cap the number of forks processed per run, in a deterministic order. Forking is
unrestricted; a few hundred forks would blow the hourly limit and the job's time
limit together. Log what was skipped, so a cap never reads as full coverage.

## 1.6 Freeze affiliation at collection time

Whether a fork owner is on the team must be decided when the snapshot is taken
and stored in it, not recomputed later. Recomputing it against today's
contributor list means that when the one genuine outside contributor lands a
pull request, re-classifying history retroactively converts every past outside
signal into an inside one — the trend rewrites itself and the milestone
un-happens.

The contributor list also needs two fixes: it currently includes
`devops-bench-sync-bot` and `k8s-ci-robot`, so the published "19 contributors"
is 17 humans; and an organisation account that holds a fork on a contributor's
behalf is not an outside adopter, which the login-matching rule cannot see.

*Built, and the second fix did not need a roster.* Fork **ownership** was the
signal and it is wrong in both directions: an org account holds 25 branches
contributors wrote, and contributors' own forks carry commits outsiders wrote.
The compare response already names the author of every commit and the collector
was discarding them. Affiliation now comes from authorship, per branch — one
outsider's 11 commits on an org account's fork used to charge all 25 of its
branches to the outside; 3 of 19 and 2 of 6 actually are. `INSIDE_ORGS` survives
only as the fallback for a fork with no commits to read.

Three defects fell out of building it:
- A login could land in **both** lists. Naming a frozen outsider as an inside
  org added it to inside and left it in outside; classification reads outside,
  so the change did nothing and reported nothing.
- Reviewers and commenters never reached the affiliation pass at all. Four
  people who have only ever reviewed or commented were in neither list.
- `claude` is a shared automation account with a user type and no `[bot]`
  suffix. Four of its commits on a fork made that fork an outside adopter.

The freeze protects a measurement from being recomputed away; it does not
protect a rule that was wrong, and logins misread by the ownership rule carry
forward on their own. `--refreeze` decides affiliation from one run alone and
records `carriedFrom: null` so the discontinuity is visible.

What is left is genuinely a judgement, so it lives in `affiliation.json` rather
than in the code: an override list with an `inside` and an `outside` array,
which anyone can edit without touching Python. It is short by design — the
derived rules answer for everyone not named in it. `outside` matters as much as
`inside`: the contributors endpoint counts anyone who merged a commit, so a
reviewer from another project who landed one fix reads as a teammate and pushes
the outside share down. An entry beats the freeze, and a login in both arrays
exits with an error rather than picking a winner.

**Stage 1 done when.** Run it with a deliberately throttled or broken token. You
still get a file. Every fork in it has either a number or a reason. The
difference between GitHub's fork count and the forks actually listed is recorded
as a field.

*Note the earlier exit test was unachievable:* GitHub reports 13 forks for
kubernetes-sigs and lists 12. It reported 12 and listed 11 the day before. That
gap is persistent, not a race, so it can be measured but never gated on.

---

# Stage 2 — Tests

Record real GitHub responses to disk once, then replay them. No network in the
test suite.

**Collection cases**, because these are the ones that go wrong quietly: a
throttled response, a permission-denied response, a response missing a field, a
comparison at the 300-file cap, a code search whose control query fails, a
branch name containing `#`, a fork deleted between listing and comparison, and a
run killed halfway through (must leave a partial file, and must not overwrite a
good one).

**Classification cases**, including the two historical mistakes in 3.1 and every
rule in 3.2 and 3.3. There are currently no tests here at all.

**One end-to-end test.** Fixture in, collect → classify → series → render, and
assert a specific number appears in the HTML. Nothing today would catch two
programs drifting apart on a format both of their own test suites still accept.

**Wire it into CI.** Both pre-commit hooks are scoped to
`^(devops_bench|tests/unit)/` and the guardrails workflow lints and tests the
same two directories, so everything under `hack/` is unlinted and untested.
Tests written here do not run until this changes.

**Done when.** Tests pass with the network off, each failure case produces a
reason string rather than a gap, and the suite runs in CI on every pull request.

---

# Stage 3 — Classification

*Built.* Reads one snapshot, writes categories and ratios. No network, so it can
be re-run over every snapshot ever saved. Every figure quoted below was measured
against the format-1 snapshot; the numbers in parentheses are what the rewritten
code reports against the fuller format-2 one, which recovers the fork default
branches and the comparisons the old collector dropped.

## 3.1 What kind of change is this

Each changed file maps to a category by its path. Each branch gets one primary
category plus any others it touched.

Two rules that are not obvious, both learned from getting it wrong:

- **A category only becomes the primary one if it is a real share of the
  change.** There is a 20% floor, but it is bypassed by its own fallback: when
  nothing clears the floor, the code takes the largest remaining category with
  no floor at all. The exact bug this rule was written to prevent still
  reproduces. 36 of 210 branches — 17% — get a primary category holding a
  minority share while a category at least 1.5× larger loses. One branch is 88%
  documentation and reads as "adding a harness". **Fixed:** the floor now applies
  to the fallback, and a branch where nothing clears it is `mixed`.
- **Tests and documentation only win when there is nothing else.** This was
  implemented as a strict tier order, which overshoots: a first-tier category at
  20% beat a second-tier category at 79%. **Fixed:** tier decides only which
  categories get first refusal — substantive work is offered the slot before
  tests and documentation, but it still has to clear the floor to take it, so a
  branch that is 90% tests is called tests rather than mixed.

**The harness rule needed a different test.** "Adding an agent harness" matched
any file under a harness directory, so editing an existing harness counted as
adding one, and a single file under `pkg/agents/runner/api/` read the
intermediate path segment as a harness name — adding a *model provider* was
reported as adding a harness. Of the 7 branches counted, 4 edited harnesses that
already existed and 2 were model providers. **Fixed:** the directory has to be
absent upstream. That leaves 4 branches, adding two genuinely new harnesses.

Because classification is pure, "absent upstream" is the constant
`UPSTREAM_HARNESSES` rather than a filesystem read; `test_classify.py` asserts it
still matches the checkout.

## 3.2 Count distinct changes, not branches

Identify a change by its content, not its branch name, and report both figures
side by side.

**The number is 189, not 167** (225 of 242). The earlier plan's 167
double-subtracted the outside branches; 210 branches collapse to 189 under the
stated rule. The rule also needed narrowing, for two reasons found by
measurement:

- **The file-path component contributed nothing.** Paths plus added plus removed
  gives 189; added plus removed alone also gives 189, and still does on the
  fuller snapshot — two integers separating everything is luck, not a property
  of the rule, and a collision risk at scale. **Fixed:** the signature hashes
  the sorted path list together with the two counts.
- **Deduplicate within an affiliation group, never across it.** Nine of the 22
  outside branches are byte-identical to branches on a contributor's fork (14 of
  28) — one organisation account mirrors a contributor and holds 86% of all
  outside branch activity. Merging across the boundary means the headline
  outside ratio swings by a third depending on an unspecified tie-break.
  **Fixed:** signatures are collapsed within each group separately, so the same
  work on both sides of the boundary counts once on each.

**Merged work cannot be labelled yet.** The plan says to label already-merged
work rather than dropping it, but the snapshot contains no merge or pull-request
data, and classification is pure by design so it cannot go and fetch it. Either
collect merge state in Stage 1 or drop the claim. Note also that a squash-merged
branch stays permanently ahead and counts as unmerged, while a rebase-merged one
drops to zero and vanishes — merge strategy, not adoption, decides.

## 3.3 Who is outside the team

Read the frozen affiliation from the snapshot (Stage 1.6). Do not recompute.
*Done — classification no longer touches the contributors list.*

The contributors endpoint returns commit authors of merged commits only, so
co-authors, reviewers, and issue authors all read as outside; and a renamed
account silently becomes outside. Seed the inside set from OWNERS and
organisation membership rather than the contributors list alone.

*Partly done.* Reviewers and commenters now reach the pass (1.6), so they are
classified rather than missing. OWNERS is still not read — this repository has
no OWNERS file — and organisation membership needs a token scope the run does
not have, so both remain open.

## 3.4 References elsewhere

A code-search hit becomes one of: depending on it, running it, or citing it.
Hits in our own repositories do not count.

**Publish nothing here until the control query passes.** *Done* — an untrusted
control makes every reference figure empty with a reason, not `0`.

**With search working, the hits are real and the taxonomy was wrong.** 13
distinct external references, not zero: `kubernetes/test-infra` runs the
benchmark from a prow job, `gke-labs/kube-agents` vendors it and declares it in
`bench/pyproject.toml`, and `kubernetes/community` and an unrelated CNCF index
cite it. Three corrections came out of that:

- Two branches of the taxonomy were literally the same code, making "citing" an
  unconditional catch-all that absorbed a Python import. **Fixed**, and an
  import shown inside a README is now a citation rather than a dependency.
- `config/jobs/` — prow — was not in the CI pattern, so the one pipeline outside
  this project that actually runs the benchmark read as a citation. **Fixed.**
- The import queries overlap, so a file matched by both was counted twice.
  **Fixed:** hits are keyed by repository and path, keeping the strongest class.

This also disproves the earlier claim that depending and running stay
structurally empty until a package is published: a vendored copy and a CI job
both count, and both exist. The dashboard reports them as measured.

A capped query is marked as capped against its real total — `"from
devops_bench"` matches 249 files and GitHub returns 100, so these counts are a
floor, not a measurement.

## 3.5 Ratios

Any ratio with nothing in the denominator is left empty, never reported as 0%.
Three specific corrections, all applied:

- **Outside forks: count owners, not repositories.** 26 forks (27) are held by
  18 distinct owners, because contributors who forked both repositories are
  counted twice while every outside owner is counted once. The denominator is
  inflated by insiders, which pushes the headline number *down*: 15.4% by
  repository (18.5%), 22.2% by owner. An activity threshold is reported
  alongside it — 2 of the 4 outside owners have never received a commit, so the
  active share is 12.5%.
- **Drop the conversion ratio.** It divides four months of forks across both
  repositories by fourteen days of visitors to one of them, and two of the four
  "conversions" happened before the window opened. The denominator is also
  mostly the team: the top referrer is an internal proxy and the top pages are
  the pull request list. Restricted to a matching window and repository it is
  2/37, which is too small to report.
- **Drop clones per cloner.** Clones step from about 20 a day to a flat 790 a
  day on 2 August, against 511 page views in the whole window — fifteen clones
  per view, and more unique cloners than unique viewers. That is continuous
  integration, not people. It cannot be published as engagement.

Unique visitors and unique cloners are also no longer summed across
repositories: they are per-repository de-duplications and do not add up.

**Still to do, in Stage 5.** Both dropped ratios are gone from the classified
record, but the dashboard recomputes its own figures in JavaScript per
repository selection, and clones-per-cloner is still the hero number there.
Replacing the hero is a dashboard design decision, not a classification one. The
two ratios that had a *wrong* definition — outside share and the unclassified
share — were fixed in the template as well, because fixing them only in
`classify.py` would have corrected numbers nobody sees.

## 3.6 The health check

Publish the share of changes the categories could not place. **Weight it by
changed lines, not by branch.** The branch-level figure is 2.4%; the
line-weighted figure is 5.0% (4.4%), and the single largest unplaced area —
`devops_bench/harness/`, 23,000 changed lines (26,521, 70% of everything
unplaced) — is invisible to the check because tier ordering hands those branches
a substantive category anyway. *Done, in both `classify.py` and the template.*

The claim that six path prefixes no longer exist in the tree does not hold up:
all 31 resolve against the current checkout. The drift is the other way round —
`devops_bench/harness/` was deleted upstream and was never in the taxonomy at
all, so the work simply went unplaced. It is now classified as `core`, alongside
`devops_bench/evalharness/`, and listed in `HISTORICAL_PREFIXES`. That drops the
line-weighted unclassified share to 1.3%.

Add a test that asserts every prefix in the taxonomy resolves against the
current checkout. That is the drift detector the health check was supposed to
be. *Done* — three of them: every prefix resolves unless it is declared
historical, every historical prefix is genuinely gone (so one that comes back
gets taken off the list), and `UPSTREAM_HARNESSES` matches the directories that
actually exist under the harness parents.

**Stage 3 done when.** Tests cover each rule, including the historical mistakes.
Re-running on the saved snapshot reports 189 distinct changes alongside 210
branches, and the unclassified share is line-weighted. **Met** — on the format-2
snapshot that is 225 distinct changes alongside 242 branches, the extra branches
being the fork default branches and the comparisons the old collector dropped.
84 tests pass.

---

# Stage 4 — The time series

**Built** — `series.py`, with `test_series.py` naming each way a trend chart
lies. It walks the store's `list()`, and `--reclassify` re-runs the current
taxonomy over every snapshot first, which is the re-runnable-over-history
promise `classify.py` alone could not keep.

A record this version cannot read is reported and skipped rather than raised.
The first snapshot ever taken has no format version, and because it is the
oldest record, a walk that raised on it could never get past the oldest date
there is — a permanent failure landing on the history rather than on the one
record. The dates skipped are carried into the series and named on the page.

**Counts add up; unique visitors do not.** This is the trap, and it is not the
one the earlier plan named. GitHub deduplicates uniques within whatever window
it is asked about, so the fourteen daily figures cannot be reassembled into a
fourteen-day total. Measured: the reported window figure is 37 unique visitors;
the daily figures sum to 89. The true window figure is not recoverable from the
daily array.

They are kept as different kinds of thing: a daily count that stitches into a
line, and a per-run window figure plotted as discrete points and never summed.
The page also no longer adds uniques across the two repositories, which was
invalid the moment both have traffic — it draws one line per repository.

**Referrers and popular pages have no daily breakdown at all.** They are
fourteen-day aggregates only. They can be sampled per run; they cannot become a
series.

**The window ends yesterday.** Measured across two observations, traffic covers
day −14 through day −1 in UTC; today is absent entirely. A weekly run therefore
has exactly seven days of slack, and two consecutive misses lose a day
permanently. "One missed run loses nothing" is true with no margin at all.

**Gaps are gaps.** Coverage comes from the run's date, not from the array's own
first and last entry — GitHub omits a quiet day entirely, so deriving the window
from the array would shrink it at the edge and turn a real zero into a gap.
Inside a covered window, absent is zero; outside every window it is a hole, and
the line breaks there. The per-date coverage from Stage 0 rides along, so a
repository whose traffic starts working reads as coverage rather than growth.

The stitching is real, not theoretical: the two runs stored today are six days
apart and cover twenty consecutive days between them, six more than GitHub
retains.

**Seed the history.** Traffic before the first run is gone and cannot be
recovered; fork and branch history is partly reconstructible from git. Nothing
has been backfilled, so the chart starts on 2026-07-29.

**Done when.** Pick any date on the chart; its numbers match the file that
covered that date. Delete a snapshot and the chart shows a gap, not a dip. A
taxonomy revision followed by a re-classify produces a chart whose step change
is labelled as one.

---

# Stage 5 — The dashboard

A single self-contained page: no network requests, no CDN, no build step.

**Built.** The single-day cards are the "latest" view, and two cards above them
are the history: *Traffic history*, the stitched daily windows with the line
broken at every gap, and *Adoption over time*, one point per collection. Both
axes are date-proportional — spacing runs by index would draw a fortnight's
silence and a day's gap the same width. The series is optional: with none, the
page says it has no history rather than drawing an empty chart.

Four things it must get right, all now enforced:

- **Escape the payload properly** (Stage −1).
- **Count distinct changes in the chart, not branches** — 3.2 settled this for
  the headline and the chart went on counting copies. People fork a fork and
  carry every branch with them: four accounts hold byte-identical copies of nine
  changes, and one person pushed the same work twice under two names. 248
  branches are 218 distinct changes; Infrastructure falls from 48 to 40 and
  Changing grading from 16 to 7, which is enough to hand the top bar to Tests.
  The bar was measuring how often work is copied, and reading as how much of the
  benchmark people extend.
- **Show the extension mix for outside forks separately.** 188 of 210 branches
  are on contributor-owned forks, so the current "extension hotspots" chart is
  the team describing itself, presented as adoption. The outside-only mix is 22
  branches from 2 accounts, 19 of them from the mirror organisation. The design
  doc's own risk table already said to report the outside ratio and never raw
  counts.
- **Distinguish unmeasurable from zero**, for the reference classes in 3.4 and
  for kubernetes-sigs traffic.

The hotspots card opens on the last 14 days, the traffic window, so both halves
of the page describe the same fortnight. It filters on the branch's last commit,
which is the only date the snapshot carries; 41 of the 218 distinct changes fall
in a fortnight, 82 in 30 days and 211 in 90, so a reader who sees only the recent
slice needs the wider steps to know what it is a slice of.

**Done when.** The page opens with no network, every chart's table view agrees
with the underlying file, and a golden-file test covers the escaping, the
missing-measurement placeholder, and the null-traffic banner.

---

# Stage 6 — Run it automatically

**Written, never run** — `.github/workflows/usage-metrics.yml`. GitHub deletes
traffic data after 14 days, so every week nobody runs it by hand is data
permanently lost.

It runs twice a week rather than weekly. The window ends yesterday, so a weekly
run has exactly seven days of slack and two consecutive misses lose a day that
cannot be recovered from anywhere; a second run costs about seven minutes and
removes that failure mode. It is guarded to `gke-labs/devops-bench`, because
without that every fork of this repository runs the collector against the
upstream repositories on the same schedule.

**Two things must exist before it can run:** the data repository, named in
`vars.USAGE_METRICS_DATA_REPO`, and a token that can write to it and read
traffic in both organisations, in `secrets.USAGE_METRICS_TOKEN`. Neither is set.
7.2 says to settle 7.3 before the first commit rather than after, because
deleting from git means rewriting history.

## 6.1 The token, which the earlier plan got wrong

The traffic endpoints are not gated on push access. They need repository
**Administration: read** — and `administration` is not a valid key in a workflow
permissions block, so the built-in `GITHUB_TOKEN` cannot hold it at any level.
The earlier plan's safety design ("write permission only on the job that opens
the pull request") buys the wrong permission entirely, and the design doc states
the requirement wrong in the same way.

What actually works: a GitHub App installation token with Administration read,
minted per run. This is also strictly safer than the alternative, because it
never needs write access at all.

Opening a pull request has a second problem: this organisation locks
`GITHUB_TOKEN` to read-only, and every existing write-path workflow here uses a
bot personal access token with a bot git identity set for CLA validation. A new
job that ignores that convention either fails at pull-request creation or opens
pull requests the CLA bot blocks forever.

## 6.2 The job writes to the store, not to a pull request

**A pull request gate loses the data it exists to save.** Traffic dies at 14
days. The repository's convention is to force-push a fixed branch, so week two
overwrites unmerged week one permanently — one person away for three weeks
means two windows gone, with every run reporting success. And no approver is
named. Observed facts are not a reviewable proposal.

With the Stage 7 store this mostly evaporates: the job writes records and
nothing waits on a human. Pull requests stay for taxonomy and code changes,
where review is meaningful.

With git as the backend (7.2) the job's write is a commit and a push to the data
repository, so there is no second credential system — a deploy key or an App
installation on that one repository is the whole of it, alongside the GitHub App
token from 6.1 that traffic needs. The rules are: **commit directly to the
default branch of the data repository, never force-push, and never overwrite a
dated record** — the 1.5 rule that a thinner run does not replace a fuller one
is what makes an append-only history safe to automate.

One thing the store does not remove: if the dashboard is published from this
repository, rendering still produces a commit, so the render step keeps whatever
review convention the repository wants. Only the data escapes it.

## 6.3 Workflow hygiene this repository already practises

- **A concurrency group.** Every existing scheduled workflow here has one. A
  manual run overlapping a scheduled one has both writing the same dated file.
- **A repository guard** (`if: github.repository == ...`). Both existing
  scheduled workflows have one. Without it every fork runs the collector on
  schedule, each spending its owner's rate budget hammering upstream.
- **A time limit**, with a partial save on timeout rather than a failure.
- **A heartbeat.** GitHub disables scheduled workflows after 60 days with no
  commit to the repository, notifying the last committer and nobody else. Only
  commits reset the clock, and a bot's count — so a repository that is developed
  is never at risk, and this one is. The `git commit … || exit 0` idiom that
  keeps a collector green through 60 idle days is not what makes this safe and
  should not be relied on as if it were.

## 6.4 The emptiness gate, defined properly

"Fail loudly when too much came back empty" as written both false-alarms and
misses:

- It **false-alarms every run**, because kubernetes-sigs traffic is legitimately
  and permanently unavailable — until someone tunes it to ignore that field, at
  which point it ignores the field that matters most.
- It **misses the real failure**, because the silent paths produce no missing
  marker at all. A dropped comparison and an empty code search both look like
  clean data.

Gate on expected denominators instead: the fork count recorded against the fork
count listed, every fork having either branches or a reason, the search control
query passing, and the remaining rate budget at end of run above a floor.

**Done when.** Two consecutive weeks run on their own, the second file's traffic
dates overlap the first, and a deliberately broken token produces a failed run
with a notification rather than a quiet green tick.

---

# Stage 7 — Storage and privacy

## 7.1 Keep every raw snapshot, forever

Whatever the backend, one rule does not bend: raw snapshots are kept
indefinitely. The stated reason collection and classification are separate
programs is that a revised taxonomy must be re-applicable to every run ever
saved. Any store with an expiry — build artifacts at 90 days being the obvious
trap — quietly voids that, and Stage 3's own acceptance test stops being
reproducible.

Size is not the obstacle. The snapshot is 2.4 MB and gzips to 119 KB: about **6
MB a year** at a weekly cadence, in any backend. (It was 924 KB before the
collector started storing pull requests, reviews and changed files. Both figures
are measured; the growth is worth knowing about because the ceiling in 7.2 is
not.)

## 7.2 The backend is git, in a repository of its own

A dated, immutable, append-only record that is written once per run and read by
walking every entry is a git history. Not *like* one — the same thing. The store
interface in 0.1 is already `put`/`get`/`list` over a directory, and the default
backend is already local files, so the whole change is a `.gitignore` line and a
`git push` in the scheduled job. No new code, no database, no cloud project, no
IAM.

This is a named and widely used pattern —
[git scraping](https://simonwillison.net/series/git-scraping/) — and GitHub
shipped [an officially supported version of it](http://rolandtanglao.com/2021/05/19/p1-simon-willison-github-scraping-official-supported-by-github-flat-data/).

**Size is not the objection, and the intuition here is wrong by two orders of
magnitude.** Consecutive snapshots are near-identical, so git deltas them almost
to nothing. Measured, on the two real snapshots six days apart:

| | |
|---|---|
| Snapshot on disk | 2.4 MB |
| First snapshot, packed into git | 252 KB |
| **Each subsequent snapshot** | **~12 KB** |

That is ~4.6 MB for a year of daily runs and under 1 MB for a year of weekly
ones. Compare the gzip-per-file figure in 7.1 (119 KB each, ~6 MB a year
weekly): git is *cheaper* than storing the same files gzipped in a bucket,
because a bucket cannot delta one object against the last.

**What git gives that a database does not:** every number is reviewable in a
diff; history cannot be rewritten without a force-push that every clone will
notice; and the provenance question in 0.1 is answered by `git log` rather than
by fields somebody has to remember to populate. 7.2's old objection to Firestore
— "whoever can write to the database can change history" — does not apply here,
and that inverts the comparison.

**Three real limits, and what each costs.**

- **Deletion requires rewriting history.** If a login ever has to come out — a
  removal request, or a private repository name that surfaced in a fork listing
  — a bucket is one `rm` and git is a force-push through every commit that ever
  touched it. This is the strongest argument for a store with real deletes, and
  it is a reason to settle 7.3 *before* the first commit rather than after.
- **The repository is the access-control boundary.** Read on the repo is read on
  the entire raw history; there is no way to grant the dashboard without the
  snapshots. A bucket has per-prefix IAM.
- **Scheduled workflows are disabled after 60 days of no commits.** Documented
  GitHub behaviour, and the classic way a git-scraping cron dies. It does not
  bite here: only commits count as activity and bot commits qualify, and this
  collector's snapshot always differs from the last one — it carries a
  collection timestamp and the leftover rate-limit budget — so every run
  commits. The `git commit … || exit 0` no-op idiom from the standard recipe is
  therefore not what keeps this alive, and should not be relied on as if it
  were.

**A repository of its own, not this one.** Every clone of the code repository
would otherwise pay for the data history — a default `git clone` fetches all
branches, so an orphan `data` branch does not avoid it. A separate repository
also makes the 7.3 decision an access-control setting on one thing instead of a
property of the main codebase.

**Escalate to Cloud Storage when — and only when — one of these is true:** a
removal request has to be honoured cleanly, someone needs the history in
BigQuery, or dashboard readers must not see raw snapshots. Cloud Storage is the
right escalation rather than Firestore, because Firestore caps a document at
1 MiB and the snapshot is **2,562,921 bytes — 2.4× over the limit** today (it
was 924,573 bytes one collector change ago, and it grows with every branch
anyone pushes to any fork, without bound). A Firestore backend would have to
gzip the record into a bytes field on day one. BigQuery external tables read
Cloud Storage directly and Firestore can be loaded from it; neither is true in
reverse. So: git now, Cloud Storage if it outgrows git, Firestore never.

Either way it is a URI behind the same three calls.

## 7.3 Names: omit them, do not hash them

This is no longer a decision to make before publishing; it has already been
published. Both the snapshot and `dashboard.html` are tracked in git today, and
the classified output carries each fork owner's login next to an
inside-or-outside label. The design doc claims affiliation is stored as a
boolean and never as a list of names.

Hashing is not a fix. The GitHub login namespace is small, public and
enumerable, so an unsalted hash is reversible in minutes; a committed salt is
equivalent to no salt; and a stable secret salt — which cross-run identity
matching requires — is one leak away from de-anonymising the entire history at
once.

The only thing Stage 3.3 needs is a membership test, which Stage 1.6 now
computes at collection time. So: **the committed and published artifacts carry
counts and category mixes only** — no logins, no per-person labels. Logins stay
in the raw snapshot only if re-classification genuinely needs them, documented
in the README and the design doc.

## 7.4 Get the SIG's agreement before publishing

Forks being public is not the whole answer. This is a derived work that names
individuals, infers their affiliation, and categorises what each is building in
their own fork — produced by a scheduled job in the vendor-side mirror, about
kubernetes-sigs contributors. Foundation practice is the other way round:
community metrics are foundation-operated and contribution-scoped.

Publishing aggregates only (7.3) resolves most of this. The remaining question —
whether the metrics directory is public at all, or produced for the SIG report —
is open question 6 in the design doc, and it blocks Stages 5, 6 and 7 together,
because committing data to a public repository *is* publishing.

---

# Stage 8 — Documentation

The README now describes the pipeline including `series.py`, and the rules the
history enforces. The design doc still needs these corrections, all measured:

| The doc or the earlier plan says | Actually |
|---|---|
| A saved file is "a few KB", under 1 MB a year | 2.4 MB raw, 119 KB gzipped — but ~12 KB a run once git deltas it, so under 1 MB a year weekly after all, for a different reason (7.2) |
| About 90 requests per run | 370 measured — 344 of them forks and branch comparisons, and unbounded in branch count |
| No usernames stored | Contributor logins plus every fork owner, in the snapshot, the classified output and the published dashboard |
| No outside users yet | One genuine outside contributor with pushed work |
| All 10 fork owners are contributors | 27 forks, 18 owners, 4 outside — 2 of whom never pushed a commit |
| No external references to the project | 13, including a prow job in `kubernetes/test-infra` that runs it |
| The traffic API requires write access | It requires Administration read, which `GITHUB_TOKEN` cannot hold |
| Data lives at `metrics/<date>.yaml`, version-controlled | Right about version control, wrong about the path and the format: JSON behind a store interface, in a data repository of its own |
| Reporting is `REPORT.md` plus a shields badge | Neither exists; the plan builds an HTML dashboard instead — reconcile or restore them |
| 167 distinct changes (earlier plan) | 189 on the format-1 snapshot, 225 of 242 branches on format 2 |

**Also write a runbook**, because the recovery window is short and the steps are
not guessable: what to do when a run fails (re-run by hand *within 14 days* or
the window is gone), where the token comes from, its permissions, who rotates
it, and what to do when the rate budget is exhausted.

**Done when.** Every number in the doc matches what the programs produce.

---

# Stage 9 — Name an owner, and detect the milestone

Someone reads these numbers on a fixed cadence and acts on them. The design doc
itself cites a CNCF project that launched a measurement programme in 2021 and
has held nothing but a README since.

This is a blocker for Stage 6, not a nicety. A scheduled job nobody reads is
worse than no job, because it looks like the question is being answered.

**And make the milestone fire.** The single event this whole system exists to
catch — the outside-signal count moving from zero to one — currently has no
detector. It has in fact already happened, and it was noticed by hand. Raise it
somewhere a person sees, or it scrolls past in a weekly commit nobody opens.

---

# Build order and what already exists

| Stage | State | Notes |
|---|---|---|
| −1 Live bugs | **Fixed** | Code search, dashboard escaping, dropped comparisons |
| 0 Formats + store | **Built** | Versioned records, provenance, coverage, `store.py` behind three calls |
| 1 Collection | **Built** | Retries, timeouts, failure recording, partial saves, frozen affiliation, pull requests and issues over GraphQL |
| 2 Tests | Partly there | 84 unit tests, no end-to-end test and no CI wiring |
| 3 Classification | **Built** | Floor, harness rule, distinct changes, reference taxonomy, line-weighted health check |
| 4 Time series | **Built** | `series.py`, with `--reclassify` as the re-classify program the architecture assumes; windows stitch, gaps stay gaps, uniques are never summed |
| 5 Dashboard | **Built** | Stitched traffic history and adoption over time, both from the series; the hero number still measures CI |
| 6 Automation | Written, unrun | `.github/workflows/usage-metrics.yml`, twice weekly; needs the data repository and its token to exist |
| 7 Storage/privacy | Decided, unbuilt | Git, in a data repository of its own; names are already in git today |
| 8 Docs | Stale | Nine measured corrections |
| 9 Owner | Unassigned | Blocks 6 |

Order matters in three specific ways:

1. **Stage −1 first.** Two of those three defects are corrupting data on every
   run, and one is a public hazard.
2. **Do not do Stage 6 before Stages 1–3.** Automating a collector that drops
   throttled forks, and a classifier whose floor does not bind, just builds a
   longer history of wrong numbers.
3. **Settle 7.3 before the next write of data**, not before publishing. The
   publishing already happened.
4. **Build the store interface (0.1) with the local-file backend.** That backend
   is also the production one — 7.2 — so nothing in the plan waits on a GCP
   project existing, and a later move to Cloud Storage is a URI change.

Fastest useful path: Stage −1, then Stage 1, then Stage 6 to stop traffic data
expiring, then 3 and 4 to make it worth reading.

## What I would leave out

- **Forks of forks.** Still not worth the requests — but record the count, which
  the fork listing already returns for free, so the size of the blind spot is a
  number rather than an assumption.
- **CI data collection**, drawn in the design doc but never built. It measures
  our own builds.
- **Issues and pull requests by affiliation.** The design doc's outside ratio
  covers these; only forks and branches are collected. Either scope them out
  explicitly or add them — silently narrowing the definition is worse than
  either.

---

## Appendix — how the claims here were checked

```bash
cd hack/usage-metrics

# Code search: the collector's call against the same query via REST
gh search code '"from devops_bench"'                        # -> []
gh api -X GET search/code -f q='"from devops_bench"' \
  --jq '.total_count'                                       # -> 249

# Distinct changes: 189, and the file paths contribute nothing
python3 -c "
import json
s=json.load(open('snapshots/2026-08-11.json'))
b=[br for r in s['repos'].values() for f in (r['forks']['value'] or [])
      for br in (f.get('branches') or [])]
p=lambda x: tuple(sorted(i['path'] for i in (x.get('files') or [])))
print(len(b),
      len({(p(x), x['additions'], x['deletions']) for x in b}),
      len({(x['additions'], x['deletions']) for x in b}))"
# -> 210 189 189

# An unexpected response shape kills the run
python3 -c "import collect; collect.gh_api = lambda p, paginate=False: {'stargazers_count': 1}; \
            print(collect.measure(lambda: collect.collect_repo('x/y')))"
# -> KeyError: 'forks_count', uncaught

# The comparison depends on upstream main, not just the branch
gh api repos/gke-labs/devops-bench/compare/main...pradeepvrd:refactor/comparison \
  --jq '{ahead:.ahead_by, behind:.behind_by, base:.base_commit.sha, mergeBase:.merge_base_commit.sha}'
# base and merge_base differ; every branch on that fork reports behind_by 175

# The fork count GitHub reports is not the fork count it lists
gh api repos/kubernetes-sigs/devops-bench --jq .forks_count          # -> 13
gh api repos/kubernetes-sigs/devops-bench/forks --paginate --jq 'length'  # -> 12

# Unique visitors are not additive
python3 -c "
import json
s=json.load(open('snapshots/2026-08-11.json'))
v=s['repos']['gke-labs/devops-bench']['traffic']['value']['views']
print(v['unique'], sum(d['unique'] for d in v['daily']))"
# -> 37 89

# Compressed size
gzip -c snapshots/2026-08-11.json | wc -c        # -> 42567, from 924573
gzip -c snapshots/2026-08-12.json | wc -c        # -> 121945, from 2562921
                                                 #    (first snapshot with pull requests)

# A branch name that blanks the dashboard is a legal ref
git check-ref-format 'refs/heads/<!--<script' && echo valid
```

Silently skipped comparisons: `collect.py`, `collect_forks`, the
`except Unavailable: continue` around the comparison call.

The primary-category floor bypassed by its own fallback: `classify.py`,
`pick_primary`, the branch taken when nothing clears `PRIMARY_SHARE_FLOOR`.

Linter and tests skip this folder: `.pre-commit-config.yaml` and
`.github/workflows/guardrails.yml`, both scoped to
`^(devops_bench|tests/unit)/`.

No scheduled job: `.github/workflows/` contains no collection workflow.
