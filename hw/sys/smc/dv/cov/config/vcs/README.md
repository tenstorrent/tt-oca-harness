<!-- SPDX-License-Identifier: Apache-2.0 -->
<!-- SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. -->

# SMC coverage scope

SMC scopes coverage in two files because the two simulators scope by different
things, and the two flows answer different questions:

| File | Flow | Mechanism | Population |
| --- | --- | --- | --- |
| `smc_cov_scope.hier` | commercial signoff | `-cm_hier` / `-cm_common_hier`, design units named by `gen_smc_cov_scope.py` | the SEP rule: DUT minus the bench, the CPU subtree, the library and interconnect cells and the I3C controllers; the bench's coverage collectors under `hw/sys/smc/dv/cov/sv` keep their assertions and covergroups but leave the code and toggle metrics; every other functional third-party IP stays graded |
| `../verilator/smc_cov_scope.vlt` | public CI | `coverage_off -file`, globs | what SMC owns: `hw/sys/smc/rtl/**`, `hw/sys/smc/regs/**`, the `hw/top` shells and the `cov/sv` points |

Both are applied at **compile** time, following what SEP measured
(`hw/sys/sep/dv/cov/config/vcs/README.md`): a report-time filter prunes the
report pages and still grades the whole database, so scope that has to hold
must keep the code out of the database. Edit either file then `--rebuild` --
neither is fingerprinted.

The VCS scope follows the rule `hw/sys/sep/dv/cov/config/vcs/sep_cov_scope.hier`
states, so the two subsystems' signoff figures are read on one definition:
the bench, the CPU subtree and the library cells leave the database, and
functional third-party IP stays graded regardless of authorship, because SMC
tests target it by name (the I3C controller, the DMA, the debug and trace
blocks, the AXI fabric). VCS scopes by design unit or instance, and those
trees are instantiated at hundreds of places inside SMC's own modules where
no `-tree` reaches them, so `gen_smc_cov_scope.py` reads the build filelists,
takes every module, interface and program compiled from the dropped trees,
and writes one `-module` line per unit under the reason it leaves; the file is
regenerated (`--check` says when it is stale) rather than kept by hand.

The Verilator scope keeps the narrower owned-files set. Verilator's
`coverage_off` takes source-path globs only, it does not apply to a file whose
last line has no newline (which is the state of several vendored files), and
the public runner compiles the coverage-instrumented model within a fixed
time budget, so widening its population to the vendored trees is a separate
decision with a measurement of its own.

## What the numbers are

The VCS figure is the SMC DUT minus the CPU subtree and the library cells,
functional third-party IP included. Not "SMC-owned RTL coverage": say which.
The Verilator figure is SMC-owned RTL. They also differ in what a point is --
Verilator's expression family against VCS's condition, FSM and toggle -- and
Verilator 5.050 leaves some vendored files instrumented that its scope names
(the known gap below), so quote the flow with the number.

## What each file excludes

### `smc_cov_scope.hier` (VCS)

    -tree smc_uvm_top 1        TB top's own body, children kept
    // bench                   units compiled from hw/sys/smc/dv/tb,
                               hw/sys/smc/dv/models and the dv/ trees of the
                               hw/ip blocks (the eFuse bank model and its
                               register block), as SEP drops efuse_bank_model
    // cpu subtree             the chipyard-generated CPU cluster, the same
                               argument SEP uses to drop sep_cpu
    // library cells           vendor/pulp-platform/common_cells, the OpenTitan
                               prim library (the cells SEP drops) and the OCAH
                               och_prim library, the same kind of leaf cell
    // interconnect cells      the vendored pulp AXI, APB, register_interface,
                               AXI-Stream and OBI mux, demux, crossbar and
                               converter children; the SMC fabric wrappers that
                               instantiate them stay graded, so a decode or
                               isolation fault still lands on SMC's own module
    // package                 axi_pkg, which would report an assertion row
                               with no logic behind it
    // i3c controllers         -tree ...u_smc_peripherals.u_i3ccore_wrapper: the six
                               I3C controllers and their AXI-Lite demux, a large
                               third-party block that one SMC leaf reaches and
                               that has its own bench (hw/ip/i3ccore_wrap/dv),
                               the same argument SEP uses to drop sep_cpu
    // bench coverage          begin line+cond+fsm+branch+tgl ... end around the
       collectors              sixteen units compiled from hw/sys/smc/dv/cov/sv:
                               the functional-coverage collectors the bench top
                               instantiates beside the DUT. Their code is bench
                               code, so it leaves the code and toggle metrics;
                               their assertions and covergroups stay, as the SMU
                               scope keeps its own

The `-module` lines are generated:

    python3 tools/dv/run_dv.py --dut smc --items smoke      # any build
    python3 hw/sys/smc/dv/cov/config/vcs/gen_smc_cov_scope.py

VCS warns `VCM-HFUFF` once per listed unit the current elaboration did not
instantiate; that is the list being a superset of one build, not an error.

### `../verilator/smc_cov_scope.vlt`

Same intent expressed over source paths. These are the patterns the file
carries, verbatim — note the absence of a `/` after the leading `*`, for the
reason under "Verilator glob matching" below:

    coverage_off -file "*hw/sys/smc/dv/tb/tb_top.sv"
    coverage_off -file "*hw/sys/smc/dv/tb/smc_tb_if.sv"
    coverage_off -file "*hw/sys/smc/dv/tb/verilator_stubs/*"
    coverage_off -file "*hw/sys/smc/dv/models/*"
    coverage_off -file "*chipyard_generated_files/*"
    coverage_off -file "*vendor/*"

`hw/sys/smc/dv/cov/sv/*` is **not** excluded — those files carry
the `OCAH_FCOV_COVER` points that populate the `user` metric family.

## Exclusion files

`coverage_policy.toml` beside this file names six `-elfile` files the report
applies, the form `hw/sys/sep/dv/cov/config/vcs/coverage_policy.toml` uses.
The first four are written by `gen_smc_cov_exclusions.py` from urg's exclusion
templates and the run's raw report (`cov/report_raw`, written without the
exclusion files). Every entry lists a point that report marks uncovered, rows,
branch arms and FSM states and transitions alike, so a reachable point is never
hidden by a pattern. That rule is a backstop rather than the argument: each
class states a fact, and the fact has to be narrow enough that its pattern
would not have named a reachable point to begin with, so no class takes a whole
state variable or a whole signal. F2 takes the edges into the always_comb
default's state that no case arm of the source produces, F3 the states of an
FSM that no tied-off response lets it reach, F4 a state whose decode arm a
parameter leaves unelaborated, F5 the edges that exist only as a state
register's reset assignment, and F6 the edge an enable-edge load cannot
supply. A vector is read from the
report's EXPRESSION table only: below it the report scores each operand again
under its own SUB-EXPRESSION heading, and a vector uncovered for an operand is
often covered for the expression containing it, so those rows are never merged
into the parent's. The classes that take operand rows, A6 and B1, read each
operand table as its own point, paired with its template entry within one
source line. A
branch arm is read from the table of the construct at its source line. Where
the report scores a construct as paths through several decisions, as it does
for a case statement or an else-if chain, each path is read whole: its decision
columns come from the annotated source (a ternary whose `?` opens its own line takes
its selector from the line above), it is paired with its template entry by
its column values, and it is written only when one of its own decisions is out
of reach under a class's fact, or when its decisions have no common solution
(C1). A comparison is one opaque truth value to that test. The signals a feature class holds decide condition rows the same way, operand tables included: a row is written when it is out of reach with them held and within reach with them free. A ternary operand reads as the arm its selector picks, a ternary point as its selector, which is how urg scores it, and an operand inside an arm whose selector the held signals keep at the other value is never evaluated, so every row of it is out of reach. The held signals of one module are also tried together, with each comparison over N-trace signals alone at the value P1 gives it, and a row out of reach only jointly is credited to the first class whose signals it names. A module urg reports per parameter set is keyed by that set, so a
fact can hold for one section and not another. Condition and
branch entries of one module are written as separate blocks, each under its
own metric's checksum, since urg checks a block against the metric it holds. Where a
fact turns on which term of an expression a row holds away from a tied value,
the class reads the report's term list for that expression and decides the row
from it, rather than matching the expression by name:

    urg -dir <run dir>/cov/merged.vdb -dump full_exclusions cond+branch+fsm -report <dir>
    python3 hw/sys/smc/dv/cov/config/vcs/gen_smc_cov_exclusions.py <dir> <run dir>/cov/report_raw/modinfo.txt

| File | Class | Fact |
| --- | --- | --- |
| `smc_regblock_exclusions.el` | A1 NO-STALL | a PeakRDL regblock without external registers hardwires `cpuif_req_stall_rd/wr` to zero: the stall branches and each stall sub-expression row that needs a stall input at one cannot occur. The handshake's valid-without-ready rows stay graded, since the cpuif holds a third request while two are in flight and its ready drops |
| `smc_regblock_exclusions.el` | A2 NO-ERROR | a regblock generated with "No valid address check" never sets `decoded_err`, `cpuif_wr_err` or `cpuif_rd_err`: its error branches and SLVERR responses cannot occur. `avsbus_controller.sv:1599` ORs its block's `pslverr` into its own, so that row with the block's error alone cannot occur either |
| `smc_regblock_exclusions.el` | A3 NO-READ-CHANNEL | the UART's read-channel select has no branch for the write-only register map, and `axi_lite_demux` raises a port's AR valid only when that port is selected, so that block's `arvalid` is never asserted. Its `axil_arvalid` register and `axil_ar_accept` stay low, every request is a write, and `readback_done`, `cpuif_rd_ack` and the external read ack (generated as zero) never rise: a row or branch path needing any of them high cannot occur. A row with `ar_accept` low and `aw_accept` high stays graded |
| `smc_regblock_exclusions.el` | A4 READ-NEVER-ERRORS | in the vendored iDMA register top `reg_re` and `reg_we` are mutually exclusive, `wr_err` is gated on `reg_we` and `addrmiss` requires that no address hit, so the per-address read term crossed with an error cannot occur |
| `smc_regblock_exclusions.el` | A5 INPUT-UNCONNECTED | the SMC integration ties that block's `devmode_i` to zero, so the explicit-error-on-unmapped-access term it gates never evaluates true |
| `smc_regblock_exclusions.el` | A6 SINGLEPULSE-RETAIN | the RDL declares the field `singlepulse`, so its storage holds a written one for a single cycle and the cpuif takes no second write in that cycle, which leaves the storage at zero at every accepted write. The retain row of the write-data ternary, and each row of its retain operand that asks for the storage at one, cannot occur; this holds at any cpuif width. A W1C or plain write-only field keeps its value between writes and stays graded |
| `smc_regblock_exclusions.el` | A7 SINGLEPULSE-LOADS | PeakRDL sets a singlepulse field's `load_next` on its software-write arm and on the else arm that clears it back to zero, so the storage loads on every clock out of reset and the path of its flop that skips the load cannot occur. A field with any arm that leaves `load_next` at zero stays graded |
| `smc_regblock_exclusions.el` | A10 HW-WRITE-EVERY-CYCLE | `filter_ctrl.rdl` gives START_ADDR and END_ADDR `hw = rw` with no write enable, so PeakRDL ends each field's `always_comb` with an else arm marked `// HW Write` that sets `load_next` as the software-write arm does (`filter_ctrl_reg.sv:540-552`); the storage loads on every clock out of reset and the path of its flop that skips the load cannot occur. The detector is A7's with that arm in place of the singlepulse clear |
| `smc_regblock_exclusions.el` | B7 DFX-INPUTS-TIED | **a bench fact, not a design one.** `smc.sv:236-241` and `smc_dfx_ctrl_status_wrap.sv:37-42` pass `mem_repair_done`, `mem_repair_success`, `mbist_done` and `mbist_pass` straight to the DFX status register's sticky fields, whose `load_next` is that input, and `hw/sys/smc/dv/tb/tb_top.sv` ties all four to one in both instances because the boot sequencer waits on them. The input-low arm of each sticky field and the no-load path of its flop have no stimulus. **Bench ports that drive those inputs retire the class** |
| `smc_regblock_exclusions.el` | C1 CONTRADICTORY-PATH | urg lists every combination of an if and else-if chain's decisions as a path. PeakRDL's response logic tests `cpuif_rd_ack` and `cpuif_wr_ack` alone inside `if (cpuif_rd_ack \|\| cpuif_wr_ack)`, so the path with the OR true and both acks false needs a contradiction. A path is written only when its own decisions, over the same signals, have no common solution |
| `smc_regblock_exclusions.el` | A8 EXTERNAL-ACK-SAME-CYCLE | in `i2c_reg`, `cpu_ctrl_reg`, `uart_16550_main_reg`, `uart_16550_main_wo_reg`, `system_timer_octs_reg`, `reset_unit_reg` and `avsbus_controller_reg` the integration drives every external register's `wr_ack` and `rd_ack` from that register's `req` and direction in the same cycle (for example `i2c_core.sv:378`, `uart_core.sv:724-733`, `smc_cpu_ctrl_wrap.sv:321-329`, `avsbus_controller.sv:1302-1306`), and PeakRDL gates `req` and `is_external` on the same direction, so `external_pending` never sets and the stall inputs it drives hold zero: the stall rows and paths and the pending-set row cannot occur. The handshake's valid-without-ready rows stay graded |
| `smc_regblock_exclusions.el` | A9 ADDRESS-FIXED | `smc_internal_regs.sv` feeds `output_remap_reg` `{1'b0, addr[2:0]}`, and `uart_log_engine_ctrl_reg` is selected only inside its four-byte window at an eight-byte aligned base, so each block's `cpuif_addr` and `rd_mux_addr` hold zero and a row needing either nonzero cannot occur |
| `smc_regblock_exclusions.el` | C3 NO-EXTERNAL-WRITE | the main UART map's only external register, RBR, is read-only, so PeakRDL gives `external_wr_ack` a constant zero and a row needing an external write acked cannot occur |
| `smc_regblock_exclusions.el` | C4 STROBE-CARRIES-DIRECTION | PeakRDL folds the direction into the decode strobe of a read-only or write-only register and into the `req` it presents for an external one, so neither is high in the other direction. A row needing that, in the block or in `i2c_core`, `uart_core` or `avsbus_controller`, which consume those reqs, cannot occur. `avsbus_controller.sv:1302-1304` ANDs the AVS_CMD and AVS_READBACK reqs with `req_is_wr` and its negation, which the block latches from `pwrite` in the setup phase, and its `axi_lite_to_apb` (`:315-341`) holds `pwrite` through access, so `R_avs_cmd_wr_en` and `R_avs_readback_rd_en` carry the direction of the transfer in flight. The test rewrites each strobe, req or enable as itself and its direction and takes a row only when that makes it unsatisfiable |
| `smc_regblock_exclusions.el` | B1 PARTIAL-LANE-WRITE | **a bench fact, not a design one.** The SMC AXI agent takes a one- or two-byte length (`smc_sys_axi_agent.py:350-354`), but no leaf of the measured run writes a block whose cpuif carries no more than 32 bits with a lane off; a leaf that does covers the rows it reaches, and the next re-pin drops them. A row of a field's software-write branch (`next_c = ...` under `// SW write`) that needs some `decoded_wr_biten` lane off, the retain row or a row of the retain or write-data operand, is reachable in the design and uncovered for want of a partial write. The test is exact: the row must be out of reach with every lane on and within reach with them free, over the report's own term list. **A block with a wider cpuif takes a half-word write from the same agent**, so its rows stay graded. The clear-on-write form of a W1C field is left out, and a leaf covers it |
| `smc_opentitan_toggle_exclusions.el` | T1 OPENTITAN-PORTS-ONLY | a unit that comes from OpenTitan is graded on its ports for toggle, its internals being verified upstream; every other unit the scope keeps is graded on all of its nets. Origin is the source's copyright line, not the unit's name, and the generator re-checks it. The ten units and their qualifying lines are listed below |
| `smc_xor_network_exclusions.el` | X1 XOR-NETWORK | a CRC or parity network is an XOR of four or more terms; condition coverage enumerates 2^n input combinations of a function the tests compare by its output |
| `smc_fsm_exclusions.el` | F2 DEFAULT | `avsbus_controller.cur_state` has `next_state = AVS_IDLE` as its always_comb default, which the extractor lists as an edge from every state; every state has a case arm and every arm assigns next_state, so the default never fires. `AVS_IDLE`, `AVS_SLAVE_RESYNC` and `AVS_END_LAST_SUBFRAME` assign AVS_IDLE in their own arm, reach it in the ordinary sequence, and stay graded |
| `smc_fsm_exclusions.el` | F3 TIEOFF | `smc_dfd_wrap` ties every `m_trc_axi_*` response input to zero, so `trace_axi_master` never completes a response handshake and cannot pass REQ_HANDSHAKE: the states an `aw_ready`, `w_ready` or `b_valid` is needed to enter, and the edges touching them, cannot occur. The request it issues on `valid_i` needs no response, so RESET_VALUE, REQ_HANDSHAKE and the edge between them stay graded |
| `smc_fsm_exclusions.el` | F4 PARAM-OFF | `efuse_interface_controller.efuse_reg_select` selects EFUSE_MMR_REG_MAP only when the instance has lifecycle state (`hw/ip/efuse/doc/memmap.adoc`); `smc_efuse_wrapper` sets `HAS_LC_STATE = 0`, so the arm is not elaborated and the state and its edges have no access that reaches them |
| `smc_fsm_exclusions.el` | F5 RESET-EDGE | a state register's reset assignment is expanded into a transition from every state; where no case arm of the source state assigns the reset state, the edge exists only if the block's reset is asserted while the FSM occupies that one state, and the package grades reset behaviour through its reset leaves. `accumulator_bank.bank_status` is one: the `BANK_PARTIAL` arm assigns only `BANK_FULL` or `BANK_PARTIAL`, so `BANK_PARTIAL->BANK_EMPTY` can only come from the reset at `accumulator_bank.sv:123` The seven `efuse_interface_shim` write-sequence states whose arms never return to `StWriteIdle`, only `StWriteFinish` doing so, are the same case |
| `smc_fsm_exclusions.el` | F6 ENABLE-EDGE | the bus monitor enters StBusBusyHigh from its StBusBusyLow arm on an idle bus, and from the monitor enable's rising edge in multi-controller mode, where the disabled branch has already parked the register at StBusFree; StBusBusyStop has no arm to StBusBusyHigh and cannot be the register's value at that edge, so only an edge from there cannot occur. The edge from StBusBusyLow is the ordinary sequence and stays graded |
| `smc_fsm_exclusions.el` | F7 SCL-HELD-LOW | `i2c_bus_monitor.sv:118` raises `start_det_trigger` only on a falling SDA while SCL is high on two samples, and `:103` clears the pending flag whenever SCL is low, so a target state driving `scl_d = 1'b0` holds the wired-AND SCL low for its whole duration and `start_detect_i` cannot rise in it: the fan-in override to AcquireStart (`i2c_target_fsm.sv:1029`) cannot fire from the seven stretch states |
| `smc_fsm_exclusions.el` | F8 NO-INTERFERENCE | `i2c_core.sv:620-622` gates `sda_released_but_low` on `scl_sync` and the interference and arbitration-lost terms on the transmitting flag, so a state leaving `transmitting_o` at zero, or holding SCL low, makes the term identically false and the override it feeds cannot fire from it: eight target states for `->WaitForStop` (`i2c_target_fsm.sv:1033`) and five controller states for `->Idle` (`i2c_controller_fsm.sv:999`). A state whose own arm assigns the same destination for another reason keeps that edge graded |
| `smc_fsm_exclusions.el` | B2 UNAIMED-OVERRIDE | **a bench fact, not a design one.** The I2C target and controller FSMs end their next-state logic with fan-in overrides (`i2c_target_fsm.sv:1017-1033`: start detect to AcquireStart; target disable, stop detect or bus timeout to Idle; arbitration loss to WaitForStop. `i2c_controller_fsm.sv:999`: interference or a failed symbol to Idle) taken on bus events and register writes. The states they leave are timed below one bit by the block's own counters, and the SMC bench drives the bus through the pads and registers, so it cannot place an event or a write in a chosen one of them. **A bench that can place a bus event or a register write in a chosen sub-bit state retires the class.** An edge the source state's own case arm assigns, read from the FSM source at generation time, stays graded; F7 and F8 name the edges the design forbids |
| `smc_fsm_exclusions.el` | F9 LOOP-INDEX-EXTRACTION | **a property of the extraction.** `telemetry_receiver.block_index` is a loop index local to an `always_comb` (declared `:185`, set `:189`, walked by the `for` at `:191`) with no flop behind it; the values and transitions the extractor records are sampled from that combinational loop and none is a state of the design. Only its uncovered points are written, so the sampled values it did record stay in the score |
| `smc_fsm_exclusions.el` | B4 SRAM-AUTOINIT-BYPASSED | **a bench fact, not a design one.** The CPU scratch SRAM is zeroed by a hardware sequence (`smc_4core_cpu.sv:437-470`) unless `smc_disable_sram_auto_init_i` is high, and `hw/sys/smc/dv/tb/tb_top.sv` ties it high, so MEM_ZERO_BUSY and its edges never run. **A bench that deasserts the input retires the class** |
| `smc_disabled_feature_exclusions.el` | P1 NTRACE-OFF | the DFD top instantiates the trace wrapper with `NUM_NTRACE_INST(0)` and `NTRACE_SUPPORT(0)`, and `trace_wrapper.sv` gives `Core_fuse_enable_Ntrace` a constant zero at zero instances, so every N-trace signal of the sink reads zero. A `trace_sink` row is taken only where the report's own term list shows it asking one of those signals for a value zero forbids; a row every N-trace term of which sits at zero stays graded, whatever the expression's other signals are. In `mmrs` the shared clock-disable and reset terms name other DFD blocks beside the N-trace one and stay graded, and so do the NTR sink's address decode and WARL checks: with the sink absent `NTR_SINK_BLK_IDX` equals `FUNNEL_BLK_IDX` (`mmrs.sv:252-253`), so they decode funnel accesses at offsets 0x10 to 0x1C. Five N-trace signals sit at one, not zero: `TrntrFlushTimeoutDone_ANY` resets to one (`trace_sink.sv:2294-2305`), `trntrRamModeBP_ANY` and `trntrMemModeBP_ANY` compare zero against a zero threshold with `<=` (`:1777`, `:1787`), and `trntrcoreFrameFillComplete_ANY` and its `_d1` copy read one because the write count they reduce stays at zero (`:1218`, `:1240`, `:1280-1286`). With `TrntrMemRamRdEn_TS1` at zero, `TrdstMemRamRdRdy_TS1` is the OR of the DST read enables (`:2131`), and the interleave flops enable only on an N-trace term and hold zero (`:2120-2146`). With the NTR sink register block absent (`mmrs.sv:1025`), the register-derived N-trace terms, the north source flag, the flush-timeout counter and the TNIF previous grant (`tnif.sv:64-73`) follow; `mmrs.sv:693` forms `Trntrissrammode` as the negation of that absent block's zero RAM mode, so it reads one; `trace_funnel.sv:206-212` maps no N-trace core, so its N-trace pid vector is zero |
| `smc_disabled_feature_exclusions.el` | P2 SKIP-TIED-OFF | both SMC fabrics instantiate the AXI filter with `filter_skip_i` tied to zero, so the arm the filter decision takes when it is high never runs; the arm it takes when low is the one the fabrics use and stays graded |
| `smc_disabled_feature_exclusions.el` | P3 WREN-TIED | the CLA assigns twenty of its MMR hardware write-enables a constant one (`cla_counter.sv`, `core_logic_analyzer.sv`), so the enable never reads zero and the write-data ternary never takes its else arm. In the SMC's timestamp scheme 0 (`smc_dfd_wrap.sv:153`) `core_logic_analyzer.sv:260` drives the CLA timestamp's upper write enable with a constant one as well |
| `smc_disabled_feature_exclusions.el` | P4 SINGLE-SOURCE | with one trace source the two-source term of `TrRamPendPkt*WrEn` is always false and the per-way pending count stays at zero (`trace_sink.sv` pending logic), so every pending valid and enable and every south-port valid reads zero. A row is taken only where the report's term list shows it out of reach with those held at zero and within reach with them free; the pending RAM's source field is RAM content and is left free, so rows ordinary trace traffic reaches stay graded. The pending entries are flops reset to zero and written only by a pending write (`trace_sink.sv:1348-1356`, `:1443-1446`), so their source, way and address fields and the read inhibits (`:1370-1383`) never read one. The DST pending-packet read inhibit is set only under a pending write or valid (`trace_sink.sv:1369-1383`), so it holds zero too |
| `smc_disabled_feature_exclusions.el` | P5 INSTR-TYPE-CONST | `mmrs.sv:606` assigns `MmrWrInstrType` a constant zero and every DFD MMR block (CLA, DST, DST sink, funnel) latches `reg_wr_instr_type` from it alone, so neither encoding the two `instr_type` comparisons of `update_value` test is ever presented and their true rows cannot occur; the write-data ternaries that pass the type to `update_value` stay graded |
| `smc_disabled_feature_exclusions.el` | P8 WREN-TIED-ZERO | `MMR_CDbgEapStatus_F_Rsvd3116_WrEn` is its CLA write structure's field and nothing else, and the CLA gives that structure a zero default and never names the field, so the enable holds zero and the then arm of the ternary it selects is unreachable; this is the converse of P3. It is the block's only reserved-field enable that qualifies: `ClaCtrlStatus`, `ClaTimestampConfig`, `MuxSelHi`, `MuxSelLo`, `LfsrMask` and `ClaTimestampOffset` each add a `reg_write & reg_addr` term that a software write to the register asserts, and the report marks all of those arms covered. The timestamp-capture enable is its structure field alone too (`cla_mmr.sv:9707`), and scheme 0 leaves that structure at zero (`core_logic_analyzer.sv:249`); TsCapture's enable ORs a register write with a structure field the CLA never names (`cla_mmr.sv:8644`), so only the row that needs that field high is taken |
| `smc_disabled_feature_exclusions.el` | P9 DEBUG-WIDTH-64 | `core_logic_analyzer` derives `DBG_SIGNAL_CONFIG` from `DEBUG_SIGNAL_WIDTH == 128` and `smc_dfd_wrap.sv:141` passes 64, so the `cla_snapshot_mmr_hi_blk` generate that drives every snapshot `Hi` write enable is not elaborated and each holds zero. The report agrees: all sixteen `Hi` true arms are uncovered and all sixteen `Lo` true arms, assigned outside that generate, are covered |
| `smc_disabled_feature_exclusions.el` | P10 PACKET-SHORTER-THAN-BANK | each accumulator bank spans `BANK_DATA_WIDTH_IN_BYTES` bytes, 32 here (`accumulator.sv:63-67`), and the packetizer is elaborated with `PACKET_WIDTH_IN_BYTES = VLT_PACKET_WIDTH / 8`, which a 64-bit debug bus makes 10 (`VLT_HDR_WIDTH = 8 + DEBUG_SIGNAL_WIDTH/8`), so one write cannot both start at or below a bank's first byte and end past its last: `target_write_byte_boundary_crosses_bank_range` is false for the life of the design. Only the row that needs it true is taken; the `equals_range_end` and `wraparound` rows of the same condition stay graded |
| `smc_disabled_feature_exclusions.el` | P11 UART-SELF-CHECK | each UART holding register stores `~^data` beside its data, written with the valid flag and cleared with it (`uart_core.sv:224-245`, `:432-454`), and each `prim_fifo_sync_parity` stores `{~^data, data}` and guards its pointers with a redundant `prim_count`, so a valid entry always has odd parity and `~^{parity, data}` reads one only on corrupted storage. The rows that need `thr_err`, `rbr_err` or either FIFO error at one follow |
| `smc_disabled_feature_exclusions.el` | P12 BREAK-IMPLIES-FRAMING | `uart_core.sv:345` forms `allzero_err` as the framing error of an all-zero frame and stores it as `break_err` beside `framing_err` in both the FIFO (`:361-362`) and the holding register (`:399-400`), so the `rx_char_err` row with `break_err` alone cannot occur. `uart_16550_main_reg` latches the two into the sticky LSR.BI and LSR.FE on the same cycle and clears both on the same LSR read, so its `intr` row with LSR.BI alone cannot occur either |
| `smc_disabled_feature_exclusions.el` | P6 LC-STATE-OFF | `smc_efuse_wrapper` instantiates the eFuse with `HAS_LC_STATE = 0`, so the lifecycle-state arms of `efuse_interface_controller`, `efuse_shadow_regs`, `efuse_shadow_reg_access_control` and `efuse_guard` are never entered and the RMA token comparisons they hold have no access that reaches them; the fuse-sense, security-disable and image-lock terms outside those arms stay graded. The arms are named by source region (`efuse_guard.sv:74-84`, `efuse_shadow_reg_access_control.sv:115-117`, `efuse_shadow_regs.sv:290-347` and the lifecycle-state write arm `:595-667`), and a region covers the operand tables of its conditions as well as their top rows |
| `smc_disabled_feature_exclusions.el` | P7 NO-ERROR-CAP | `idma_backend_wrapper` elaborates the backend with `ErrorCap = NO_ERROR_HANDLING`, whose bypass gives the legalizer's `flush_i` and `kill_i` a constant zero, so a term needing either asserted is false for the life of the design; the `r_ready_i`/`w_ready_i` backpressure rows and the software-writable `opt_tf_q.decouple_rw` branch stay graded |
| `smc_disabled_feature_exclusions.el` | P13 CLAMP-TIED | `generic_ipx_clk_rst_ctrl` forms `o_gated_func_clamp` as `i_func_clamp \| i_fuse_dis`; `smc_dfd_wrap` ties both to zero for the CLA, DST source, DST sink and funnel, and the DFD top ties both to one for the NTR sink; the trace network interface clamp is the AND of the DST inputs and the absent N-trace side's, and the MMR interface clamp the AND over every block, so both are zero. Each gated clamp is constant, and the ternary arm the other value selects in `cla_wrapper`, `trace_wrapper`, `dst_wrapper`, `tnif_wrapper` and `mmrs` cannot occur. With the NTR sink absent every block of `mmrs`' clamp vector is a zero clamp, so `clamp_hit` (`mmrs.sv:626`), which `mmr_req_ctrl` returns as `rsp_err`, is zero and `apb2mmr`'s error row that needs it cannot occur. Every `generic_ipx_clk_rst_ctrl` instance (`clk_rst_wrapper.sv:139-332`, `mmrs.sv:324-447`) takes one value for both `i_func_clamp` and `i_fuse_dis`, the NTR sink also ties its clock-disable value and control to one (`dfd_top_cla_dst_apb.sv:425-428,590-593`) so its clock-enable select is zero, and `trace_funnel.sv:248` ANDs the enabled sources with the funnel's zero clamp |
| `smc_disabled_feature_exclusions.el` | P14 JTAG-MMR-TIED | `smc_dfd_wrap` ties `i_jtag_mmr_req_vld` to zero, `mmrs` tests it directly and `mmr_req_ctrl` sets `gnt_is_jtag` from it alone, so no arm selecting the JTAG request can occur |
| `smc_disabled_feature_exclusions.el` | P15 SECURE-TM-TIED | `smc_efuse_wrapper` ties `secure_tm_i` to zero, so the secure-test-mode arms of `efuse_shadow_regs`, `efuse_shadow_reg_access_control` and `efuse_guard` cannot occur. The program-lock and read-lock arms beside them stay graded; the copy of `(sw_lock_bits[2:1] == 2'b11)` in the `secure_tm_i` arm of `efuse_shadow_reg_access_control.sv:129` is named by its region |
| `smc_disabled_feature_exclusions.el` | P16 SINK-ENABLE-CONST | the DFD top elaborates `mmrs` with `NTRACE_SUPPORT(0)` and default `TRACE_SINK_SUPPORT` and `DST_SUPPORT` of one, so `NTR_SINK_EN` is zero and `DST_SINK_EN` one, and the arm of each `if` on them that the constant does not select cannot occur. `CLA_EN`, `DST_EN` and `TRACE_SINK_SUPPORT` are one and `NTR_EN` zero (`mmrs.sv:87-92`), so each clamp and fuse term they select is read with them |
| `smc_disabled_feature_exclusions.el` | P17 ONE-TRACE-CORE | the DFD top passes the trace wrapper `NUM_CORES` as the larger of `NUM_DST_INST(1)` and `NUM_NTRACE_INST(0)`, and the wrapper passes it to the trace sink, so the then arm of `NUM_CORES > 1` cannot occur, and the south-channel frame start it guards stays at its zero default, which closes the arm that needs it (`trace_sink.sv:779`). The south write pointer is an OR over no cores (`trace_sink.sv:600-610`), so the south write way reads zero; a core's pointer never matches its own pending frame (`:911`), so the overflow-pending flop (`:872-881`) never sets; and the north way is the staged OR of each valid core's pointer, staged with the valid (`:514-540`, `:625`), so a non-zero way comes with the north write enable. `trace_network.sv:64-66,149-205` gives each `trace_hop` one core in its path and zero upstream repeaters and hops to the tail, so `num_cores_enabled` is at most one (`trace_hop.sv:104-108`) and the setup counter never leaves its target of zero (`:81-96`) |
| `smc_disabled_feature_exclusions.el` | P18 TDR-OVERRIDE-TIED | `avsbus_controller.sv:366` assigns `i_tdr_peripherals_apb2avsbus_postdiv_override` a constant zero, so the TDR arm of each post-divider ternary it selects (`:372-375`) cannot occur |
| `smc_disabled_feature_exclusions.el` | P19 NTR-RAM-READ-TIED | the DFD top connects the trace wrapper's `trRamDataRdEn` to a constant zero, so the trace sink's `trRamDataRdEn_ANY` is zero and the N-trace RAM data read never occurs: the `InsnTraceRdEn` rows that need it high and the read-address and read-enable arms it selects (`trace_sink.sv:1672`, `:1674`, `:1678`) cannot occur |
| `smc_disabled_feature_exclusions.el` | P20 TCOUNT-SELECT-PAIRED | the I2C FSMs reload their counter by `tcount_sel` only under `load_tcount` and assign it only named values, so the case's `default` item cannot occur in either FSM; the target assigns `tNoDelay` only beside `load_tcount = 0` (`i2c_target_fsm.sv:703-704`, `:1008-1009`), every reload pairing `tSetupData` or `tHoldData`, so its `tNoDelay` item cannot occur either. The controller reloads with `tNoDelay` on purpose, and that item stays graded |
| `smc_disabled_feature_exclusions.el` | P22 DFD-CONTROL-TIED | `smc_dfd_wrap.sv` ties the DFD top's `i_critical_signal_hold`, `i_dst_clk_dis` and `i_timestamp` to zero and `i_sdtrig_control` to `TRIG_TRACE_NONE`, so the warm-reset override terms of `clk_rst_wrapper`, its DST clock-disable extension, the CLA time-match event and the DST sdtrig start and stop hold zero: a row or path needing one of them high cannot occur |
| `smc_disabled_feature_exclusions.el` | P24 DIVIDER-INIT-NEVER-SET | `avsbus_controller.sv:407-415` assigns `do_initial_divider_setting` only `1'b0`, under reset and on a divider update, so a row needing it high cannot occur |
| `smc_disabled_feature_exclusions.el` | P25 SINK-WRITEBACK-TIED | `trace_sink.sv:2357-2362` gives the DST RAM-control write structure a zero default and sets only the empty and enable enables, `:2423` assigns the read-pointer-high write structure zero, and `trace_funnel.sv:330-333` tie the RAM start and limit write structures to zero, and `trace_funnel.sv:293-295` and `mmrs.sv:1371` tie the funnel's control and disable-input write structures to zero, so the stop-on-wrap, mode, active, start, limit and read-pointer-high hardware enables `dst_sink_mmr` ORs with a software write hold zero, as do `funnel_mmr`'s control, empty and disable-input enables, and each hardware-write row cannot occur |
| `smc_disabled_feature_exclusions.el` | P26 OUTPUT-FLOP-PARAM | urg reports `tt_debug_bus_mux`'s condition coverage as one section per parameter set, and each section's members agree on `DISABLE_OUTPUT_FLOP`: the L3 muxes elaborate it at 1 and the L2 and CLA muxes at 0 (`smc_dfd_wrap.sv:95`, `:119`). In each section the comparisons on the parameter (`tt_debug_bus_mux.sv:162`, `:168`) are constant, so the row needing the other value cannot occur, and at 1 the toggle-mode arm (`:169-173`) that tests it at 0 never executes. The fact is keyed by section; the branch report merges the sections, so its arms stay graded |
| `smc_disabled_feature_exclusions.el` | C5 SIGNAL-IDENTITY | the source defines one signal from another: `uart_core.sv:951-952` assigns `tx_enable` and `rx_enable` the same expression, `uart_core.sv:155,189,195` forms `thr_rready` from a term that includes `thr_rvalid`, `system_timer_octs_core.sv:240` forms `credit_gen_pulse` with `enable` as a term, `cla_arithmetic_compare.sv:24-25` derives `compare_equal` and `below_compare_int` from the same masked value, and `efuse_shadow_reg_access_control.sv:167-190` raises `write_locked_o` only on the arm that forwards no request. `i2c_controller_fsm.sv:280` ORs `event_sda_unstable_o` into `event_arbitration_lost_o`; `i2c_core.sv:1059` drives the controller's halt input from `CONTROLLER_EVENTS.intr`, the unmasked OR of fields that include the NACK and NACK-timeout bits it also drives (`:402`, `:686`; `i2c_reg.sv:3747-3751`); `log_engine.sv:72-93` requests an entry exactly when its length is nonzero and `prim_arbiter_tree.sv:112-183` returns a requesting leaf's data; `avsbus_async_fifo.sv:81-86` derives `wr_full_o` and `vacant_slots_o` from the same pointers, so full means no vacant slot; and `idma_nd_midend.sv:90-92,227` makes the request valid its first stage, which ready, last and busy include, while `idma_frontend_wrapper.sv:247,262` feeds it the frontend's valid. The test rewrites the dependent signal and takes a row only when that makes it unsatisfiable |
| `smc_disabled_feature_exclusions.el` | P27 PAGE-WIDTH-BOUND | `idma_legalizer_page_splitter.sv:37-39` forms `page_addr_width` as `OffsetWidth` plus the 3-bit `max_llen_i` or 8 and clamps it at 12. `OffsetWidth` is `$clog2(StrbWidth)`, 3 on the SMC's 64-bit backend, so the width is at most 11 and the clamp arm and its condition row never occur |
| `smc_disabled_feature_exclusions.el` | P28 LOG-WRITE-OKAY | `uart_log_engine_wrap.sv:252-313` wires the log engine's write port only to its own UART, whose demux (`uart_16550.sv:141-158`) sends every write to `uart_16550_main_reg`, `_wo_reg` or `_dl_reg`, each generated with `cpuif_wr_err = '0` (`:1405`, `:472`, `:343`); `axi_lite_from_mem.sv:204-206` reports an error only on SLVERR or DECERR, so `log_write_err` (`log_engine.sv:491`) holds zero. The status bit also takes `INTR_TEST.LOG_WRITE_ERR`, so its interrupt rows stay graded |
| `smc_disabled_feature_exclusions.el` | P29 FIELD-MAP-LOCKS | `smc_efuse_pkg.sv:196-235` gives every field `WRITE_UNLOCK` and `READ_UNLOCK` save the LOCKS meta-field, which is `WRITE_SET_ONLY` under the all-ones index the lock lookups never lock (`efuse_shadow_reg_access_control.sv:233-248`, `efuse_guard.sv:152-165`), and an unmapped address reads lock zero. No address carries the write-lock or read-lock code or lock bit 3, and a set-only address is never hardware write-locked. `efuse_program_interface.sv:79` and `efuse_read_interface.sv:74` present address 0, inside LOCKS, while idle, so `efuse_guard` sees no lock unless an operation is in flight; programming or reading a locked field stays graded |
| `smc_disabled_feature_exclusions.el` | P30 CCG-HYST-OFF | both `generic_ccg` instances set `HYST_EN` to zero (`smc_dfd_wrap.sv:73-75`, `tt_debug_bus_mux.sv:119`), so `hyst_on` is a constant zero (`generic_ccg.sv:64-65`) |
| `smc_disabled_feature_exclusions.el` | P31 OCTS-CREDIT-SPEC | **a property of the register specification.** `system_timer_octs.rdl:32-39` requires CREDIT_VAL to exceed PULSE_WIDTH, and `system_timer_octs_core.sv:302` counts a PULSE_WIDTH of zero as one, and `CreditValGreaterThanPulseWidth_A` (`:334`) states the same bound on that effective width, so CREDIT_VAL is at least two and above the pulse width. The enable only ever sets (`:108-114`), and until it does the credit counter is held at zero (`:219-221`), so the row at `:244` with the enable low and the counter at CREDIT_VAL minus one cannot occur. A pulse lasts its width (`:305-331`), a credit follows the last credit or counter reset by CREDIT_VAL cycles, a start resets the counter (`:219-221`), and CREDIT_VAL and PULSE_WIDTH change in one register write, so the row at `:316` with a credit during an active pulse cannot occur either. **A specification that admits a CREDIT_VAL at or below the pulse width retires the class** |
| `smc_disabled_feature_exclusions.el` | C6 EARLIER-ARM-TAKES | an else arm or later else-if runs only when the tests before it fail, so a row an earlier test takes is never evaluated: `smc_cpu_ctrl_wrap.sv:150` makes `reset_wdt_count` high whenever a core's `wdt_timeout_cluster_i` is low and the counter's `if` takes that reload first (`:159`); `vlt_packet_compression.sv:389` takes a timestamp packet without a grant before `:395`; `avsbus_controller.sv:884` takes a retry with a countdown above zero before `:889`; and `efuse_shadow_regs.sv:565` takes a setup-only write outside the lifecycle-state field before `:594`; `i2c_controller_fsm.sv:663` takes an enabled host before `:689`, `:703` takes `!trans_started && !scl_i` before `:707` and `:713`, and `:967` takes a disable mid-transaction before `:972`; `i2c_bus_monitor.sv:284` takes a disabled monitor before `:286`; `idma_channel_coupler.sv:141` takes a ready first AW before `:147` and `:152`; `idma_axi_read.sv:153` takes a non-last beat before `:156`; and `vlt_packet_compression.sv:451` sits inside `else if (retry_ts_packet_tx)` (`:447`), so its third term is always one. The rows are listed by their report terms in `EARLIER_ARM_ROWS` |
| `smc_disabled_feature_exclusions.el` | C7 ENUM-MEMBERS-ONLY | a variable assigned only members of its enum never takes a non-member: `efuse_shadow_regs.sv:357-435` resets the sense state to `StIdle` and names one of its four members in every assignment, so the `default` item (`:419-422`) never runs; the program, read and sense requesters issue only `READ`, `PROGRAM` or `PROGRAM_READ_BACK` or the all-zero default (`efuse_program_interface.sv:140`, `efuse_read_interface.sv:131`, `efuse_shadow_regs.sv:389`), never the unused `2'b11` (`efuse_pkg.sv:187-191`) that `efuse_interface_shim.sv:514` and `:545-547` need after their `READ` test |
| `smc_disabled_feature_exclusions.el` | C8 APB-PHASE-ORDER | `axi_lite_to_apb.sv:286,307-308,335-336` drives `penable` only with `psel` and holds the request from setup until `pready`; the local crossbar (`smc_local_xbar.sv:386-409`), `avsbus_controller.sv:315-341` and `prim_axi_lite_to_apb_single.sv:75-91` use it, `apb_demux.sv:39-40` gates `psel` and `penable` with one select, and `mmrs.sv:763` passes `psel` through the interface clamp P13 holds at zero. `apb2mmr.sv:68` raises `pready` only from `psel`, `penable` and `rsp_vld`, and `mmr_req_ctrl.sv:60-62,222-226` answers two cycles after a grant the setup phase raises at the earliest and grants nothing more meanwhile, so no response meets a setup phase. Rows needing `penable` without `psel`, `pready` without `penable`, or a setup-phase response cannot occur; `apb2mmr`'s decode-miss rows stay graded, as the crossbar forwards a 1 MB window (`smc_local_xbar.sv:121-122`) to 16 KB of MMR blocks |
| `smc_disabled_feature_exclusions.el` | C9 W2C-PULSE | `cla_node_eap.sv:145-152` pulses `reset_eap_status_w2c` on the rising edge of an EAP status W2C bit, and the CLA loads its zero write-back on that cycle (`core_logic_analyzer.sv:464-517`, `cla_mmr.sv:4336-4337`); `mmr_req_ctrl.sv:60-62,222` grants nothing for two cycles after a grant, so no software write lands on the clearing cycle and the bit is never high two cycles running |
| `smc_disabled_feature_exclusions.el` | C10 VALID-WITH-COMMAND | `efuse_program_interface.sv:140-141` sets the request's program command and valid together and `:155,163,178,195` clear both to the all-zero default; the read and sense requesters issue only `READ`, so `efuse_interface_shim.sv:351` never sees a program command without valid |
| `smc_disabled_feature_exclusions.el` | C11 AVS-IRQ-DETECT-REARM | `avsbus_controller.sv:1516-1526` shifts the slave-interrupt detector on negedges and `:701-704` changes state on posedges; `:1412-1427` sets the interrupt flag, with priority over its clear, at any posedge that sees an idle or resync state with the detector at `00`, and the next negedge re-arms the detector to `11` once the state has left them with the flag set. No posedge sees `00` outside those states (`:1416`) |
| `smc_disabled_feature_exclusions.el` | C12 POP-ONLY-NONEMPTY | the readback FIFO pops only with `~apb_readback_buf_empty` (`avsbus_controller.sv:1606`). The command FIFO's pop flop is set at `:971,996,1013,1043,1068`, each on `fifos_ready_to_launch_frame` (`:1553-1554`, which includes `~avs_cmd_buf_empty`) in the same cycle or, for the post-resync launch, on the resync exit's `fifos_ready_to_launch_frame_rb_en_b` (`:1565-1567`) with no pop between; every popping state moves to a shift state that clears it, and END_MID and END_LAST push the readback whenever they pop, so their launch test equals the next-state one. A read-side empty flag falls only without a pop, so `avsbus_async_fifo.sv:63` never sees a read while empty |
| `smc_disabled_feature_exclusions.el` | C13 COUNTER-VALID-PAIRED | `idma_axi_write.sv:236-255,292-305` resets the write beat counter and its valid flag together, loads them together, and clears the flag in the cycle the counter steps from one to zero, so the counter is zero whenever the flag is low (`:240`). `system_timer_octs_core.sv:182-186` holds the count at zero until a start or sync load, and `:108-114` sets the sticky enable on the same edge, so `reg_running_o`'s row with the enable low and a nonzero count (`:350`) cannot occur |
| `smc_disabled_feature_exclusions.el` | C14 STROBE-MASK-NONZERO | `idma_axi_write.sv:118` shifts an all-ones first mask by an offset below the strobe width, and `:136-145` masks a first-and-last beat from its offset to its tailer, which the legalizer forms as the offset plus a burst length of at least one (`idma_generated.sv:3901-3910,4031`; zero lengths rejected at `:8649-8654`). Neither mask is zero, so the rows at `:159` and `:164` that need an empty buffer to cover it cannot occur |
| `smc_disabled_feature_exclusions.el` | C15 UNSIGNED-WRAP-DECODE | `smc_padring.sv:122-132` decodes the GPIO window with a 32-bit subtraction (`gpio_pkg::ADDR_WIDTH`) from `SMC_TOP_GPIO_INTF_BASE_ADDR(0)` = 0xC0003000, so an address below the base wraps to at least 0x3FFFD000 and its index is far above `NUM_GPIO_WRAPS` = 65; the in-window test never passes below the base |
| `smc_disabled_feature_exclusions.el` | A11 APB-ACK-FIRST-ACTIVE-CYCLE | the APB cpuif raises `is_active` and `cpuif_req` on one edge (`efuse_interface_ctrl_reg.sv:46-72`), and these blocks ack every request in that cycle: `efuse_interface_ctrl_reg.sv:631,687-691` ack from the request with no stall, and `avsbus_controller_reg.sv:1055-1059,1163-1168` ack external registers from their own request (A8) and internal ones from the request. `is_active` is never high without an ack (`:68`) |
| `smc_disabled_feature_exclusions.el` | D1 SINGLE-OUTSTANDING-DEMUX | each block sits directly behind an `axi_lite_demux` with `MaxTrans(1)` (`smc_internal_regs.sv:277-809`, `smc_ip_integration.sv:223`, `smc_misc_wrap.sv:76`, `telemetry_receiver_wrap.sv:92`, `uart_log_engine_wrap.sv:139`, `i2c_wrap.sv:133`, `uart_16550.sv:170`). The demux raises AR valid only while its R FIFO is not full (`axi_lite_demux.sv:386-400`), pushed at the AR handshake and popped at R, and W valid only while its B FIFO is not full (`:305-330`), pushed at the W handshake and popped at B; the block answers R or B only after the accept that empties its AR or W holding register (`output_remap_reg.sv:80-117`). Each AR and W therefore arrives with ready high, and the AR and W valid-without-ready rows cannot occur. The write-only UART map's read channel stays A3's. That map takes no reads, and its demux's W FIFO holds an AW's select until the W is taken (`axi_lite_demux.sv:250-256`) while the B FIFO holds each W back until the previous B, so when the next AW can first arrive the block holds the previous AW and W with no response in flight (`uart_16550_main_wo_reg.sv:106-110`, stall `:223-224` never set under A8) and accepts them; its AW valid-without-ready row and the accept-with-ack rows at `:107` and `:109` cannot occur. The zeroer's `axi_to_axi_lite` gates AW on a depth-one ID FIFO pushed at the AW handshake and popped at B (`axi_to_axi_lite.sv:219-222`, `zeroer.sv:83-84`), so its AW row cannot occur either. Blocks that take reads keep the AW row graded, since a held read can win the arbitration and defer the write accept, and `cpu_ctrl` allows two writes outstanding |
| `smc_disabled_feature_exclusions.el` | D2 W-FOLLOWS-AW | the same blocks take their W from a demux master port that raises W valid only once the select its AW pushed is in the W FIFO, and holds that AW valid until its handshake (`axi_lite_demux.sv:230-308`). The block keeps `awready` and `wready` equal except while it holds an AW without its W (`output_remap_reg.sv:114-117`), so a W is never taken before its AW and the `axil_awvalid && axil_wvalid` row with W alone cannot occur. Blocks behind an xbar or a filter demux stay graded: a spill register on AW after the W FIFO push could let W arrive first |
| `smc_disabled_feature_exclusions.el` | B9 SECURITY-DISABLE-TIED | **a bench fact, not a design one.** `hw/sys/smc/dv/tb/tb_top.sv` ties `sep_security_disable_i` to zero in both instances (`:1246`, `:3458`) and `smc_efuse_wrapper.sv:227` passes it unchanged to `efuse_interface_controller` and its shadow registers, so the security-disable terms of the requester mux (`efuse_interface_controller.sv:757`), the sense-done status (`:447`) and the fuse-sense load hold zero. **A bench port that drives the input retires the class** |
| `smc_disabled_feature_exclusions.el` | B8 DFD-BENCH-INPUTS-TIED | **a bench fact, not a design one.** `hw/sys/smc/dv/tb/tb_top.sv` ties `xtrigger_ss_i` and `tdr_dbg_ctrl_clock_stop_en_i` to zero in both instances; they reach the CLA crosstrigger input and the DFD clock-stop gate unchanged, so the crosstrigger edge, the timestamp load it arms and the TDR clock-stop term hold zero. **Bench ports that drive those inputs retire the class** |
| `smc_disabled_feature_exclusions.el` | B6 SIM-ONLY-FUSE-BYPASS | **a property of this bench and its policy, not of the design.** `efuse_shadow_regs.sv:151-205` reads `+skip_fuse_sense` in simulation-only initial blocks and `:163` ties `sim_skip_fuse_sense` to zero outside simulation; with the plusarg set the shadow registers take a preload file or zeros in place of the sensed fuse image (`:443-446`, `:485`). The DV policy (section 1.6) forbids a skipped fuse sense as evidence and no SMC testlist entry passes the plusarg, so the plusarg arms, the preload flag the initial block sets only with `sim_skip_fuse_sense` high (`:176-190`), and every row or branch path that needs `sim_skip_fuse_sense` high never run. **A policy change admitting the plusarg retires the class** |
| `smc_disabled_feature_exclusions.el` | B12 BANK-MODEL-NO-SLVERR | **a property of this bench, not of the design.** `smc_ip_integration.sv:145-160` answers the eFuse shim with `efuse_bank_model`, whose `efuse_bank_reg` drives `pslverr` from `cpuif_rd_err \| cpuif_wr_err` with both tied to zero (`efuse_bank_reg.sv:77,164,186-191`). No read, program or read-back returns SLVERR, so the read-back error row (`efuse_interface_shim.sv:448`) and the sense status (`:220`, `efuse_shadow_regs.sv:513`) cannot show one; the model's injected program failures corrupt the data, which the mismatch term still grades. **A bank model or macro that can return SLVERR retires the class** |
| `smc_disabled_feature_exclusions.el` | B13 LANE-ZERO-FILL | **a property of this bench, not of the design alone.** `i2c_reg`, `log_engine_reg`, `telemetry_receiver_reg` and the `i2c_core` FDATA fields sit in `periph_main` (`smc_local_xbar.sv:115`), reached only through the 64-to-32 `axi_dw_converter` (`:258`), whose downsizer starts each narrow beat at zero and copies only the lanes inside the transfer size (`axi_dw_downsizer.sv:730,776-787`). Inside that size no master of this bench leaves a one on an unstrobed lane: a CPU store strobes every lane of its size, the iDMA masks unstrobed lanes (`idma_backend_wrapper.sv:146`), the zeroer writes zero (`zeroer.sv:416`), and the cocotb AXI masters on the system and SEP ports write contiguous bytes with every other lane zero. The write-data-with-enable-low rows of the W1C clear operands and the FDATA flag fields cannot occur; rows B1 already takes stay in the regblock file. **A master that drives data on an unstrobed lane inside its transfer size retires the class** |

A regblock whose stall is `external_pending` (it has external registers)
gets A2 only; a regblock that decodes errors gets neither. `--check` reports
when the committed files no longer match the templates.

The fifth file is a covergroup exclusion. `-cm_hier` scopes line, condition,
FSM, toggle and branch, and `-cm_common_hier` extends it to assertions;
neither reaches a covergroup, so a covergroup declared inside RTL is graded
wherever the elaboration instantiates it. The six
`cg_bus_event_fsm_transitions` groups the chipsalliance I3C core declares in
`i3c_target_fsm.sv` therefore land in urg's GROUP score beside SMC's own
`cov/sv` covergroups even though the scope file drops the `u_i3ccore_wrapper`
tree from every code metric. `gen_smc_group_exclusions.py` writes
`smc_group_exclusions.el` from urg's group template, so the definition
checksum and every instance path come from urg, and `--check` tells whether
the committed file is stale. Every covergroup under `u_dut` must fall in a
class the script names; one that does not stops the script.

    urg -dir <run dir>/cov/merged.vdb -dump full_exclusions group -report <dir>
    python3 hw/sys/smc/dv/cov/config/vcs/gen_smc_group_exclusions.py <dir>/fullexclude.tb_def

| File | Class | Fact |
| --- | --- | --- |
| `smc_group_exclusions.el` | VENDORED-I3C | the I3C controllers' internals are graded by `hw/ip/i3ccore_wrap/dv`; SMC reaches them through its own fabric and grades that reach with the `cov/sv` points |

What remains in GROUP is the `u_smc_*_fcov::cg_*` set, the covergroup half of
SMC's functional coverage; the `cov/sv` cover properties are the other half
and are read under `assertion`.

## Why these exclusions

The chipyard-generated CPU cluster dominates the unscoped denominator and is
reached only by the CPU-boot tests, so an unscoped headline is a statement
about a core nobody grades here -- the same reason SEP drops `sep_cpu`. The
six I3C controllers are the same case at the peripheral level: one SMC leaf
reaches them, they carried three fifths of the uncovered points under the
SEP rule, and `hw/ip/i3ccore_wrap/dv` grades their internals. The library
cells (pulp `common_cells`, OpenTitan `prim*`, OCAH `och_prim`) are leaf
primitives whose branches depend on parameters no SMC test chooses, and the
vendored interconnect cells (pulp AXI/APB mux, demux, crossbar and converter
children) are the same kind of parameterised library inside the fabric; SMC's
own fabric wrappers around them stay graded. Everything else the build
compiles stays graded: the vendored DMA, debug and trace blocks, and the
`hw/ip` and `hw/common` blocks SMC integrates, because SMC tests drive them
by name and their reachability from the SMC boundary is part of what this
bench claims. The Verilator public-CI scope keeps the narrower
owned-files set for the reasons above.

## Known gap in the Verilator scope

`coverage_off -file "*vendor/*"` drops chipsalliance/i3c-core and
lowRISC/opentitan but **not** `vendor/pulp-platform/**` or
`vendor/tenstorrent/tt-hw-debug/**`. No file pattern reaches those two trees
(`*pulp-platform/*` and `*tt-hw-debug/*` are inert), so they stay in the
denominator. Patterns that do nothing are not carried in the scope file:
config that looks like scope and does nothing is worse than a documented gap.

The SYS_OUT responder is the shared VIP slave agent, class code with no RTL to
score; only its interface instance and struct bridge sit in the TB body. VCS
has no equivalent gap: `-module` names every unit regardless of where its
source file ends.

## Verilator glob matching

`coverage_off -file` matches the path as Verilator **opened** the file, not the
absolute path it records in the generated code. The filelist is absolute, but
files reached through `+incdir+` are opened relative, so a pattern has to cover
both forms:

| Pattern | relative open | absolute open |
| --- | --- | --- |
| `*/vendor/*` | not matched | matched |
| `*vendor/*` | matched | matched |
| `*vendor*` | matched | matched |

A leading `*/` therefore scopes only half the tree and says nothing about it.
The relatively-opened half then stays fully instrumented while the build
succeeds and nothing warns. Verify a scope
change by counting `__vlCoverInsert` sites per source bucket in the generated
model, not by the build passing.

## VCS bring-up checklist

On a VCS run check that: the compile accepts `-lca -cm_common_hier`; 
`gen_smc_cov_scope.py --check` passes (a unit added to a vendored tree since
the file was generated would otherwise be graded, and VCS accepts a stale
scope file silently); and `u_dut` matches
`smc_uvm_top` in every column, which is what shows assertions were scoped too.

## VCS scope behaviour

- **An include-list does not restrict instrumentation.** `+tree` leaves the
  design database unscoped; only `-tree` takes effect, and VCS accepts the
  file silently either way. Name what to drop.
- **`-cm_hier` alone does not scope assertions.** It governs line, condition,
  FSM, toggle and branch only; without `-cm_common_hier` the excluded
  hierarchy is gone from the code metrics but still graded for assertions.
- **`-cm_common_hier` needs `-lca`.** An opt-in switch, not a separate
  licence.

## Toggle inside OpenTitan units

`smc_opentitan_toggle_exclusions.el` carries the T1 rule. `-cm_tgl portsonly`
applies to a whole run and cannot name one unit, and a `begin tgl(portsonly)
... end` block in `smc_cov_scope.hier` is not an option either:
`hw/sys/smu/dv/cov/config/vcs/README.md` records that VCS keeps the toggle
points of the subtrees a hierarchy file drops once a metric block is present,
and this scope drops 603 units that way. The nets are therefore excluded at
report time, which also means the effect shows up without a `--rebuild`.

A unit qualifies on the copyright line of the source the build compiles it
from, checked again whenever the file is generated. Units compiled from
`vendor/lowRISC/` are all `prim*` library cells the scope already drops, and
the lowRISC-headered files under `vendor/chipsalliance/i3c-core/` sit inside
the I3C wrapper the scope drops as a tree, so neither is named here. A child
module of a listed unit is its own unit: unless it is listed too, it keeps all
of its nets.

| Unit | Source | Copyright line | Port bits kept | Nets excluded |
| --- | --- | --- | ---: | ---: |
| `i2c` | `hw/ip/i2c/rtl/i2c.sv` | `Copyright lowRISC contributors (OpenTitan project).` | 36 | 197 |
| `i2c_core` | `hw/ip/i2c/rtl/i2c_core.sv` | same | 214 | 173 |
| `i2c_controller_fsm` | `hw/ip/i2c/rtl/i2c_controller_fsm.sv` | same | 44 | 35 |
| `i2c_target_fsm` | `hw/ip/i2c/rtl/i2c_target_fsm.sv` | same | 48 | 43 |
| `i2c_bus_monitor` | `hw/ip/i2c/rtl/i2c_bus_monitor.sv` | same | 18 | 22 |
| `uart_16550` | `hw/ip/uart/uart_16550/rtl/uart_16550.sv` | `Copyright lowRISC contributors.` | 35 | 148 |
| `uart_core` | `hw/ip/uart/uart_16550/rtl/uart_core.sv` | same | 83 | 161 |
| `uart_rx` | `hw/ip/uart/uart_16550/rtl/uart_rx.sv` | same | 16 | 12 |
| `uart_tx` | `hw/ip/uart/uart_16550/rtl/uart_tx.sv` | same | 12 | 7 |
| `prim_clock_mux2` | `hw/common/och_prim_generic/rtl/prim_clock_mux2.sv` | `Copyright lowRISC contributors (OpenTitan project).` | 4 | 0 |
| **total** | | | **510** | **798** |

`prim_clock_mux2` declares nothing but its ports, so it contributes no entry;
it is listed because the rule reaches it. The scope drops `hw/common/och_prim/`
but not `och_prim_generic/`, which is why this one is graded at all.

    urg -dir <run dir>/cov/merged.vdb -dump full_exclusions tgl -report <dir>
    python3 hw/sys/smc/dv/cov/config/vcs/gen_smc_opentitan_toggle_exclusions.py <dir>
