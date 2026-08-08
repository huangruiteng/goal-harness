# Independent user: 13+ hour C++ algorithm accuracy run

> **Case type:** Independent user
>
> **Evidence strength:** Owner-approved user report with one public method reference
> **Runtime / scale:** More than 13 hours; one long-running agent reported

## Scenario And Problem

An independent user used LoopX on a complex C++ algorithm accuracy problem. The
reported failure mode was not simply that the code was hard to read: a long
execution could drift into local parameter tuning, lose the original accuracy
goal, and repeatedly compress away useful context about call relationships.

## How LoopX Ran

LoopX kept the multi-stage task aligned to the declared vision for more than 13
hours. When the current route no longer appeared able to satisfy that vision,
replan prompted public research instead of more local thrashing. The run then
selected the public
[`codebase-memory-mcp`](https://github.com/DeusData/codebase-memory-mcp) project
to help inspect C++ call and coupling relationships.

## Human Intervention

The user reported no parameter micromanagement or repeated local redirection
during the multi-stage run. This is not a claim of zero human involvement in
the surrounding project: the original goal and final assessment still came
from the user.

## Outcome

The user reported a clear improvement in final precision, less context
compression, and enough retained experiment evidence to understand why the
final approach worked. The private project and its measurements are not
available for independent reproduction, so the performance result remains a
user-reported outcome.

## Evidence

![Authorized user feedback reporting a LoopX C++ algorithm run lasting more than 13 hours with improved precision and retained evidence](../../assets/showcases/user-feedback/cpp-accuracy-13h-user-report.jpg)

*Source: an owner-approved message excerpt from the LoopX public Lark developer
group. Runtime and outcome are user-reported.*

![Authorized follow-up explaining that LoopX replan triggered public research and found a code-memory MCP](../../assets/showcases/user-feedback/cpp-accuracy-public-research-user-report.jpg)

*Source: an owner-approved follow-up message excerpt from the same LoopX public
Lark developer group, describing the public-research transition.*

## Evidence Boundary

The screenshots are owner-approved message excerpts from the LoopX public Lark
developer group and are stored as local repository assets. The project
repository, raw run state, prompts, experiment data, and performance
measurements remain private. The MCP repository is public and independently
inspectable; it does not independently prove the reported precision gain.
