<!-- SPDX-License-Identifier: Apache-2.0 -->
<!-- SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. -->

# SMC coverage

SMC collects **line, branch, expression and functional coverage** on Verilator.
Toggle is off: a toggle-instrumented native database per test leaf does not fit
a reseeded regression on standard CI runner disk before merge.

## What the number is

Say which one you are quoting. The three are not comparable to each other.

| Number | Denominator |
| --- | --- |
| Verilator code | the SMC DUT **minus the CPU cluster, the I3C core, the lowRISC prims and TB code** -- pulp glue and tt-hw-debug still counted |
| VCS code | the SMC DUT **minus the CPU cluster, the I3C core, the debug-bus block and TB code** -- pulp glue still counted |
| `user` functional | the 467 `OCAH_FCOV_COVER` points in `sv/`, nothing else |

None of them is "SMC coverage". `config/vcs/README.md` carries the two scope
files, the exclusions each expresses, and the Verilator glob gap that makes the
two sets differ.

## Two mechanisms, and they are not interchangeable

    config/verilator/smc_cov_scope.vlt   coverage_off -> the point never enters
                                         the database. Structural OUT: code
                                         this DUT does not own. Compile time.
    config/verilator/coverage_policy.toml
                                         [[holes]] -> the point exists and is
                                         not hit, carried with a category, a
                                         rationale, an owner and an expiry.

The scope file takes `-file` globs only; there is no `-module` form. The policy
takes exact hierarchies, which the scope file cannot express. A point that is
someone else's code belongs in the scope file; a point that is SMC's and is not
yet driven belongs in the policy.

`sv/*` is **never** added to the scope file: those files carry the points that
populate the `user` metric family.

## Functional coverage

`sv/` carries 16 modules of cover-property points, all instantiated in
`tb/tb_top.sv` -- 467 points, one per cell:

| Module | Points | Intent it makes real |
| --- | ---: | --- |
| `smc_map_fcov.sv` | 138 | address-map region decode, window tops, alias/remap and spare-block decode, region sizes |
| `smc_periph_fcov.sv` | 64 | per-instance peripheral decode, ATB receivers, I2C mode enables, mailbox levels, the peripheral-clock AXI-Lite CDC bridge |
| `smc_fabric_fcov.sv` | 44 | inbound/outbound fabric handshakes, response encodings, SYS_IN and JTAG manager paths |
| `smc_clk_fcov.sv` | 40 | clock-domain ratios, gating windows, stall windows |
| `smc_axi_chan_fcov.sv` | 24 | AXI channel-level handshake and burst shape |
| `smc_zeroer_fcov.sv` | 23 | zeroer command registers, master port, outstanding counter, FSM encodings |
| `smc_reset_fcov.sv` | 22 | reset-domain release order and ndmreset |
| `smc_rst_seq_fcov.sv` | 20 | cold-boot chain order, reset-sync edges, primary-reset scope |
| `smc_cpu_fcov.sv` | 19 | PLIC context state, CLINT MTIME/MTIMECMP, per-core direct pins |
| `smc_efuse_fcov.sv` | 18 | fuse sense, shadow-register load, bank-control AXI-Lite, SHIM command handshake |
| `smc_dma_fcov.sv` | 16 | DMA stream-0 command registers, frontend handshake, master port |
| `smc_int_fcov.sv` | 12 | interrupt vectors as whole buses, not hand-picked slices |
| `smc_filt_fcov.sv` | 8 | inbound filter hit/isolate decisions |
| `smc_iso_fcov.sv` | 8 | isolation and FLR sequencing state |
| `smc_gpio_fcov.sv` | 7 | pad direction map, input readback, pad-control decode |
| `smc_clk_domain_fcov.sv` | 4 | clock-domain connectivity |

A point must need stimulus beyond power-up and reset release. A level true in
the quiescent state is either absent or qualified by a sticky flag recording
that its counterpart happened first.

## The cell map

`smc_cell_map.json` has 699 entries and is the trace from a point back to the
scenario that asked for it. 268 entries name a point (`cell`, `scenario`,
`module`, `milestone`); the remaining 431 are `UNMAPPED:` -- a cell that was
asked for and deliberately given no point, with the reason:

| Reason | Entries | Meaning |
| --- | ---: | --- |
| `tbd` | 299 | no test reaches the cell yet; the entry names the stimulus it needs |
| `blocked` | 107 | an open spec finding leaves no pinned expected value, so no honest point can be written |
| `unreachable_at_level` | 25 | the observable does not exist at this DUT boundary (adopter block replaced by a terminator, elaboration constant, port absent from `hw/top`) |

A cell with no entry either way is the failure mode the file exists to prevent.

## Policy threshold and expiry semantics

`config/verilator/coverage_policy.toml` grades the `user` family against a
90% floor on the **effective** population. Every `[[holes]]` entry is
`disposition = "waive"`, `status = "accepted"`, and carries an `expires` date:
the point leaves the denominator until that date, after which it grades as open
again. That is what a deferral means here -- a date, not a permanent removal.

Two categories are in use:

- `missing_stimulus` -- no enrolled test drives the condition. The rationale
  names the cell and, where one is proposed, the test.
- `needs_review` -- the cell is blocked by an open spec finding. The point
  stays on the implemented behaviour and takes no credit until the finding is
  answered.

Selectors are exact hierarchies with `expected_matches = 1`. A waived point
that starts firing is a hard error, not a silent pass: the grade fails loudly
so the waiver gets removed.

## Status

Measured on the graded `hosted` run:

| | user points | hit | raw | waived | effective |
| --- | ---: | ---: | ---: | ---: | ---: |
| `--dut smc --items hosted --cov` | 467 | 380 | 81.37% | 87 | 100.00% |

Raw is the number to read; effective is what the gate sees once the deferrals
are accepted. Both are in the report and neither is hidden.

The VCS half is a **carrier, not a number**: `config/vcs/coverage_policy.toml`
and `config/vcs/smc_cov_scope.hier` exist so scope and policy sit in the same
place on SMC as they do on SEP, but no SMC run on VCS exists and neither file
has produced a score.
