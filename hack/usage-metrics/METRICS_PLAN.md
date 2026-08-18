# Community velocity and engagement — metrics plan

A companion to `PRODUCTION_PLAN.md`. That plan answers *does anyone outside the
team use this*. This one answers two harder questions:

- **Velocity** — can this project absorb a contribution when one arrives?
- **Engagement** — how deep does involvement go, and does it come back?

And it ties both to **extension hotspots**: not just which parts of the codebase
get touched, but which ones people can actually get their work merged into.

*Revised after review by two independent models. The first draft's central claim
was disproven by the project's own data; what replaces it is below. Corrections
to the numbers that draft published are marked throughout.*

---

# The finding that reframes everything

The project has exactly one *pull request author* from outside the team. Their
entire history:

```
kubernetes-sigs #66   opened 2026-07-31   open, 12 days
kubernetes-sigs #76   opened 2026-08-06   open,  6 days
kubernetes-sigs #77   opened 2026-08-06   open,  6 days

human comments on all three:  only the author
human reviews on all three:   only the author
```

Meanwhile the team merges its own work in a median of 22.6 hours.

**So team velocity does not measure readiness for outside contributors.** The
first draft of this plan claimed it did, and proposed publishing 22.6 hours as a
readiness signal. That dashboard would have rendered green while the only real
outside contribution in the project's history sat unanswered. The two numbers
are not related: internal work is pre-coordinated between colleagues who talk
daily, and it tells you nothing about how a cold arrival is received.

The corrected framing:

| Track | What it honestly measures | Publish? |
|---|---|---|
| **Internal process health** | How the team works with itself. A *lower bound* on outside experience — outside can only be slower | Yes, labelled as internal |
| **Outside experience** | What a cold contributor actually gets. Currently: nothing, three times | Yes, as an alert on named cases — not as a rate |
| **Organizational diversity** | Whether the project is one company or several | Yes. This is the readiness number a SIG reviewer asks for first |

The third track is new and did not appear in the first draft. Both reviewers
independently identified it as the most important omission, and it is the one
split with a usable sample *today*.

---

# Family 0 — The outside-contribution alert

**Build this first.** It was scheduled last in the first draft, behind metrics
that cannot see the problem it catches.

Not a metric. A standing list of every open issue and pull request from outside
the team with no human response, and how long it has been waiting. It fires into
a place a person reads.

Why not a metric: at this sample size a percentage is theatre. "0 of 3" is a
fact you can act on this afternoon; "0% outside response rate" is a statistic
about one identifiable person, which also collides with the privacy rule in
`PRODUCTION_PLAN.md` 7.3 — published artifacts carry aggregates only. So this
one stays internal until the floor is met, and it doubles as the Stage 9
milestone detector that plan asks for.

**Response means a human.** This repository runs prow, dependabot, coderabbit,
easycla and a sync bot; CI comments land within seconds on every pull request.
Filter by account type, `[bot]` suffix, *and* a deny-list — each catches cases
the others miss.

*Measurable today: yes — the rewritten collector stores every pull request and
issue with its comments and reviews. Run against live data it returns the three
pull requests above, and correctly does not flag kubernetes-sigs issue #3, filed
by a second outside account and answered by a human in **3 hours**.*

That contrast is sharper than the original claim and worth stating on the page:
outside **questions** get answered quickly; outside **code** does not get
answered at all.

---

# Family 1 — Velocity: how the team's own process behaves

Everything here is labelled internal. It is a lower bound on the outside
experience, never a proxy for it.

## V1 · Time to first human response
*CHAOSS: Time to First Response.*

Pull request opened → first comment or review by a human who is not the author.
Median and 90th percentile, per month.

**Two things that will corrupt it.** The bot filter above, and — on the
kubernetes-sigs side — the fact that human approval flows through prow as
`/lgtm` and `/approve` *comments*, not formal GitHub reviews. Counting only
formal reviews undercounts human engagement on that repo, and a filter that
strips everything bot-adjacent will discard the human comment that triggered the
bot label.

Also confounded by out-of-band coordination: a review arranged in chat looks
instant here. Lower bound only, and say so on the page.

## V2 · Time to merge

Opened → merged. Median and p90 per month, bucketed by change size.

Measured over all 196 merged PRs: **median 22.6 hours, p90 148.9 hours**,
longest 454. 53% land within a day, 21% within an hour.

**State the percentile method.** Nearest-rank gives 148.9; linear interpolation
gives 144.2. Both are correct and the first draft quoted one without saying
which. Use nearest-rank, matching `hack/telemetry-metrics/aggregate.py`, and
write it down.

Report median and p90, never a mean — the 454-hour tail moves a mean around
meaninglessly.

## V3 · Review coverage

Share of merged PRs carrying at least one review from a human other than the
author.

**Corrected.** The first draft sampled 40 merged PRs, found 40 with human
reviews, and called this healthy. Over the full population it is **10 of 196
(5.1%) with no human non-author review** — gke-labs #4, #8, #41, #67 with no
reviews at all, a consecutive self-merged batch at #126 and #129–132, and
kubernetes-sigs #58 merged in about two minutes with only a bot review. A
40-sample misses a 5% stratum about 13% of the time; it got lucky.

Compute over the population, not a sample — the same GraphQL query returns it
for free. And split V2's under-one-hour share by reviewed versus unreviewed,
because part of that 21% is self-merges rather than fast review.

## V4 · Merge rate and backlog age
*CHAOSS: Change Request Closure Ratio.*

Merged ÷ (merged + closed unmerged), plus the age distribution of what is open.

**Exclude the migration and sync class.** Bulk "Migration: flip" and sync
pull requests are closed unmerged by design, so including them means V4 measures
the mirroring process rather than review.

**Split open PRs into awaiting-review and awaiting-author.** An age
distribution alone cannot tell "nobody has looked" from "the author stalled" —
and that distinction is the entire diagnosis for the three stuck outside PRs.

## V5 · Revert rate

Share of merged PRs reverted within 14 days. Currently 1 revert in 309 commits:
useful as a guard on V2, noise as a trend for years. Publish the count, not a
rate.

---

# Family 2 — Engagement: how deep, and does it return?

## E1 · Contribution counts, not a ladder

Distinct people per quarter at each of: forked · pushed to their fork · opened
an issue · opened a PR · got one merged · reviewed someone else's · active in
2+ distinct months.

**Drawn as independent counts, not a connected funnel.** The first draft drew a
ladder; it is not one. Three people have reviewed without ever authoring a pull
request, so "reviewed" is not a subset of "opened a PR."

The "visited" rung is dropped entirely. Traffic uniques are 14-day
non-additive figures — `PRODUCTION_PLAN.md` measures 37 against a daily sum of
89 — so there is no such thing as a quarterly visitor count.

This still replaces the conversion ratio that `PRODUCTION_PLAN.md` withdrew,
because each rung is a count of people rather than a ratio across mismatched
populations.

## E2 · Retention

Of people whose first merged PR landed in month M, the share who merged another
within 90 days. A cohort curve.

**Two honest caveats.** First-merge cohorts here are 4, 3, 2 and 6 people — all
but one below the 5-person floor, so this is essentially unpublishable as a rate
under this plan's own rule. Publish the cohort counts and leave the percentage
suppressed. And retention among colleagues is employment, not community health;
it only becomes the metric it claims to be once the outside cohort is non-empty.

## E3 · Concentration
*CHAOSS: Bus Factor / Elephant Factor.*

Top-3 author share of merged PRs, and the count of people with 5 or more merged
PRs. Measured: **63%**. Normal for a project this young; it is the number that
has to fall for "community" to mean anything.

## E4 · Review reciprocity

Distinct reviewers ÷ distinct authors. Measured: 14 human non-author reviewers
against 16 authors.

The first draft also proposed a "share of reviews by non-maintainers", which
neither plan defines. Either define maintainer from OWNERS or drop the
sub-metric — an undefined denominator is how the withdrawn conversion ratio
happened.

---

# Family 3 — Organizational diversity

New in this revision. Both reviewers flagged its absence as the most serious
omission, for the same reason: this is a Google-built project mirrored into
kubernetes-sigs, so "outside" substantively means "not one company," and
vendor-neutrality is an explicit expectation of the governance it sits under. It
is also the only affiliation split with a workable sample today.

## O1 · Merged pull requests by organisation

Share held by the top organisation, and the count of organisations with any
merged work. The Elephant Factor.

## O2 · Distinct contributors by organisation, per quarter

Whether the second organisation is one person or a group.

## O3 · Reviewers by organisation

The most load-bearing of the three. A project where every review comes from one
company is single-vendor regardless of who writes the code — and review capacity
is what V1 ultimately depends on.

## Where the affiliation data comes from — not the obvious place

**GitHub profile company fields do not work.** Sampled eight active authors:
five are blank, and the three populated are inconsistent (`@google`, `Google`,
`Onix`). Building on this field would produce a chart that is mostly "unknown"
and quietly wrong where it isn't.

Use, in order: the **CNCF `gitdm` affiliation mapping** (`cncf/gitdm`), which is
the same source DevStats uses and is maintained by the foundation; then public
Kubernetes org membership, which the API does answer; then commit email domains,
excluding the free-mail providers; then unknown, reported as its own visible
category rather than folded into anyone.

Publish the unknown share alongside every organisational figure. A diversity
number computed over 40% unknowns is not a diversity number.

**Check DevStats first.** kubernetes-sigs repositories are ingested by CNCF
DevStats, which already computes much of Families 1–3 for that side of the
mirror. Confirm per-repository coverage before building any of this — it may be
partly free.

---

# Family 4 — Extension hotspots: where does work land, and where does it stall?

## H1 · Hotspots split by affiliation

Distinct changes per category, inside and outside, drawn separately. 188 of 210
fork branches are on contributor-owned forks, so today's undivided chart is the
team describing itself while being labelled adoption. Already required by
`PRODUCTION_PLAN.md` Stage 5.

## H2 · The friction funnel — rebuilt from pull request states

The first draft defined this as *fork branches touching a category → PRs
touching it → merged PRs touching it*, and called it the most valuable metric
here. **Both reviewers showed it does not compute**, for four independent
reasons:

- **Success deletes its own evidence.** Merging a PR usually deletes the head
  branch, so upstreamed work leaves stage 1 while remaining in stages 2 and 3.
  The funnel inverts.
- **Merge method decides membership.** A squash-merged branch stays permanently
  ahead and counts as stuck; a rebase-merged one drops to zero and vanishes.
  This repository has squash, merge-commit and rebase all enabled, and uses all
  three — 213 first-parent commits on main break down as 58 squash-style
  subjects, 67 merge commits, and ~88 with no extractable PR link.
- **Stock versus flow.** Fork branches are a point-in-time snapshot; PRs are an
  all-time record. Those cannot be rungs of one funnel.
- **Different categorisers.** Fork comparisons are capped at 300 files; PR file
  lists are not. The same change gets categorised differently at each stage.

**Rebuilt definition — one population, three states:**

```
PRs opened touching a category  →  PRs reviewed  →  PRs merged
```

Every rung comes from the same GraphQL pull request record, so it reconstructs
over full history, survives branch deletion, and is immune to merge method. The
question it answers is unchanged and still the most useful one here: which parts
of the codebase do people try to change and fail to land.

Keep the fork-branch category counts as a **separate stock figure**, labelled an
upper bound with the merge-method caveat stated. It is still the only view of
work that never became a pull request at all.

## H3 · Intended surface versus core

Share of outside changes touching declared extension points — tasks, verifiers,
harnesses, providers — against core internals. Rising core share means the
extension API is insufficient, and it shows up here long before anyone files an
issue. Requires the project to declare which paths are extension points, which
is a useful forcing function on its own.

## H4 · Time to merge, per category

V2 broken down by H1's categories. Separates "slow to review" from "hard to
write". Expect most cells suppressed by the floor — publish it as a
trailing-quarter figure, not monthly.

## H5 · Divergence half-life

Median age of unmerged outside fork branches, per category. The earliest
available warning that someone is maintaining a private fork of a subsystem.

**Not free, contrary to the first draft.** Snapshot branch records carry
`name, aheadBy, behindBy, additions, deletions, fileListTruncated, files` — no
date of any kind. The collector discards the commit dates the compare response
already returns. Storing the head commit date is a one-line collector change,
after which this genuinely is free.

---

# The floor rule, corrected

No **rate, ratio or median** is published for a group with fewer than 5 distinct
people **or** fewer than 10 observations — whichever binds first. Counts are
always shown.

The first draft stopped there. Four things it missed:

- **Counts never suppress.** Growth from 1 to 3 to 4 contributors is exactly
  what a young project needs to see, and suppressing it hides the only signal
  there is. Only percentages and medians are withheld.
- **Sparse is not the same as absent.** `PRODUCTION_PLAN.md` Stage 4 already
  renders uncovered dates as gaps. A floor-suppressed point would look
  identical. Give it its own marker — a shaded low-confidence band, not a hole.
- **The newest point always flickers.** Merged PRs per month run 8, 44, 64, 79,
  1 — the current month is always under the floor, so every chart's latest value
  would appear weeks late. Use trailing-quarter windows for anything
  floor-bound.
- **Complements leak.** Publishing an "all" series and a "team" series lets
  anyone subtract to recover the suppressed outside figure — at n=1, that is one
  named person's numbers. Suppress the complement too.

---

# What has to be collected that is not

The current collector gathers repo facts, traffic, contributors, fork branches
and code search. **None of Families 0–3 is possible with that.**

| New input | How |
|---|---|
| Pull requests, all states, with authors and timings | GraphQL |
| Reviews per PR | Same GraphQL query |
| First human comment per PR | GraphQL timeline, with a pagination overflow path |
| Issues, with first response | GraphQL |
| Changed files per PR | Same GraphQL query |
| Organisation affiliation | `cncf/gitdm`, refreshed periodically |

**GraphQL, confirmed.** A reviewer fetched the entire two-repo corpus — 296
pull requests with reviews, authors and timestamps — in **4 queries**. The
equivalent over REST is roughly 300 calls on top of the ~345 the collector
already makes. One caveat: prow posts three to five comments in the first minute
of every kubernetes-sigs pull request, so first-human-comment needs a
pagination overflow path on bot-heavy PRs.

**`git log` is dropped.** The first draft proposed sourcing merged commit
authors and files from a local clone, which contradicts its own trap list
("count pull requests, never commits, for anything about people") and fails in
practice: ~88 of 213 first-parent commits have no extractable PR link, commit
emails do not map reliably to GitHub logins, and two clones would be needed.
Take authorship and files from the pull request record instead. Keep a clone
only for churn volume, where no person or PR attribution is involved.

---

# Traps, collected

- **Bots.** Filter by account type, `[bot]` suffix, *and* a deny-list. prow
  alone would make time-to-first-response read as seconds.
- **Affiliation is circular, and self-destructs on success.** The contributors
  endpoint returns merged-commit authors, so anyone outside who merges one PR
  becomes inside at the next snapshot — outside retention is definitionally
  empty forever and the milestone erases itself. Freeze outside status at
  **first-ever contribution**, seed the inside set from OWNERS and org
  membership rather than the contributors list, and **case-fold logins**:
  `AishSundar` and `Fuxiao-Gao` appear in different casing than the stored
  entries, and naive matching reports 3 outside authors instead of 1.
- **An organisation account holding a contributor's fork is not an adopter, and
  login matching cannot see it.** Live example: `onix-net` holds forks of both
  repositories carrying **25 diverged branches**, one of them 126 commits ahead
  — far more outside-looking work than every other outside account combined. The
  branches are named `ehole/…`, the same prefix a contributor uses on their
  personal fork, so this is one person's work under a company account, not an
  independent adopter. No API field distinguishes the two. The inside set needs
  a hand-maintained list of such accounts, and the choice for this one — team, or
  partner company that counts as outside — is a judgement someone has to make
  and write down.
- **The outside sample is n=0, not n=1**, for anything about merged work. That
  contributor has no merged pull requests, so outside time-to-merge, retention
  and hotspots have no observations at all — not a small sample, none.
- **Cross-repo duplication is smaller than the first draft claimed.** It
  asserted naive counts double. Measured: title overlap between the two repos is
  **1 pull request**, the sync bot authored 10, and excluding bot-authored PRs
  moves the median 22.6h → 23.0h. The rule needed is "exclude bot-authored pull
  requests", not a content-hash dedupe layer. Keep dedupe for fork branches,
  where the duplication is real.
- **Squash merges** destroy per-commit authorship. Count pull requests.
- **Means.** Every duration is a median plus a p90, with the percentile method
  stated.
- **Weekends.** A Friday PR merged Monday is not slow. Either measure in
  business hours or say plainly that it is not adjusted.
- **Every ratio names its denominator on the page.**

---

# How it plugs into the existing plan

| Existing stage | What this adds |
|---|---|
| 0 Formats + store | Two more record kinds: pull requests (with reviews and files) and organisation affiliation |
| 1 Collection | GraphQL PR/issue/review collection; store the branch head commit date for H5 |
| 2 Tests | Bot filtering, case-folded affiliation, the floor rule, complement suppression |
| 3 Classification | Families 0–4 computed here — still pure, still re-runnable over history |
| 4 Time series | Monthly and trailing-quarter series; sparse and gap must render differently |
| 5 Dashboard | Four panels: the alert, internal velocity, organisational diversity, the friction funnel |
| 9 Owner | Family 0 *is* the milestone detector that stage asks for |

**Build order.**

1. **Family 0**, the alert. It is the only thing here that catches a live
   problem, and it is a single query.
2. **Family 3**, organisational diversity — the readiness number with a real
   sample, and the one a SIG reviewer asks for first.
3. **V1–V4 and E3**, internal process health, clearly labelled internal.
4. **H2 rebuilt**, the friction funnel from PR states.
5. Everything gated on outside sample size, which cannot be published for a
   while regardless.

**What I would leave out.** Anything needing a survey or off-platform data.
Anything framed as individual productivity — that is not what this measures and
framing it that way would poison the project's relationship with its own
contributors. And any composite "developer experience" score: composites hide
which input moved, which is the only thing anyone can act on.

---

## Appendix — measured while writing and revising this

```bash
# Corpus: 216 + 80 = 296 PRs, 157 + 39 = 196 merged, 24 + 6 = 30 issues
# 16 distinct human PR authors; 1 outside the contributor list, with 3 PRs
# Bots authoring PRs: devops-bench-sync-bot, dependabot[bot]
# Top-3 author share of human PRs: 63%

# The three outside PRs, all open, author-only engagement
for n in 66 76 77; do
  gh api repos/kubernetes-sigs/devops-bench/issues/$n/comments \
    --jq '[.[]|select(.user.type=="User")|.user.login]|unique'
done
# -> ["isadominguez314"] each

# Review coverage over the population, not a sample
#   10 of 196 merged PRs (5.1%) have no human non-author review
#   gke-labs #4 #8 #41 #67 #126 #129 #130 #131 #132, kubernetes-sigs #58

# Time to merge, 196 merged PRs
#   median 22.6h   p90 148.9h nearest-rank / 144.2h interpolated   max 454h
#   under 1h 21%   under 24h 53%

# Organisation affiliation is not in profile fields
for u in jessie1111101 pradeepvrd itssimrank geojaz richackard \
         eugeneng04 isadominguez314 ameukam; do
  gh api users/$u --jq '"\(.login) company=\(.company // "-")"'
done
# -> 5 of 8 blank; populated ones inconsistent (@google, Google, Onix)

# Public Kubernetes org membership does answer
gh api orgs/kubernetes/members/ameukam --silent && echo member   # -> member
```

Every figure came from the live API. The saved snapshot contains no pull request
data at all, which is the gap this plan closes.
