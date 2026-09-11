<!-- SPDX-License-Identifier: Apache-2.0 -->
<!-- SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. -->

# Conflict size against current main

Measured 11 September 2026 against freshly fetched main
`13cafe6a1ea37ff126d2c88adeabd555984cb9cb`. Main has advanced since the earlier
handoff readback at `94eae6729`. This assessment used `git merge-tree --write-tree
--messages <main> <branch-SHA>` in the isolated delivery clone; no checkout,
branch tip or source file was changed and no conflict was resolved.

| Revision tested against main | Conflicted files | Text conflict blocks |
| --- | ---: | ---: |
| Conventions #1641, `327e02099` | 5 | 10 |
| Framework #1642, `a9a0004e9` | 5 | 10 |
| Accepted DTP pilot #1643, `829b09cf5` | 15 | 24 |
| Accepted viewer 004i, `a0c6b15d1` | 16 | 25 |
| Current TRM implementation, `4200cc97a` | 16 | 25 |
| Separate IG #1644, `5925c078d` | 4 | 4 plus a binary PDF conflict |

The current TRM's 25 text conflicts contain 187 lines from main and 351 from the
TRM side (538 lines across both sides). These are conflict-region sizes, not an
estimate of lines requiring manual rewriting or of all semantic integration work.
The handoff-only additions do not overlap main; the current implementation is
the relevant source merge. Replaying each historical commit individually could
produce a different number of stops than this final-tree merge.

## TRM conflict composition

- **Inherited baseline: 5 files / 10 blocks.** Three small IG index corrections,
  four Verilator Makefile blocks, one SEP port-table block, one SMC port-table
  block, and one `ocah.mk` inclusion. These predate the DTP appearance work.
- **Documentation reconciliation: 9 files / 13 blocks.** CTN/JIU/PTAP/STAP
  introduction or architecture content; DTP JTAG, overview and port reference.
  Much is heading/structure reconciliation, but technical updates need preservation.
- **Shared CSS: 2 files / 2 blocks.** Main's table/image styling versus the TRM
  port-table and accessible viewer additions. Preserve both applicable behaviors
  and rerun affected products; blindly taking either side loses work.

Concrete technical examples show why this is not just choosing a side:

- Main's DTP port table has `dbg_disable_i` with active-high disable semantics;
  the older TRM table has `feat_ctrl_i` with enable-polarity semantics.
- Main describes continued I/O STAP TCK drive when a generate is disabled,
  whereas the old TRM row describes a blanket tie-off.
- Main includes external OTP DFT disable outputs in the SEP reference and
  corrects SEP test-mode integration text.
- Main has new debug-disable explanations that overlap the restructured
  JIU/PTAP/STAP headings and prose.

There are no RTL file conflicts in this merge result. That does not mean the
older documentation already reflects the updated RTL. The recent 004j SVG
corrections add no conflict files/blocks relative to accepted 004i; the SVGs
themselves are not among the conflicted paths.

## Separate Integrator Guide branch

IG #1644 has conflicts in `doc/integrator/src/index.adoc`, `src/revision.adoc`,
shared `extra.css`, and the generated PDF. Two text conflicts in the old index
span 2,565 main-side lines versus eight IG-side lines because the PR splits
the monolithic document into chapter files. The revision entry and CSS add two
smaller conflicts. All four text regions total 2,573 main-side / 53 branch-side
lines. The PDF is binary and should follow resolved source/build provenance.

The large index conflict is largely relocation, not necessarily 2,565 lines to
rewrite. The real work is mapping main's intervening technical edits into the
new chapter sources and checking for content loss. The current TRM/main merge
does not integrate that IG branch or measure the later TRM-plus-IG combination.

## Implication for transfer

TRM is a bounded but substantive integration job: sixteen files, mostly prose,
references and shared styling, plus inherited build-file conflicts. It merits
a separate task with content reconciliation and full affected HTML/PDF checks.
The IG chapter split makes combining both jobs more involved.

Preserving the reviewed source on a new transfer branch remains a reasonable
first step. If the owner wants a main-based delivery instead, explicitly include
the integration work and select whether/when to incorporate #1644; do not claim
an automatically merged result has preserved technical correctness.

Raw merge-tree records and exact paths: [results.json](main-conflicts.json).
Per-block sizes: [TRM](main-trm-hunk-sizes.json),
[IG](main-ig-hunk-sizes.json). The sender retains diagnostic merged text with conflict markers locally; it
is not a proposed resolution or part of this source branch.
