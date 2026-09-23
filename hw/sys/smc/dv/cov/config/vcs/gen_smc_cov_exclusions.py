#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Write the SMC VCS coverage exclusion files from urg's exclusion templates.

Two structural facts of the compiled design leave coverage points that no
access from this bench can reach, and SEP records the same facts in
`hw/sys/sep/dv/cov/config/vcs/sep_regblock_exclusions.el`:

* A1 NO-STALL: a PeakRDL register block whose cpuif has no external
  registers hardwires `cpuif_req_stall_rd` and `cpuif_req_stall_wr` to zero,
  so the AXI-Lite handshake can never see valid without ready and the stall
  branches of the request path never execute.
* A2 NO-ERROR: a PeakRDL register block generated without an address or
  access check ("No valid address check" in the generated source) never sets
  `decoded_err`, `cpuif_wr_err` or `cpuif_rd_err`, so its error branches and
  the SLVERR values of `bresp`/`rresp` never occur.

Three more facts belong to one block each rather than to a family:

* A3 NO-READ-CHANNEL: the UART selects its write-only register map on the
  write channel only, so that block's AR channel is never driven and every
  condition over it, the read handshake included, has no access behind it.
* A4 READ-NEVER-ERRORS: the vendored iDMA register top raises an error only
  on a write (`wr_err` is gated on `reg_we`) or on an access that hits
  nothing (`addrmiss` requires no hit), and read and write are mutually
  exclusive, so the per-address read term crossed with an error cannot occur.
* A5 INPUT-UNCONNECTED: the same block's `devmode_i` is left unconnected by
  the SMC integration, so the explicit-error-on-unmapped-access term it gates
  never evaluates true.

A sixth belongs to the register specification rather than to the generated code:

* A6 SINGLEPULSE-RETAIN: a field the RDL declares `singlepulse` holds a written
  one for a single cycle, and the cpuif accepts no second write in that cycle,
  so the storage reads zero at every write the field sees. The retain row of the
  write-data ternary needs the storage at one while a write arrives with that
  lane disabled, and no access produces it. A W1C or a plain write-only field
  keeps its value between writes, so its retain row stays graded: only the
  bench's inability to drive a partial write lane leaves that one uncovered.

Two facts are the integration's: the DFD top instantiates its trace wrapper
with `NUM_NTRACE_INST(0)` and `NTRACE_SUPPORT(0)`, so the trace sink's N-trace
half has no source behind it (P1 NTRACE-OFF, named by the `trntr` signal
prefix, and the NTR-sink MMR rows of `mmrs`); both SMC fabrics tie the AXI
filter's `filter_skip_i` to zero (P2 SKIP-TIED-OFF); the CLA drives twenty
of its MMR hardware write-enables with a constant one, so their write-data
ternaries never take the else arm (P3 WREN-TIED); one trace source can never
prime the sink's per-way pending count (P4 SINGLE-SOURCE); and the MMR
instruction type has no driver outside the MMR files (P5 INSTR-TYPE-CONST).

Two more are the integration's as well: `smc_efuse_wrapper` instantiates the
eFuse with `HAS_LC_STATE = 0`, so the lifecycle-state arms of
`efuse_shadow_regs` and `efuse_guard` are never entered and the RMA token
comparisons inside them have no access that reaches them (P6 LC-STATE-OFF); and
`idma_backend_wrapper` elaborates the backend with
`ErrorCap = NO_ERROR_HANDLING`, whose bypass assigns the legalizer's `flush_i`
and `kill_i` a constant zero (P7 NO-ERROR-CAP). The legalizer's
`opt_tf_q.decouple_rw` is not one of these: `CONFIG.DECOUPLE_RW` is a
software-writable RDL field the frontend carries into the backend options, so
that branch stays graded.

The CLA holds a second write-enable fact, the converse of P3: its MMR write
structures carry a zero default and never name their reserved fields' enables,
so `MMR_CDbgEapStatus_F_Rsvd3116_WrEn`, `MMR_CDbgClaCtrlStatus_F_Rsvd6216_WrEn`
and `MMR_CDbgClaTimestampConfig_F_Rsvd1_WrEn` hold zero and the then arm of the
ternary each selects is unreachable (P8 WREN-TIED-ZERO). The reserved enables
of `MuxSelHi`, `MuxSelLo`, `LfsrMask` and `ClaTimestampOffset` have no CLA
output port to read the fact from and stay graded.

A third fact is not a register block's: a CRC or parity network is an XOR
reduction, and condition coverage enumerates 2^n input combinations of it.
The X1 XOR-NETWORK class names those expressions.

Three FSM facts follow from the source rather than from any access. urg's FSM
score counts transitions, and the extractor lists every assignment to the
state variable as a transition:

* F1 LOOPVAR: `telemetry_receiver.block_index` is the loop variable of the
  message decoder, extracted as an FSM because it is a state-shaped register;
  its settled value is fixed by `NUM_BLOCKS_PER_PACKET`.
* F2 DEFAULT: `avsbus_controller.cur_state` has `next_state = AVS_IDLE` as the
  always_comb default, which the extractor reads as an edge from every state
  to AVS_IDLE; every case arm assigns next_state, so the default never fires.
* F3 TIEOFF: `trace_axi_master.state` never leaves RESET_VALUE because
  `smc_dfd_wrap` ties every `m_trc_axi_*` response input to zero.
* F4 PARAM-OFF: `efuse_interface_controller.efuse_reg_select` reaches
  EFUSE_MMR_REG_MAP only when the instance has lifecycle state, and
  `smc_efuse_wrapper` instantiates it with `HAS_LC_STATE = 0`, so the decode
  arm that selects the state is not elaborated.
* F6 ENABLE-EDGE: a state register that loads one state on an enable rising
  edge, where the disabled branch parks the register at another state, can
  only reach it from that one predecessor; edges into it from any other state
  are the same extraction artefact as F2.
* F5 RESET-EDGE: a state register's reset assignment is expanded into a
  transition from every state. Where no case arm assigns the reset state, the
  only way to cover such an edge is to assert the block's reset while the FSM
  occupies that one state. Reset behaviour is graded by the reset tests, not
  by landing a reset in each protocol state.

Input is the set of templates urg writes for the merged database::

    urg -dir <run dir>/cov/merged.vdb -dump full_exclusions cond+branch+fsm -report <dir>

which leaves fullexclude_module.{cond,branch,fsm} in the working directory.
Every checksum and entry text below comes from those templates.

Only rows and branches the merged report marks uncovered are written, so a
reachable row is never hidden by a pattern. The report has to be the one urg
wrote without an exclusion file: the runner keeps it as
`<run dir>/cov/report_raw/modinfo.txt` beside the effective report, and a row
the effective report already shows as `Excluded` would otherwise drop out of
the regenerated file.

    python3 gen_smc_cov_exclusions.py <template dir> <run dir>/cov/report_raw/modinfo.txt
    python3 gen_smc_cov_exclusions.py <template dir> <modinfo.txt> --check
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[6]
REGBLOCK_OUT = HERE / "smc_regblock_exclusions.el"
XOR_OUT = HERE / "smc_xor_network_exclusions.el"
FEATURE_OUT = HERE / "smc_disabled_feature_exclusions.el"
FSM_OUT = HERE / "smc_fsm_exclusions.el"

CHECKSUM_RE = re.compile(r"^// CHECKSUM: (\"[^\"]*\")")
MODULE_RE = re.compile(r"^// MODULE: (\S+)")
FILE_RE = re.compile(r'^// ANNOTATION: "FileName: (\S+), LineNumber: (\d+)"')
ENTRY_RE = re.compile(r"^// ((?:Condition|Block|Branch|Line|Fsm|State|Transition) .*)$")
FSM_ENTRY_RE = re.compile(r'^(State|Transition) (\S+?)(?:->(\S+))? "[^"]*"$')
HANDSHAKE_RE = re.compile(
    r"\((s_axil_\w*valid)\s*&&\s*(s_axil_\w*ready)\)\s+1\s+-1\"\s+\(\d+ \"10\"\)"
)
STALL_RE = re.compile(r"cpuif_req_stall")
ERROR_RE = re.compile(r"decoded_err|cpuif_wr_err|cpuif_rd_err|readback_err|axil_resp_buffer_err")
XOR_TERM_RE = re.compile(r"^\((?:[A-Za-z_][\w\[\]\.:]*\s*\^\s*){3,}[A-Za-z_][\w\[\]\.:]*\)")
COND_ROW_RE = re.compile(r'^(Condition \d+ "\d+" "(.*) 1 -1") \((\d+) "([01]+)"\)$')
BRANCH_ROW_RE = re.compile(r'^(Branch \d+ "\d+" "(.*)") \((\d+)\) "(.*) (1|0)"$')

A1 = (
    "SMC-REGBLOCK-A1-NOSTALL: the PeakRDL cpuif of this block hardwires "
    "cpuif_req_stall_rd and cpuif_req_stall_wr to zero, so an AXI-Lite request is "
    "accepted the cycle it is valid and the stall branches of the request path never "
    "execute; the valid-without-ready row of each handshake condition has no access "
    "that can produce it."
)
A2 = (
    "SMC-REGBLOCK-A2-NOERROR: the block is generated without an address or access "
    "check, so decoded_err, cpuif_wr_err and cpuif_rd_err hold zero and bresp/rresp "
    "never leave OKAY; the error branches have no access that can enter them. The "
    "fabric's own SLVERR and DECERR paths are graded on their modules, not here."
)
X1 = (
    "SMC-X1-XOR-NETWORK: a CRC or parity network is an XOR reduction of its inputs, and "
    "condition coverage of it enumerates every combination of the terms; the network's "
    "function is one value per input vector and is proven by the data the block "
    "produces, which the tests compare."
)
F1 = (
    "SMC-FSM-F1-LOOPVAR: block_index is the loop variable of the message decoder, a "
    "state-shaped register the extractor reports as an FSM; its settled value is fixed "
    "by NUM_BLOCKS_PER_PACKET and no ATB stimulus moves it."
)
F2 = (
    "SMC-FSM-F2-DEFAULT: next_state = AVS_IDLE is the always_comb default of the protocol "
    "FSM, which the extractor lists as a transition from every state; every case arm "
    "assigns next_state, so no state reaches AVS_IDLE through the default."
)
F3 = (
    "SMC-FSM-F3-TIEOFF: smc_dfd_wrap ties every m_trc_axi_* response input to zero, so "
    "the trace write master never sees a handshake and its state register cannot leave "
    "RESET_VALUE."
)
F4 = (
    "SMC-FSM-F4-PARAM-OFF: the MMR register map exists only when the eFuse instance has "
    "lifecycle state, and smc_efuse_wrapper instantiates the controller with HAS_LC_STATE "
    "= 0, so the decode arm selecting EFUSE_MMR_REG_MAP is not elaborated and no access "
    "reaches the state or its edges."
)

F5 = (
    "SMC-FSM-F5-RESET-EDGE: the state register's reset assignment is expanded into a "
    "transition from every state, and no case arm of this FSM assigns the reset state, "
    "so the edge exists only if the block's reset is asserted while the FSM occupies "
    "that one state. The DV package grades reset behaviour through its reset leaves."
)

F6 = (
    "SMC-FSM-F6-ENABLE-EDGE: the state register loads StBusBusyHigh only on the rising "
    "edge of the monitor enable in multi-controller mode, and its disabled branch parks "
    "the register at StBusFree, so the predecessor at that edge is always StBusFree; an "
    "edge into it from any other state is an extraction artefact."
)

# (module, fsm) -> list of (class, selector). Selector None takes every point of
# the FSM; ("to", S) the uncovered transitions into S; ("state", S) the state S
# and the uncovered transitions that touch it; ("edges", (...)) exactly those
# uncovered transitions.
FSM_FACTS: "dict[tuple[str, str], list[tuple[str, tuple[str, object] | None]]]" = {
    ("telemetry_receiver", "block_index"): [(F1, None)],
    ("avsbus_controller", "cur_state"): [(F2, ("to", "AVS_IDLE")), (F5, ("to", "AVS_RESET"))],
    ("trace_axi_master", "state"): [(F3, None)],
    ("efuse_interface_controller", "efuse_reg_select"): [(F4, ("state", "EFUSE_MMR_REG_MAP"))],
    ("zeroer", "cur_state"): [(F5, ("edges", ("ST_ISSUE_ADDR->ST_IDLE",)))],
    ("efuse_shadow_regs", "efuse_sense_state_q"): [(F5, ("edges", ("StRead->StIdle",)))],
    ("i2c_bus_monitor", "state_q"): [
        (F6, ("edges", ("StBusBusyLow->StBusBusyHigh", "StBusBusyStop->StBusBusyHigh")))
    ],
    ("smc_cool_reset_wrap", "flr_counter_state"): [(F5, ("edges", ("COUNT_DOWN->IDLE",)))],
}


A3 = (
    "SMC-REGBLOCK-A3-NOREADCHANNEL: uart_16550.sv selects the write-only register map on "
    "the write channel only -- its read-channel select has no branch for that map -- so "
    "this block's AR channel is never driven and no access can produce a condition over it."
)
A4 = (
    "SMC-REGBLOCK-A4-READNEVERERRORS: in this block reg_re and reg_we are mutually "
    "exclusive, wr_err is gated on reg_we and addrmiss requires that no address hit, so a "
    "read that hits an address always sees reg_error low and the crossed term cannot occur."
)
A5 = (
    "SMC-REGBLOCK-A5-INPUTUNCONNECTED: the SMC integration leaves this block's devmode_i "
    "unconnected, so the explicit-error-on-unmapped-access term it gates never evaluates "
    "true."
)
A6 = (
    "SMC-REGBLOCK-A6-SINGLEPULSE-RETAIN: the RDL declares these fields singlepulse, so the "
    "storage holds a written one for a single cycle and the cpuif accepts no second write in "
    "that cycle; the retain row of the write-data ternary needs the storage at one while a "
    "write arrives with that lane disabled and no access produces it. Fields of the same block "
    "that keep their value between writes stay graded."
)

P1 = (
    "SMC-P1-NTRACE-OFF: the DFD top instantiates the trace wrapper with NUM_NTRACE_INST(0) "
    "and NTRACE_SUPPORT(0), so the trace sink's N-trace half has no source behind it; the "
    "conditions over its trntr signals have no stimulus that can reach them."
)

P3 = (
    "SMC-P3-WREN-TIED: the CLA drives this hardware write-enable with a constant one, so the "
    "term never reads zero and the write-data ternary it selects never takes its else arm; no "
    "software stimulus moves a tie-off."
)
P4 = (
    "SMC-P4-SINGLE-SOURCE: with NUM_NTRACE_INST(0) the trace sink has one source, so the "
    "two-source term of TrRamPendPkt*WrEn is always false and the per-way pending count, which "
    "only increments from those enables, stays at zero for the life of the design; a row that "
    "needs a TrRamPend* signal or a south-port valid asserted follows. A row that holds those "
    "signals at their constant value and turns on another term stays graded, because ordinary "
    "trace traffic reaches it."
)
P5 = (
    "SMC-P5-INSTR-TYPE-CONST: reg_wr_instr_type has no driver outside the MMR files, so the APB "
    "path only ever issues one instruction type and the other encoding is never presented."
)
# The same twenty enables under the two spellings urg reports: the source-side
# struct field in a condition, and the MMR block's flattened net in a branch.
WREN_TIED = (
    "ClactrlstatusWr.CurrentNodeWrEn|ClatimestampWr.TimestampLowerWrEn|"
    "ClatimestampconfigWr.ResyncWrEn|EapstatusWr.Node[0-3]Eap[0-3]WrEn|"
    "ClaMmrCdbgclacounter[0-3]CfgWr.(Upper)?CounterWrEn|TrdstcontrolWr.TrdstemptyWrEn|"
    "MMR_CDbgClaCtrlStatus_F_CurrentNode_WrEn|MMR_CDbgClaTimestamp_F_TimestampLower_WrEn|"
    "MMR_CDbgClaTimestampConfig_F_Resync_WrEn|MMR_CDbgEapStatus_F_Node[0-3]Eap[0-3]_WrEn|"
    "MMR_CDbgClaCounter[0-3]Cfg_F_(Upper)?Counter_WrEn"
)
P2 = (
    "SMC-P2-SKIP-TIED-OFF: smc_input_fabric and smc_output_fabric both instantiate the AXI "
    "filter with filter_skip_i tied to zero, so the skip arm of the filter decision never "
    "runs and no access can produce a condition over it."
)
P8 = (
    "SMC-P8-WREN-TIED-ZERO: the CLA assigns its MMR write structure a zero default and never "
    "names these reserved fields' write enables, so each holds zero; the enable's true arm and "
    "the then arm of the write-data ternary it selects have no stimulus. This is the converse "
    "of P3, where a constant one leaves the else arm unreachable instead."
)
# The reserved-field enables of the three CLA write structures that the source
# defaults to zero and never assigns. The MuxSel, LfsrMask and TimestampOffset
# reserved enables have no CLA output port and stay graded.
WREN_ZERO = (
    r"MMR_CDbgEapStatus_F_Rsvd3116_WrEn"
    r"|MMR_CDbgClaCtrlStatus_F_Rsvd6216_WrEn"
    r"|MMR_CDbgClaTimestampConfig_F_Rsvd1_WrEn"
)
P6 = (
    "SMC-P6-LC-STATE-OFF: smc_efuse_wrapper instantiates the eFuse with HAS_LC_STATE = 0, so "
    "the lifecycle-state arms of the shadow registers and the guard are never entered and the "
    "RMA token comparisons they hold have no access that can reach them. The fuse-sense, "
    "security-disable and image-lock terms outside those arms stay graded."
)
P7 = (
    "SMC-P7-NO-ERROR-CAP: idma_backend_wrapper elaborates the backend with ErrorCap = "
    "NO_ERROR_HANDLING, whose bypass assigns the legalizer's flush and kill inputs a constant "
    "zero, so a term that needs either of them asserted is false for the life of the design. "
    "The read and write backpressure rows of the same expressions stay graded."
)

# (file suffix, first line, last line) of the source region a fact covers, for
# where one file carries the same expression text inside and outside the region.
LC_STATE_ARM = ("efuse_shadow_regs.sv", 290, 347)


def in_region(src: str, region: "tuple[str, int, int] | None") -> bool:
    """Whether a template entry's source line falls in a fact's region."""
    if region is None:
        return True
    path, _, line = src.rpartition(":")
    name, first, last = region
    return path.endswith(name) and first <= int(line) <= last

# module -> [(class, expression pattern, term-vector pattern or None, source
# region or None)] for conditions a disabled build option or a tied-off
# integration input leaves without a source. The vector pattern pins which row
# of a multi-term expression the fact covers and the region which occurrence of
# a repeated expression, so a row an access can reach stays graded. Only
# uncovered rows are taken.
FEATURE_FACTS: "dict[str, list[tuple[str, object, object, object]]]" = {
    "trace_sink": [
        (P1, re.compile(r"\btrntr"), None, None),
        # The pending valid is the leading term: the row that turns it on is the
        # fact's, the row that leaves it off belongs to ordinary trace traffic.
        (P4, re.compile(r"^\(TrRamPendPktVld_ANY\[\d\] &"), re.compile(r"^1"), None),
        (P4, re.compile(r"^\(\(\(~\|TrRamPend\w*PktVld_ANY\)\) &"), re.compile(r"^0"), None),
        (P4, re.compile(r"^\(TrRamPend(Wr|Rd)En_ANY\[\d\] \|"), None, None),
        (P4, re.compile(r"TrRamPendPkt(North|South)WrEn_TS0"), None, None),
        (P4, re.compile(r"TrRamSouth|TR_TS_South|South_Vld"), None, None),
    ],
    "axi_filter_wrap": [(P2, re.compile(r"filter_skip_i"), None, None)],
    "cla_mmr": [
        (P3, re.compile(WREN_TIED, re.I), None, None),
        (P8, re.compile(WREN_ZERO), re.compile(r"^1$"), None),
        (P5, re.compile(r"instr_type"), None, None),
    ],
    "mmrs": [(P1, re.compile(r"ntr_sink|NTR_SINK|\bTrramstart(low|high)_Warl"), None, None)],
    "efuse_shadow_regs": [
        (
            P6,
            re.compile(r"lc_state_cur|rma_(sip|chiplet)_token_match_i|SHADOW_IDX_TRANSIENT_RMA_EN"),
            None,
            None,
        ),
        (
            P6,
            re.compile(r"write_setup_only && is_lc_state_access && apb_req_from_ac\.pstrb\[0\]"),
            None,
            None,
        ),
        (P6, re.compile(r"sim_skip_fuse_sense|security_disable_i"), None, LC_STATE_ARM),
    ],
    "efuse_guard": [
        (P6, re.compile(r"rma_(sip|chiplet)_token_match_i"), None, None),
        (P6, re.compile(r"pro_read_intf_(wr|rd)_index == '0"), None, None),
        (P6, re.compile(r"pro_read_intf_lock_lc_state_write"), re.compile(r"^01$"), None),
    ],
    "idma_legalizer_rw_axi": [
        (P7, re.compile(r"\| kill_i\)$"), re.compile(r"^01$"), None),
        (P7, re.compile(r"& \(\(!flush_i\)\)\)$"), re.compile(r"^1+0$"), None),
    ],
}
# Branch arms a feature fact also names: the else arm of a write-data ternary whose
# enable is a tied constant.
FEATURE_BRANCH_FACTS: "dict[str, list[tuple[str, object, str]]]" = {
    "cla_mmr": [
        (P3, re.compile(WREN_TIED, re.I), "0"),
        (P8, re.compile(WREN_ZERO), "1"),
    ],
    "idma_legalizer_rw_axi": [(P7, re.compile(r"^kill_i$"), "1")],
}

# PeakRDL builds a software write as storage-with-the-lane-masked OR incoming
# data, and urg scores the two operands as one row each. RETAIN is the row where
# the first operand alone carries the result: the storage holds a one and the
# write leaves that lane disabled. The row where the second operand carries it
# is a plain write of a one, which an access reaches.
RETAIN = re.compile(r"^10$")


def retain(fields: str) -> "re.Pattern[str]":
    """The retain operand of the named `REG.FIELD` alternation."""
    return re.compile(r"^\(\(field_storage\.(?:" + fields + r")\.value & \(\(~decoded_wr_biten\[")


# The singlepulse fields of the I2C map, named one at a time: seven siblings of
# INTR_TEST are plain rw fields that keep their value between writes, and
# SMBUS_CTRL carries a second field spelled SMBALERT that is one of them.
I2C_SINGLEPULSE = (
    r"INTR_TEST\.(RX_OVERFLOW|SCL_INTERFERENCE|SDA_INTERFERENCE|SDA_UNSTABLE"
    r"|STRETCH_TIMEOUT|CMD_COMPLETE|UNEXP_STOP|HOST_TIMEOUT|SMBALERT"
    r"|(CONTROLLER|TARGET)_(TX|RX)_FIFO_ERROR)"
    r"|FIFO_CTRL\.(RXRST|FMTRST|ACQRST|TXRST)"
    r"|TARGET_ACK_CTRL\.NACK"
)


# module -> [(class, expression pattern, term-vector pattern or None)]. These
# are facts about one block, checked against its own source, not about a
# family. The vector pattern pins which row of a multi-term expression the
# fact covers, so a sibling row that an access can reach stays graded.
EXTRA_FACTS: "dict[str, list[tuple[str, object, object]]]" = {
    "uart_16550_main_wo_reg": [
        (A3, re.compile(r"arvalid|ar_accept|prev_was_rd"), None),
        (A6, retain(r"FCR\.(RCVR|XMIT)_FIFO_RESET"), RETAIN),
    ],
    "idma_reg64_2d_reg_top": [
        (A4, re.compile(r"addr_hit\[\d+\]\s*&\s*reg_re"), re.compile(r"^110$")),
        (A5, re.compile(r"devmode_i"), re.compile(r"^1")),
    ],
    "avsbus_controller_reg": [
        (A6, retain(r"AVS_INTERRUPT_CLEAR\.\w+|AVS_CFG_1\.FORCE_SLAVE_RESYNC_OPERATION"), RETAIN),
    ],
    "telemetry_receiver_reg": [
        (A6, retain(r"CTRL\.(BUFFER_POP|TELEMETRY_RX_FLUSH)|INTR_TEST\.MISSING_LAST"), RETAIN),
    ],
    "system_timer_octs_reg": [(A6, retain(r"TIMER_START\.START"), RETAIN)],
    "i2c_reg": [(A6, retain(I2C_SINGLEPULSE), RETAIN)],
    "log_engine_reg": [(A6, retain(r"INTR_TEST\.LOG_(FETCH|WRITE)_ERR"), RETAIN)],
    "efuse_interface_ctrl_reg": [
        (
            A6,
            retain(
                r"EFUSE_INTERFACE_CTRL_STATUS\.\w+_error_clear"
                r"|EFUSE_PROGRAM_CTRL\.efuse_program_go"
                r"|EFUSE_READ_CTRL\.efuse_read_go"
            ),
            RETAIN,
        )
    ],
    "cpu_ctrl_reg": [(A6, retain(r"WDT_TIMEOUT_RESET\.reset_cycle_count_\d"), RETAIN)],
}


def uncovered_rows(modinfo: Path) -> dict[tuple[str, str], set[str]]:
    """(module, expression) -> set of term vectors the report marks Not Covered.

    Below each EXPRESSION the report scores its operands again under their own
    SUB-EXPRESSION headings. Those rows are the operand's, not the expression's,
    and a vector uncovered for an operand is often covered for the expression
    that contains it, so `expr` is None across a SUB-EXPRESSION table and its
    rows are dropped. An empty `expr` is a different state: it is the long XOR
    network urg prints as a numbered term list instead of an expression.
    """
    rows: dict[tuple[str, str], set[str]] = {}
    module = ""
    expr: str | None = ""
    terms: list[str] = []
    in_cond = False
    for line in modinfo.read_text(errors="replace").splitlines():
        m = re.match(r"^(\w+) Coverage for Module : (\S+)", line)
        if m:
            in_cond = m.group(1) == "Cond"
            module = m.group(2).split("(")[0]
            expr = ""
            terms = []
            continue
        if not in_cond:
            continue
        if re.match(r"^\s*SUB-EXPRESSION", line):
            expr = None
            terms = []
            continue
        m = re.match(r"^\s*EXPRESSION\s*(.*)$", line)
        if m:
            expr = m.group(1).strip()
            terms = []
            continue
        # A long XOR network is listed one term per row under "Number  Term".
        m = re.match(r"^\s*\d+\s+(\S+)\s*(\^?)\s*$", line)
        if m and expr == "":
            terms.append(m.group(1).rstrip(")"))
            if not m.group(2):
                expr = "(" + " ^ ".join(terms) + ")"
            continue
        m = re.match(r"^\s*((?:[01]\s+)+)Not Covered", line)
        if m and expr:
            rows.setdefault((module, expr), set()).add(m.group(1).replace(" ", ""))
    return rows


class Section:
    def __init__(self, checksum: str, module: str) -> None:
        self.checksum = checksum
        self.module = module
        self.entries: list[tuple[str, str]] = []  # (source line annotation, entry)


def parse(template: Path) -> dict[str, Section]:
    sections: dict[str, Section] = {}
    checksum = ""
    current: Section | None = None
    src = ""
    for line in template.read_text(errors="replace").splitlines():
        m = CHECKSUM_RE.match(line)
        if m:
            checksum = m.group(1)
            continue
        m = MODULE_RE.match(line)
        if m:
            current = sections.setdefault(m.group(1), Section(checksum, m.group(1)))
            continue
        m = FILE_RE.match(line)
        if m:
            src = f"{m.group(1)}:{m.group(2)}"
            continue
        m = ENTRY_RE.match(line)
        if m and current is not None:
            current.entries.append((src, m.group(1)))
    return sections


def regblock_facts(module: str, source: str) -> tuple[bool, bool]:
    """(stall hardwired, no error decode) for a generated register block source."""
    path = Path(source.split(":")[0])
    if "/regs/gen/sv/" not in str(path) or not path.is_file():
        return (False, False)
    text = path.read_text(errors="replace")
    stall0 = bool(re.search(r"assign cpuif_req_stall_rd = '0", text))
    noerr = "No valid address check" in text
    return (stall0, noerr)


def select_regblock(entry: str, stall0: bool, noerr: bool, uncovered: set[str]) -> str | None:
    """Return the class an entry belongs to, or None when it stays graded."""
    m = COND_ROW_RE.match(entry)
    if m:
        expr, vec = m.group(2), m.group(4)
        if vec not in uncovered:
            return None
        if stall0 and (HANDSHAKE_RE.search(entry) or STALL_RE.search(expr)):
            return A1
        if noerr and ERROR_RE.search(expr):
            return A2
        return None
    m = BRANCH_ROW_RE.match(entry)
    if m:
        cond, direction = m.group(2), m.group(5)
        if direction != "1":
            return None
        if stall0 and STALL_RE.search(cond):
            return A1
        if noerr and ERROR_RE.search(cond):
            return A2
    return None


def extra_entries(templates: dict[str, dict[str, Section]], module: str) -> list[tuple[str, str]]:
    """Every condition and branch template entry of a module named in EXTRA_FACTS."""
    if module not in EXTRA_FACTS:
        return []
    out: list[tuple[str, str]] = []
    for metric in ("cond", "branch"):
        section = templates[metric].get(module)
        if section is not None:
            out += section.entries
    return out


def select_extra(module: str, entry: str, uncovered: dict[tuple[str, str], set[str]]) -> str | None:
    """Return the per-block class an uncovered entry belongs to, or None."""
    m = COND_ROW_RE.match(entry)
    vec = None
    if m:
        expr, vec = m.group(2), m.group(4)
        if vec not in uncovered.get((module, expr), set()):
            return None
    else:
        m = BRANCH_ROW_RE.match(entry)
        if m is None or m.group(5) != "1":
            return None
        expr = m.group(2)
    for reason, pattern, vector in EXTRA_FACTS[module]:
        if not pattern.search(expr):
            continue
        if vector is not None and (vec is None or not vector.match(vec)):
            continue
        return reason
    return None


def render_regblock(
    templates: dict[str, dict[str, Section]], uncovered: dict[tuple[str, str], set[str]]
) -> tuple[str, int]:
    out = [
        "// SPDX-License-Identifier: Apache-2.0",
        "// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.",
        "//==================================================",
        "// SMC VCS coverage exclusions -- PeakRDL regblock structural facts.",
        "// Format Version: 2",
        "// ExclMode: default",
        "//",
        "// Generated by gen_smc_cov_exclusions.py from urg's exclusion templates and",
        "// the merged report; regenerate rather than edit. Only rows and branch",
        "// directions the report marks uncovered are listed. The generator's",
        "// docstring and the ANNOTATION before each block state the two facts",
        "// (A1 NO-STALL, A2 NO-ERROR) and which blocks each applies to.",
        "//==================================================",
    ]
    modules = sorted({m for t in templates.values() for m in t})
    count = 0
    for module in modules:
        block: list[tuple[str, str]] = []
        facts_cache: dict[str, tuple[bool, bool]] = {}
        checksum = ""
        for metric in ("cond", "branch"):
            section = templates[metric].get(module)
            if section is None:
                continue
            checksum = checksum or section.checksum
            for src, entry in section.entries:
                stall0, noerr = facts_cache.setdefault(
                    src.split(":")[0], regblock_facts(module, src)
                )
                if not (stall0 or noerr):
                    continue
                m = COND_ROW_RE.match(entry)
                rows = uncovered.get((module, m.group(2)), set()) if m else set()
                reason = select_regblock(entry, stall0, noerr, rows)
                if reason:
                    block.append((reason, entry))
        for src, entry in extra_entries(templates, module):
            reason = select_extra(module, entry, uncovered)
            if reason:
                block.append((reason, entry))
        if not block:
            continue
        out += ["", f"CHECKSUM: {checksum}"]
        for reason in (A1, A2, A3, A4, A5, A6):
            if any(r == reason for r, _ in block):
                out.append(f'ANNOTATION: "{reason}"')
        out.append(f"MODULE: {module}")
        out += [e for _, e in block]
        count += len(block)
    return "\n".join(out) + "\n", count


def render_xor(
    templates: dict[str, dict[str, Section]], uncovered: dict[tuple[str, str], set[str]]
) -> tuple[str, int]:
    out = [
        "// SPDX-License-Identifier: Apache-2.0",
        "// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.",
        "//==================================================",
        "// SMC VCS coverage exclusions -- XOR reduction networks (CRC, parity).",
        "// Format Version: 2",
        "// ExclMode: default",
        "//",
        "// Generated by gen_smc_cov_exclusions.py from urg's condition template and",
        "// the merged report; regenerate rather than edit. Only conditions that are",
        "// an XOR of four or more terms are listed, and only their uncovered rows;",
        "// the network's output is what the tests compare.",
        "//==================================================",
    ]
    count = 0
    for module, section in sorted(templates["cond"].items()):
        rows = []
        for _, entry in section.entries:
            m = COND_ROW_RE.match(entry)
            if m is None:
                continue
            expr, vec = m.group(2), m.group(4)
            if XOR_TERM_RE.match(expr) and vec in uncovered.get((module, expr), set()):
                rows.append(entry)
        if rows:
            out += ["", f"CHECKSUM: {section.checksum}", f'ANNOTATION: "{X1}"', f"MODULE: {module}"]
            out += rows
            count += len(rows)
    return "\n".join(out) + "\n", count


def uncovered_fsm(modinfo: Path) -> dict[tuple[str, str], set[str]]:
    """(module, fsm) -> states and "a->b" transitions the report marks Not Covered."""
    out: dict[tuple[str, str], set[str]] = {}
    module = fsm = ""
    in_fsm = False
    for line in modinfo.read_text(errors="replace").splitlines():
        m = re.match(r"^(\w+) Coverage for (Module|Instance) : (\S+)", line)
        if m:
            in_fsm = m.group(1) == "FSM" and m.group(2) == "Module"
            module = m.group(3).split("(")[0]
            continue
        if not in_fsm:
            continue
        m = re.match(r"^Summary for FSM :: (\S+)", line)
        if m:
            fsm = m.group(1)
            continue
        m = re.match(r"^(\S+)\s+\S+\s+Not Covered", line)
        if m and fsm:
            out.setdefault((module, fsm), set()).add(m.group(1))
    return out


def render_fsm(
    templates: dict[str, dict[str, Section]], uncovered: dict[tuple[str, str], set[str]]
) -> tuple[str, int]:
    out = [
        "// SPDX-License-Identifier: Apache-2.0",
        "// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.",
        "//==================================================",
        "// SMC VCS coverage exclusions -- FSM extraction facts.",
        "// Format Version: 2",
        "// ExclMode: default",
        "//",
        "// Generated by gen_smc_cov_exclusions.py from urg's FSM template and the",
        "// merged report; regenerate rather than edit. F1 and F3 take every point of",
        "// a state variable that is not a reachable control FSM; F2 takes only the",
        "// uncovered edges the always_comb default contributes; F4 takes a state whose",
        "// decode arm a parameter leaves unelaborated, and F5 the uncovered edges that",
        "// exist only as a state register's reset assignment. The generator's docstring",
        "// and the ANNOTATION before each block state the facts.",
        "//==================================================",
    ]
    count = 0
    for module, section in sorted(templates["fsm"].items()):
        fsm = ""
        block: list[tuple[str, str]] = []
        for _, entry in section.entries:
            if entry.startswith("Fsm "):
                fsm = entry.split()[1]
                if (module, fsm) in FSM_FACTS:
                    block.append(("", entry))
                continue
            facts = FSM_FACTS.get((module, fsm))
            m = FSM_ENTRY_RE.match(entry)
            if not facts or m is None:
                continue
            kind, src, dst = m.group(1), m.group(2), m.group(3)
            missing = uncovered.get((module, fsm), set())
            edge = f"{src}->{dst}"
            for reason, selector in facts:
                if selector is None:
                    block.append((reason, entry))
                    break
                mode, target = selector
                if kind == "State":
                    if mode == "state" and src == target:
                        block.append((reason, entry))
                        break
                    continue
                if edge not in missing:
                    continue
                if (
                    (mode == "to" and dst == target)
                    or (mode == "state" and target in (src, dst))
                    or (mode == "edges" and edge in target)
                ):
                    block.append((reason, entry))
                    break
        if not any(r for r, _ in block):
            continue
        out += ["", f"CHECKSUM: {section.checksum}"]
        for reason in (F1, F2, F3, F4, F5, F6):
            if any(r == reason for r, _ in block):
                out.append(f'ANNOTATION: "{reason}"')
        out.append(f"MODULE: {module}")
        out += [e for _, e in block]
        count += sum(1 for r, _ in block if r)
    return "\n".join(out) + "\n", count


def render_feature(
    templates: dict[str, dict[str, Section]], uncovered: dict[tuple[str, str], set[str]]
) -> tuple[str, int]:
    out = [
        "// SPDX-License-Identifier: Apache-2.0",
        "// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.",
        "//==================================================",
        "// SMC VCS coverage exclusions -- features the build leaves out.",
        "// Format Version: 2",
        "// ExclMode: default",
        "//",
        "// Generated by gen_smc_cov_exclusions.py from urg's condition template and",
        "// the merged report; regenerate rather than edit. Only uncovered rows over",
        "// the signals of a feature the integration instantiates with zero instances",
        "// are listed; the ANNOTATION before each block states the fact.",
        "//==================================================",
    ]
    count = 0
    modules = sorted(set(FEATURE_FACTS) | set(FEATURE_BRANCH_FACTS))
    for module in modules:
        block: list[tuple[str, str]] = []
        checksum = ""
        section = templates["cond"].get(module)
        if section is not None:
            checksum = section.checksum
            for src, entry in section.entries:
                m = COND_ROW_RE.match(entry)
                if m is None:
                    continue
                expr, vec = m.group(2), m.group(4)
                if vec not in uncovered.get((module, expr), set()):
                    continue
                for reason, pattern, vector, region in FEATURE_FACTS.get(module, []):
                    if not pattern.search(expr):
                        continue
                    if vector is not None and not vector.match(vec):
                        continue
                    if not in_region(src, region):
                        continue
                    block.append((reason, entry))
                    break
        bsection = templates["branch"].get(module)
        if bsection is not None:
            checksum = checksum or bsection.checksum
            for _, entry in bsection.entries:
                m = BRANCH_ROW_RE.match(entry)
                if m is None:
                    continue
                cond, direction = m.group(2), m.group(5)
                for reason, pattern, want in FEATURE_BRANCH_FACTS.get(module, []):
                    if direction == want and pattern.search(cond):
                        block.append((reason, entry))
                        break
        if not block:
            continue
        out += ["", f"CHECKSUM: {checksum}"]
        for reason in (P1, P2, P3, P4, P5, P6, P7, P8):
            if any(r == reason for r, _ in block):
                out.append(f'ANNOTATION: "{reason}"')
        out.append(f"MODULE: {module}")
        out += [e for _, e in block]
        count += len(block)
    return "\n".join(out) + "\n", count


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("template_dir", type=Path, help="holds fullexclude_module.{cond,branch,fsm}")
    ap.add_argument("modinfo", type=Path, help="the run's cov/report/modinfo.txt")
    ap.add_argument("--check", action="store_true", help="fail if the committed files are stale")
    args = ap.parse_args()
    templates = {
        m: parse(args.template_dir / f"fullexclude_module.{m}") for m in ("cond", "branch", "fsm")
    }
    uncovered = uncovered_rows(args.modinfo)
    reg_text, reg_n = render_regblock(templates, uncovered)
    xor_text, xor_n = render_xor(templates, uncovered)
    fsm_text, fsm_n = render_fsm(templates, uncovered_fsm(args.modinfo))
    feat_text, feat_n = render_feature(templates, uncovered)
    outputs = (
        (REGBLOCK_OUT, reg_text),
        (XOR_OUT, xor_text),
        (FSM_OUT, fsm_text),
        (FEATURE_OUT, feat_text),
    )
    if args.check:
        stale = [p for p, t in outputs if not p.is_file() or p.read_text() != t]
        for p in stale:
            print(f"{p} is stale; rerun without --check", file=sys.stderr)
        return 1 if stale else 0
    for p, t in outputs:
        p.write_text(t)
    print(
        f"wrote {REGBLOCK_OUT.name}: {reg_n} entries; {XOR_OUT.name}: {xor_n} entries; "
        f"{FSM_OUT.name}: {fsm_n} entries; {FEATURE_OUT.name}: {feat_n} entries"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
