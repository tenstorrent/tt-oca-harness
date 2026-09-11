<!-- SPDX-License-Identifier: Apache-2.0 -->
<!-- SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. -->

# TRM ownership transfer — start here

Prepared 11 September 2026. Give this file to the colleague's coordinating agent.
It is self-contained for task scope and sequencing; supporting briefs, evidence
and build instructions are in [handoff/trm](handoff/trm/README.md).
The original conversation and the original machine are not required.

**Publication state:** local candidate, awaiting agreement on the GitHub branch
and PR base. Proposed branch: `docs/trm-colleague-handoff`, proposed draft PR base:
`docs/trm-dtp-pilot-v2` (#1643). Do not assume that branch exists remotely until
the sender confirms publication. No new PR number has been assigned.

## First action

Read this file, the repository `AGENTS.md`, [current findings](handoff/trm/CURRENT-REVIEW.md)
and [working agreement](handoff/trm/WORKING-AGREEMENT.md). Inspect the checkout's
branch, HEAD and working status before changing anything. The transferred branch
contains all work through implementation commit
`4200cc97a48933163fd56f4ae290474471a7d972`, plus a separate handoff-only commit.
The source commit is **not accepted**. Do not restart from `main` or an older PR.

After publication, a fresh clone can start with:

```bash
git clone --branch docs/trm-colleague-handoff https://github.com/tenstorrent/tt-oca-harness.git
cd tt-oca-harness
git status --short
git log -2 --oneline
git merge-base --is-ancestor 4200cc97a48933163fd56f4ae290474471a7d972 HEAD
```

If the owner selects another branch name, use the final published name instead.
Nominate one coordinating/review agent and one implementation owner. This handoff
does not by itself authorize launching additional agents. The coordinator owns
plans, briefs and independent acceptance; implementation results do not constitute
acceptance. The incoming coordinator maintains this transferred handoff, rather
than the former coordinator's machine/workspace.

## Objective and completed work

Produce coherent, readable and maintainable HTML/PDF technical reference material
for DTP, SMC, SEP and their parent SMU. Prioritize beta structure and presentation;
correct material technical errors encountered and record lesser inherited issues.
This is not an exhaustive RTL or register-generation audit. "DEP" in the original
request meant SEP. Publication order is DTP → SEP → SMC; the later implementation
order is SMC → full SEP restructure → completed SMU narrative.

| Deliverable | State | Exact accepted/source revision |
| --- | --- | --- |
| Authoring conventions and structure design | Historically accepted; PR #1641 draft | `327e02099101fe83ad29b253bce82c1a3a74d6f6` |
| SMU publishing framework | Historically accepted; PR #1642 draft | `a9a0004e9ca465b7c4bf65e8adb52ee3f74e451c` |
| DTP pilot | Historically accepted; PR #1643 draft; later appearance feedback remains active | `829b09cf54dde1969dc309733f97f8fb32cefbdd` |
| 004h: navigation, selector and links | Independently accepted locally | `01dd44a2772cff926f9e0906de0b41f4277a8e0f` |
| 004i: image viewer and table containment | Independently accepted locally | `a0c6b15d11d379fbc640e05a621dbe0fa0e519bb` |
| 004j: DTP/PTAP diagrams | **Not accepted; two correction areas remain** | Submitted `4200cc97a48933163fd56f4ae290474471a7d972` |
| 004k: OCAH, SEP token and CTN figures | Queued after 004j acceptance | No accepted base assigned yet |
| 004l: SEP hierarchy and connectivity matrix | Queued after 004k acceptance | No accepted base assigned yet |

The new branch includes accepted 004h/004i and unaccepted 004j cumulatively.
Preserve that distinction. A push, draft PR or successful build is not acceptance.

## Active task: finish 004j

Continue from the transferred tip, preserving existing commits. The accepted
implementation base for 004j remains `a0c6b15d11d379fbc640e05a621dbe0fa0e519bb`.
Add focused corrections; do not rewrite history or begin 004k early.

Two areas remain:

1. **PTAP input label collision.** The route at SVG y=390 crosses the lower part
   of `IJTAG_SI` (Chromium bounds y=371–394). Keep the names visibly associated
   with their input path while leaving full glyphs clear of connectors. Moving a
   name far away or back onto its route does not satisfy both requirements.
2. **Meaning and legends.** The caption says BSR_SI/IJTAG_SI receive TDI fan-out,
   while the figure shows those labels entering the return mux. RTL drives
   `bsr_host_scan_out_o` and `ijtag_host_scan_out_o` from `client_tdi_i`; the
   corresponding `*_scan_in_i` signals enter return selection. Resolve the endpoint
   perspective consistently. The PTAP TDI-to-TDR path is dashed, but the prose
   describes TDI fan-out as solid; external returns and TDO are solid despite
   the scan-return legend. DTP's legend likewise calls its dashed TDO path solid.

The [current review](handoff/trm/CURRENT-REVIEW.md) contains exact evidence and RTL
references. These are diagnostic examples, not a mandated layout. Check related
risks yourself and provide an accurate retained/moved/omitted content map.

Permitted implementation changes remain exactly:

- `hw/sys/dtp/doc/assets/dtp_arch_overview.svg`
- `hw/sys/dtp/doc/overview.adoc` — figure/caption/immediately supporting explanation only
- `hw/ip/jtag/jtag_ptap/doc/assets/ptap_module_diagram.svg`
- `hw/ip/jtag/jtag_ptap/doc/architecture.adoc` — figure/caption/immediately supporting explanation only
- `doc/trm/AUTHORING.md` — §7c figure guidance only

Do not edit RTL, RDL, shared UI/build glue, other figures, repository agent
instructions or unrelated chapter content. The handoff-only additions
`TRM-HANDOFF.md` and `handoff/trm/` are coordinator-owned transfer records, not
implementation scope. Account for them separately when comparing against the
accepted implementation base. Keep all handoff material outside published books.

Preserve the 004h/004i behavior, full 77-row DTP port reference, 14 compatibility
routes, Module Hierarchy content and source ownership. The checked-in
`doc/trm/dist/ocah-trm.pdf` matches the accepted base; new PDFs are review artifacts,
not source changes to commit. An unrelated untracked `SEP_LC_Block.png` existed
in the original execution clone. It is not needed for this task and is not included
in the Git source transfer; do not invent or add it as part of 004j.

## Fixed acceptance and evidence requirements

Before implementation, create or repair meaningful measurements/tests, state
expected outcomes and demonstrate the reported failures against the starting
revision. Then use the same criteria to assess the correction. The implementation
agent owns design, risk analysis and verification; the coordinator independently
challenges the evidence. Never weaken criteria, invent results or turn unknowns
into passes. Escalate material ambiguity or evidence-backed disagreement to the
human owner rather than guessing.

- Main labels: at least **14 CSS px** at 1280 px viewport and 100% browser zoom.
- Essential inline labels: at least **12 CSS px** under the same conditions.
- Essential PDF labels: at least **9 native points** after placement/scaling.
- Full labels, clear orthogonal connectors, accurate directions and legends,
  meaningful endpoints, no unrelated text/block crossings, no lost information.
- Rendered checks at 1440, 1280, 1024, 768 and 390 CSS px. Exercise native 200%
  desktop browser zoom; it remains outstanding for the final appearance package.
- Fresh regeneration-disabled release TRM HTML/PDF and affected consumers,
  including IG. Stage all six products for combined HTML and enforce the Antora
  error gate. [Build/check instructions](handoff/trm/VALIDATION.md).
- Keep AUTHORING, STRUCTURE, DV defines and internal release history absent from
  published HTML/PDF, including direct-address pages. AUTHORING is a separate
  customer handover document, not TRM content.

The latest independent builds passed: six-product staging, TRM HTML, combined
HTML and 635-page PDF. Font floors, TDR containment, clock-stop/CTM route separation,
aggregator containment and the two corrected PDF ASCII arrows pass. Screenshots
and measurements are in [evidence](handoff/trm/evidence/README.md).
Those passes do not close the two outstanding findings.

Earlier author geometry checks reported 14/14 but omitted rendered text/route
collisions and semantic consistency. Another script skipped renamed/moved labels
and rescaled widths already expressed in SVG coordinates. Do not use their green
counts as acceptance or depend on old machine-local scripts. Discover current
rendered labels, preserve coverage and distinguish glyph observations from
bounding-box warnings. Default PDF extraction scaling is not native point size.

## Work after 004j

The coordinator accepts the exact corrected SHA before activating each next task:

1. **004k:** OCAH overview, SEP token-processing and CTN architecture figures.
   Use [the queued brief](handoff/trm/briefs/004k.md); insert 004j's accepted SHA.
2. **004l:** concise SEP hardware explanation and semantic connectivity matrix.
   Use [the queued brief](handoff/trm/briefs/004l.md); insert 004k's accepted SHA.
3. Assemble matching HTML/PDF, changed-page index, physical PDF page references,
   source diff and checksums for the human owner's **appearance approval**.
4. Only then commission separate bounded tasks for SMC, full SEP restructure,
   completed SMU narrative and final publication review. Accept each before advancing.
5. The human owner arranges internal peer review. Track findings against exact
   revisions, resolve and reverify. **Merge requires separate owner approval.**

For 004k preserve token/security semantics, including triple redundancy versus
majority voting, valid codes and fault behavior. For 004l preserve all 55 matrix
values (five initiators × eleven destinations), ten Crossbar columns versus the
Dedicated Path/Boot ROM column, unique interface/ownership information and deferred
AGP/RAS status. These appearance tasks do not authorize a full SEP restructure.

## GitHub stack and later integration

Verified on 11 September 2026:

| PR | Head branch | Base branch | State |
| --- | --- | --- | --- |
| [#1641](https://github.com/tenstorrent/tt-oca-harness/pull/1641) | `docs/trm-conventions` | `main` | Open draft; merge conflict |
| [#1642](https://github.com/tenstorrent/tt-oca-harness/pull/1642) | `docs/trm-smu-framework` | `docs/trm-conventions` | Open draft |
| [#1643](https://github.com/tenstorrent/tt-oca-harness/pull/1643) | `docs/trm-dtp-pilot-v2` | `docs/trm-smu-framework` | Open draft |
| Proposed transfer PR | `docs/trm-colleague-handoff` | `docs/trm-dtp-pilot-v2` | Not created |

The proposed transfer is stacked on #1643, not directly on main. No existing PR
tip has been advanced or rewritten for this handoff. There are 13 appearance
commits after #1643, plus a separate handoff-only commit. Exact revisions
and remote readback are in [provenance](handoff/trm/github-state.json).

Main was `94eae6729096f1b7d46a499b4bdd509ba860922d` at verification. Integrator Guide
draft [#1644](https://github.com/tenstorrent/tt-oca-harness/pull/1644), branch
`docs/integrator-guide-usability`, head `5925c078d89315963d2162203956ab5ca0b355a9`,
targets main and also reports a merge conflict. Open IG checklist
[#1459](https://github.com/tenstorrent/tt-oca-harness/pull/1459) is separate work.
Neither is incorporated into this transferred TRM source. Coordinate an agreed
main/IG revision with the human owner before rebasing/merging the documentation
stack, then reverify affected products. Preserve other owners' changes.

The conventions PR inherits baseline changes from earlier IG/lint work because
its ancestry diverged from main. Integration must reconcile that history; do not
merge the stack merely because a later stacked PR reports no conflict. Existing
IG checks against this branch do not certify #1644 or its eventual integration.
Register regeneration and AOU milestone scope remain explicit unresolved decisions.

Tracking: milestone [#145](https://github.com/tenstorrent/tt-oca-harness/issues/145),
SMU [#1609](https://github.com/tenstorrent/tt-oca-harness/issues/1609),
DTP [#1610](https://github.com/tenstorrent/tt-oca-harness/issues/1610),
SMC [#73](https://github.com/tenstorrent/tt-oca-harness/issues/73),
SEP [#1611](https://github.com/tenstorrent/tt-oca-harness/issues/1611),
peer review [#109](https://github.com/tenstorrent/tt-oca-harness/issues/109),
publication/handover [#110](https://github.com/tenstorrent/tt-oca-harness/issues/110).
Keep GitHub updates concise; retain detailed execution evidence separately.

## Agent start prompt

> Read TRM-HANDOFF.md and its linked current review, working agreement and
> validation contract. Resume 004j from the transferred branch containing
> 4200cc97a48933163fd56f4ae290474471a7d972. It is not accepted. Establish valid
> failing measurements before correcting the remaining PTAP label collision and
> inconsistent direction/line-style explanations. Preserve all accepted behavior
> and permitted-path boundaries. Return exact revisions, a focused diff, current
> content mapping, build logs and matching rendered evidence for independent
> review. Do not start 004k, incorporate IG/main, publish, contact reviewers or
> merge without the applicable coordinator/owner authorization.
