<!-- SPDX-License-Identifier: Apache-2.0 -->
<!-- SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. -->

# 004j port closeout review — two remaining correction areas

Reviewed 11 September 2026 at `4200cc97a48933163fd56f4ae290474471a7d972`,
branch `docs/trm-appearance-dtp-figures`, following `14da26416`. Accepted task base
remains `a0c6b15d11d379fbc640e05a621dbe0fa0e519bb`.
**Not accepted; 004k stays queued.** Continue the [active brief](../../TRM-HANDOFF.md#active-task-finish-004j).

## Confirmed fixes

The clock-stop and CTM routes no longer share a vertical segment. The aggregator
bottom line now fits inside the box: Chromium bounds end at y=315, before the
y=316 boundary. The stacked formula remains tight, with overlapping font boxes,
but that alone is not an additional blocking finding. The two changed PDF labels
now contain literal `->`, confirmed in both raster and extracted text. Other
scan-chain figures are unchanged and outside this task's permitted paths.

The TDO label is now visibly associated with its output arrow. PTAP's boundary,
TMS/TRST and seven TDR entries retain their improvements. DTP main labels remain
14.41 CSS px; essential inline and native PDF font floors pass. The caption now
mentions instruction selection and the ZLB retimer bypass.

## 1. PTAP input-label collision remains

Moving the input names nearer the route restored their association, but put the
route through the lower part of `IJTAG_SI`. Its Chromium bounds are
x=14–105.52, y=371–394; the input line runs from x=14 to 270 at **y=390**.
The SVG's own comment estimates the label bottom beyond that line too.
`BSR_SI /` and `IJTAG_SI` font boxes also overlap at y=371–377.

The rendered input line meets/overprints the lower label and its underscores.
See [PTAP HTML](evidence/ptap-1280.png) and [PDF physical page 31](evidence/p31.png).
Keep port names clearly associated with their paths while leaving the complete
glyphs clear of connectors. Nearness alone does not establish that outcome.
These measurements are diagnostics, not proposed coordinates.

## 2. Prose still conflicts with the paths it explains

The new fan-out explanation reverses the SI/SO interpretation used by this figure.
It says `BSR_SI`/`IJTAG_SI` receive direct TDI fan-out and `BSR_SO`/`IJTAG_SO`
return through the mux, while the diagram labels the arrow **entering the mux**
`BSR_SI`/`IJTAG_SI`.

The RTL provides an unambiguous reference: `bsr_host_scan_out_o` and
`ijtag_host_scan_out_o` are assigned `client_tdi_i` (`jtag_ptap.sv:537–538`);
`bsr_host_scan_in_i` and `ijtag_host_scan_in_i` feed return selection
(`jtag_ptap.sv:1158–1180,1228–1229`). If legacy SI/SO abbreviations use a different
endpoint perspective, explicitly map that perspective and keep the figure and
prose consistent. Do not infer direction from an abbreviation alone.

The line-style legend also remains false:

- PTAP says solid grey carries TDI fan-out and dashed grey carries scan-out
  returns. Its TDI-to-TDR branch is dashed, while its BSR/iJTAG return and TDO
  output arrows are solid.
- DTP lists TDO scan-out among solid-grey examples, but its PTAP-to-pad TDO arrow
  is dashed. The external clock-stop request is also dashed and is not explained
  by the return/secondary-selection/gold-clock-stop definition.

Make the legend describe the rendered arrows accurately. Retain the useful ZLB
qualification; normal retiming and the bypass during ZLB data shift are distinct
(`jtag_ptap.sv:1249–1310`). These are continuations of the existing meaning and
legend findings, not an expansion of scope.

## Evidence and next handoff

The independent run reproduces **14/14 geometry passes**. That script checks
font sizes, text start positions and segment midpoints against hard-coded blocks;
it does not measure the input-label collision or compare legends with paths.
Use tests/measurements against this submitted revision that expose both remaining
areas before further implementation. Preserve passing behavior without treating
the count as proof of unmeasured properties. The student owns the method and design.

Include a current content/connection map and revision-specific verification
evidence in the next handoff. The available task-directory handoff still names
`53ae2d3f0`; current source comments still contain stale estimates and contradictory
distances. Existing prose destinations can account for removed detail, but must
be identified accurately. No additional approval gate is introduced.

Independent six-product staging, TRM HTML, combined HTML and the 635-page TRM PDF
all exit 0 in regeneration-disabled release mode, with the Antora error gate.
Both Antora logs are empty. TRM and IG browser checks at 1440/1280/1024/768/390
show no page-wide overflow; viewers open and close. IG reproduces the figure
findings. Native 200% browser zoom remains a final appearance-package check;
no standalone IG PDF was rebuilt here.

The incremental diff changes four allowed files; the cumulative diff contains
the five permitted paths. Whitespace checks pass; the tracked PDF equals the
accepted base, and the untracked SEP image is preserved. Module Hierarchy and
unchanged compatibility/reference source are preserved. Publication filename
exclusions pass. Coordination files were unchanged before this review's updates.
No production edits or remote actions were made.

- [Build commands and exits](evidence/build-commands.json)
- [Source/preservation checks and PDF checksum](evidence/verification.json)
- [TRM browser measurements](evidence/browser.json), [IG measurements](evidence/integrator/browser.json)
- [PDF measurements](evidence/pdf-labels.json), [DTP PDF page 21](evidence/p21.png)
- [Author geometry run](evidence/author/geom-submitted.log)
- [Incremental diff](https://github.com/tenstorrent/tt-oca-harness/compare/14da264164ef7570fba2b2a78317e12cb4634fdd...4200cc97a48933163fd56f4ae290474471a7d972), [cumulative diff](https://github.com/tenstorrent/tt-oca-harness/compare/a0c6b15d11d379fbc640e05a621dbe0fa0e519bb...4200cc97a48933163fd56f4ae290474471a7d972)
