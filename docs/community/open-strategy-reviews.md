# Open Strategy Reviews

> [简体中文](open-strategy-reviews.zh-CN.md)

LoopX Open Strategy Reviews are periodic public working sessions for users,
contributors, and maintainers to compare a small set of current technical
directions. They turn broad Discussion and RFC feedback into a bounded next
step, an owner, and an evidence request.

They are not roadmap votes, release commitments, or a second governance path.
Shipped behavior remains defined by `main`, released artifacts, and stable
contracts. The
[Current Technical Directions](../project/technical-directions.md) map remains
the canonical portfolio view, and each RFC keeps the status written in that
RFC.

## When To Schedule A Review

A maintainer may schedule a review when two or more public directions have
cross-cutting questions that are hard to resolve asynchronously and at least
two people can present evidence, a prototype, or a concrete design tension.

Weekend sessions can make participation easier for volunteer contributors,
but LoopX does not impose a weekly meeting. The maintainer chooses each date
from contributor availability and publishes it at least 48 hours in advance.
After the first two sessions, maintainers should keep, change, or stop the
cadence based on the acceptance signals below.

## Before The Review

Create one GitHub Discussion in the **General** category as the session's
public agenda and record. Link the current technical-directions map and every
RFC, tracker, issue, or prototype needed as pre-reading.

Limit the final agenda to four directions. A proposed agenda item should use
this compact card:

```text
Direction:
Problem or outcome:
Current public evidence or prototype:
Unresolved question:
Requested review outcome:
Links:
Willing owner, if any:
```

The facilitator freezes the agenda before the meeting. Items without a public
problem statement or a concrete question remain asynchronous Discussion
topics instead of consuming the live session.

## Session Format

A first review should fit in 75 minutes:

| Time | Activity |
| --- | --- |
| 5 minutes | Re-state the shipped baseline, governance boundary, and agenda. |
| 48 minutes | Review up to four directions, no more than 12 minutes each. |
| 12 minutes | Compare priorities, dependencies, and evidence gaps. |
| 10 minutes | Confirm dispositions, owners, next artifacts, and review points. |

The facilitator should invite contributors to present their own work. A
strategy review should not become a maintainer monologue or a tour of every
idea in the repository.

## Review Dispositions

Each agenda item ends in exactly one session disposition:

| Disposition | Meaning |
| --- | --- |
| `route_to_bounded_work` | The next useful slice is clear; create or update a claimable issue or task-board row. |
| `require_evidence` | The question needs a user case, benchmark, parity check, prototype, or other named evidence before implementation expands. |
| `keep_visible` | The direction remains useful context, but no current owner or promotion gate justifies new work. |
| `defer` | Stop spending meeting or implementation time until a stated trigger changes. |

A disposition does not itself change an RFC stage, promote an integration
branch, appoint a maintainer, or authorize implementation. Material changes to
stage, scope, implementation lead, branch, or promotion gate follow the
repository's normal pull-request and governance path.

## Required Public Record

Within 48 hours, add a summary comment to the session Discussion:

| Direction | Current stage | Evidence reviewed | Disposition | Owner | Next artifact or evidence | Next review trigger |
| --- | --- | --- | --- | --- | --- | --- |

Then route the result:

- update the technical-directions map through a pull request when canonical
  portfolio facts changed;
- update or open an RFC when the architectural boundary changed;
- create a bounded issue or task-board row before implementation is claimed;
- leave unresolved questions in the Discussion with an explicit evidence
  request instead of converting silence into approval.

The written Discussion summary is the meeting record. A call recording is
optional and requires participant consent; it never replaces the public text.

## Participation And Public Boundary

- Keep agenda items, examples, and notes public-safe. Do not post credentials,
  private customer or employer context, raw transcripts, private links, or
  unpublished evaluation data.
- A chat group, video call, or livestream is transport and distribution, not
  project authority.
- Participation, presentation, or popularity does not grant merge, release,
  subsystem, or maintainer authority.
- When consensus is not reached, the lead maintainer records the unresolved
  options or the final decision and rationale in the relevant public artifact.
- Material directional conclusions should be summarized in English and
  Chinese so live-language choice does not silently exclude contributors.

## Pilot Acceptance Signals

Do not judge the pilot by attendance alone. After two sessions, continue or
change the format based on whether:

1. a contributor other than the lead maintainer independently explained or
   challenged a LoopX direction;
2. at least two review items produced an owner and a bounded public artifact;
3. those artifacts received evidence, implementation, or a documented stop
   decision before the next review; and
4. repeated cross-direction questions became easier to find and did not need
   to be re-litigated from chat history.

If these signals do not appear, return the work to asynchronous Discussions
instead of preserving a meeting for its own sake.
