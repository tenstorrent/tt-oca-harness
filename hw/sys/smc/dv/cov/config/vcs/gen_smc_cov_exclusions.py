#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Write the SMC VCS coverage exclusion files from urg's exclusion templates.

Two structural facts of the compiled design leave coverage points that no
access from this bench can reach, and SEP records the same facts in
`hw/sys/sep/dv/cov/config/vcs/sep_regblock_exclusions.el`:

* A1 NO-STALL: a PeakRDL register block whose cpuif has no external
  registers hardwires `cpuif_req_stall_rd` and `cpuif_req_stall_wr` to zero,
  so the stall branches of the request path never execute and no row of a
  stall sub-expression that needs a stall input at one occurs. The handshake
  still sees valid without ready once two requests are in flight.
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
* A5 INPUT-UNCONNECTED: the same block's `devmode_i` is tied to zero by
  the SMC integration, so the explicit-error-on-unmapped-access term it gates
  never evaluates true.

A sixth belongs to the register specification rather than to the generated code:

* A6 SINGLEPULSE-RETAIN: a field the RDL declares `singlepulse` holds a written
  one for a single cycle, and the cpuif accepts no second write in that cycle,
  so the storage reads zero at every write the field sees. The retain row of the
  write-data ternary, and each row of its retain operand that asks for the
  storage at one, needs the storage at one during a write, and no access
  produces it.

One class is the bench's own, and is marked as such rather than dressed as a
property of the design:

* B1 PARTIAL-LANE-WRITE: a field that keeps its value between writes does take
  that same retain row when a write leaves one lane disabled while it holds a
  one. The SMC AXI agent writes whole 32-bit words, so on a block whose cpuif
  is no wider than that every write has every lane on, and every row of a
  field's software-write branch that needs a lane off, whether the retain row
  or a row of the retain or write-data operand, is uncovered for want of an
  agent rather than for want of a path. On a block with a wider cpuif the same
  agent issues a half-word write, which does leave lanes disabled, so those rows
  stay graded. The
  clear-on-write row of a W1C field is a different expression and a leaf covers
  it.

Two facts are the integration's: the DFD top instantiates its trace wrapper
with `NUM_NTRACE_INST(0)` and `NTRACE_SUPPORT(0)`, so every N-trace signal of
the trace sink reads zero and a row asking one of them for a one cannot occur
(P1 NTRACE-OFF, decided against the report's term list rather than a name
prefix, plus the NTR-sink MMR decode of `mmrs`); both SMC fabrics tie the AXI
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

Two are UART logic facts. Each holding register and parity FIFO stores its
data with `~^data` beside it and a redundant pointer count, so the storage
self-check `~^{parity, data}` reads one only on corrupted storage (P11
UART-SELF-CHECK); and `break_err` is formed as the framing error of an all-zero
frame and stored beside that framing error, so it never appears alone (P12
BREAK-IMPLIES-FRAMING).

One more is the geometry the parameters fix: a bank spans 32 bytes and a VLT
packet is 10, the header being `8 + DEBUG_SIGNAL_WIDTH/8` bits wide on top of a
64-bit debug bus, so no single write can start at or below a bank's first byte
and end past its last and `target_write_byte_boundary_crosses_bank_range` is
false for the life of the design (P10 PACKET-SHORTER-THAN-BANK).

`core_logic_analyzer` derives `DBG_SIGNAL_CONFIG` from
`DEBUG_SIGNAL_WIDTH == 128` and `smc_dfd_wrap` passes 64, so the
`cla_snapshot_mmr_hi_blk` generate that drives every snapshot `Hi` write enable
is not elaborated and each holds zero (P9 DEBUG-WIDTH-64). The `Lo` halves are
assigned outside that generate, and the report agrees: all sixteen `Hi` true
arms are uncovered and all sixteen `Lo` true arms are covered.

The CLA holds a second write-enable fact, the converse of P3:
`MMR_CDbgEapStatus_F_Rsvd3116_WrEn` is its write structure's field and nothing
else, and the CLA gives that structure a zero default and never names the
field, so the enable holds zero and the then arm of the ternary it selects is
unreachable (P8 WREN-TIED-ZERO). It is the only reserved-field enable of the
block that qualifies: `ClaCtrlStatus`, `ClaTimestampConfig`, `MuxSelHi`,
`MuxSelLo`, `LfsrMask` and `ClaTimestampOffset` each add a
`reg_write & reg_addr` term, which a software write to the register asserts.

A third fact is not a register block's: a CRC or parity network is an XOR
reduction, and condition coverage enumerates 2^n input combinations of it.
The X1 XOR-NETWORK class names those expressions.

Three FSM facts follow from the source rather than from any access. urg's FSM
score counts transitions, and the extractor lists every assignment to the
state variable as a transition:

* F2 DEFAULT: `avsbus_controller.cur_state` has `next_state = AVS_IDLE` as the
  always_comb default, which the extractor reads as an edge from every state
  to AVS_IDLE; every case arm assigns next_state, so the default never fires.
* F3 TIEOFF: `smc_dfd_wrap` ties every `m_trc_axi_*` response input to zero,
  so `trace_axi_master` never completes a response handshake and cannot pass
  REQ_HANDSHAKE. The request it issues on `valid_i` needs no response, so
  RESET_VALUE, REQ_HANDSHAKE and the edge between them stay graded.
* F4 PARAM-OFF: `efuse_interface_controller.efuse_reg_select` reaches
  EFUSE_MMR_REG_MAP only when the instance has lifecycle state, and
  `smc_efuse_wrapper` instantiates it with `HAS_LC_STATE = 0`, so the decode
  arm that selects the state is not elaborated.
* F6 ENABLE-EDGE: a state register that loads one state on an enable rising
  edge takes whatever its disabled branch parked it at as the predecessor of
  that edge, so a state no case arm sends to the loaded state cannot precede
  it, and an edge from such a state is the same extraction artefact as F2. A
  state whose own arm assigns the loaded state reaches it in the ordinary
  sequence and stays graded.
* F7 SCL-HELD-LOW: the bus monitor raises `start_detect` only on a falling SDA
  while SCL is high on two samples and clears its pending flag whenever SCL is
  low, so a target state driving `scl_d = 1'b0` holds the wired-AND SCL low for
  its duration and the override to AcquireStart cannot fire from it.
* F8 NO-INTERFERENCE: `sda_released_but_low` is gated on `scl_sync` and the
  interference terms on the transmitting flag, so a state that leaves
  `transmitting_o` at zero, or holds SCL low, makes the term identically false
  and the override it feeds cannot fire from it. A state whose own arm assigns
  the same destination for another reason keeps that edge graded.
* B2 UNAIMED-OVERRIDE, the bench's own like B1: the same fan-in overrides are
  taken on bus events and register writes that the SMC bench, driving the bus
  through the pads and the registers, cannot place in a chosen one of the
  sub-bit states the block's counters time. The edge an override would take
  out of a given state is uncovered for want of that aim. A bench that can
  place a bus event or a write in a chosen sub-bit state retires the class. An
  edge the source state's own case arm assigns, read from the FSM source at
  generation time, stays graded.
* F9 LOOP-INDEX-EXTRACTION, a property of the extraction: `block_index` is a
  loop index local to an `always_comb` with no flop behind it, so the values
  and transitions the extractor records for it are sampled from a
  combinational loop and none is a state of the design. Only its uncovered
  points are written.
* B4 SRAM-AUTOINIT-BYPASSED, the bench's own: the CPU scratch SRAM zeroing is a
  hardware sequence the SMC testbench top bypasses by tying
  `smc_disable_sram_auto_init_i` high, so MEM_ZERO_BUSY is never entered. A
  bench that deasserts the input retires the class.
* F5 RESET-EDGE: a state register's reset assignment is expanded into a
  transition from every state. Where no case arm assigns the reset state, the
  only way to cover such an edge is to assert the block's reset while the FSM
  occupies that one state. Reset behaviour is graded by the reset tests, not
  by landing a reset in each protocol state.

Seven more tie-offs and parameters decide branch decisions rather than condition
rows. The DFD's gated functional clamps are each a constant OR of two tied
inputs (P13 CLAMP-TIED); its JTAG MMR requester's valid is tied to zero (P14
JTAG-MMR-TIED); the eFuse's secure test mode input is tied to zero (P15
SECURE-TM-TIED); `mmrs` derives its NTR and DST sink enables from parameters
(P16 SINK-ENABLE-CONST); and the trace sink has one core (P17 ONE-TRACE-CORE), and the AVS controller ties its own TDR post-divider
override to zero (P18 TDR-OVERRIDE-TIED). The DFD top ties the trace sink's
N-trace RAM read enable to zero (P19 NTR-RAM-READ-TIED), and a P1 decision over
N-trace signals alone, a comparison included, holds the value the tie-off
gives it.
The I2C FSMs reload their counter by an enumerated select assigned only its
named values, and the target pairs its no-delay select only with no reload, so
those case items never execute (P20 TCOUNT-SELECT-PAIRED).
The DFD wrapper also ties the DFD top's critical-signal hold, DST clock disable,
timestamp input and sdtrig control (P22 DFD-CONTROL-TIED), and the bench ties the
CLA crosstrigger and TDR clock-stop inputs (B8 DFD-BENCH-INPUTS-TIED). The signals
these classes hold decide condition rows as well as branch paths, operand tables
included.
A module's held signals are also tried together, each comparison over N-trace
signals alone at its tied value, so the trace sink's N-trace read path and its
pending buffer, and the MMR fabric's JTAG and NTR-sink paths, are read as the
facts that hold them.

Four more are the register blocks' own. Where an integration acks every
external register in the cycle it is requested, the pending flag never sets and
the stalls hold zero (A8 EXTERNAL-ACK-SAME-CYCLE); two single-register blocks
only ever see address zero (A9 ADDRESS-FIXED); the main UART map has no external
write ack (C3 NO-EXTERNAL-WRITE); and a read-only or write-only register's strobe
or external req carries its direction, in the block and in the logic that
consumes the req (C4 STROBE-CARRIES-DIRECTION).
The bench ties the four DFX status inputs the boot sequencer waits on high, so
the input-low arms of their sticky fields have no stimulus (B7
DFX-INPUTS-TIED, the bench's own).

One more belongs to the bench and its policy: the eFuse's simulation-only
`+skip_fuse_sense` bypass replaces the sensed fuse image, the DV policy forbids
it as evidence, and no SMC leaf passes it (B6 SIM-ONLY-FUSE-BYPASS). A policy
change admitting the plusarg retires the class.
P1, P4, P6, F3 and A1 read branch paths as well as rows, by the same signals.

Two regblock facts are PeakRDL's own. A field the RDL declares singlepulse sets
its load_next on every arm, so the path of its flop that skips the load never
runs (A7 SINGLEPULSE-LOADS); and the response logic tests each ack alone inside
a test of the two ORed, so the path with the OR true and both acks false is a
contradiction urg lists as a path (C1 CONTRADICTORY-PATH).

Input is the set of templates urg writes for the merged database::

    urg -dir <run dir>/cov/merged.vdb -dump full_exclusions cond+branch+fsm -report <dir>

which leaves fullexclude_module.{cond,branch,fsm} in the working directory.
Every checksum and entry text below comes from those templates.

Only points the merged report marks uncovered are written, rows, branch arms
and FSM states and transitions alike, so a reachable point is never hidden by a
pattern. The report scores each operand of a condition again beneath it, and
the classes that take operand rows pair each template point with its report
table within its own source line, since the operand of a write has the same
text in every bit-0 field of a block. A condition vector is read from the report's EXPRESSION table alone
and a branch arm from the table of the construct at that source line. Where
the report scores a construct as paths through several decisions, as it does
for a case statement or an else-if chain, each path is read whole: the decision
columns are read from the annotated source, the path is paired with its
template entry by its column values, and it is written only when one of its own
decisions is out of reach under a class's fact, or when its decisions have no
common solution (C1). A comparison is one opaque truth value to that test, so
two bit fields are never read as one. The rule is a backstop, not the argument: a class
states a fact, and the fact has to be narrow enough that the pattern would
never have named a reachable point in the first place. The report has to be the one urg
wrote without an exclusion file: the runner keeps it as
`<run dir>/cov/report_raw/modinfo.txt` beside the effective report, and a row
the effective report already shows as `Excluded` would otherwise drop out of
the regenerated file.

    python3 gen_smc_cov_exclusions.py <template dir> <run dir>/cov/report_raw/modinfo.txt
    python3 gen_smc_cov_exclusions.py <template dir> <modinfo.txt> --check
"""

from __future__ import annotations

import argparse
import itertools
import re
import sys
from pathlib import Path
from typing import NamedTuple

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
STALL_RE = re.compile(r"cpuif_req_stall")
STALL_OPERAND = re.compile(r"^cpuif_req_stall_(?:rd|wr)\b")
ERROR_RE = re.compile(r"decoded_err|cpuif_wr_err|cpuif_rd_err|readback_err|axil_resp_buffer_err")
XOR_TERM_RE = re.compile(r"^\((?:[A-Za-z_][\w\[\]\.:]*\s*\^\s*){3,}[A-Za-z_][\w\[\]\.:]*\)")
COND_ROW_RE = re.compile(r'^(Condition \d+ "\d+" "(.*) 1 -1") \((\d+) "([01]+)"\)$')
BRANCH_ROW_RE = re.compile(r'^(Branch \d+ "\d+" "(.*)") \((\d+)\) "(.*) (1|0)"$')

A1 = (
    "SMC-REGBLOCK-A1-NOSTALL: the PeakRDL cpuif of this block hardwires "
    "cpuif_req_stall_rd and cpuif_req_stall_wr to zero, so the stall branches of the "
    "request path never execute and no row of a stall sub-expression that needs a stall "
    "input at one has an access that can produce it. The handshake's valid-without-ready "
    "rows stay graded: with two requests in flight the cpuif holds the next one, and its "
    "ready drops."
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
F2 = (
    "SMC-FSM-F2-DEFAULT: next_state = AVS_IDLE is the always_comb default of the protocol FSM, "
    "which the extractor lists as a transition from every state; every state has a case arm and "
    "every arm assigns next_state, so the default never fires. The three states whose own arm "
    "assigns AVS_IDLE reach it in the ordinary sequence and stay graded."
)
F3 = (
    "SMC-FSM-F3-TIEOFF: smc_dfd_wrap ties every m_trc_axi_* response input to zero, so the "
    "trace write master never completes a response handshake and cannot pass REQ_HANDSHAKE; "
    "the states an aw_ready, w_ready or b_valid is needed to enter, and the edges touching "
    "them, have no stimulus. The request the master issues on valid_i is reachable, so "
    "RESET_VALUE, REQ_HANDSHAKE and the edge between them stay graded."
)
F4 = (
    "SMC-FSM-F4-PARAM-OFF: the MMR register map exists only when the eFuse instance has "
    "lifecycle state, and smc_efuse_wrapper instantiates the controller with HAS_LC_STATE "
    "= 0, so the decode arm selecting EFUSE_MMR_REG_MAP is not elaborated and no access "
    "reaches the state or its edges."
)

F5 = (
    "SMC-FSM-F5-RESET-EDGE: the state register's reset assignment is expanded into a "
    "transition from every state, and no case arm of the source state assigns the reset "
    "state, so the edge exists only if the block's reset is asserted while the FSM occupies "
    "that one state. The DV package grades reset behaviour through its reset leaves."
)

F6 = (
    "SMC-FSM-F6-ENABLE-EDGE: the monitor enters StBusBusyHigh from the StBusBusyLow arm on an "
    "idle bus, and from the rising edge of the monitor enable in multi-controller mode, where "
    "the disabled branch has already parked the register at StBusFree; StBusBusyStop has no arm "
    "to StBusBusyHigh and cannot be the register's value at that edge, so an edge from there is "
    "an extraction artefact. The edge from StBusBusyLow is the ordinary sequence and stays "
    "graded."
)

F7 = (
    "SMC-FSM-F7-SCL-HELD-LOW: the bus monitor raises start_detect only on a falling SDA while "
    "SCL is high on two samples, and clears the pending flag whenever SCL is low, so a target "
    "state that drives scl_d = 1'b0 holds the wired-AND SCL low for its whole duration and "
    "start_detect_i cannot rise in it. The fan-in override that takes the FSM to AcquireStart "
    "cannot fire from such a state."
)
F8 = (
    "SMC-FSM-F8-NO-INTERFERENCE: sda_released_but_low is gated on scl_sync, and the "
    "interference and arbitration-lost terms built on it are gated on the transmitting flag, "
    "so from a state whose output block leaves transmitting_o at zero, or that drives scl_d "
    "low, the term is identically false and the fan-in override it feeds cannot fire from that "
    "state. A state whose own case arm assigns the same destination for another reason is not "
    "named here."
)

B2 = (
    "SMC-FSM-B2-UNAIMED-OVERRIDE: a property of this bench, not of the design. The I2C "
    "FSMs end their next-state logic with fan-in overrides taken on a bus event or a register "
    "write: start detect to AcquireStart; stop detect, bus timeout or target disable to Idle; "
    "arbitration loss to WaitForStop; controller interference or a failed symbol to Idle. The "
    "states those overrides leave are timed below one bit by the block's own counters, and "
    "the SMC bench drives the bus through the pads and the registers, so it cannot place a "
    "bus event or a write in a chosen one of them; the edge an override would take out of a "
    "given state is uncovered for want of that aim. A bench that can place a bus event or a "
    "register write in a chosen sub-bit state retires the class. An edge the source state's "
    "own case arm assigns is reachable another way and stays graded, and F7 and F8 name the "
    "edges the design itself forbids."
)
F9 = (
    "SMC-FSM-F9-LOOP-INDEX-EXTRACTION: a property of the extraction, not of the design. "
    "block_index is a loop index local to an always_comb, set at the top of the block and "
    "walked by the for loop over the message's counters, with no flop behind it. The extractor "
    "reports it as an FSM because it is state-shaped, and the values and transitions it "
    "records are whichever it samples from that combinational loop; none of them is a state or "
    "a transition of the design. Only the points the report marks uncovered are written, so "
    "the sampled values it did record stay in the score."
)
B4 = (
    "SMC-FSM-B4-SRAM-AUTOINIT-BYPASSED: a property of this bench, not of the design. The CPU "
    "scratch SRAM is zeroed by a hardware sequence that runs after its reset unless "
    "smc_disable_sram_auto_init_i is high, and the SMC testbench top ties that input high, so "
    "the sequence goes from MEM_ZERO_IDLE straight to MEM_ZERO_DONE and MEM_ZERO_BUSY is never "
    "entered. A bench that deasserts the input runs the sequence and retires the class."
)
ARM_LABEL = re.compile(r"^(\s+)([A-Za-z_]\w*)\s*:\s*begin\b")
STATE_ASSIGN = re.compile(r"\bstate_d\s*=\s*(\w+)")
_ARMS: dict[tuple[str, str], frozenset[str]] = {}


def arms_assigning(source: str, dst: str) -> frozenset[str]:
    """The states whose own case arm in an FSM source assigns state_d = dst.

    Only assignments inside a `unique case (state_q)` arm count; the fan-in
    overrides after the `endcase` are what B2 is about, so they are not an arm.
    """
    path = Path(source.rpartition(":")[0])
    key = (str(path), dst)
    if key in _ARMS:
        return _ARMS[key]
    if not path.is_file():
        raise SystemExit(f"{path} not found: the FSM source the template names must be readable")
    arms: set[str] = set()
    case_indent: int | None = None
    arm = ""
    for line in path.read_text(errors="replace").splitlines():
        if case_indent is None:
            m = re.match(r"^(\s*)unique case \(state_q\)", line)
            if m:
                case_indent, arm = len(m.group(1)), ""
            continue
        if line.strip().startswith("endcase") and len(line) - len(line.lstrip()) == case_indent:
            case_indent = None
            continue
        m = ARM_LABEL.match(line)
        if m and len(m.group(1)) == case_indent + 2:
            arm = m.group(2)
            continue
        if arm and dst in STATE_ASSIGN.findall(line):
            arms.add(arm)
    _ARMS[key] = frozenset(arms)
    return _ARMS[key]


# The eFuse write sequence states whose own arm does not return to StWriteIdle;
# only StWriteFinish does, so an edge from these to StWriteIdle is the reset.
EFUSE_WRITE_MID = (
    "StWriteInit",
    "StWriteSetup",
    "StWriteAccess",
    "StWriteWait",
    "StWriteReadBackSetup",
    "StWriteReadBackAccess",
    "StWriteReadBackWait",
)
# Target states that drive scl_d = 1'b0 for their whole duration, so the bus
# monitor cannot see a start in them.
I2C_SCL_LOW = (
    "StretchAddr",
    "StretchAddrAck",
    "StretchAddrAckSetup",
    "StretchTx",
    "StretchTxSetup",
    "StretchAcqFull",
    "StretchAcqSetup",
)
# Target states that leave transmitting_o at zero, or hold SCL low, and whose
# own arm does not assign WaitForStop. StretchAddr and StretchAddrAck hold SCL
# low too but assign it themselves, so they keep that edge graded.
I2C_NO_ARB_LOSS = (
    "Idle",
    "AcquireStart",
    "AcquireByte",
    "TransmitWait",
    "TransmitAck",
    "StretchAddrAckSetup",
    "StretchTxSetup",
    "StretchAcqSetup",
)
# Controller states that leave transmitting_o at zero and do not raise
# ctrl_symbol_failed, which only SetupStart, SetupStop and HoldStop do, and
# whose own arm does not assign Idle. ClockPulseAck and ReadClockPulse do assign
# it, on an unexpected start or stop, so they keep that edge graded.
I2C_NO_SYMBOL_FAIL = (
    "Active",
    "ClockLowAck",
    "HoldDevAck",
    "ReadClockLow",
    "ReadHoldBit",
)

# The states whose own case arm of avsbus_controller assigns AVS_IDLE, so that an
# edge from them is the sequence rather than the always_comb default.
AVS_IDLE_ARMS = ("AVS_IDLE", "AVS_SLAVE_RESYNC", "AVS_END_LAST_SUBFRAME")

# (module, fsm) -> list of (class, selector). ("to", S) takes the transitions
# into S; ("to_default", (S, arms)) those into S from a state that is not in
# arms, for where only some of the source's states reach S through a case arm;
# ("state", S) the state S and the transitions that touch it; ("edges", (...))
# exactly those transitions; ("override", S) the transitions into S from every
# state whose own case arm, read from the FSM source, does not assign S. A
# selector of None takes every point of the variable, which is right only where
# the variable is not a state register of the design at all.
FSM_FACTS: "dict[tuple[str, str], list[tuple[str, tuple[str, object] | None]]]" = {
    ("avsbus_controller", "cur_state"): [
        (F2, ("to_default", ("AVS_IDLE", AVS_IDLE_ARMS))),
        (F5, ("to", "AVS_RESET")),
    ],
    ("trace_axi_master", "state"): [
        (F3, ("state", "AW_HANDSHAKE")),
        (F3, ("state", "W_HANDSHAKE")),
        (F3, ("state", "RESP_HANDSHAKE")),
        (F5, ("edges", ("REQ_HANDSHAKE->RESET_VALUE",))),
    ],
    ("efuse_interface_controller", "efuse_reg_select"): [(F4, ("state", "EFUSE_MMR_REG_MAP"))],
    ("zeroer", "cur_state"): [(F5, ("edges", ("ST_ISSUE_ADDR->ST_IDLE",)))],
    ("efuse_shadow_regs", "efuse_sense_state_q"): [(F5, ("edges", ("StRead->StIdle",)))],
    ("i2c_bus_monitor", "state_q"): [(F6, ("edges", ("StBusBusyStop->StBusBusyHigh",)))],
    ("smc_cool_reset_wrap", "flr_counter_state"): [(F5, ("edges", ("COUNT_DOWN->IDLE",)))],
    ("accumulator_bank", "bank_status"): [(F5, ("edges", ("BANK_PARTIAL->BANK_EMPTY",)))],
    ("efuse_interface_shim", "efuse_write_state_q"): [
        (F5, ("edges", tuple(f"{s}->StWriteIdle" for s in EFUSE_WRITE_MID))),
    ],
    ("smc_4core_cpu", "state"): [(B4, ("state", "MEM_ZERO_BUSY"))],
    ("telemetry_receiver", "block_index"): [(F9, None)],
    ("i2c_target_fsm", "state_q"): [
        (F7, ("edges", tuple(f"{s}->AcquireStart" for s in I2C_SCL_LOW))),
        (F8, ("edges", tuple(f"{s}->WaitForStop" for s in I2C_NO_ARB_LOSS))),
        (B2, ("override", "AcquireStart")),
        (B2, ("override", "Idle")),
        (B2, ("override", "WaitForStop")),
    ],
    ("i2c_controller_fsm", "state_q"): [
        (F8, ("edges", tuple(f"{s}->Idle" for s in I2C_NO_SYMBOL_FAIL))),
        (B2, ("override", "Idle")),
    ],
}


A3 = (
    "SMC-REGBLOCK-A3-NOREADCHANNEL: uart_16550.sv selects the write-only register map on the "
    "write channel only -- its read-channel select has no branch for that map -- and the AXI-Lite "
    "demux raises a port's AR valid only when that port is selected, so this block's arvalid is "
    "never asserted. Its arvalid register and ar_accept therefore stay low, every request it "
    "sees is a write, and its read acks never rise; a row or branch path that needs any of them "
    "high cannot occur. A row with ar_accept low and aw_accept high stays graded, as the write "
    "channel produces it."
)
A4 = (
    "SMC-REGBLOCK-A4-READNEVERERRORS: in this block reg_re and reg_we are mutually "
    "exclusive, wr_err is gated on reg_we and addrmiss requires that no address hit, so a "
    "read that hits an address always sees reg_error low and the crossed term cannot occur."
)
A5 = (
    "SMC-REGBLOCK-A5-INPUTUNCONNECTED: the SMC integration ties this block's devmode_i to "
    "zero, so the explicit-error-on-unmapped-access term it gates never evaluates true, in the "
    "expression or in its operand table."
)
A6 = (
    "SMC-REGBLOCK-A6-SINGLEPULSE-RETAIN: the RDL declares these fields singlepulse, so the "
    "storage holds a written one for a single cycle and the cpuif accepts no second write in "
    "that cycle, which leaves the storage at zero at every write the block accepts. The retain "
    "row of the write-data ternary, and each row of its retain operand that asks for the "
    "storage at one, needs the storage at one during a write, and no access produces it. "
    "Fields of the same block that keep their value between writes stay graded."
)

A8 = (
    "SMC-REGBLOCK-A8-EXTERNAL-ACK-SAME-CYCLE: every external register of this block is acked "
    "in the cycle it is requested, since its integration drives each wr_ack and rd_ack from the "
    "register's own req and direction, and PeakRDL gates that req and the is_external term on "
    "the same direction. decoded_req_is_external therefore always meets an ack, external_pending "
    "never sets, and the stall inputs it drives hold zero: the stall rows and paths, and the "
    "pending-set row, cannot occur. The handshake's valid-without-ready rows stay graded."
)
A9 = (
    "SMC-REGBLOCK-A9-ADDRESS-FIXED: the integration presents this single-register block only "
    "address zero at the bit its cpuif decodes (output_remap_reg is fed {1'b0, addr[2:0]}, and "
    "uart_log_engine_ctrl_reg is selected only inside a four-byte window at an eight-byte "
    "aligned base), so cpuif_addr and rd_mux_addr hold zero and a row that needs either "
    "nonzero cannot occur."
)
C3 = (
    "SMC-REGBLOCK-C3-NO-EXTERNAL-WRITE: the block's only external register is read-only, so "
    "PeakRDL gives external_wr_ack a constant zero, and a row that needs an external write "
    "acknowledged cannot occur."
)
C4 = (
    "SMC-REGBLOCK-C4-STROBE-CARRIES-DIRECTION: PeakRDL folds the access direction into the "
    "decode strobe of a read-only or write-only register, and into the req it presents for an "
    "external one, so the strobe or req is never high in the other direction. A row that needs "
    "it high in that direction, in the block or in the logic that consumes the req, cannot "
    "occur; the test rewrites each strobe or req as itself and its direction, and takes a row "
    "only when that makes it unsatisfiable."
)
B7 = (
    "SMC-REGBLOCK-B7-DFX-INPUTS-TIED: a property of this bench, not of the design. The SMC "
    "passes mem_repair_done, mem_repair_success, mbist_done and mbist_pass straight to the DFX "
    "status register's sticky fields, whose load_next is that input, and the testbench ties all "
    "four high because the boot sequencer waits on them; a row or path that needs one of them, "
    "or its load, low has no stimulus here. "
    "Bench ports that drive those inputs retire the class."
)
B1 = (
    "SMC-REGBLOCK-B1-PARTIAL-LANE-WRITE: a property of this bench, not of the design. The SMC "
    "AXI agent writes whole 32-bit words, so on a register block whose cpuif carries no more "
    "than that, every write it issues has every lane on. A row of a field's software-write "
    "branch that needs some lane off, the retain row, a row of the retain operand or of the "
    "write-data operand, is reachable in the design and uncovered for want of a partial write; "
    "an agent that issues one covers it. A block whose cpuif is wider takes a half-word write "
    "from this same agent, so its rows stay graded. The clear-on-write form of a W1C field is "
    "left out, and a leaf covers it."
)
# The width of the write the bench's AXI agent issues. A register block whose
# cpuif is no wider than this cannot be written a part at a time, and PeakRDL
# never builds a register wider than the cpuif, so the block's width settles it
# for every register in it.
AGENT_WRITE_BITS = 32
CPUIF_WIDTH = re.compile(r"logic \[(\d+):0\] cpuif_wr_data;")


def cpuif_data_width(source: str) -> "int | None":
    """The cpuif write-data width of a generated register block, from its source."""
    path = Path(source.split(":")[0])
    if not is_regblock_source(source) or not path.is_file():
        return None
    m = CPUIF_WIDTH.search(path.read_text(errors="replace"))
    return int(m.group(1)) + 1 if m else None


def is_regblock_source(src: str) -> bool:
    """Whether a template entry comes from a generated register block."""
    return "/regs/gen/sv/" in src


P1 = (
    "SMC-P1-NTRACE-OFF: the DFD top instantiates the trace wrapper with NUM_NTRACE_INST(0) and "
    "NTRACE_SUPPORT(0), and trace_wrapper.sv gives Core_fuse_enable_Ntrace a constant zero at "
    "zero instances, so every N-trace signal of the sink reads zero. A row is taken only where "
    "the report's own term list shows it asking one of those signals for a value that zero "
    "forbids; a row every N-trace term of which sits at zero stays graded, whatever the "
    "expression's other signals are, and so does the NTR-sink MMR decode of mmrs."
)

P3 = (
    "SMC-P3-WREN-TIED: the CLA drives this hardware write-enable with a constant one, so the "
    "term never reads zero and the write-data ternary it selects never takes its else arm; no "
    "software stimulus moves a tie-off."
)
P4 = (
    "SMC-P4-SINGLE-SOURCE: with NUM_NTRACE_INST(0) the trace sink has one source, so the "
    "two-source term of TrRamPendPkt*WrEn is always false and the per-way pending count, which "
    "only increments from those enables, stays at zero for the life of the design; every "
    "pending valid, write and read enable, and every south-port valid, reads zero. A row is "
    "taken only where the report's own term list shows it out of reach with those held at zero "
    "and within reach with them free. The pending RAM's source field is RAM content and is "
    "left free, so a row that holds the dead signals at zero and turns on another term stays "
    "graded, as ordinary trace traffic reaches it."
)
P5 = (
    "SMC-P5-INSTR-TYPE-CONST: mmrs assigns MmrWrInstrType a constant zero, and every DFD MMR "
    "block latches its reg_wr_instr_type from that net alone, so the set and clear encodings "
    "update_value tests are never presented and their true rows cannot occur in any of the "
    "blocks."
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
    "SMC-P8-WREN-TIED-ZERO: this reserved field's write enable is the CLA write structure's "
    "field alone, with no register-write term beside it, and the CLA gives that structure a "
    "zero default and never names the field; the enable holds zero, so its true arm and the "
    "then arm of the write-data ternary it selects have no stimulus. This is the converse of "
    "P3, where a constant one leaves the else arm unreachable instead."
)
P9 = (
    "SMC-P9-DEBUG-WIDTH-64: core_logic_analyzer derives DBG_SIGNAL_CONFIG from "
    "DEBUG_SIGNAL_WIDTH == 128 and smc_dfd_wrap passes 64, so the cla_snapshot_mmr_hi_blk "
    "generate that drives every snapshot Hi write enable is not elaborated and each of them "
    "holds the zero its write structure defaults to; the enable's true arm and the then arm of "
    "the ternary it selects have no stimulus. The Lo halves are assigned outside that generate "
    "and stay graded."
)
P10 = (
    "SMC-P10-PACKET-SHORTER-THAN-BANK: a bank spans BANK_DATA_WIDTH_IN_BYTES bytes, 32 at this "
    "instantiation, and the packetizer is elaborated with PACKET_WIDTH_IN_BYTES = "
    "VLT_PACKET_WIDTH / 8, which a 64-bit debug bus makes 10, so one write cannot both start "
    "at or below a bank's first byte and end past its last; the term asking whether it does is "
    "false for the life of the design. The two sibling terms of the same condition are "
    "reachable and stay graded."
)
P11 = (
    "SMC-P11-UART-SELF-CHECK: each UART holding register stores its data with the parity bit "
    "~^data beside it, written together with the valid flag and cleared together with it, and "
    "each parity FIFO stores {~^data, data} and guards its pointers with a redundant count, so "
    "a valid stored entry always has odd parity and the check ~^{parity, data} reads one only "
    "on corrupted storage. The I2C core's four FIFOs are the same secure parity FIFO, so their "
    "err_o reads one only on corruption too. No access produces that, so the rows that need a "
    "self-check or FIFO error at one have no stimulus."
)
P12 = (
    "SMC-P12-BREAK-IMPLIES-FRAMING: uart_core forms break_err as the framing error of a frame "
    "whose data is all zeros and stores it in the same entry as that framing error, in the "
    "FIFO and in the holding register alike, so an entry carrying break_err always carries "
    "framing_err as well; the row that needs break_err alone has no stimulus."
)
# The whole condition, so that a change to the order of its terms stops the
# vector matching rather than moving it onto a sibling.
BANK_RANGE = re.compile(
    r"^\(target_write_byte_boundary_equals_range_end"
    r" \|\| target_write_byte_boundary_crosses_bank_range"
    r" \|\| target_write_byte_wraparound\)$"
)

# The snapshot write enables of the half a 64-bit debug bus does not elaborate.
WREN_HI = re.compile(r"SignalSnapshotNode\d+Eap\d+Hi_F_Value_WrEn")


# The one reserved-field enable the MMR block drives from its write structure
# alone. Every other MMR_CDbg*_F_Rsvd*_WrEn carries a `reg_write & reg_addr`
# term, so a software write to that register asserts it.
WREN_ZERO = r"MMR_CDbgEapStatus_F_Rsvd3116_WrEn"
P6 = (
    "SMC-P6-LC-STATE-OFF: smc_efuse_wrapper instantiates the eFuse with HAS_LC_STATE = 0, so "
    "the lifecycle-state arms of the interface controller, the shadow registers, their access "
    "control and the guard are never entered and the RMA token comparisons they hold have no "
    "access that can reach them. The fuse-sense, "
    "security-disable and image-lock terms outside those arms stay graded."
)
P7 = (
    "SMC-P7-NO-ERROR-CAP: idma_backend_wrapper elaborates the backend with ErrorCap = "
    "NO_ERROR_HANDLING, whose bypass assigns the legalizer's flush and kill inputs and the write "
    "datapath's poison a constant zero, so a term that needs one of them asserted is false for "
    "the life of the design. "
    "The read and write backpressure rows of the same expressions stay graded."
)

P13 = (
    "SMC-P13-CLAMP-TIED: generic_ipx_clk_rst_ctrl forms o_gated_func_clamp as i_func_clamp | "
    "i_fuse_dis; smc_dfd_wrap ties both inputs to zero for the CLA, the DST source, the DST "
    "sink and the funnel, and the DFD top ties both to one for the NTR sink. The trace network "
    "interface takes the AND of the DST inputs and the absent N-trace side's, and the MMR "
    "interface takes the AND over every block, the CLA's included, so both are zero as well. "
    "Each gated clamp holds one value for the life of the design and the ternary arm the other "
    "value selects never executes."
)
P14 = (
    "SMC-P14-JTAG-MMR-TIED: smc_dfd_wrap ties i_jtag_mmr_req_vld to zero, mmrs tests it "
    "directly, and mmr_req_ctrl grants the JTAG requester exactly when it is high "
    "(gnt_is_jtag = jt_req_vld), so no arm that selects the JTAG request executes."
)
P15 = (
    "SMC-P15-SECURE-TM-TIED: smc_efuse_wrapper ties the eFuse's secure_tm_i to zero, so the "
    "secure-test-mode arms of the shadow registers, their access control and the guard never "
    "execute, and the guard's secure_tm_blocked, which the program interface reads, holds zero. "
    "The program-lock and read-lock arms beside them stay graded."
)
P16 = (
    "SMC-P16-SINK-ENABLE-CONST: the DFD top elaborates mmrs with NTRACE_SUPPORT(0) and the "
    "default TRACE_SINK_SUPPORT and DST_SUPPORT of one, so mmrs derives NTR_SINK_EN as zero and "
    "DST_SINK_EN as one, and the arm of each if on those enables that the constant does not "
    "select never executes."
)
P17 = (
    "SMC-P17-ONE-TRACE-CORE: the DFD top passes the trace wrapper NUM_CORES as the larger of "
    "NUM_DST_INST(1) and NUM_NTRACE_INST(0), and the wrapper passes it on to the trace sink, so "
    "NUM_CORES > 1 is false, its then arm never executes, and the south-channel frame start it "
    "guards stays at its zero default."
)
P19 = (
    "SMC-P19-NTR-RAM-READ-TIED: the DFD top connects the trace wrapper's trRamDataRdEn to a "
    "constant zero, so the trace sink's trRamDataRdEn_ANY is zero for the life of the design and "
    "the N-trace RAM data read never occurs; a row or arm that needs it high cannot."
)
P22 = (
    "SMC-P22-DFD-CONTROL-TIED: smc_dfd_wrap ties the DFD top's i_critical_signal_hold, "
    "i_timestamp and every CLA, DST, DST-sink and funnel fuse and clock disable to zero, and "
    "its i_sdtrig_control to TRIG_TRACE_NONE. So the warm-reset override terms, the fuse and "
    "clock-disable terms and extensions, the CLA time-match event (a timestamp of zero never "
    "reaches a nonzero match value) and the DST sdtrig start and stop hold zero, and a row or "
    "path that needs one of them high cannot occur."
)
B8 = (
    "SMC-B8-DFD-BENCH-INPUTS-TIED: a property of this bench, not of the design. The "
    "testbench ties the SMC's xtrigger_ss_i and tdr_dbg_ctrl_clock_stop_en_i to zero in both "
    "instances, and they reach the CLA crosstrigger input and the DFD clock-stop gate "
    "unchanged. The CLA crosstrigger edge, the timestamp load it arms and the TDR clock-stop "
    "term therefore hold zero here. Bench ports that drive those inputs retire the class."
)
P24 = (
    "SMC-P24-DIVIDER-INIT-NEVER-SET: avsbus_controller assigns do_initial_divider_setting only "
    "1'b0, under reset and on a divider update, so it is zero for the life of the design and a "
    "row that needs it high cannot occur."
)
C5 = (
    "SMC-C5-SIGNAL-IDENTITY: the source defines one signal from another, so a row that needs "
    "them apart cannot occur: uart_core assigns tx_enable and rx_enable the same expression, "
    "baud_rate_divisor != 0, and system_timer_octs_core forms credit_gen_pulse with enable as "
    "one of its terms. The test rewrites the dependent signal in those terms and takes a row "
    "only when that makes it unsatisfiable."
)
B9 = (
    "SMC-B9-SECURITY-DISABLE-TIED: a property of this bench, not of the design. The testbench "
    "ties sep_security_disable_i to zero in both instances, and it reaches the eFuse shadow "
    "registers unchanged, so the security-disable term of the fuse-sense load holds zero here. "
    "A bench port that drives the input retires the class."
)
P20 = (
    "SMC-P20-TCOUNT-SELECT-PAIRED: the I2C FSMs pick a counter reload with tcount_sel only "
    "under load_tcount, assign tcount_sel nothing but its named values, and the target assigns "
    "tNoDelay only beside load_tcount = 0 (its defaults at the top of the next-state block and "
    "in its default arm), every reload pairing tSetupData or tHoldData. The case's default item, "
    "and the target's tNoDelay item, never execute. The controller reloads with tNoDelay on "
    "purpose, so that item stays graded there."
)
P25 = (
    "SMC-P25-SINK-WRITEBACK-TIED: the trace sink gives its DST RAM-control write structure a "
    "zero default and sets only the empty and enable write enables, assigns the RAM read-pointer "
    "high write structure a constant zero, and the funnel ties the RAM start and limit write "
    "structures to zero, so the stop-on-wrap, mode and active enables and the start, limit and "
    "read-pointer-high enables the DST sink MMR ORs with a software write hold zero, and the "
    "hardware-write row of each cannot occur."
)
B6 = (
    "SMC-B6-SIM-ONLY-FUSE-BYPASS: a property of this bench and its policy, not of the design. "
    "efuse_shadow_regs reads the +skip_fuse_sense plusarg in simulation-only initial blocks and "
    "ties sim_skip_fuse_sense to zero outside simulation; with the plusarg set, the shadow "
    "registers take a preload file or zeros in place of the sensed fuse image. The DV policy "
    "(section 1.6) forbids a skipped fuse sense as evidence, and no SMC testlist entry passes "
    "the plusarg, so the plusarg arms and every row or path that needs sim_skip_fuse_sense high "
    "never run here. A policy change admitting the plusarg retires the class."
)
P18 = (
    "SMC-P18-TDR-OVERRIDE-TIED: avsbus_controller.sv assigns its TDR post-divider override "
    "i_tdr_peripherals_apb2avsbus_postdiv_override a constant zero, so each ternary it selects "
    "takes the register value and the TDR arm never executes."
)
A7 = (
    "SMC-REGBLOCK-A7-SINGLEPULSE-LOADS: the RDL declares these fields singlepulse, and PeakRDL "
    "sets the field's load_next on its software-write arm and on the else arm that clears it "
    "back to zero, so the storage loads on every clock out of reset and the path of its flop "
    "that skips the load never runs."
)
C1 = (
    "SMC-REGBLOCK-C1-CONTRADICTORY-PATH: urg lists every combination of an if and else-if "
    "chain's decisions as a path, including combinations whose decisions contradict one "
    "another. PeakRDL's response logic enters `if (cpuif_rd_ack || cpuif_wr_ack)` and then "
    "tests each ack alone, so the path through the outer branch with both inner tests false "
    "needs the disjunction true and both of its terms false. A path is written only when its "
    "own decisions, read over the same signals, have no common solution."
)

# (file suffix, first line, last line) of the source region a fact covers, for
# where one file carries the same expression text inside and outside the region.
LC_STATE_ARM = ("efuse_shadow_regs.sv", 290, 347)

# update_value's set and clear encodings, which MmrWrInstrType tied to zero never presents.
INSTR_TYPE_TEST = re.compile(r"^\(instr_type == 2'b\d+\)$")

# The trace sink's N-trace RAM read enable, tied to zero at the DFD top.
NTR_RAM_READ = re.compile(r"^trRamDataRdEn_ANY$")

# The eFuse's simulation-only fuse-sense bypass: the flag and the plusarg test
# that sets it, as the path reader names a plusarg test.
SIM_SKIP = re.compile(r"^(?:sim_skip_fuse_sense|plusarg_skip_fuse_sense)$")


def in_region(src: str, region: "tuple[str, int, int] | None") -> bool:
    """Whether a template entry's source line falls in a fact's region."""
    if region is None:
        return True
    path, _, line = src.rpartition(":")
    name, first, last = region
    return path.endswith(name) and first <= int(line) <= last


# Identifiers the NUM_NTRACE_INST(0) / NTRACE_SUPPORT(0) instantiation leaves
# without a source. trace_wrapper.sv drives Core_fuse_enable_Ntrace from a
# ternary on the parameter and gives it '0 at zero instances, so each of these
# reads zero for the life of the design.
NTRACE_NAME = re.compile(r"^(trntr|insntrace)|ntrace", re.I)
# A name carrying both halves is the mux between them, not the N-trace side.
SHARED_NAME = re.compile(r"ntraceordst|dstorntrace", re.I)
TERM_IDENT = re.compile(r"[A-Za-z_][A-Za-z_0-9]*(?:\.[A-Za-z_][A-Za-z_0-9]*)*")
LITERAL = re.compile(r"^\d*'[bhdo]?[0-9a-fA-F_]+(\[[^\]]*\])?$")
COMPARE = re.compile(r"^(.+?)\s*(!=|==|>=|<=|>|<)\s*(.+)$", re.S)


def _peel(text: str) -> str:
    t = text.strip()
    while t.startswith("(") and t.endswith(")") and _balanced(t[1:-1]):
        t = t[1:-1].strip()
    return t


def _balanced(text: str) -> bool:
    depth = 0
    for c in text:
        depth += c == "("
        depth -= c == ")"
        if depth < 0:
            return False
    return depth == 0


def _split_top(text: str, op: str) -> "list[str]":
    parts, depth, cur = [], 0, ""
    for i, c in enumerate(text):
        depth += c == "("
        depth -= c == ")"
        if depth == 0 and c == op and not (i + 1 < len(text) and text[i + 1] == op):
            parts.append(cur)
            cur = ""
        else:
            cur += c
    parts.append(cur)
    return [p.strip() for p in parts if p.strip()]


def term_identifiers(term: str) -> "list[str]":
    """The signal names of a term, with sized literals left out."""
    out = []
    for m in TERM_IDENT.finditer(term):
        if m.start() and term[m.start() - 1] in "'0123456789":
            continue
        out.append(m.group(0))
    return out


def is_ntrace_term(term: str) -> bool:
    """Whether every signal the term reads is one the tie-off leaves at zero."""
    ids = term_identifiers(term)
    return bool(ids) and all(NTRACE_NAME.search(i) and not SHARED_NAME.search(i) for i in ids)


def _numeric(term: str) -> "int | None":
    """Value of an arithmetic term with every N-trace signal at zero."""
    t = _peel(term)
    m = re.fullmatch(r"\d+'\((.*)\)", t, re.S)
    if m:
        return _numeric(m.group(1))
    for op in ("+", "*"):
        parts = _split_top(t, op)
        if len(parts) > 1:
            vals = [_numeric(p) for p in parts]
            if any(v is None for v in vals):
                return None
            out = 0 if op == "+" else 1
            for v in vals:
                out = out + v if op == "+" else out * v
            return out
    if LITERAL.match(t) or re.fullmatch(r"\d+(\[[^\]]*\])?", t):
        digits = re.sub(r"\[[^\]]*\]$", "", t)
        base = 16 if "'h" in digits else 2 if "'b" in digits else 8 if "'o" in digits else 10
        return int(re.sub(r"^\d*'[bhdo]?", "", digits).replace("_", ""), base)
    return 0 if is_ntrace_term(t) else None


def tied_value(term: str) -> "int | None":
    """The value an N-trace-only term holds with those signals at zero."""
    t = _peel(term)
    if re.fullmatch(r"~\s*[|&^]?\s*" + TERM_IDENT.pattern + r"(\[[^\]]*\])?", t):
        return 1
    if re.fullmatch(r"[|&^]?\s*" + TERM_IDENT.pattern + r"(\[[^\]]*\])?", t):
        return 0
    for op, fold in (("|", max), ("&", min), ("^", lambda v: sum(v) % 2)):
        parts = _split_top(t, op)
        if len(parts) > 1:
            vals = [tied_value(p) if is_ntrace_term(p) else None for p in parts]
            if any(v is None for v in vals):
                return None
            return fold(vals)
    m = COMPARE.match(t)
    if m:
        left, op, right = _numeric(m.group(1)), m.group(2), _numeric(m.group(3))
        if left is None or right is None:
            return None
        return int(
            {
                "==": left == right,
                "!=": left != right,
                ">": left > right,
                "<": left < right,
                ">=": left >= right,
                "<=": left <= right,
            }[op]
        )
    return None


def ntrace_tied_off(terms: "list[str]", vector: str) -> bool:
    """Whether a row asks an N-trace term for a value the tie-off forbids.

    A row every N-trace term of which sits at the value the tie-off gives it is
    one the fact says nothing about, whatever the expression's other signals
    are, so it stays graded. A term this cannot evaluate is no argument for
    excluding the row either.
    """
    if len(terms) != len(vector):
        return False
    for term, bit in zip(terms, vector):
        if not is_ntrace_term(term):
            continue
        value = tied_value(term)
        if value is not None and int(bit) != value:
            return True
    return False


def expression_terms(modinfo: Path) -> "dict[tuple[str, str], list[str]]":
    """(module, expression) -> the term texts the report lists for a top-level expression."""
    return {
        (module, point.text): list(point.terms)
        for module, points in report_points(modinfo).items()
        for point in points
        if not point.sub and point.terms
    }


LANE_IDENTIFIER = re.compile(r"[A-Za-z_][\w$]*(?:\[[^\]]*\])*(?:\.[A-Za-z_][\w$]*(?:\[[^\]]*\])*)*")


SIZED_LITERAL = re.compile(r"\d*'[sS]?([bhdoBHDO])([0-9a-fA-F_xXzZ]+)")


def _python_condition(term: str, names: list[str]) -> "str | None":
    """A term as a Python expression over v[i], one boolean per signal name, or None.

    Every signal is abstracted to one bit, which is exact for the one-bit enables,
    valids and lanes the classes below ask about; a reduction of a vector becomes
    the signal itself, and a comparison between signals stays a comparison. A
    ternary or anything else this does not read gives None, so the row is left out.
    """
    if "?" in term:
        return None

    def literal(m: re.Match) -> str:
        return "0" if re.fullmatch(r"0+", m.group(2).replace("_", "")) else "1"

    body = SIZED_LITERAL.sub(literal, term)
    body = re.sub(r"\b(\d+)\[[^\]]*\]", r"\1", body)

    def slot(m: re.Match) -> str:
        if m.group(0) not in names:
            names.append(m.group(0))
        return f" v[{names.index(m.group(0))}] "

    body = LANE_IDENTIFIER.sub(slot, body)
    body = re.sub(r"~\s*[|&^]", " not ", body)
    body = re.sub(r"(^|\()\s*[|&^](?=\s*(?:v\[|\())", r"\1", body)
    for a, b in (("&&", " and "), ("||", " or "), ("!=", " != "), ("==", " == ")):
        body = body.replace(a, b)
    body = re.sub(r"!(?!=)", " not ", body)
    body = body.replace("~", " not ").replace("&", " and ").replace("|", " or ")
    return body.replace("^", " != ").strip()


def _row_satisfiable(
    terms: tuple[str, ...], vector: str, forced: "re.Pattern[str] | None", value: int
) -> "bool | None":
    """Whether some value of the terms' signals gives the row, with the forced ones held."""
    compiled = []
    names: list[str] = []
    for term in terms:
        local: list[str] = []
        body = _python_condition(term, local)
        if body is None:
            return None
        try:
            compiled.append((local, compile(body, "<term>", "eval")))
        except SyntaxError:
            return None
        names += [n for n in local if n not in names]
    free = [n for n in names if forced is None or not forced.search(n)]
    if len(free) > 12:
        return None
    for bits in itertools.product((0, 1), repeat=len(free)):
        env = dict(zip(free, bits))
        env.update({n: value for n in names if n not in env})
        try:
            got = "".join(
                str(int(bool(eval(code, {}, {"v": [env[n] for n in local]}))))
                for local, code in compiled
            )
        except Exception:
            return None
        if got == vector:
            return True
    return False


def _row_satisfiable_held(
    terms: "tuple[str, ...]", vector: str, held: "list[tuple[re.Pattern[str], int]]"
) -> "bool | None":
    """Whether some value of the free signals gives the row, every held signal at its value."""
    compiled = []
    names: list[str] = []
    for term in terms:
        local: list[str] = []
        body = _python_condition(term, local)
        if body is None:
            return None
        try:
            compiled.append((local, compile(body, "<term>", "eval")))
        except SyntaxError:
            return None
        names += [n for n in local if n not in names]
    fixed: dict[str, int] = {}
    for n in names:
        for pattern, value in held:
            if pattern.search(n):
                fixed[n] = value
                break
    free = [n for n in names if n not in fixed]
    if len(free) > 12:
        return None
    for bits in itertools.product((0, 1), repeat=len(free)):
        env = dict(zip(free, bits))
        env.update(fixed)
        try:
            got = "".join(
                str(int(bool(eval(code, {}, {"v": [env[n] for n in local]}))))
                for local, code in compiled
            )
        except Exception:
            return None
        if got == vector:
            return True
    return False


def needs_forced_away(
    terms: "tuple[str, ...] | list[str] | None",
    vector: str,
    forced: "re.Pattern[str]",
    value: int,
) -> bool:
    """Whether a row is out of reach with the forced signals held but within reach with them free."""
    if not terms or len(terms) != len(vector):
        return False
    terms = tuple(terms)
    return _row_satisfiable(terms, vector, forced, value) is False and bool(
        _row_satisfiable(terms, vector, None, value)
    )


WRITE_LANE = re.compile(r"^decoded_wr_biten\b")


def needs_lane_off(terms: "tuple[str, ...] | None", vector: str) -> bool:
    """Whether a row needs some write lane off: out of reach with every lane on."""
    return needs_forced_away(terms, vector, WRITE_LANE, 1)


# P4's dead signals: with one trace source the pending count stays at zero, so
# every pending valid and write or read enable reads zero, and the south port
# has no source. The pending RAM's source field is RAM content rather than a
# tied signal, so it is left free, as is every north-side signal.
SINGLE_SOURCE_DEAD = re.compile(
    r"TrRamPend(?:Pkt)?(?:Vld|WrEn|RdEn|NorthWrEn|SouthWrEn)|TrRamPend\w*PktVld|"
    r"South\w*Vld|TrRamSouth\w*|TR_TS_South\w*|TrRamPerWayPendToWriteCnt\w*"
)


def single_source_row(terms: "list[str]", vector: str) -> bool:
    """Whether a row needs a signal P4 holds at zero to be one."""
    return needs_forced_away(terms, vector, SINGLE_SOURCE_DEAD, 0)


# module -> [(class, expression pattern, term-vector test or None, source
# region or None)] for conditions a disabled build option or a tied-off
# integration input leaves without a source. The third field pins which row of a
# multi-term expression the fact covers: a pattern the vector must match, or a
# predicate over the report's terms and the vector, for where the answer depends
# on which term the row holds away from its tied value. The region pins which
# occurrence of a repeated expression. A row an access can reach stays graded,
# and only uncovered rows are taken.
FEATURE_FACTS: "dict[str, list[tuple[str, object, object, object]]]" = {
    "trace_sink": [
        (P1, re.compile(r"\btrntr|ntrace|insntrace", re.I), ntrace_tied_off, None),
        (P4, re.compile(r"TrRamPend|TrRamSouth|TR_TS_South|South_Vld"), single_source_row, None),
        (
            P19,
            re.compile(r"trRamDataRdEn_ANY"),
            lambda t, v: needs_forced_away(t, v, NTR_RAM_READ, 0),
            None,
        ),
    ],
    "axi_filter_wrap": [(P2, re.compile(r"^\(filter_skip_i \?"), re.compile(r"^1$"), None)],
    "dst_mmr": [(P5, INSTR_TYPE_TEST, re.compile(r"^1$"), None)],
    "dst_sink_mmr": [(P5, INSTR_TYPE_TEST, re.compile(r"^1$"), None)],
    "funnel_mmr": [(P5, INSTR_TYPE_TEST, re.compile(r"^1$"), None)],
    "cla_mmr": [
        (P3, re.compile(WREN_TIED, re.I), None, None),
        (P8, re.compile(WREN_ZERO), re.compile(r"^1$"), None),
        (P9, WREN_HI, re.compile(r"^1$"), None),
        (P5, INSTR_TYPE_TEST, re.compile(r"^1$"), None),
    ],
    "mmrs": [
        (P1, re.compile(r"NTR_SINK_\w+_REG_ADDR|MmrCs\[NTR_SINK_BLK_IDX\]"), None, None),
        (P1, re.compile(r"Trntrissrammode|Trramstart(low|high)_Warl"), None, None),
    ],
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
        (P6, re.compile(r"."), None, LC_STATE_ARM),
        (
            B6,
            re.compile(r"sim_skip_fuse_sense"),
            lambda t, v: needs_forced_away(t, v, SIM_SKIP, 0),
            None,
        ),
    ],
    "accumulator_bank": [(P10, BANK_RANGE, re.compile(r"^010$"), None)],
    "uart_core": [
        (
            P11,
            re.compile(r"^\((thr|rbr)_rvalid && \(\(~\^\{\1_parity, \1_rdata\}\)\)\)$"),
            re.compile(r"^11$"),
            None,
        ),
        (
            P11,
            re.compile(r"^\(tx_fifo_thr_err \|\| rx_fifo_rbr_err\)$"),
            re.compile(r"^(01|10)$"),
            None,
        ),
        (
            P12,
            re.compile(
                r"^\((rx_fifo_rdata|rbr_rdata)\.break_err \|\| \1\.framing_err"
                r" \|\| \1\.parity_err\)$"
            ),
            re.compile(r"^100$"),
            None,
        ),
    ],
    "efuse_guard": [
        (P6, re.compile(r"rma_(sip|chiplet)_token_match_i"), None, None),
        (P6, re.compile(r"pro_read_intf_(wr|rd)_index == '0"), None, None),
        (P6, re.compile(r"pro_read_intf_lock_lc_state_write"), re.compile(r"^01$"), None),
        (P6, re.compile(r"."), None, ("efuse_guard.sv", 74, 84)),
    ],
    "efuse_shadow_reg_access_control": [
        (P6, re.compile(r"."), None, ("efuse_shadow_reg_access_control.sv", 115, 117)),
    ],
    "mmr_req_ctrl": [(P16, re.compile(r"."), None, ("mmr_req_ctrl.sv", 167, 167))],
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
        (P9, WREN_HI, "1"),
    ],
    "idma_legalizer_rw_axi": [(P7, re.compile(r"^kill_i$"), "1")],
}

# Facts over the decisions of a multi-decision branch path, as (class, signals,
# value): a path is written when one of its decisions is out of reach with the
# signals held at that value and within reach with them free.
NTRACE_SIGNAL = re.compile(r"^(?!.*(?:ntraceordst|dstorntrace))(?:trntr|insntrace|.*ntrace)", re.I)
LC_STATE_OFF = re.compile(r"^(?:HAS_LC_STATE|is_lc_state_access)$")
SECURE_TM = re.compile(r"^secure_tm_i$")
BRANCH_PATH_FACTS: "dict[str, list[tuple[str, re.Pattern[str], int]]]" = {
    "efuse_guard": [(P6, LC_STATE_OFF, 0), (P15, SECURE_TM, 0)],
    "efuse_interface_controller": [(P6, LC_STATE_OFF, 0)],
    "efuse_shadow_reg_access_control": [(P6, LC_STATE_OFF, 0), (P15, SECURE_TM, 0)],
    "efuse_shadow_regs": [
        (P6, LC_STATE_OFF, 0),
        (P15, SECURE_TM, 0),
        (B6, SIM_SKIP, 0),
        (B9, re.compile(r"^security_disable_i$"), 0),
    ],
    "efuse_program_interface": [(P15, re.compile(r"^secure_tm_blocked_i$"), 0)],
    "i2c_core": [(P11, re.compile(r"^(?:controller|target)_(?:tx|rx)_fifo_error$"), 0)],
    "idma_legalizer_rw_axi": [(P7, re.compile(r"^(?:flush_i|kill_i)$"), 0)],
    "idma_axi_write": [(P7, re.compile(r"^dp_poison_i$"), 0)],
    "trace_sink": [
        (P1, NTRACE_SIGNAL, 0),
        (P1, re.compile(r"^Tr(?:ram|customram)\w*\.\w+"), 0),
        (P4, SINGLE_SOURCE_DEAD, 0),
        (P19, NTR_RAM_READ, 0),
        (P17, re.compile(r"^trdstsouthcoresNewFrameStart_ANY$"), 0),
    ],
    "mmr_req_ctrl": [
        (
            P14,
            re.compile(
                r"^(?:jt_req_vld|gnt_is_jtag|launch_is_jtag|rsp_is_jtag|ram_is_jtag_q|ram_cs_is_jtag)$"
            ),
            0,
        ),
        (P16, re.compile(r"^(?:gnt_ram_rd_ntr|ram_is_ntr_q|ram_cs_is_ntr|ram_rd_en_ntr)$"), 0),
        (P14, re.compile(r"^gnt_is_jtag$"), 0),
        (P16, re.compile(r"^NTR_SINK_EN$"), 0),
        (P16, re.compile(r"^DST_SINK_EN$"), 1),
    ],
    "avsbus_controller": [
        (P18, re.compile(r"^i_tdr_peripherals_apb2avsbus_postdiv_override$"), 0),
        (P24, re.compile(r"^do_initial_divider_setting$"), 0),
    ],
    "cla_wrapper": [(P13, re.compile(r"^cla_gated_func_clamp\b"), 0)],
    "clk_rst_wrapper": [
        (P13, re.compile(r"^(?:dst_func_clamp_ext|dst_fuse_dis_ext)\b"), 0),
        (P1, re.compile(r"^(?:ntr_gated_reset_n|ntr_func_enable)\b"), 0),
        (
            P1,
            re.compile(
                r"^(?:ntr_func_clamp_ext|ntr_fuse_dis_ext|ntr_clk_dis_ext|ntr_clk_dis_ctrl_ext)\b"
            ),
            1,
        ),
        (P22, re.compile(r"^(?:i_critical_signal_hold|dst_clk_dis_ext)\b"), 0),
    ],
    "tnif": [(P1, re.compile(r"^(?:ntr_req_in|ntr_bp_in|ntr_flush_in|ntr_pull_out)$"), 0)],
    "trace_hop": [(P1, NTRACE_SIGNAL, 0)],
    "core_logic_analyzer": [
        (P22, re.compile(r"^time_match_event$"), 0),
        (B8, re.compile(r"^(?:xtrigger_in\[0\]|xtrigger_posedge|timestamp_load)$"), 0),
    ],
    "smc_dfd_wrap": [(B8, re.compile(r"^tdr_dbg_ctrl_clock_stop_en_i$"), 0)],
    "dst_wrapper": [
        (P13, re.compile(r"^dst_gated_func_clamp\b"), 0),
        (P22, re.compile(r"^sdtrig_dst_trace_(?:start|stop)$"), 0),
    ],
    "tnif_wrapper": [(P13, re.compile(r"^(?:dst|tnif)_gated_func_clamp\b"), 0)],
    "mmrs": [
        (P13, re.compile(r"^(?:intf|cla|dst|dst_sink|funnel)_gated_func_clamp\b"), 0),
        (P13, re.compile(r"^(?:ntr|ntr_sink)_gated_func_clamp\b"), 1),
        (P14, re.compile(r"^i_jtag_mmr_req_vld$"), 0),
        (P22, re.compile(r"^i_(?:cla|dst|dst_sink|funnel)_(?:fuse_dis|clk_dis)\b"), 0),
        (P22, re.compile(r"^i_critical_signal_hold$"), 0),
        (P1, re.compile(r"^i_ntr(?:_sink)?_(?:fuse_dis|clk_dis|clk_dis_ctrl|func_clamp)\b"), 1),
        (P1, re.compile(r"^ntr(?:_sink)?_gated_reset_n\b"), 0),
    ],
    "dst_mmr": [(P13, re.compile(r"^MMR_Trdstcontrol_F_Trdstempty_WrEn$"), 1)],
    "dst_sink_mmr": [
        (P13, re.compile(r"^MMR_Trdstramcontrol_F_Trdstramempty_WrEn$"), 1),
        (
            P25,
            re.compile(
                r"^DstSinkMmr(?:Trdstramcontrol\w*\.Trdstram(?:stoponwrap|mode|active)WrEn"
                r"|Trdstram(?:startlow|starthigh|limitlow|limithigh|rphigh)Wr\.\w*WrEn)$"
            ),
            0,
        ),
    ],
    "trace_wrapper": [
        (P13, re.compile(r"^(?:dst_sink|funnel|dst)_gated_func_clamp\b"), 0),
        (P13, re.compile(r"^(?:ntr_sink|ntr)_gated_func_clamp\b"), 1),
    ],
    "trace_axi_master": [(F3, re.compile(r"^axi_resp_i\.(?:aw_ready|w_ready|b_valid)$"), 0)],
}

# Decisions on an elaboration-time constant: (class, condition, value it holds).
BRANCH_CONSTANT_DECISIONS: "dict[str, list[tuple[str, str, int]]]" = {
    "trace_sink": [(P17, "NUM_CORES>1", 0)],
    **{
        block: [(P5, "instr_type==2'b01", 0), (P5, "instr_type==2'b10", 0)]
        for block in ("cla_mmr", "dst_mmr", "dst_sink_mmr", "funnel_mmr")
    },
}

# Case items no path reaches, per case condition: (class, condition, items).
BRANCH_DEAD_CASE_ITEMS: "dict[str, list[tuple[str, str, frozenset[str]]]]" = {
    "i2c_target_fsm": [(P20, "tcount_sel", frozenset({"tNoDelay", "default"}))],
    "i2c_controller_fsm": [(P20, "tcount_sel", frozenset({"default"}))],
}

# Case items of a state F3 leaves unreachable.
BRANCH_DEAD_ITEMS: "dict[str, tuple[str, frozenset[str]]]" = {
    "trace_axi_master": (F3, frozenset({"AW_HANDSHAKE", "W_HANDSHAKE", "RESP_HANDSHAKE"})),
}


# Signals the source defines from others: (class, name, what it stands for).
SIGNAL_IDENTITIES: "dict[str, list[tuple[str, str, str]]]" = {
    "uart_core": [(C5, "rx_enable", "tx_enable")],
    "system_timer_octs_core": [(C5, "credit_gen_pulse", "(credit_gen_pulse && enable)")],
    # smc_dfd_wrap drives every present block's clock-disable control from one net.
    "mmrs": [
        (P22, "i_dst_clk_dis_ctrl", "i_cla_clk_dis_ctrl"),
        (P22, "i_dst_sink_clk_dis_ctrl", "i_cla_clk_dis_ctrl"),
        (P22, "i_funnel_clk_dis_ctrl", "i_cla_clk_dis_ctrl"),
    ],
}


def _tie_ntrace(term: str) -> str:
    """A term with each comparison over N-trace signals alone replaced by its tied value."""

    def tie(m: re.Match) -> str:
        body = re.sub(r"\$bits\([^()]*\)'\s*", "", m.group(0))
        if not is_ntrace_term(body):
            return m.group(0)
        value = tied_value(body)
        return m.group(0) if value is None else ("1'b1" if value else "1'b0")

    before = None
    while before != term:
        before = term
        term = COMPARISON.sub(tie, term)
    return term


def feature_row_class(module: str, terms: "tuple[str, ...] | None", vector: str) -> "str | None":
    """The feature class whose held signals put a condition row out of reach, or None.

    Each comparison is one opaque truth value here, as on the branch paths.
    """
    if not terms:
        return None
    facts = BRANCH_PATH_FACTS.get(module, [])
    ntrace = any(r == P1 for r, _, _ in facts)
    names: dict[str, str] = {}
    plain = []
    for term in terms:
        text = _opaque(_one_bit(_tie_ntrace(term) if ntrace else term), names)
        if text is None:
            return None
        plain.append(text)
    for reason, forced, value in BRANCH_PATH_FACTS.get(module, []):
        if needs_forced_away(plain, vector, _scoped(forced), value):
            return reason
    if facts:
        # Held together: a row out of reach only jointly is credited to the first
        # class whose signals it names, or to P1 when an N-trace comparison decided it.
        free = []
        opened: dict[str, str] = {}
        for term in terms:
            text = _opaque(_one_bit(term), opened)
            if text is None:
                return None
            free.append(text)
        held = [(_scoped(forced), value) for _, forced, value in facts]
        # A row too wide to enumerate free is still out of reach when the held signals
        # alone rule it out; only a row the free check shows impossible is left to C1.
        if (
            _row_satisfiable_held(tuple(plain), vector, held) is False
            and _row_satisfiable(tuple(free), vector, None, 0) is not False
        ):
            ids = [n for t in plain for n in LANE_IDENTIFIER.findall(t)]
            for reason, forced, _ in facts:
                if any(_scoped(forced).search(n) for n in ids):
                    return reason
            if ntrace:
                return P1
    identities = SIGNAL_IDENTITIES.get(module, [])
    if identities:
        rewritten = tuple(plain)
        for _, name, meaning in identities:
            rewritten = tuple(re.sub(rf"\b{re.escape(name)}\b", meaning, t) for t in rewritten)
        held = [(_scoped(forced), value) for _, forced, value in facts]
        if rewritten != tuple(plain) and _row_satisfiable_held(rewritten, vector, held) is False:
            if _row_satisfiable(tuple(plain), vector, None, 0):
                return identities[0][0]
    return None


def feature_path_class(
    module: str, construct: "BranchConstruct", values: tuple[str, ...]
) -> "str | None":
    """The feature class that forbids a branch path, or None."""
    dead = BRANCH_DEAD_ITEMS.get(module)
    if dead and construct.decisions[0][0] == "case" and values[0] in dead[1]:
        return dead[0]
    for reason, condition, items in BRANCH_DEAD_CASE_ITEMS.get(module, []):
        for (kind, text), taken in zip(construct.decisions, values):
            if kind == "case" and _bare(text) == condition and taken in items:
                return reason
    for reason, condition, value in BRANCH_CONSTANT_DECISIONS.get(module, []):
        for (_, text), taken in zip(construct.decisions, values):
            if _bare(text) == condition and taken in ("0", "1") and int(taken) != value:
                return reason
    for reason, forced, value in BRANCH_PATH_FACTS.get(module, []):
        if path_needs_forced_away(construct, values, forced, value):
            return reason
    if any(r == P1 for r, _, _ in BRANCH_PATH_FACTS.get(module, [])):
        # A decision over N-trace signals alone holds the value P1's tie-off
        # gives it, comparisons included; a width cast does not change it.
        for (kind, text), taken in zip(construct.decisions, values):
            if taken not in ("0", "1") or kind not in ("if", "?") or not text:
                continue
            term = re.sub(r"\$bits\([^()]*\)'\s*", "", text)
            if is_ntrace_term(term) and tied_value(term) not in (None, int(taken)):
                return P1
    return None


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


# Per-block signals a fact holds at one value, as (class, signals, value). A row
# or a branch path is written when it is out of reach with the signals held and
# within reach with them free. The UART demux never selects the write-only map
# on the read channel, so that block's AR valid stays low, nothing sets its
# arvalid register or ar_accept, every request it sees is a write, and its read
# acks (readback_done and the external read ack, which it generates as zero)
# never rise.
# Blocks whose external registers are all acked the cycle they are requested.
EXTERNAL_ACK_BLOCKS = frozenset(
    {
        "i2c_reg",
        "cpu_ctrl_reg",
        "uart_16550_main_reg",
        "uart_16550_main_wo_reg",
        "system_timer_octs_reg",
        "reset_unit_reg",
        "avsbus_controller_reg",
    }
)
STALL_OR_PENDING = re.compile(r"^(?:cpuif_req_stall_(?:rd|wr)|external_pending)\b")
PENDING_SET = re.compile(
    r"^\(decoded_req_is_external & \(\(~external_wr_ack\)\) & \(\(~external_rd_ack\)\)\)$"
)

# Logic that consumes a register block's external req, and the blocks whose req it reads.
REQ_CONSUMERS: "dict[str, tuple[str, ...]]" = {
    "i2c_core": ("i2c_reg",),
    "uart_core": ("uart_16550_main_reg", "uart_16550_main_wo_reg"),
    "avsbus_controller": ("avsbus_controller_reg",),
}

REGBLOCK_PATH_FACTS: "dict[str, list[tuple[str, re.Pattern[str], int]]]" = {
    "idma_reg64_2d_reg_top": [(A5, re.compile(r"^devmode_i$"), 0)],
    "output_remap_reg": [(A9, re.compile(r"^(?:cpuif_addr|rd_mux_addr)$"), 0)],
    "uart_log_engine_ctrl_reg": [(A9, re.compile(r"^(?:cpuif_addr|rd_mux_addr)$"), 0)],
    "uart_16550_main_reg": [(C3, re.compile(r"^external_wr_ack$"), 0)],
    "dfx_ctrl_status_reg": [
        (
            B7,
            re.compile(
                r"^(?:hwif_in\.STATUS_SMU\.(?:mem_repair_done|mem_repair_success|mbist_done"
                r"|mbist_pass)\.next|field_combo\.STATUS_SMU\.(?:mem_repair_done"
                r"|mem_repair_success|mbist_done|mbist_pass)\.load_next)$"
            ),
            1,
        )
    ],
    "uart_16550_main_wo_reg": [
        (
            A3,
            re.compile(
                r"^(?:(?:s_)?axil_arvalid|axil_ar_accept|cpuif_rd_ack|readback_done"
                r"|(?:readback_)?external_rd_ack)$"
            ),
            0,
        )
    ],
}

# module -> [(class, expression pattern, term-vector pattern or None)]. These
# are facts about one block, checked against its own source, not about a
# family. The vector pattern pins which row of a multi-term expression the
# fact covers, so a sibling row that an access can reach stays graded.
EXTRA_FACTS: "dict[str, list[tuple[str, object, object]]]" = {
    "uart_16550_main_wo_reg": [
        (A3, re.compile(r"^\(\(\(!\w*arvalid\)\)"), re.compile(r"^0")),
        (A3, re.compile(r"^\(\w*arvalid &&"), re.compile(r"^1")),
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


class Point(NamedTuple):
    """One condition point of the report: an EXPRESSION or a SUB-EXPRESSION table."""

    text: str
    line: int
    sub: bool
    uncovered: frozenset[str]
    terms: "tuple[str, ...] | None"


NUMBERED_TERM = re.compile(r"^\s*\d+\s+(\S.*?)\s*$")
TERM_OPERATOR = re.compile(r"\s(\|\||&&|\||&|\^|\+)$")


def report_points(modinfo: Path) -> dict[str, list[Point]]:
    """module -> every condition point of the report, top-level and sub-expression, in order.

    urg prints most expressions on one line with their terms underlined beneath.
    One too long for that is printed as a numbered list, one term per row, each
    row but the last ending in the operator that joins it to the next and the
    last carrying the expression's closing parenthesis; a long XOR network and a
    one-term ternary are the same list with single-token or single terms.
    """
    out: dict[str, list[Point]] = {}
    module = ""
    in_cond = False
    lineno = 0
    cur: dict | None = None
    mode = ""

    def close() -> None:
        if cur is not None and cur["text"]:
            out.setdefault(module, []).append(
                Point(
                    cur["text"],
                    cur["line"],
                    cur["sub"],
                    frozenset(cur["unc"]),
                    tuple(cur["terms"]) if cur["terms"] else None,
                )
            )

    for line in modinfo.read_text(errors="replace").splitlines():
        m = re.match(r"^(\w+) Coverage for Module : (\S+)", line)
        if m:
            close()
            cur = None
            in_cond = m.group(1) == "Cond"
            module = m.group(2).split("(")[0]
            continue
        if not in_cond:
            continue
        m = re.match(r"^\s*LINE\s+(\d+)\s*$", line)
        if m:
            lineno = int(m.group(1))
            continue
        m = re.match(r"^\s*(SUB-EXPRESSION|EXPRESSION)(?: (.*))?$", line)
        if m:
            close()
            text = (m.group(2) or "").strip()
            cur = {
                "text": text,
                "line": lineno,
                "sub": m.group(1) == "SUB-EXPRESSION",
                "unc": set(),
                "terms": None,
                "parts": [],
            }
            mode = "underline" if text else "numbered"
            col = line.index(m.group(2)) if m.group(2) else 0
            continue
        if cur is None:
            continue
        if mode == "underline":
            spans = [(s.start(), s.end(), s.group(0)) for s in re.finditer(r"-+\d+-+", line)]
            if spans:
                cur["terms"] = [
                    term
                    for _, term in sorted(
                        (
                            int(re.sub(r"\D", "", tok)),
                            cur["text"][max(0, s - col) : e - col].strip(),
                        )
                        for s, e, tok in spans
                    )
                ]
            mode = "rows"
            continue
        if mode == "numbered":
            m = NUMBERED_TERM.match(line)
            if m and m.group(1) != "Term":
                body = m.group(1)
                op = TERM_OPERATOR.search(body)
                if op:
                    cur["parts"].append((body[: op.start()].strip(), op.group(1)))
                    continue
                parts = cur["parts"] + [(body[:-1] if body.endswith(")") else body, "")]
                cur["text"] = "(" + " ".join(t + (f" {o}" if o else "") for t, o in parts) + ")"
                cur["terms"] = [t for t, _ in parts]
                mode = "rows"
            continue
        m = re.match(r"^\s*((?:[01]\s+)+)Not Covered", line)
        if m:
            cur["unc"].add(m.group(1).replace(" ", ""))
    close()
    return out


class TemplatePoint(NamedTuple):
    """One condition point of urg's exclusion template, with its rows."""

    text: str
    line: int
    source: str
    rows: tuple[tuple[str, str], ...]


TEMPLATE_SOURCE = re.compile(
    r'^// ANNOTATION: "(?:vcs_gen_start:\S*?:vcs_gen_end:)?FileName: (\S+), LineNumber: (\d+)"'
)
TEMPLATE_CONDITION = re.compile(r'^// (Condition (\d+) "\d+" "(.*) 1 -1"(?: \(\d+ "([01]+)"\))?)$')


def template_points(template: Path) -> dict[str, list[TemplatePoint]]:
    """module -> the condition points of urg's condition template, in template order."""
    raw: dict[str, list[list]] = {}
    module = source = ""
    for line in template.read_text(errors="replace").splitlines():
        m = MODULE_RE.match(line)
        if m:
            module = m.group(1)
            continue
        m = TEMPLATE_SOURCE.match(line)
        if m:
            source = f"{m.group(1)}:{m.group(2)}"
            continue
        m = TEMPLATE_CONDITION.match(line)
        if m is None or not module:
            continue
        points = raw.setdefault(module, [])
        if not points or points[-1][0] != m.group(2):
            points.append([m.group(2), m.group(3), source, []])
        if m.group(4) is not None:
            points[-1][3].append((m.group(4), m.group(1)))
    return {
        mod: [
            TemplatePoint(text, int(src.rpartition(":")[2] or 0), src, tuple(rows))
            for _, text, src, rows in pts
        ]
        for mod, pts in raw.items()
    }


NEGATED = re.compile(r"^\( ~ (.*) \)$")


def _same_point(a: str, b: str) -> bool:
    """The template writes a negated operand as `( ~ X )` where the report tables `X`."""
    na, nb = NEGATED.match(a), NEGATED.match(b)
    return (na.group(1) if na else a) == (nb.group(1) if nb else b)


def align_points(
    report: list[Point], template: list[TemplatePoint]
) -> list[tuple[TemplatePoint, Point]]:
    """Pair each template point with its report point, within one source line at a time.

    The operand of a write, `(decoded_wr_data[0] & decoded_wr_biten[0])`, has the
    same text in every bit-0 field of a block, and a generate loop puts every
    iteration on one line, so neither text nor line alone names a point. Within
    one line both files list the points in the same order. A template point with
    no match is left out, so a layout this does not read fails closed.
    """
    by_line: dict[int, list[Point]] = {}
    for point in report:
        by_line.setdefault(point.line, []).append(point)
    pairs = []
    cursor: dict[int, int] = {}
    for tp in template:
        candidates = by_line.get(tp.line, [])
        k = cursor.get(tp.line, 0)
        while k < len(candidates) and not _same_point(candidates[k].text, tp.text):
            k += 1
        if k < len(candidates):
            pairs.append((tp, candidates[k]))
            cursor[tp.line] = k + 1
    return pairs


_SOURCE_LINES: dict[str, list[str]] = {}


def in_write_branch(source: str) -> bool:
    """Whether a regblock source line is a field's next value inside its software-write branch.

    PeakRDL writes `next_c = ...` under `if(decoded_reg_strb.X && decoded_req_is_wr)
    begin // SW write`, so a condition there is scored only while a write to the
    register is being accepted. The clear-on-write form of a W1C field is left out.
    """
    path, _, line = source.rpartition(":")
    if not line.isdigit():
        return False
    lines = _SOURCE_LINES.setdefault(path, Path(path).read_text(errors="replace").splitlines())
    n = int(line) - 1
    if not 0 <= n < len(lines):
        return False
    stmt = lines[n].strip()
    if not stmt.startswith("next_c") or "~(decoded_wr_data" in stmt.replace(" ", ""):
        return False
    previous = next((lines[k] for k in range(n - 1, max(n - 6, -1), -1) if lines[k].strip()), "")
    return "// SW write" in previous


RETAIN_OPERAND = re.compile(
    r"^\(field_storage\.(\S+)\.value & \(\(~decoded_wr_biten\[([^\]]+)\]\)\)\)$"
)


def singlepulse_value_row(module: str, text: str, vector: str) -> bool:
    """Whether a row asks a singlepulse field's retain operand for the storage at one.

    A6 names a field by the retain-or-write ternary it heads; this rebuilds that
    ternary from the operand to ask the same question of it.
    """
    m = RETAIN_OPERAND.match(text)
    if m is None or not vector.startswith("1"):
        return False
    whole = (
        f"((field_storage.{m.group(1)}.value & ((~decoded_wr_biten[{m.group(2)}]))) | "
        f"(decoded_wr_data[{m.group(2)}] & decoded_wr_biten[{m.group(2)}]))"
    )
    return any(r is A6 and p.search(whole) for r, p, _ in EXTRA_FACTS.get(module, []))


def uncovered_rows(modinfo: Path) -> dict[tuple[str, str], set[str]]:
    """(module, expression) -> set of term vectors the report marks Not Covered.

    Top-level expressions only. A SUB-EXPRESSION table scores an operand of the
    expression above it, and a vector uncovered for an operand is often covered
    for the expression that contains it, so its rows are never merged into the
    parent's; the classes that take operand rows read report_points instead.
    """
    rows: dict[tuple[str, str], set[str]] = {}
    for module, points in report_points(modinfo).items():
        for point in points:
            if not point.sub and point.uncovered:
                rows.setdefault((module, point.text), set()).update(point.uncovered)
    return rows


def branch_status(modinfo: Path) -> dict[tuple[str, int, str], str]:
    """(module, source line, direction) -> the report's status for that branch arm.

    The branch report annotates a construct's source, marks its decision points
    `-1-`, `-2-` and so on, and then scores the paths through them in a table.
    Only a construct with a single decision has one arm per direction, which is
    what a class names; a case statement or a chain of else-ifs scores paths
    across several columns and is left out, so a caller asking about one cannot
    mistake a path for an arm.
    """
    out: dict[tuple[str, int, str], str] = {}
    module = ""
    in_branch = False
    last_src: int | None = None
    construct: int | None = None
    table: str | None = None
    for line in modinfo.read_text(errors="replace").splitlines():
        m = re.match(r"^(\w+) Coverage for (Module|Instance) : (\S+)", line)
        if m:
            in_branch = m.group(1) == "Branch" and m.group(2) == "Module"
            module = m.group(3).split("(")[0]
            last_src = construct = table = None
            continue
        if not in_branch:
            continue
        # A data row such as "1   Covered" also looks like an annotated source
        # line, so the table states are read before the source line is.
        if table == "header":
            if line.strip():
                table = "single" if line.split()[:2] == ["-1-", "Status"] else "multi"
            continue
        if table is not None:
            if not line.strip():
                table = None
                continue
            m = re.match(r"^([01])\s+(Covered|Not Covered)$", line.strip())
            if table == "single" and construct is not None and m:
                out[(module, construct, m.group(1))] = m.group(2)
            continue
        if re.match(r"^\s*Branches:\s*$", line):
            table = "header"
            continue
        if re.match(r"^\s+-1-\s*$", line):
            construct = last_src
            continue
        m = re.match(r"^(\d+)\s", line)
        if m:
            last_src = int(m.group(1))
    return out


def branch_is_uncovered(
    branches: dict[tuple[str, int, str], str], module: str, src: str, direction: str
) -> bool:
    """Whether the report marks this branch arm Not Covered.

    An arm the report does not score as a single-decision construct is not
    written, so a path through a case statement is never mistaken for one.
    """
    line = src.rpartition(":")[2]
    if not line.isdigit():
        return False
    return branches.get((module, int(line), direction)) == "Not Covered"


class BranchConstruct(NamedTuple):
    """One branch construct of the report: its decisions and the status of each path."""

    line: int
    decisions: "tuple[tuple[str, str | None], ...]"
    paths: "tuple[tuple[tuple[str, ...], str], ...]"


class BranchTemplate(NamedTuple):
    """One branch construct of urg's exclusion template, with an entry per path."""

    line: int
    source: str
    condition: str
    paths: "tuple[tuple[tuple[str, ...], str], ...]"


REPORT_SOURCE_LINE = re.compile(r"^(\d+)\s+\S")
DECISION_MARK = re.compile(r"-(\d+)-")
UNANNOTATED_DECISION = re.compile(r"^\s+-(\d+)-\s+(?!-\d+-)(\S.*?)\s*$")
DECISION_KEYWORD = re.compile(r"(?:end\s+)?(?:else\s+)?(?:unique\s+|priority\s+)?(if|case)\s*(\()")
TEMPLATE_BRANCH_ROW = re.compile(r'^// (Branch (\d+) "\d+" "(.*)" \(\d+\) "(.*)")$')
TEMPLATE_BRANCH_HEAD = re.compile(r'^// Branch (\d+) "\d+" "(.*)"$')


def _parenthesised(text: str, start: int) -> "str | None":
    """The balanced parenthesised text that opens at text[start]."""
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "(":
            depth += 1
        elif text[i] == ")":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return None


def _ternary_selector(text: str, question: int) -> "str | None":
    """The operand left of the `?` at text[question], read back to its delimiter."""
    depth = 0
    i = question - 1
    while i >= 0:
        c = text[i]
        if c in ")]}":
            depth += 1
        elif c in "([{":
            if depth == 0:
                break
            depth -= 1
        elif depth == 0 and c in ":?,;":
            break
        elif depth == 0 and c == "=":
            if i > 0 and text[i - 1] in "=!<>":
                i -= 2
                continue
            if i + 1 < len(text) and text[i + 1] == "=":
                i -= 1
                continue
            break
        i -= 1
    return text[i + 1 : question].strip() or None


def _decision(source_line: str, column: int) -> "tuple[str, str | None]":
    """(kind, condition) of the decision whose marker sits at this column of a source line.

    The report writes each `-N-` marker under the `if`, `case` or `?` it numbers,
    in the same columns as the annotated source line above it. A condition that
    continues onto the next line is not read and gives None.
    """
    m = re.match(r"^\d+\s+", source_line)
    low = m.end() if m else 0
    if column < len(source_line) and source_line[column] == "?":
        return ("?", _ternary_selector(source_line[low:], column - low))
    m = DECISION_KEYWORD.match(source_line[column:])
    if m:
        return (m.group(1), _parenthesised(source_line[column:], m.start(2)))
    return ("", None)


def _continued_selector(source_line: str) -> "str | None":
    """The right-hand side of an assignment line, when it is one balanced term."""
    body = re.sub(r"^\d+\s+", "", source_line).strip()
    m = re.match(r"^(?:assign\s+)?[\w.\[\]]+\s*=\s*(.+)$", body)
    if m is None:
        return None
    rhs = m.group(1).strip()
    if rhs.startswith("(") and _parenthesised(rhs, 0) == rhs:
        return rhs
    return None


def branch_constructs(modinfo: Path) -> dict[str, list[BranchConstruct]]:
    """module -> every branch construct of the report, in report order, all paths included."""
    out: dict[str, list[BranchConstruct]] = {}
    lines = modinfo.read_text(errors="replace").splitlines()
    module = None
    last: "tuple[int, str] | None" = None
    previous: "tuple[int, str] | None" = None
    decisions: dict[int, tuple[str, str | None]] = {}
    first: "int | None" = None
    i = 0
    while i < len(lines):
        line = lines[i]
        m = re.match(r"^(\w+) Coverage for (Module|Instance) : (\S+?)(?:\(|\s|$)", line)
        if m:
            module = m.group(3) if m.group(1) == "Branch" and m.group(2) == "Module" else None
            last, decisions, first = None, {}, None
            i += 1
            continue
        if module is None:
            i += 1
            continue
        if line.startswith("Branches:"):
            j = i + 1
            while j < len(lines) and not lines[j].strip():
                j += 1
            width = len(lines[j].split()) - 1 if j < len(lines) else 0
            k = j + 1
            paths = []
            while k < len(lines) and lines[k].strip():
                tokens = lines[k].split()
                if tokens[-2:] == ["Not", "Covered"]:
                    paths.append((tuple(tokens[:-2]), "Not Covered"))
                elif tokens[-1:] == ["Covered"]:
                    paths.append((tuple(tokens[:-1]), "Covered"))
                k += 1
            if first is not None:
                columns = tuple(decisions.get(n, ("", None)) for n in range(1, width + 1))
                out.setdefault(module, []).append(BranchConstruct(first, columns, tuple(paths)))
            last, decisions, first = None, {}, None
            i = k
            continue
        m = REPORT_SOURCE_LINE.match(line)
        listed = UNANNOTATED_DECISION.match(line)
        if m:
            previous = last
            last = (int(m.group(1)), line)
        elif listed and last is not None:
            # The report lists the decisions of a construct it cannot annotate
            # in place, one per line, beneath the source line.
            n, text = int(listed.group(1)), listed.group(2)
            if text.endswith(" ? ...;"):
                decisions[n] = ("?", text[: -len(" ? ...;")])
            else:
                decisions[n] = _decision(text, 0)
            if n == 1:
                first = last[0]
        elif last is not None:
            for mark in DECISION_MARK.finditer(line):
                n = int(mark.group(1))
                decisions[n] = _decision(last[1], mark.start())
                if decisions[n] == ("?", None) and previous is not None:
                    # A ternary whose `?` opens its own line takes its
                    # selector from the right-hand side of the line above.
                    decisions[n] = ("?", _continued_selector(previous[1]))
                if n == 1:
                    first = last[0]
        i += 1
    return out


def _path_values(path: str) -> tuple[str, ...]:
    return tuple(re.sub(r"\s+", "", path).split(","))


def branch_templates(template: Path) -> dict[str, list[BranchTemplate]]:
    """module -> every branch construct of urg's branch template, in template order."""
    out: dict[str, list[BranchTemplate]] = {}
    module = source = ""
    for line in template.read_text(errors="replace").splitlines():
        m = MODULE_RE.match(line)
        if m:
            module = m.group(1)
            continue
        m = TEMPLATE_SOURCE.match(line)
        if m:
            source = f"{m.group(1)}:{m.group(2)}"
            continue
        m = TEMPLATE_BRANCH_ROW.match(line)
        if m and module:
            construct = out[module][-1]
            if not m.group(4).startswith(m.group(3) + " "):
                continue
            path = _path_values(m.group(4)[len(m.group(3)) + 1 :])
            out[module][-1] = construct._replace(paths=construct.paths + ((path, m.group(1)),))
            continue
        m = TEMPLATE_BRANCH_HEAD.match(line)
        if m and module:
            line_no = int(source.rpartition(":")[2] or 0)
            out.setdefault(module, []).append(BranchTemplate(line_no, source, m.group(2), ()))
    return out


def _bare(condition: "str | None") -> str:
    """A condition without spaces, outer parentheses or the value of a loop index."""
    text = re.sub(r"\[\w+\]", "[]", re.sub(r"\s+", "", condition or ""))
    while text.startswith("(") and _parenthesised(text, 0) == text:
        text = text[1:-1]
    return text


def _construct_key(condition: "str | None") -> str:
    """A first decision as both sides print it: the template escapes quotes,
    parenthesises each operand, folds a `$bits(...)'` cast to its width and
    drops a binary literal's leading zeros, and the annotated source does none
    of these."""
    text = (condition or "").replace('\\"', '"')
    text = re.sub(r"\$bits\([^()]*\)'\s*|\b\d+'(?=\s*\()", "", text)
    text = re.sub(r"\b(\d+'[bB])0+(?=[01])", r"\1", text)
    return re.sub(r"[()]", "", _bare(text))


def align_branches(
    report: list[BranchConstruct], template: list[BranchTemplate]
) -> list[tuple[BranchTemplate, BranchConstruct]]:
    """Pair template constructs with report constructs whose first decision reads the same.

    A generate loop repeats one construct at one line, so constructs are paired
    by their order within a line. The template dates a decision inside an
    instance's port list from the instance's first line and the report from the
    decision's own, so what is left is paired by condition, in order, a few lines
    on, and only where both sides hold the same number of that condition.
    """
    by_line: dict[int, list[BranchConstruct]] = {}
    for c in report:
        by_line.setdefault(c.line, []).append(c)
    seen: dict[int, int] = {}
    out = []
    used: set[int] = set()
    left: list[BranchTemplate] = []
    for t in template:
        n = seen.get(t.line, 0)
        seen[t.line] = n + 1
        candidates = by_line.get(t.line, [])
        c = candidates[n] if n < len(candidates) else None
        if (
            c is not None
            and c.decisions
            and _construct_key(c.decisions[0][1]) == _construct_key(t.condition)
        ):
            out.append((t, c))
            used.add(id(c))
        else:
            left.append(t)
    rest: dict[str, list[BranchConstruct]] = {}
    for c in report:
        if id(c) not in used and c.decisions:
            rest.setdefault(_construct_key(c.decisions[0][1]), []).append(c)
    wanted: dict[str, list[BranchTemplate]] = {}
    for t in left:
        wanted.setdefault(_construct_key(t.condition), []).append(t)
    for key, ts in wanted.items():
        cs = rest.get(key, [])
        if len(cs) != len(ts):
            continue
        pairs = list(zip(ts, cs))
        if all(0 < c.line - t.line <= 16 for t, c in pairs):
            out += pairs
    return out


# A comparison is one opaque truth value to the evaluator: its two sides are
# wider than a bit, so reading them as bits could invent a contradiction. The
# same comparison text is the same value wherever it recurs in one path.
COMPARISON = re.compile(r"\(([^()]*?[^=!<>])\s*(==|!=|>=|<=|>|<)\s*([^=<>][^()]*?)\)")


def _opaque(condition: str, names: dict[str, str]) -> "str | None":
    before = None
    while before != condition:
        before = condition
        condition = COMPARISON.sub(
            lambda m: names.setdefault(m.group(0), f"cmp{len(names)}_"), condition
        )
    if re.search(r"==|!=|>=|<=|(?<![<>])[<>](?![<>])", condition):
        return None
    return condition


def _binary_decisions(
    construct: BranchConstruct, values: tuple[str, ...]
) -> "tuple[list[str], str] | None":
    """The if and ternary decisions a path takes, as conditions and one bit each."""
    names: dict[str, str] = {}
    terms, vector = [], ""
    for (kind, condition), value in zip(construct.decisions, values):
        if value not in ("0", "1") or kind not in ("if", "?") or not condition:
            continue
        term = _opaque(condition, names)
        if term is None:
            return None
        terms.append(term)
        vector += value
    return terms, vector


def contradictory_path(construct: BranchConstruct, values: tuple[str, ...]) -> bool:
    """Whether a path's own decisions, read over the same signals, have no common solution."""
    decided = _binary_decisions(construct, values)
    if decided is None or len(decided[0]) < 2:
        return False
    return _row_satisfiable(tuple(decided[0]), decided[1], None, 0) is False


def path_needs_forced_away(
    construct: BranchConstruct,
    values: tuple[str, ...],
    forced: "re.Pattern[str]",
    value: int,
) -> bool:
    """Whether one decision of the path is out of reach with the forced signals held."""
    for (kind, condition), taken in zip(construct.decisions, values):
        if taken not in ("0", "1") or kind not in ("if", "?") or not condition:
            continue
        term = _opaque(_one_bit(condition), {})
        if term is not None and needs_forced_away([term], taken, _scoped(forced), value):
            return True
    return False


def _one_bit(condition: str) -> str:
    """A condition with plusarg tests named and one-bit literal compares read as the bit.

    `X == 1'b1` holds exactly when X is one wherever X is held at zero or one,
    which is all a forced-signal test asks of it.
    """
    condition = re.sub(r'\$test\$plusargs\("(\w+)"\)', r"plusarg_\1", condition)
    names: dict[str, str] = {}
    condition = re.sub(
        r"\$value\$plusargs\([^()]*\)",
        lambda m: names.setdefault(m.group(0), f"value_plusarg{len(names)}"),
        condition,
    )
    condition = re.sub(r"\b([A-Za-z_]\w*)\s*==\s*1'b1\b", r"\1", condition)
    condition = re.sub(r"\b([A-Za-z_]\w*)\s*==\s*1'b0\b", r"!\1", condition)
    # A width cast and a replication keep a one-bit value's truth.
    condition = re.sub(r"\$bits\([^()]*\)'\s*(?=\()|\b\d+'(?=\()", "", condition)
    return re.sub(r"\{\s*\w+\s*\{([^{}]*)\}\s*\}", r"(\1)", condition)


def _scoped(pattern: "re.Pattern[str]") -> "re.Pattern[str]":
    """A held-signal pattern that also names the signal under a generate scope."""
    if not pattern.pattern.startswith("^"):
        return pattern
    return re.compile(r"^(?:[A-Za-z_]\w*(?:\[\d+\])?\.)*" + pattern.pattern[1:], pattern.flags)


def singlepulse_load_fields(source: str) -> frozenset[str]:
    """Fields of a generated register block whose load_next is set on every arm."""
    path = Path(source.split(":")[0])
    if not path.is_file():
        return frozenset()
    out = set()
    for m in re.finditer(
        r"always_comb begin(.*?)\n    end\n", path.read_text(errors="replace"), re.S
    ):
        body = m.group(1)
        field = re.search(r"field_combo\.([\w.\[\]]+)\.load_next = load_next_c;", body)
        if field is None or "// singlepulse clears back to 0" not in body:
            continue
        loads = re.findall(r"load_next_c = ([^;]*);", body)
        if loads.count("'0") == 1 and set(loads) == {"'0", "'1"}:
            out.add(re.sub(r"\[\w+\]", "[]", field.group(1)))
    return frozenset(out)


def register_directions(source: str) -> "dict[str, str]":
    """Register name -> the direction its strobe or external req carries, "1" write, "0" read."""
    path = Path(source.split(":")[0])
    if not path.is_file():
        return {}
    text = path.read_text(errors="replace")
    out: dict[str, str] = {}
    for m in re.finditer(
        r"decoded_reg_strb\.([\w.]+)\s*=\s*cpuif_req_masked\s*&\s*\([^;]*\)\s*&\s*(!?)cpuif_req_is_wr;",
        text,
    ):
        out[m.group(1)] = "0" if m.group(2) else "1"
    for m in re.finditer(
        r"assign hwif_out\.([\w.]+)\.req\s*=\s*(!?)decoded_req_is_wr\s*\?\s*decoded_reg_strb\.",
        text,
    ):
        out[m.group(1)] = "0" if m.group(2) else "1"
    return out


def _directed(term: str, directions: "dict[str, str]", consumer: bool) -> str:
    """A term with each directed strobe or req written as itself and its direction."""
    if consumer:

        def req(m: re.Match) -> str:
            name = m.group(1).rsplit(".", 1)[-1]
            d = directions.get(name)
            if d is None:
                return m.group(0)
            neg = "" if d == "1" else "!"
            return f"({m.group(0)} && {neg}{m.group(1)}.req_is_wr)"

        return re.sub(r"\b((?:[A-Za-z_]\w*\.)*[A-Za-z_]\w*)\.req\b(?!_is_wr)", req, term)

    def strobe(m: re.Match) -> str:
        d = directions.get(m.group(1))
        if d is None:
            return m.group(0)
        neg = "" if d == "1" else "!"
        return f"({m.group(0)} && {neg}decoded_req_is_wr)"

    return re.sub(r"decoded_reg_strb\.([\w.]+?)(?=[\s)&|]|$)", strobe, term)


def direction_row(
    terms: "tuple[str, ...] | None", vector: str, directions: "dict[str, str]", consumer: bool
) -> bool:
    """Whether a row is satisfiable as written but not with each strobe or req directed."""
    if not terms or len(terms) != len(vector) or not directions:
        return False
    directed = tuple(_directed(t, directions, consumer) for t in terms)
    if directed == tuple(terms):
        return False
    return _row_satisfiable(directed, vector, None, 0) is False and bool(
        _row_satisfiable(tuple(terms), vector, None, 0)
    )


def singlepulse_skip_path(
    construct: BranchConstruct, values: tuple[str, ...], fields: frozenset[str]
) -> bool:
    """Whether a path skips the load of a field whose load_next is always set."""
    for (kind, condition), taken in zip(construct.decisions, values):
        m = re.fullmatch(r"\(field_combo\.([\w.\[\]]+)\.load_next\)", condition or "")
        if kind == "if" and taken == "0" and m and re.sub(r"\[\w+\]", "[]", m.group(1)) in fields:
            return True
    return False


def uncovered_paths(
    report: list[BranchConstruct], template: list[BranchTemplate]
) -> "list[tuple[BranchConstruct, tuple[str, ...], str]]":
    """(construct, path values, template entry) for every path the report marks Not Covered."""
    out = []
    for t, c in align_branches(report, template):
        status = {values: s for values, s in c.paths}
        for values, entry in t.paths:
            if len(values) == len(c.decisions) and status.get(values) == "Not Covered":
                out.append((c, values, entry))
    return out


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


def select_regblock(
    entry: str,
    stall0: bool,
    noerr: bool,
    uncovered: set[str],
    module: str,
    src: str,
    branches: dict[tuple[str, int, str], str],
) -> str | None:
    """Return the class an entry belongs to, or None when it stays graded."""
    m = COND_ROW_RE.match(entry)
    if m:
        expr, vec = m.group(2), m.group(4)
        if vec not in uncovered:
            return None
        if stall0 and STALL_RE.search(expr):
            return A1
        if noerr and ERROR_RE.search(expr):
            return A2
        return None
    m = BRANCH_ROW_RE.match(entry)
    if m:
        cond, direction = m.group(2), m.group(5)
        if direction != "1" or not branch_is_uncovered(branches, module, src, direction):
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


def select_extra(
    module: str,
    entry: str,
    uncovered: dict[tuple[str, str], set[str]],
    src: str,
    branches: dict[tuple[str, int, str], str],
) -> str | None:
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
        if not branch_is_uncovered(branches, module, src, "1"):
            return None
        expr = m.group(2)
    for reason, pattern, vector in EXTRA_FACTS[module]:
        if not pattern.search(expr):
            continue
        if vector is not None and (vec is None or not vector.match(vec)):
            continue
        return reason
    return None


REGBLOCK_CLASSES = (A1, A2, A3, A4, A5, A6, A7, A8, A9, B1, B7, C1, C3, C4)
FEATURE_CLASSES = (
    P1,
    P2,
    P3,
    P4,
    P5,
    P6,
    P7,
    P8,
    P9,
    P10,
    P11,
    P12,
    P13,
    P14,
    P15,
    P16,
    P17,
    P18,
    P19,
    P20,
    P22,
    P24,
    P25,
    C5,
    F3,
    B6,
    B8,
    B9,
)


def metric_blocks(
    templates: dict[str, dict[str, Section]],
    module: str,
    block: list[tuple[str, str]],
    order: tuple[str, ...],
) -> list[str]:
    """A module's entries as one block per metric, each under that metric's checksum.

    urg checks a block's checksum against the metric of the entries it holds, and
    the condition and branch templates give one module different checksums.
    """
    out: list[str] = []
    for metric, kind in (("cond", "Condition "), ("branch", "Branch ")):
        entries = [(r, e) for r, e in block if e.startswith(kind)]
        if not entries:
            continue
        out += ["", f"CHECKSUM: {templates[metric][module].checksum}"]
        out += [f'ANNOTATION: "{r}"' for r in order if any(x == r for x, _ in entries)]
        out.append(f"MODULE: {module}")
        out += [e for _, e in entries]
    return out


def render_regblock(
    templates: dict[str, dict[str, Section]],
    uncovered: dict[tuple[str, str], set[str]],
    branches: dict[tuple[str, int, str], str],
    report_points_by_module: dict[str, list[Point]],
    template_points_by_module: dict[str, list[TemplatePoint]],
    paths: "dict[str, list[tuple[BranchConstruct, tuple[str, ...], str]]]",
    branch_sources: dict[str, str],
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
        "// docstring and the ANNOTATION before each block state each fact and",
        "// which blocks it applies to. B1 is the bench's own and says so.",
        "//==================================================",
    ]
    modules = sorted({m for t in templates.values() for m in t})
    count = 0
    for module in modules:
        block: list[tuple[str, str]] = []
        facts_cache: dict[str, tuple[bool, bool]] = {}
        for metric in ("cond", "branch"):
            section = templates[metric].get(module)
            if section is None:
                continue
            for src, entry in section.entries:
                stall0, noerr = facts_cache.setdefault(
                    src.split(":")[0], regblock_facts(module, src)
                )
                if not (stall0 or noerr):
                    continue
                m = COND_ROW_RE.match(entry)
                rows = uncovered.get((module, m.group(2)), set()) if m else set()
                reason = select_regblock(entry, stall0, noerr, rows, module, src, branches)
                if reason:
                    block.append((reason, entry))
        for src, entry in extra_entries(templates, module):
            reason = select_extra(module, entry, uncovered, src, branches)
            if reason:
                block.append((reason, entry))
        # Then the write-branch rows that need a write lane off: A6's where a
        # singlepulse field's retain operand is asked for the storage at one,
        # which the design forbids at any cpuif width, and B1's for the rest,
        # which only a block no wider than the agent's write leaves unreachable.
        taken = {e for _, e in block}
        tpoints = template_points_by_module.get(module, [])
        width = cpuif_data_width(tpoints[0].source) if tpoints else None
        aligned = align_points(report_points_by_module.get(module, []), tpoints)
        stall0 = bool(tpoints) and regblock_facts(module, tpoints[0].source)[0]
        stall_class = A1 if stall0 else A8 if module in EXTERNAL_ACK_BLOCKS else None
        for tp, rp in aligned if stall_class else ():
            if not is_regblock_source(tp.source):
                continue
            for vector, entry in tp.rows:
                if entry in taken or vector not in rp.uncovered:
                    continue
                if (STALL_RE.search(tp.text) or stall_class == A8) and needs_forced_away(
                    rp.terms, vector, STALL_OR_PENDING if stall_class == A8 else STALL_OPERAND, 0
                ):
                    block.append((stall_class, entry))
                    taken.add(entry)
                elif stall_class == A8 and PENDING_SET.match(tp.text) and vector == "111":
                    block.append((A8, entry))
                    taken.add(entry)
        # Directed strobes and reqs, in the block and in the logic consuming its reqs.
        if tpoints and is_regblock_source(tpoints[0].source):
            directions, consumer = register_directions(tpoints[0].source), False
        else:
            directions, consumer = {}, True
            for owner in REQ_CONSUMERS.get(module, ()):
                owned = template_points_by_module.get(owner, [])
                if owned:
                    directions.update(register_directions(owned[0].source))
        for tp, rp in aligned if directions else ():
            for vector, entry in tp.rows:
                if entry in taken or vector not in rp.uncovered:
                    continue
                if direction_row(rp.terms, vector, directions, consumer):
                    block.append((C4, entry))
                    taken.add(entry)
        for tp, rp in aligned:
            for vector, entry in tp.rows:
                if entry in taken or vector not in rp.uncovered:
                    continue
                for reason, forced, value in REGBLOCK_PATH_FACTS.get(module, []):
                    if needs_forced_away(rp.terms, vector, forced, value):
                        block.append((reason, entry))
                        taken.add(entry)
                        break
        for tp, rp in aligned:
            if not is_regblock_source(tp.source) or "decoded_wr_biten" not in tp.text:
                continue
            if not in_write_branch(tp.source):
                continue
            for vector, entry in tp.rows:
                if entry in taken or vector not in rp.uncovered:
                    continue
                if singlepulse_value_row(module, tp.text, vector):
                    reason = A6
                elif (
                    width is not None
                    and width <= AGENT_WRITE_BITS
                    and needs_lane_off(rp.terms, vector)
                ):
                    reason = B1
                else:
                    continue
                block.append((reason, entry))
                taken.add(entry)
        source = branch_sources.get(module, "")
        if is_regblock_source(source):
            stall = regblock_facts(module, source)[0]
            pulses = singlepulse_load_fields(source)
            for construct, values, entry in paths.get(module, []):
                if entry in taken:
                    continue
                if contradictory_path(construct, values):
                    reason = C1
                elif stall and path_needs_forced_away(construct, values, STALL_OPERAND, 0):
                    reason = A1
                elif module in EXTERNAL_ACK_BLOCKS and path_needs_forced_away(
                    construct, values, STALL_OR_PENDING, 0
                ):
                    reason = A8
                elif singlepulse_skip_path(construct, values, pulses):
                    reason = A7
                else:
                    reason = next(
                        (
                            r
                            for r, forced, value in REGBLOCK_PATH_FACTS.get(module, [])
                            if path_needs_forced_away(construct, values, forced, value)
                        ),
                        None,
                    )
                if reason is None:
                    continue
                block.append((reason, entry))
                taken.add(entry)
        if not block:
            continue
        out += metric_blocks(templates, module, block, REGBLOCK_CLASSES)
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
        "// merged report; regenerate rather than edit. F2 takes the edges into the",
        "// always_comb default's state that no case arm of the source produces, F3 the",
        "// states a tied-off response never lets the master enter, F4 a state whose",
        "// decode arm a parameter leaves unelaborated, F5 the edges that exist only as",
        "// a state register's reset assignment, F6 the edge an enable-edge load cannot",
        "// supply, F7 and F8 the I2C override edges the design forbids from a state, and",
        "// B2 the rest of those override edges, which this bench cannot aim. The",
        "// generator's docstring and the ANNOTATION before each block state the facts.",
        "//==================================================",
    ]
    count = 0
    for module, section in sorted(templates["fsm"].items()):
        fsm = fsm_source = ""
        block: list[tuple[str, str]] = []
        for where, entry in section.entries:
            if entry.startswith("Fsm "):
                fsm, fsm_source = entry.split()[1], where
                if (module, fsm) in FSM_FACTS:
                    block.append(("", entry))
                continue
            facts = FSM_FACTS.get((module, fsm))
            m = FSM_ENTRY_RE.match(entry)
            if not facts or m is None:
                continue
            kind, src, dst = m.group(1), m.group(2), m.group(3)
            edge = f"{src}->{dst}"
            point = edge if kind == "Transition" else src
            if point not in uncovered.get((module, fsm), set()):
                continue
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
                if mode == "override":
                    if dst == target and src not in arms_assigning(fsm_source, target):
                        block.append((reason, entry))
                        break
                    continue
                if mode == "to_default":
                    state, arms = target
                    if dst == state and src not in arms:
                        block.append((reason, entry))
                        break
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
        for reason in (F2, F3, F4, F5, F6, F7, F8, F9, B2, B4):
            if any(r == reason for r, _ in block):
                out.append(f'ANNOTATION: "{reason}"')
        out.append(f"MODULE: {module}")
        out += [e for _, e in block]
        count += sum(1 for r, _ in block if r)
    return "\n".join(out) + "\n", count


def render_feature(
    templates: dict[str, dict[str, Section]],
    uncovered: dict[tuple[str, str], set[str]],
    branches: dict[tuple[str, int, str], str],
    terms: dict[tuple[str, str], list[str]],
    paths: "dict[str, list[tuple[BranchConstruct, tuple[str, ...], str]]]",
    points: "dict[str, list[tuple[TemplatePoint, Point]]]",
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
    modules = sorted(
        set(FEATURE_FACTS)
        | set(FEATURE_BRANCH_FACTS)
        | set(BRANCH_PATH_FACTS)
        | set(BRANCH_CONSTANT_DECISIONS)
        | set(BRANCH_DEAD_ITEMS)
        | set(BRANCH_DEAD_CASE_ITEMS)
        | set(SIGNAL_IDENTITIES)
    )
    for module in modules:
        block: list[tuple[str, str]] = []
        section = templates["cond"].get(module)
        if section is not None:
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
                    if callable(vector):
                        if not vector(terms.get((module, expr), []), vec):
                            continue
                    elif vector is not None and not vector.match(vec):
                        continue
                    if not in_region(src, region):
                        continue
                    block.append((reason, entry))
                    break
        bsection = templates["branch"].get(module)
        if bsection is not None:
            for src, entry in bsection.entries:
                m = BRANCH_ROW_RE.match(entry)
                if m is None:
                    continue
                cond, direction = m.group(2), m.group(5)
                if not branch_is_uncovered(branches, module, src, direction):
                    continue
                for reason, pattern, want in FEATURE_BRANCH_FACTS.get(module, []):
                    if direction == want and pattern.search(cond):
                        block.append((reason, entry))
                        break
            taken = {e for _, e in block}
            for construct, values, entry in paths.get(module, []):
                if entry in taken:
                    continue
                reason = feature_path_class(module, construct, values)
                if reason:
                    block.append((reason, entry))
                    taken.add(entry)
        # The same held signals decide condition rows, operand tables included.
        taken = {e for _, e in block}
        for tp, rp in points.get(module, []):
            for vector, entry in tp.rows:
                if entry in taken or vector not in rp.uncovered:
                    continue
                reason = feature_row_class(module, rp.terms, vector)
                if reason:
                    block.append((reason, entry))
                    taken.add(entry)
        if not block:
            continue
        out += metric_blocks(templates, module, block, FEATURE_CLASSES)
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
    branches = branch_status(args.modinfo)
    report_branches = branch_constructs(args.modinfo)
    template_branches = branch_templates(args.template_dir / "fullexclude_module.branch")
    paths = {
        module: uncovered_paths(report_branches.get(module, []), constructs)
        for module, constructs in template_branches.items()
    }
    branch_sources = {m: c[0].source for m, c in template_branches.items() if c}
    report_points_by_module = report_points(args.modinfo)
    template_points_by_module = template_points(args.template_dir / "fullexclude_module.cond")
    reg_text, reg_n = render_regblock(
        templates,
        uncovered,
        branches,
        report_points_by_module,
        template_points_by_module,
        paths,
        branch_sources,
    )
    xor_text, xor_n = render_xor(templates, uncovered)
    fsm_text, fsm_n = render_fsm(templates, uncovered_fsm(args.modinfo))
    feat_text, feat_n = render_feature(
        templates,
        uncovered,
        branches,
        expression_terms(args.modinfo),
        paths,
        {
            m: align_points(report_points_by_module.get(m, []), tps)
            for m, tps in template_points_by_module.items()
            if m in BRANCH_PATH_FACTS or m in SIGNAL_IDENTITIES
        },
    )
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
