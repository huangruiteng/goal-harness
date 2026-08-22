# LoopX Brand Guide For External Use

This guide is for open-source projects, commercial companies, users, writers,
and event organizers that want to mention LoopX, describe an integration, or
show the LoopX name or artwork. It is practical project guidance, not legal
advice. The separate [Name And Marks](trademarks.md) page records the current
project position on names and marks.

The short rule is: identify LoopX accurately, identify your own product clearly,
and never make a reader infer sponsorship, certification, partnership, or an
official release where none exists.

## 1. What LoopX Is

Use this description as a factual starting point:

> LoopX is an open, provider-neutral, local-first dynamic goal control plane
> for long-running agent work. It keeps goals, todos, decision scope, gates,
> evidence, quota, handoff, and recovery legible across bounded turns.

LoopX runs on top of agent harnesses. The harness or application still executes
the work; LoopX keeps the control state reviewable and recoverable.

Do not describe LoopX as a model, an agent runtime, a complete agent platform,
or an autonomous production controller. LoopX does not grant credentials,
approve destructive or production actions, or turn an unverified run into proof
of success.

## 2. Choose The Relationship Words First

Choose the narrowest relationship that your public implementation and evidence
support:

| If your project or product… | Say… | Do not imply… |
| --- | --- | --- |
| links to or discusses LoopX | “mentions LoopX” or “documents LoopX” | an integration or endorsement |
| calls a public LoopX command or contract | “uses LoopX” | that LoopX operates your service |
| exchanges state through a maintained adapter | “integrates with LoopX” | that the adapter is an official product |
| adds a provider or extension around LoopX | “extends LoopX” | that the extension is maintained by LoopX |
| is a modified distribution | “a fork of LoopX” or “based on LoopX” | that it is an official LoopX release |
| is only exploring an idea | “proposed” or “experimental” | shipped compatibility |

Only use “official LoopX”, “certified by LoopX”, “LoopX partner”, or similar
language when a maintainer has explicitly authorized that wording for the
specific surface and version.

## 3. Name And Package Usage

- Write the project name as **LoopX**. Do not write `Loop X`, `loop-x`, or use
  an unqualified “autonomous agent platform” as a substitute.
- A project, company, hosted service, package, domain, or social account that
  is not operated by LoopX should not use `LoopX` as its primary identity in a
  way that looks official.
- Descriptive names such as `acme-loopx-adapter` may explain a real
  integration, but the surrounding page must identify Acme as the operator and
  must not use “official” or equivalent language.
- A fork or materially modified distribution should have its own primary name;
  state the LoopX relationship in a secondary description instead.
- Keep the exact project name and relationship visible in titles, package
  descriptions, directory listings, and social profile bios rather than hiding
  it in a badge or footer.

## 4. Logo And Artwork

The repository's current public artwork is available under [`docs/assets/`](../assets/),
including [`loopx-logo.png`](../assets/loopx-logo.png), the social preview, and
control-plane diagrams.

When showing a mark or screenshot:

- preserve the artwork, aspect ratio, and readable contrast;
- keep enough surrounding space that the mark is not mistaken for your own
  product mark;
- link the surrounding reference to the official LoopX repository or docs;
- identify your product as the operator when the mark appears on an integration
  page, hosted service, or commercial product page.

Do not redraw, distort, recolor, crop into a new logo, animate, combine, or
place the mark in a way that makes your offering look like an official LoopX
surface. Do not use a LoopX mark as the favicon, app icon, or primary avatar of
an unrelated product without maintainer permission.

If the supplied artwork does not fit your layout, use the word **LoopX** in
plain text and link to the project rather than inventing a replacement mark.

## 5. Guidance For Common External Surfaces

### Open-source README or documentation

Good:

> Acme Relay integrates with LoopX to persist bounded goal state. Acme Relay
> is an independent project; see the integration guide and the LoopX project.

Include the relevant version, adapter, or command when the claim is version
specific. A “works with LoopX” badge must link to a page that explains what is
actually exercised; a badge is not proof of certification.

### Commercial product or hosted service

Name the company and service as the primary product. Explain what the service
does with LoopX and who operates it. “Acme Cloud integrates with LoopX” is
clearer than “LoopX Cloud” when LoopX does not operate the service.

Do not use LoopX in a pricing tier, domain, account name, or sales headline in a
way that suggests the service is hosted, sold, or supported by the LoopX
project. Do not claim a partnership merely because an API or adapter exists.

### Fork, plugin, extension, or distribution

Give the distribution a distinct primary name and describe the relationship:
“Acme Flow, a fork of LoopX” or “Acme Flow, an extension for LoopX.” Preserve
the notices required by the applicable software license. Make material changes,
support boundaries, and the absence of LoopX endorsement clear.

### Blog, talk, benchmark, or comparison

Use LoopX to identify the subject accurately. Attribute measurements to the
specific public setup, version, and evidence. Do not turn a single demo, star
count, benchmark row, or user report into a claim that LoopX universally
delivers the result.

## 6. Co-branding, Campaigns, And Official-looking Uses

Ask maintainers before launch if a use involves any of the following:

- a joint logo, “official” integration badge, certification, or partner mark;
- a hosted service, paid offering, conference track, or campaign whose name
  prominently includes LoopX;
- a package, domain, social account, or app icon that could be confused with a
  LoopX-operated surface;
- a press quote, launch copy, or compatibility statement presented as a LoopX
  announcement;
- a modified distribution whose visual identity closely follows the LoopX
  project identity.

Open a focused GitHub issue with the proposed wording, surface, and relevant
version. Do not put credentials, private evidence, embargoed security details,
or private business arrangements in the issue.

## 7. ADOPTERS And Public Attribution

Projects and users may voluntarily add a public, self-attested entry to
[`ADOPTERS.md`](../../ADOPTERS.md). The directory records what the submitter
claims to use, not what LoopX certifies or endorses. Choose an adoption mode,
state whether it is active or experimental, link to public evidence, and avoid
private or unverifiable claims.

The maintainer-observed [ecosystem adoption inventory](../community/ecosystem-adoption.md)
is a different record. Do not copy an observation into `ADOPTERS.md` without a
voluntary owner or user submission.

## 8. Attribution And Claim Hygiene

For any external reference:

1. Link **LoopX** to the canonical repository or the relevant versioned docs.
2. Name the external project's operator and support boundary.
3. Say which command, adapter, release, or public behavior was used.
4. Label the claim as shipped, observed, reported, or proposed when the
   distinction matters.
5. Say what the evidence does not establish; in particular, do not imply
   endorsement or universal capability.

The Apache and historical MIT license files cover the code and documentation
under their terms. They do not turn a third-party product into an official
LoopX product or grant permission to misrepresent project identity.

## 9. Quick Review Checklist

Before publishing a page, package, launch, or visual that mentions LoopX:

- Is **LoopX** spelled and linked correctly?
- Is the external operator or author unmistakable?
- Is the relationship word supported by the implementation and evidence?
- Is the version, adapter, or tested surface named where relevant?
- Could a reader mistake the page, package, logo, or service for an official
  LoopX offering?
- Does the copy avoid certification, sponsorship, partnership, or endorsement
  language unless explicitly authorized?
- Are screenshots, user data, private paths, and raw runs public-safe?
- If the use is ambiguous, has a focused maintainer question been opened before
  launch?
