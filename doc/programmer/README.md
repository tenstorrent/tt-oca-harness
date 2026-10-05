<!-- SPDX-License-Identifier: Apache-2.0 -->
<!-- SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. -->

# OCAH Programmer's Guide

The Programmer's Guide describes what software does with OCAH hardware. It is
one book, `src/index.adoc`, built from:

- the SMC and SEP chapters (`src/smc-programming.adoc`, `src/sep-programming.adoc`):
  bring-up and general operation of each subsystem's blocks;
- the common chapter (`src/sep-smc-common.adoc`): fabric address remapping, AXI
  filters, mailboxes and the other blocks both subsystems use;
- the DTP chapter (`src/dtp-programming.adoc`): cross-trigger programming and
  debug-host procedures;
- the AoU chapter: the vendored AoU software operation guide, staged by
  `doc/stage-docs.sh`; and
- appendices A to D: the SMC Boot ROM, SEP Boot ROM and Key Manager Application
  ROM manuals, staged from `hw/**/doc`, and the reset reference
  (`src/resets.adoc`).

Build it with `make ocah-doc-programmer-pdf` or as part of
`make ocah-doc-combined-html`.

## What belongs here

The guide owns ordered steps, initialization and bring-up, configuration
procedures, interrupt servicing, recovery, code and worked examples, "software
must" guidance, and debug-host procedures. The Technical Reference Manual owns
hardware behaviour, structure, constraints, register semantics, reset values and
timing. Where a TRM paragraph mixes the two, the procedure lives here and the
TRM keeps the hardware sentence with a pointer to the section here.
Manufacturing and tester procedures stay in the TRM. `doc/trm/AUTHORING.md`
states the same rule from the TRM side.

Name sections with kebab-case anchors prefixed by the subsystem (`smc-`, `sep-`,
`dtp-`), write steps as numbered lists, and link back to the TRM with guarded
links: an `xref:ocah-docs:...` in HTML and the published URL in PDF.
