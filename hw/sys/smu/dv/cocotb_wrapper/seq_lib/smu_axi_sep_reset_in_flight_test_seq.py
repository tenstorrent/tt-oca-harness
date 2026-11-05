# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The SEP-facing SMU links across one IC_RESET hold of sep_reset_n with traffic in flight.

The DTP IC_RESET TDR override (ovrd 1, val 0) drives the SEP boot-qualified
reset ``sep_reset_n`` low with the SMC primary reset high
(``hw/sys/sep/doc/reset_controller.adoc``). The SEP-originated producer is the
four-instruction ICCM stub of ``smu_sep_reset_inflight_test`` (``lw t0, 0(a0)``,
``ebreak``, ``sb a1, 0(a0)``, ``ebreak``) written by abstract memory writes and
entered through ``dpc`` with ``dcsr.ebreakm`` set, plus the debug module's
system bus. The SEP route demux sends an SMC-aperture address to the SEP-to-SMC
port and an address in the SEP's SMU window through the outbound filter to
``sep_out`` (``hw/sys/sep/doc/fabric.adoc``). The other initiators are the
bench ext_in master and the DTP JTAG2AXI bridge on smc_out; ext_out is the
bench responder on ``u_axi_out_if``.

S1 SETUP: bring-up, the hart halted, the stub written, ``dcsr.ebreakm``, the
   SEP aperture and the SEP egress outbound filter over the system bus, the
   responder withholding READY and delaying B and R; the reset nets read 1;
   CTRL-G2B-OKAY: one write then read on every route the leaf uses.
S2 SEP2SMC: the stub stores and loads one SMC-aperture word and the system bus
   reads it; per access the link taken, AxUSER, AxPROT and AWATOP are recorded.
S3 LOAD: ext_in reads and writes toward the SEP SRAM with RREADY and BREADY
   withheld, a JTAG2AXI write and read toward the SEP SRAM, and the stub armed
   for one egress store toward the stalled ext_out.
S4 SEP_RESET: the first IC_RESET scan stages the override and carries the
   stub's resume; the store is held at ext_out; the second scan holds
   sep_reset_n low. Every clk_smu_i edge while sep_reset_n is low samples the
   SEP-driven VALIDs of the SEP-to-SMC port and sep_out, B and R VALID of the
   converter output toward the SEP, the crossbar-driven sep_in VALIDs and the
   reset nets. One JTAG2AXI read goes into the SEP aperture during the reset;
   no checker expects its response (OBS-G2B-RESET-ENDS, SF-003).
S5 NONSEP_DURING_RESET: a JTAG2AXI write and read to ext_out and an ext_in
   write and read to the SMC scratchpad while sep_reset_n is low; then the
   override is released and the bench expectation window closes.
S6 RELEASE_LIVENESS: every B and R on smu_in, dtp_dbg and sep_out is held
   against the issue log; the debug module is brought up again, the hart
   halted and the stub rewritten, then one fresh write and read on every S1
   route, a bridge write read back over ext_in or the system bus, and the stub
   store and load to ext_out and to the SMC aperture, with no cold reset before
   them; last, one JTAG2AXI read, observed only (OBS-G2B-J2A-READ-AFTER-HOLD,
   SF-003); the one cold reset of the leaf follows.
S7 TIMEOUT: every wait is bounded in clk_smu_i edges, polls or captures; an
   expiry fails the leaf and is classified as unanswered-transaction evidence.
   The two observed JTAG2AXI reads are capture windows that never fail it.

Observation is passive: the ext_in pins, the request and response structs of
the dtp_dbg, sep_out and SEP-to-SMC links, the ports of the bench checker
instances, the reset nets and the bench expectation-window signals. The bench
protocol checkers and need gates grade under VCS only.
"""

from __future__ import annotations

from collections import Counter

import cocotb
from cocotb.triggers import ClockCycles, RisingEdge
from cocotb.utils import get_sim_time
from env.smu_axi_monitor import smu_axi_monitor
from ocah_axi_vip import RESP_OKAY, clear_profile

from seq_lib.smu_addr_map import OUTBOUND0_END, OUTBOUND0_FILTER_CONFIG, OUTBOUND0_START
from seq_lib.smu_axi_concurrent_initiators_stall_test_seq import EXT_J2A, SPM_LOCAL
from seq_lib.smu_axi_helpers import make_smu_axi_master
from seq_lib.smu_axi_sep_lsu_initiator_stall_test_seq import _LinkTap
from seq_lib.smu_axi_smc_cool_reset_in_flight_test_seq import LINKS
from seq_lib.smu_dtp_sep_dm_dmi_test_seq import (
    DMI_IDLE_TCKS,
    DMI_OP_READ,
    DMI_OP_WRITE,
    pack_dmi,
    unpack_dmi,
)
from seq_lib.smu_dtp_sep_dm_sba_test_seq import (
    EGRESS_ADDR,
    EGRESS_PAGE_END,
    OUTBOUND_CFG_OPEN,
    OUTBOUND_END_ADDR,
    OUTBOUND_FILTER_CONFIG,
    OUTBOUND_START_ADDR,
    SBADDRESS0_ADDR,
    SBCS_ADDR,
    SBCS_SBACCESS_32,
    SBCS_SBBUSY,
    SBCS_SBBUSYERROR,
    SBCS_SBERROR_MASK,
    SBCS_SBERROR_SHIFT,
    SBCS_SBERROR_W1C,
    SBCS_SBREADONADDR,
    SBDATA0_ADDR,
)
from seq_lib.smu_dtp_sep_ic_reset_effect_test_seq import (
    ALL_ONES,
    CAPTURE_POLL_CLK,
    SBA_POLL_LIMIT,
    SEP_HELD,
    SEP_STAGED,
    WSTRB_FULL,
)
from seq_lib.smu_filter_helpers import PASS_ALL_END, PASS_RW_CONFIG
from seq_lib.smu_jtag_helpers import (
    DTP_DEFAULT_IDCODE,
    DTP_IR_IC_RESET,
    DTP_IR_SMC_AXI_SINGLE_OP,
    J2A_OP_READ,
    J2A_OP_WRITE,
    J2A_STATUS_BUSY,
    J2A_STATUS_SUCCESS,
    SMC_DBG_AXSIZE_8B,
    SMC_DBG_SINGLE_OP_LEN,
    SMU_IC_RESET_LEN,
    pack_single_op,
    unpack_single_op,
)
from seq_lib.smu_sep_reset_inflight_test_seq import (
    AARSIZE_32,
    ABSTRACT_POLLS,
    ABSTRACTCS,
    ABSTRACTCS_BUSY,
    ALLHALTED,
    ALLRESUMEACK,
    CMD_ACCESS_MEMORY,
    CMDERR_MASK,
    CMDERR_SHIFT,
    COMMAND,
    CSR_DCSR,
    CSR_DPC,
    DATA0,
    DATA1,
    DCSR_EBREAKM_M,
    DMACTIVE,
    DMCONTROL,
    DMSTATUS,
    EBREAK_POLLS,
    HALT_POLLS,
    HALTREQ,
    REG_A0,
    REG_A1,
    RESUMEREQ,
    STUB,
    STUB_LOAD,
    STUB_STORE,
    TRANSFER,
    WRITE,
)
from seq_lib.smu_tb_pins import smc_primary_reset
from seq_lib.smu_xbar_decerr_burst_response_test_seq import _ExtInMonitor, _hx, _rn, _val
from seq_lib.smu_xbar_reset_held_target_test_seq import (
    DURING_ADDR,
    LEVEL_BOUND,
    SEP_WIN_BASE,
    SEP_WIN_SIZE,
    SRAM_GLOBAL,
    TRACE_SPAN,
    WINDOW_CLOSE_BOUND,
    WINDOW_CLOSE_MARGIN,
    XFER_BOUND,
    smu_xbar_reset_held_target_test_seq,
)

EVIDENCE = (
    "CHK-G2B-SEP-VALID-LOW",
    "CHK-G2B-NO-PHANTOM",
    "CHK-G2B-LIVENESS",
    "CHK-G2B-SEP2SMC",
    "CHK-G2B-WINDOW",
    "CHK-NONVAC",
    "CHK-TIMEOUT-PATHS",
)
HOLD = "G2B"

# The four instructions of the stub; the stub's NMI-vector word is not written.
STUB_WORDS = STUB[:4]

# --- addresses: SEP SRAM through the SEP aperture [SEP_WIN_BASE, +SEP_WIN_SIZE) ---
SEP_S1_EXT = SRAM_GLOBAL + 0x100
SEP_S1_J2A = SRAM_GLOBAL + 0x108
SEP_LOAD_WR = (SRAM_GLOBAL + 0x110, SRAM_GLOBAL + 0x118)
SEP_LOAD_J2A_WR = SRAM_GLOBAL + 0x120
SEP_S6_EXT = SRAM_GLOBAL + 0x130
SEP_S6_J2A = SRAM_GLOBAL + 0x138
# SMC scratchpad words (SMC-local offsets, placed through the SMC aperture)
SPM_S1 = SPM_LOCAL + 0x40
SPM_S5 = SPM_LOCAL + 0x48
SPM_S6 = SPM_LOCAL + 0x50
# ext_out words: JTAG2AXI through smc_out, and the stub through sep_out (SEP SMU window)
EXT_J2A_S1 = EXT_J2A
EXT_J2A_S5 = EXT_J2A + 0x100
EGRESS_S1 = EGRESS_ADDR + 0x40
EGRESS_HELD = EGRESS_ADDR + 0x80
EGRESS_S6 = EGRESS_ADDR + 0xC0
# The bridge writes this ext_out word through smc_out; the system bus reads it back through sep_out.
EGRESS_J2A_S6 = EGRESS_ADDR + 0x200

# --- ext_in IDs ---
S1_IDS = {"sep": (0x01, 0x02), "spm": (0x03, 0x04)}
LOAD_ARIDS = (0x11, 0x12)
LOAD_AWIDS = (0x13, 0x14)
S5_IDS = (0x21, 0x22)
S6_IDS = {"sep": (0x31, 0x32), "spm": (0x33, 0x34)}
S6_J2A_READBACK_ARID = 0x35

# --- words ---
W_S1_EXT = 0x6201_0001_6201_0002
W_S1_J2A = 0x6201_0003_6201_0004
W_S1_SPM = 0x6201_0005_6201_0006
W_S1_EXT_OUT = 0x6201_0007_6201_0008
W_LOAD = (0x6203_0001_6203_0002, 0x6203_0003_6203_0004)
W_LOAD_J2A = 0x6203_0005_6203_0006
W_S5_EXT_OUT = 0x6205_0001_6205_0002
W_S5_SPM = 0x6205_0003_6205_0004
W_S6_EXT = 0x6206_0001_6206_0002
W_S6_J2A = 0x6206_0003_6206_0004
W_S6_SPM = 0x6206_0005_6206_0006
W_S6_EXT_OUT = 0x6206_0007_6206_0008
# the byte each stub store writes, one per access
BYTE = {"s1": 0xA1, "s2": 0xA2, "s3": 0xA3, "s6_ext": 0xA6, "s6_smc": 0xA7}

# --- responder: READY withheld in bounded windows and B/R delayed (S1 on); the held store ---
RESP_STALL = 16
RESP_DELAY = 32
RESPONDER_GUARD = 40_000

# --- bounds, clk_smu_i edges unless named ---
EGRESS_BOUND = 4_000
LOAD_ACCEPT_BOUND = 4_000
OBS_BOUND = 20_000
J2A_LOAD_CAPTURES = 4
J2A_OBS_CAPTURES = 16
J2A_IDLE_POLLS = 32
FALL_SEEN_BOUND = 4

FENCE = (
    "SETUP",
    "SEP2SMC",
    "LOAD",
    "SEP_RESET",
    "NONSEP_DURING_RESET",
    "RELEASE_LIVENESS",
)
KINDS = ("j2a", "dmi", "ext_in", "ic_reset")
# Access budget per term (contract steps S1-S6): JTAG2AXI, DMI/system-bus, ext_in, IC_RESET scans.
BUDGET = {
    "SETUP": {"j2a": 4, "dmi": 18, "ext_in": 4, "ic_reset": 0},
    "SEP2SMC": {"j2a": 0, "dmi": 8, "ext_in": 0, "ic_reset": 0},
    "LOAD": {"j2a": 2, "dmi": 3, "ext_in": 4, "ic_reset": 0},
    "SEP_RESET": {"j2a": 1, "dmi": 1, "ext_in": 0, "ic_reset": 2},
    "NONSEP_DURING_RESET": {"j2a": 2, "dmi": 0, "ext_in": 2, "ic_reset": 2},
    "RELEASE_LIVENESS": {"j2a": 3, "dmi": 28, "ext_in": 5, "ic_reset": 0},
}
# Planned count per term: routes, SMC-aperture accesses, ext_in requests outstanding plus the armed
# stub store, edges with sep_reset_n low, accesses issued during the reset, fresh routes after the
# release.
PLANNED = {
    "SETUP": 5,
    "SEP2SMC": 3,
    "LOAD": 5,
    "SEP_RESET": 2,
    "NONSEP_DURING_RESET": 4,
    "RELEASE_LIVENESS": 6,
}
# Requests outstanding at the fall of sep_reset_n per port. The dtp_dbg cell is not drivable: see
# DTP_NOT_DRIVABLE.
OUTSTANDING_PLAN = {"smu_in": 4, "sep_out": 1}

TAPPED = ("dtp_dbg", "xbar_sep_out", "sep_to_smc", "xbar_sep_in")
SEP_LINKS = ("xbar_sep_out", "sep_to_smc")
# SEP-driven VALIDs graded while sep_reset_n is low, read from the bench checker ports.
GRADED = {
    "sep_to_smc": ("u_sep_to_smc_axi_sva", ("awvalid", "wvalid", "arvalid")),
    "sep_out": ("u_xbar_sep_out_axi_sva", ("awvalid", "wvalid", "arvalid")),
    "iwc_sep": ("u_iwc_sep_axi_sva", ("bvalid", "rvalid")),
}
SEPIN = ("u_xbar_sep_in_axi_sva", ("awvalid", "wvalid", "arvalid", "bvalid", "rvalid"))
NETS = ("sep_reset_n_o", "obs_sep_rst_n_o", "rst_primary_smc_clk_n_o", "obs_xbar_rst_n_o")

DMA_NOT_DRIVABLE = (
    "INFO-CELL-NOT-DRIVABLE: SEP2SMC/secure-DMA hw/sys/sep/doc/fabric.adoc, Transaction "
    "Routing: \"On the SMC path the CPU masters drive SEP's ID and the secure DMA master drives "
    "`OTHERS` (AxUSER zero), and every master drive NS 0\"; this leaf's SEP producers are the "
    "CPU LSU (the stub) and the debug module's system bus, and no bench path drives the SEP "
    "secure DMA without firmware"
)
DTP_NOT_DRIVABLE = (
    "INFO-CELL-NOT-DRIVABLE: LOAD/dtp_dbg JTAG2AXI write and read toward the SEP SRAM outstanding "
    "at the fall; hw/ip/jtag/jtag_ptap/doc/architecture.adoc, *_JTAG2AXI_CAPS rd_pl_depth and "
    'wr_pl_depth: "0 indicates only a single outstanding transaction allowed at any given time", '
    'and *_AXI_SINGLE_OP op: "The latest operation was attempted before the previous operation '
    "completed; the previous AXI request is still in progress. The operation attempted in this "
    'access will be ignored"; the bridge drives its own BREADY and RREADY, so the bench cannot '
    "hold its response as it holds the ext_in ones, and the SEP SRAM answers within the S3 "
    "captures, so the one operation the port takes completes before the two IC_RESET scans that "
    "lead to the fall"
)
SMC_APERTURE_ATTRS = (
    "hw/sys/sep/doc/fabric.adoc sep-outbound-attributes-table: SMC aperture, AxUSER the "
    "initiator's, NS the initiator's; the CPU masters drive SEP's ID and NS 0"
)


def _now() -> int:
    return int(get_sim_time(unit="ns"))


def _lane(rdata: int | None, addr: int) -> int | None:
    """The byte at ``addr`` in its 64-bit beat."""
    if rdata is None:
        return None
    return (rdata >> (8 * (addr % 8))) & 0xFF


class smu_axi_sep_reset_in_flight_test_seq(smu_xbar_reset_held_target_test_seq):
    """One IC_RESET hold of sep_reset_n with ext_in, JTAG2AXI and SEP-originated traffic."""

    def __init__(self, test) -> None:
        super().__init__(test)
        test.declare_evidence(*EVIDENCE)
        self.mem = None
        self.term = "SETUP"
        self.used: dict[str, Counter] = {t: Counter() for t in FENCE}
        self.config = Counter()
        self.fence: list[tuple[str, int, int, int]] = []
        self.term_ns: dict[str, int] = {}
        self.taps: dict[str, _LinkTap] = {}
        self.wcyc = 0
        self.watch_on = False
        self.h = {
            "on": False,
            "low": 0,
            "fall": None,
            "rise": None,
            "entry": None,
            "edges": Counter(),
            "high": [],
            "x": [],
            "sepin_high": {sig: [] for sig in SEPIN[1]},
            "sepin_x": 0,
            "nets_bad": [],
            "prim_fall_inside": [],
        }
        self.accesses: list[dict] = []
        self.j2a_ops: list[dict] = []
        self.ext_ops: dict[str, dict] = {}
        self.routes: dict[str, dict] = {}
        self.load: dict[str, object] = {}
        self.override: dict[str, int] = {}
        self.obs: dict[str, object] = {}

    # ------------------------------------------------------------------ bookkeeping

    def _enter(self, term: str, step: str, text: str) -> None:
        self.term = term
        self.term_ns[term] = _now()
        self._info(f"STEP {step}: t={_now()}ns cycle={self.mon.cyc} term={term} {text}")

    def _use(self, kind: str, n: int = 1) -> None:
        self.used[self.term][kind] += n

    def _fence(self, count: int) -> None:
        term = self.term
        self.fence.append((term, self.term_ns[term], count, PLANNED[term]))
        used = " ".join(f"{k}={self.used[term][k]}/{BUDGET[term][k]}" for k in KINDS)
        self._info(
            f"G2B-TERM: {term} t={self.term_ns[term]}ns count={count} planned={PLANNED[term]} "
            f"{used}"
        )

    def _verdict(self, chk: str, observed, expected, line: str) -> None:
        """One compare bound to ``chk``; the evidence line is printed only after it held."""
        try:
            self.sb.expect_eq(f"{chk} graded", observed, expected, evidence=chk)
        except AssertionError as exc:
            self.failures.append(str(exc))
            return
        self.log.info("%s", line)

    def _last(self, name: str) -> str:
        tap = self.taps[name]
        out = {}
        for ch, evs in tap.ev.items():
            if evs:
                e = evs[-1]
                out[ch] = {k: (_hx(v) if isinstance(v, int) else v) for k, v in e.items()}
        return f"{name}: {out}"

    def _nets_text(self) -> str:
        return " ".join(f"{n}={_hx(_val(getattr(self.dut, n)))}" for n in NETS)

    def _classify(self, kind: str, cls: str, what: str, link: str | None = None) -> None:
        last = self._last(link) if link in self.taps else f"ext_in: {self.mon.state()}"
        self._info(
            f"CLASSIFY: kind={kind} class={cls} t={_now()}ns {what}; last={last} {self._nets_text()}"
        )

    def _marks(self) -> dict[str, dict[str, int]]:
        return {name: tap.mark() for name, tap in self.taps.items()}

    def _tsince(self, mks: dict, name: str, ch: str) -> list[dict]:
        return self.taps[name].since(mks[name], ch)

    # ------------------------------------------------------------------ observation

    def _start_taps(self) -> None:
        dut = self.dut
        self.taps = {name: _LinkTap(dut, name, rq, rp) for name, rq, rp in LINKS if name in TAPPED}
        self.watch_on = True
        cocotb.start_soon(self._watch())

    async def _watch(self) -> None:
        """The link taps on every clk_smu_i edge; the hold levels while the hold is armed."""
        dut = self.dut
        h = self.h
        prim = smc_primary_reset(dut)
        graded = {
            link: [(sig, getattr(getattr(dut, inst), sig)) for sig in sigs]
            for link, (inst, sigs) in GRADED.items()
        }
        sepin = [(sig, getattr(getattr(dut, SEPIN[0]), sig)) for sig in SEPIN[1]]
        win = dut.obs_sep_in_expect_window_open
        prev_prim = _val(prim)
        while self.watch_on:
            await RisingEdge(dut.clk_smu_i)
            self.wcyc += 1
            c = self.wcyc
            for tap in self.taps.values():
                tap.sample(c)
            p = _val(prim)
            if _val(win) == 1 and prev_prim == 1 and p != 1:
                h["prim_fall_inside"].append((c, p))
            prev_prim = p
            if not h["on"]:
                continue
            sep = _val(dut.sep_reset_n_o)
            if sep == 0 and h["rise"] is None:
                h["low"] += 1
                k = h["low"]
                levels = {link: {s: _val(hd) for s, hd in sigs} for link, sigs in graded.items()}
                sin = {s: _val(hd) for s, hd in sepin}
                rst = _val(dut.obs_sep_rst_n_o)
                if rst != 1 or p != 1:
                    h["nets_bad"].append((c, rst, p))
                if k == 1:
                    h["fall"] = c
                    h["entry"] = (c, levels, sin)
                else:
                    for link, sv in levels.items():
                        h["edges"][link] += 1
                        for s, v in sv.items():
                            if v != 0:
                                h["high"].append((c, link, s, v))
                for s, v in sin.items():
                    if v is None:
                        h["sepin_x"] += 1
                    elif v != 0:
                        h["sepin_high"][s].append(c)
            elif sep == 1 and h["fall"] is not None and h["rise"] is None:
                h["rise"] = c
            elif sep is None:
                h["x"].append(c)

    async def _obs_until(self, label: str, cond, bound: int) -> int | None:
        """An observation window: ends when ``cond`` holds or after ``bound`` edges; never graded."""
        start = self.mon.cyc
        for used in range(bound + 1):
            if cond():
                self.windows.append(
                    {"label": label, "length": bound, "start": start, "outcome": f"done@{used}"}
                )
                return used
            await RisingEdge(self.dut.clk_smu_i)
        self.windows.append(
            {"label": label, "length": bound, "start": start, "outcome": "not done"}
        )
        return None

    # ------------------------------------------------------------------ debug module

    async def _dm(self, addr: int, data: int, op: int, label: str) -> int:
        return await self._dmi_op(addr, data, op, label, record=False)

    async def _dm_wait(self, mask: int, polls: int, label: str) -> int:
        used, status = 0, 0
        while used < polls:
            status = await self._dm(DMSTATUS, 0, DMI_OP_READ, f"{label}_st{used}")
            used += 1
            if status & mask == mask:
                break
        reached = status & mask == mask
        self._site(
            "dm_status", label, polls, "polls", used, f"dmstatus=0x{status:08x}", not reached
        )
        return used

    async def _abstract(self, command: int, label: str) -> None:
        await self._dm(COMMAND, command, DMI_OP_WRITE, f"{label}_cmd")
        used, status = 0, ABSTRACTCS_BUSY
        while used < ABSTRACT_POLLS:
            status = await self._dm(ABSTRACTCS, 0, DMI_OP_READ, f"{label}_acs{used}")
            used += 1
            if not status & ABSTRACTCS_BUSY:
                break
        self._site(
            "abstract",
            label,
            ABSTRACT_POLLS,
            "polls",
            used,
            f"abstractcs=0x{status:08x}",
            bool(status & ABSTRACTCS_BUSY),
        )
        cmderr = (status >> CMDERR_SHIFT) & CMDERR_MASK
        if cmderr:
            await self._dm(ABSTRACTCS, CMDERR_MASK << CMDERR_SHIFT, DMI_OP_WRITE, f"{label}_clr")
            raise AssertionError(f"abstract command {label} 0x{command:08x} cmderr={cmderr}")

    async def _reg_write(self, regno: int, value: int, label: str) -> None:
        self._use("dmi")
        await self._dm(DATA0, value & 0xFFFF_FFFF, DMI_OP_WRITE, f"{label}_data0")
        await self._abstract(AARSIZE_32 | TRANSFER | WRITE | regno, label)

    async def _mem_write(self, addr: int, value: int, label: str) -> None:
        self._use("dmi")
        await self._dm(DATA1, addr, DMI_OP_WRITE, f"{label}_data1")
        await self._dm(DATA0, value, DMI_OP_WRITE, f"{label}_data0")
        await self._abstract(CMD_ACCESS_MEMORY | AARSIZE_32 | WRITE, label)

    async def _halt(self, label: str) -> int:
        self._use("dmi")
        await self._dm(DMCONTROL, DMACTIVE | HALTREQ, DMI_OP_WRITE, f"{label}_haltreq")
        return await self._dm_wait(ALLHALTED, HALT_POLLS, f"{label}_halt")

    async def _resume(self, label: str) -> int:
        """Resume into the stub and wait, bounded, for its ebreak."""
        self._use("dmi")
        await self._dm(DMCONTROL, DMACTIVE | RESUMEREQ, DMI_OP_WRITE, f"{label}_resumereq")
        return await self._dm_wait(ALLHALTED | ALLRESUMEACK, EBREAK_POLLS, f"{label}_ebreak")

    async def _install_stub(self, tag: str) -> None:
        for addr, insn in STUB_WORDS:
            await self._mem_write(addr, insn, f"{tag}_stub_0x{addr:x}")
        await self._reg_write(CSR_DCSR, DCSR_EBREAKM_M, f"{tag}_dcsr")

    async def _program_egress(self, tag: str) -> None:
        """SEP outbound filter entry over the egress page, over the system bus."""
        for addr, data, name in (
            (OUTBOUND_START_ADDR, EGRESS_ADDR, "start"),
            (OUTBOUND_END_ADDR, EGRESS_PAGE_END, "end"),
            (OUTBOUND_FILTER_CONFIG, OUTBOUND_CFG_OPEN, "config"),
        ):
            self._use("dmi")
            await self._sba_write(addr, data, f"{tag}_egress_{name}")

    async def _aperture(self, tag: str) -> dict:
        self._use("dmi", 2)
        return await self._program_sep_aperture(tag)

    async def _sba_read_obs(self, addr: int, label: str) -> tuple[int, int | None]:
        """A system-bus read whose error code is recorded, not raised; the busy poll is bounded."""
        self._use("dmi")
        await self._dm(
            SBCS_ADDR,
            SBCS_SBACCESS_32 | SBCS_SBREADONADDR | SBCS_SBERROR_W1C,
            DMI_OP_WRITE,
            f"{label}_sbcs",
        )
        await self._dm(SBADDRESS0_ADDR, addr, DMI_OP_WRITE, f"{label}_addr")
        used, sbcs = 0, SBCS_SBBUSY
        while used < SBA_POLL_LIMIT:
            sbcs = await self._dm(SBCS_ADDR, 0, DMI_OP_READ, f"{label}_sbcs{used}")
            used += 1
            if not sbcs & SBCS_SBBUSY:
                break
        self._site(
            "sba_busy",
            label,
            SBA_POLL_LIMIT,
            "polls",
            used,
            f"sbcs=0x{sbcs:08x}",
            bool(sbcs & SBCS_SBBUSY),
        )
        err = (sbcs >> SBCS_SBERROR_SHIFT) & SBCS_SBERROR_MASK
        if err or sbcs & SBCS_SBBUSYERROR:
            await self._dm(
                SBCS_ADDR, SBCS_SBERROR_W1C | SBCS_SBBUSYERROR, DMI_OP_WRITE, f"{label}_clr"
            )
            return err or 8, None
        return 0, await self._dm(SBDATA0_ADDR, 0, DMI_OP_READ, f"{label}_data")

    # ------------------------------------------------------------------ SEP accesses

    def _requests(self, mks: dict, ch: str, addr: int) -> list[tuple[str, dict]]:
        """The access's request on sep_out (by address) or on the SEP-to-SMC port.

        The SEP-to-SMC request is taken whatever its address: the SMC-aperture
        address that port carries is what OBS-G2B-ADDR measures, SF-023.
        """
        key = f"{ch}addr"
        out = [(n, e) for n in SEP_LINKS for e in self._tsince(mks, n, ch) if e[key] == addr]
        if not out:
            out = [("sep_to_smc", e) for e in self._tsince(mks, "sep_to_smc", ch)]
        return out

    def _responses(self, mks: dict, name: str, rch: str, ident) -> list[dict]:
        key = "bid" if rch == "b" else "rid"
        return [
            e
            for e in self._tsince(mks, name, rch)
            if e[key] == ident and (rch == "b" or e.get("rlast") == 1)
        ]

    async def _sep_wait(self, rec: dict) -> None:
        """Bounded: the request appears on a SEP link and its response with the issued ID."""
        mks, ch, addr = rec["mks"], rec["ch"], rec["addr"]
        rch = "b" if ch == "aw" else "r"

        def answered() -> bool:
            reqs = self._requests(mks, ch, addr)
            return bool(reqs) and bool(self._responses(mks, reqs[0][0], rch, reqs[0][1][f"{ch}id"]))

        await self._until(f"{rec['label']}_response", answered, XFER_BOUND)
        name, req = self._requests(mks, ch, addr)[0]
        rec.update(link=name, req=req, id=req[f"{ch}id"], req_cyc=req["cyc"], done_w=self.wcyc)

    async def _stub(self, kind: str, addr: int, label: str, byte: int = 0) -> dict:
        """One stub access: a0 (and a1) and dpc written, resume, ebreak, then its response."""
        mks = self._marks()
        await self._reg_write(REG_A0, addr, f"{label}_a0")
        if kind == "store":
            await self._reg_write(REG_A1, byte, f"{label}_a1")
        await self._reg_write(CSR_DPC, STUB_STORE if kind == "store" else STUB_LOAD, f"{label}_dpc")
        await self._resume(label)
        rec = {
            "label": label,
            "kind": kind,
            "src": "stub",
            "addr": addr,
            "ch": "aw" if kind == "store" else "ar",
            "mks": mks,
            "byte": byte,
            "term": self.term,
        }
        await self._sep_wait(rec)
        self.accesses.append(rec)
        return rec

    async def _stub_pair(self, addr: int, label: str, byte: int) -> tuple[dict, dict]:
        st = await self._stub("store", addr, f"{label}_store", byte)
        ld = await self._stub("load", addr, f"{label}_load")
        return st, ld

    async def _sba_access(self, addr: int, label: str) -> dict:
        mks = self._marks()
        err, value = await self._sba_read_obs(addr, label)
        rec = {
            "label": label,
            "kind": "load",
            "src": "system_bus",
            "addr": addr,
            "ch": "ar",
            "mks": mks,
            "sberror": err,
            "value": value,
            "term": self.term,
        }
        await self._sep_wait(rec)
        self.accesses.append(rec)
        return rec

    def _resp_window(self, rec: dict) -> list[dict]:
        """Responses on the access's link with its ID, up to the next request on that link."""
        name, ch = rec["link"], rec["ch"]
        rch = "b" if ch == "aw" else "r"
        tap = self.taps[name]
        nxt = [e["cyc"] for e in tap.ev[ch] if e["cyc"] > rec["req_cyc"]]
        end = min(nxt) if nxt else None
        return [
            e
            for e in self._responses(rec["mks"], name, rch, rec["id"])
            if e["cyc"] > rec["req_cyc"] and (end is None or e["cyc"] < end)
        ]

    def _sep_view(self, rec: dict) -> dict:
        resps = self._resp_window(rec)
        code = "bresp" if rec["ch"] == "aw" else "rresp"
        lane = None
        if rec["ch"] == "ar" and resps:
            lane = _lane(resps[0].get("rdata"), rec["addr"])
        return {
            "requests": len(
                [
                    e
                    for _, e in self._requests(rec["mks"], rec["ch"], rec["addr"])
                    if e["cyc"] <= rec["done_w"]
                ]
            ),
            "one_response_issued_id": len(resps) == 1 and rec["id"] is not None,
            "resp": [_rn(e[code]) for e in resps],
            "lane": lane,
        }

    # ------------------------------------------------------------------ JTAG2AXI

    async def _j2a(self, op: int, addr: int, data: int, label: str) -> dict:
        """A graded JTAG2AXI single operation and its dtp_dbg handshakes."""
        mks = self._marks()
        self._use("j2a")
        status, rdata = await self._fabric(op, addr, data, label)
        rec = {"label": label, "op": op, "addr": addr, "mks": mks, "status": status}
        rec["rdata"] = rdata
        self.j2a_ops.append(rec)
        return rec

    def _j2a_view(self, rec: dict) -> dict:
        ch, rch, key = ("aw", "b", "bid") if rec["op"] == J2A_OP_WRITE else ("ar", "r", "rid")
        reqs = self._tsince(rec["mks"], "dtp_dbg", ch)
        resps = [e for e in self._tsince(rec["mks"], "dtp_dbg", rch) if rch == "b" or e["rlast"]]
        ident = reqs[0][f"{ch}id"] if reqs else None
        same = [e for e in resps if e[key] == ident and ident is not None]
        return {
            "status": rec["status"],
            "requests": len(reqs),
            "responses": len(resps),
            "issued_id": len(same),
        }

    async def _j2a_obs(self, op: int, addr: int, data: int, label: str, captures: int) -> dict:
        """A JTAG2AXI operation whose outcome is observed over ``captures`` status captures.

        An operation attempted while the port holds another is ignored by the
        bridge (``hw/ip/jtag/jtag_ptap/doc/architecture.adoc``, AXI_SINGLE_OP op
        field); the issue scan's capture records the state it met.
        """
        mks = self._marks()
        wstrb = WSTRB_FULL if op == J2A_OP_WRITE else 0
        raw = pack_single_op(op, addr, data, wstrb=wstrb, size=SMC_DBG_AXSIZE_8B)
        issued_at = _now()
        cap, _ = await self._dr(
            DTP_IR_SMC_AXI_SINGLE_OP, raw, SMC_DBG_SINGLE_OP_LEN, f"{label}_issue"
        )
        self._use("j2a")
        met, _ = unpack_single_op(cap)
        status, rdata, used = J2A_STATUS_BUSY, 0, 0
        for used in range(1, captures + 1):
            cap, _ = await self._dr(
                DTP_IR_SMC_AXI_SINGLE_OP,
                0,
                SMC_DBG_SINGLE_OP_LEN,
                f"{label}_c{used}",
                counted=False,
            )
            status, rdata = unpack_single_op(cap)
            if status != J2A_STATUS_BUSY:
                break
            await ClockCycles(self.dut.clk_smu_i, CAPTURE_POLL_CLK)
        outcome = f"met={met} status={status} captures={used}"
        self.windows.append(
            {"label": label, "length": captures, "start": self.mon.cyc, "outcome": outcome}
        )
        rec = {
            "label": label,
            "op": op,
            "addr": addr,
            "mks": mks,
            "met": met,
            "status": status,
            "rdata": rdata,
            "captures": used,
            "issued_ns": issued_at,
            "done_ns": _now() if status != J2A_STATUS_BUSY else None,
        }
        self.j2a_ops.append(rec)
        return rec

    async def _j2a_idle(self, label: str) -> int:
        """Bounded: the JTAG2AXI port leaves busy before a graded operation is issued."""
        status, used = J2A_STATUS_BUSY, 0
        while True:
            cap, _ = await self._dr(
                DTP_IR_SMC_AXI_SINGLE_OP,
                0,
                SMC_DBG_SINGLE_OP_LEN,
                f"{label}_c{used}",
                counted=False,
            )
            status, _ = unpack_single_op(cap)
            used += 1
            if status != J2A_STATUS_BUSY or used >= J2A_IDLE_POLLS:
                break
            await ClockCycles(self.dut.clk_smu_i, CAPTURE_POLL_CLK)
        self._site(
            "op_capture",
            label,
            J2A_IDLE_POLLS,
            "captures",
            used,
            f"op={status}",
            status == J2A_STATUS_BUSY,
        )
        return status

    # ------------------------------------------------------------------ ext_in

    async def _ext_route(self, tag: str, addr: int, word: int, ids: tuple[int, int]) -> dict:
        self._use("ext_in", 2)
        res = await self._sram_write_read(tag, addr, word, ids[0], ids[1])
        self.ext_ops[tag] = {"addr": addr, "ids": ids, "res": res}
        return res

    async def _ext_read(self, tag: str, addr: int, arid: int) -> dict:
        self._use("ext_in")
        mk = self.mon.mark()
        ok = await self._xfer(f"{tag}_read", self._issue_read(addr, 8, 3, arid), fatal=False)
        r = self._since(mk, "r", {arid}, "rid")
        return {
            "r_done": ok is not None,
            "rresp": [_rn(x["rresp"]) for x in r],
            "rdata": [_hx(x["rdata"]) for x in r],
        }

    @staticmethod
    def _ext_ok(res: dict) -> tuple:
        return (res["w_done"], res["bresp"], res["r_done"], res["rresp"], res["rdata"])

    @staticmethod
    def _ext_want(word: int) -> tuple:
        okay = _rn(RESP_OKAY)
        return (True, [okay], True, [okay], [_hx(word)])

    # ------------------------------------------------------------------ responder

    def _responder_stall(self) -> None:
        self.mem.enable_backpressure(channels=("aw", "w", "ar"), stall_cycles=RESP_STALL)

    def _ext_readies(self, held: bool) -> None:
        chans = self.master.driver.channels
        chans["r_ready_delay"].pause = held
        chans["b_ready_delay"].pause = held

    # ------------------------------------------------------------------ steps

    async def _s1_setup(self) -> None:
        dut = self.dut
        sb = self.sb
        await self.cfg.reset_done.wait()
        self.mon = _ExtInMonitor(dut)
        self._start_taps()
        await RisingEdge(dut.clk_smu_i)
        self._enter("SETUP", "S1", "bring-up, hart halted, stub, aperture, egress filter, routes")
        sim = cocotb.SIM_NAME or "unknown simulator"
        graded = "graded by the bench at final" if "vcs" in sim.lower() else "not graded"
        self.log.info("INFO-RUN-MODE: %s, protocol gates %s", sim, graded)
        self._info(f"SEED: RANDOM_SEED={self.seed} (every access of this leaf is directed)")
        sb.expect_eq("S1 SEP=1 build with the crossbar elaborated", _val(dut.sep_enabled_o), 1)
        self.lv["on"] = True
        cocotb.start_soon(self._level_watch())
        self.mem = self.cfg.axi_out_mem
        idcode = await self._jtag_bringup("s1")
        lc, dbg = await self._posture("s1")
        security = _val(dut.tb_smc_jtag2axi_security_disable)
        inb = await self._program_inbound0("s1")
        outb = []
        for addr, data, name in (
            (OUTBOUND0_START, 0, "start"),
            (OUTBOUND0_END, PASS_ALL_END, "end"),
            (OUTBOUND0_FILTER_CONFIG, PASS_RW_CONFIG, "config"),
        ):
            status, _ = await self._fabric(J2A_OP_WRITE, addr, data, f"s1_outbound0_{name}")
            outb.append(status)
        self.config["j2a_filter"] += 6
        dmactive = await self._activate_debug_module("s1")
        self.config["dmi_bringup"] += 2
        await self._halt("s1")
        await self._install_stub("s1")
        ports = await self._aperture("s1")
        await self._program_egress("s1")
        nets = {n: _val(getattr(dut, n)) for n in NETS}
        sb.expect_eq(
            "S1 access path open, hart halted, SEP aperture placed and reset nets at 1",
            (
                _hx(idcode),
                dbg,
                security,
                inb,
                outb,
                dmactive,
                _hx(ports["sep_base"]),
                _hx(ports["sep_size"]),
                nets,
            ),
            (
                _hx(DTP_DEFAULT_IDCODE),
                0,
                0,
                [J2A_STATUS_SUCCESS] * 3,
                [J2A_STATUS_SUCCESS] * 3,
                1,
                _hx(SEP_WIN_BASE),
                _hx(SEP_WIN_SIZE),
                {n: 1 for n in NETS},
            ),
        )
        self._info(f"S1 lc_state={_hx(lc)} ports={ports} nets={nets}")
        self.ports = self._ports()
        self.master = await make_smu_axi_master(dut, dut.clk_smu_i, smc_primary_reset(dut))
        clear_profile(self.master.driver)
        self._responder_stall()
        self.mem.set_response_delay(RESP_DELAY)
        okay = _rn(RESP_OKAY)
        ok, want = {}, {}
        res = await self._ext_route("s1_ext_sep", SEP_S1_EXT, W_S1_EXT, S1_IDS["sep"])
        ok["ext_in->sep_sram"] = self._ext_ok(res)
        want["ext_in->sep_sram"] = self._ext_want(W_S1_EXT)
        spm = self._smc_view(SPM_S1)
        res = await self._ext_route("s1_ext_spm", spm, W_S1_SPM, S1_IDS["spm"])
        ok["ext_in->smc_spm"] = self._ext_ok(res)
        want["ext_in->smc_spm"] = self._ext_want(W_S1_SPM)
        for route, addr, word in (
            ("j2a->sep_sram", SEP_S1_J2A, W_S1_J2A),
            ("j2a->ext_out", EXT_J2A_S1, W_S1_EXT_OUT),
        ):
            w = await self._j2a(J2A_OP_WRITE, addr, word, f"s1_{route}_wr")
            r = await self._j2a(J2A_OP_READ, addr, 0, f"s1_{route}_rd")
            ok[route] = (w["status"], r["status"], _hx(r["rdata"]))
            want[route] = (J2A_STATUS_SUCCESS, J2A_STATUS_SUCCESS, _hx(word))
        st, ld = await self._stub_pair(EGRESS_S1, "s1_stub_ext", BYTE["s1"])
        sv, lw = self._sep_view(st), self._sep_view(ld)
        ok["stub->ext_out"] = (
            st["link"],
            sv["resp"],
            lw["resp"],
            _hx(lw["lane"]),
            _hx(self.mem.read_int(EGRESS_S1, 1)),
        )
        want["stub->ext_out"] = (
            "xbar_sep_out",
            [okay],
            [okay],
            _hx(BYTE["s1"]),
            _hx(BYTE["s1"]),
        )
        sb.expect_eq("CTRL-G2B-OKAY one write then read on every route the leaf uses", ok, want)
        self.log.info("CTRL-G2B-OKAY: routes=%d %s", len(ok), ok)
        self.routes["s1"] = ok
        self._fence(len(ok))
        self.steps["S1"] = True

    def _sep2smc_obs(self, recs: list[dict], step: str) -> None:
        tie = []
        addrs = []
        for rec in recs:
            req = rec["req"]
            ch = rec["ch"]
            view = self._sep_view(rec)
            tie.append(
                f"{rec['label']}:link={rec['link']} {ch}id={_hx(rec['id'])} "
                f"{ch}user={_hx(req.get(f'{ch}user'))} {ch}prot={_hx(req.get(f'{ch}prot'))} "
                f"resp={view['resp']}"
            )
            addrs.append(
                f"{rec['label']}:issued={_hx(rec['addr'])} on_link={_hx(req.get(f'{ch}addr'))} "
                f"resp={view['resp']}"
            )
        smc_driven = sum(len(self.taps["sep_to_smc"].ev[ch]) for ch in ("aw", "ar"))
        self.log.info(
            "OBS-G2B-SEP2SMC-TIE: step=%s sep_to_smc_aw_ar_handshakes=%d (SMC sep_axi_in %s) %s; "
            "table: %s; observation only, SF-012",
            step,
            smc_driven,
            "driven by the SEP-to-SMC port" if smc_driven else "no AW/AR seen",
            " ".join(tie),
            SMC_APERTURE_ATTRS,
        )
        self.log.info(
            "OBS-G2B-ADDR: step=%s %s; filters: SMC inbound entry 0 and outbound entry 0 over the "
            "whole space (JTAG2AXI), SEP outbound entry over the egress page, every other entry at "
            "reset; observation only, SF-023, SF-012",
            step,
            " ".join(addrs),
        )

    async def _s2_sep2smc(self) -> None:
        self._enter(
            "SEP2SMC", "S2", "stub store and load and one system-bus read in the SMC aperture"
        )
        spm = self._smc_view(SPM_S1)
        st, ld = await self._stub_pair(spm, "s2_stub_smc", BYTE["s2"])
        sba = await self._sba_access(spm, "s2_sba_smc")
        recs = [st, ld, sba]
        self._sep2smc_obs(recs, "S2")
        atop = [
            f"{n}:awaddr={_hx(e['awaddr'])} awatop={_hx(e['awatop'])}"
            for n in SEP_LINKS
            for e in self.taps[n].ev["aw"]
        ]
        self.log.info(
            "OBS-G2B-ATOP-SEP: every sep_out and SEP-to-SMC AW so far: %s; observation only, SF-017",
            " ".join(atop) or "none",
        )
        self._fence(len(recs))
        self.steps["S2"] = True

    async def _s3_load(self) -> None:
        dut = self.dut
        mon = self.mon
        self._enter("LOAD", "S3", "ext_in and JTAG2AXI toward the SEP SRAM held; the stub armed")
        mk = mon.mark()
        self._ext_readies(True)
        for arid, addr in zip(LOAD_ARIDS, (SEP_S1_EXT, SEP_S1_J2A)):
            self._issue_read(addr, 8, 3, arid)
        for awid, addr, word in zip(LOAD_AWIDS, SEP_LOAD_WR, W_LOAD):
            self._issue_write(addr, word.to_bytes(8, "little"), 3, awid)
        self._use("ext_in", 4)
        await self._until(
            "s3_load_accepted",
            lambda: (
                len(self._since(mk, "ar", set(LOAD_ARIDS), "arid")) == len(LOAD_ARIDS)
                and len(self._since(mk, "aw", set(LOAD_AWIDS), "awid")) == len(LOAD_AWIDS)
            ),
            LOAD_ACCEPT_BOUND,
        )
        jw = await self._j2a_obs(
            J2A_OP_WRITE, SEP_LOAD_J2A_WR, W_LOAD_J2A, "s3_j2a_sep_wr", J2A_LOAD_CAPTURES
        )
        jr = await self._j2a_obs(J2A_OP_READ, SEP_S1_J2A, 0, "s3_j2a_sep_rd", J2A_LOAD_CAPTURES)
        await self._reg_write(REG_A0, EGRESS_HELD, "s3_a0")
        await self._reg_write(REG_A1, BYTE["s3"], "s3_a1")
        await self._reg_write(CSR_DPC, STUB_STORE, "s3_dpc")
        ext = self._unanswered_ext(mk, None)
        dtp = int(jr["status"] == J2A_STATUS_BUSY or jw["status"] == J2A_STATUS_BUSY)
        self.load = {"mk": mk, "j2a": (jw, jr), "ns": _now()}
        self.log.info(
            "INFO-G2B-OUTSTANDING: t=%dns step=S3 smu_in=%d ids=%s dtp_dbg=%d j2a_wr=(met %d, "
            "status %d) j2a_rd=(met %d, status %d) sep_out=armed (resumed in the first IC_RESET "
            "scan)",
            _now(),
            len(ext),
            sorted(_hx(i) for i in ext),
            dtp,
            jw["met"],
            jw["status"],
            jr["met"],
            jr["status"],
        )
        self.log.info("%s", DTP_NOT_DRIVABLE)
        self._info(f"S3 ext_in valid/ready={mon.levels} rready={_val(dut.ext_in_rready)}")
        if len(ext) < OUTSTANDING_PLAN["smu_in"]:
            self._classify(
                "load-below-plan",
                "bench-side",
                f"S3 smu_in outstanding {len(ext)} against the plan {OUTSTANDING_PLAN['smu_in']} "
                "with RREADY and BREADY withheld by the bench master",
            )
            raise AssertionError(
                f"S3 LOAD below its planned count: smu_in={len(ext)} plan={OUTSTANDING_PLAN}"
            )
        self._fence(len(ext) + 1)
        self.steps["S3"] = True

    def _unanswered_ext(self, mk: dict, until: int | None) -> dict[int, str]:
        """ext_in requests of the LOAD set accepted and not answered by mon cycle ``until``."""
        out = {}
        for ch, rch, ids, key, rkey in (
            ("ar", "r", LOAD_ARIDS, "arid", "rid"),
            ("aw", "b", LOAD_AWIDS, "awid", "bid"),
        ):
            for e in self._since(mk, ch, set(ids), key):
                resp = [
                    x
                    for x in self._since(mk, rch, {e[key]}, rkey)
                    if (until is None or x["cyc"] <= until) and (rch == "b" or x["rlast"] == 1)
                ]
                if not resp:
                    out[e[key]] = f"{ch}@{e['cyc']}"
        return out

    async def _s4_sep_reset(self) -> None:
        dut = self.dut
        out = dut.u_axi_out_if
        lv = self.lv
        h = self.h
        self._enter("SEP_RESET", "S4", "IC_RESET staged with the stub resume, then held")
        rec = self.holds[HOLD] = {"fall": None, "rise": None, "early": [], "hold_samples": 0}
        rec["trace"] = []
        lv["pre"].clear()
        lv["armed"] = HOLD
        h["on"] = True
        self.mem.enable_backpressure(channels=("aw", "w"), stall_cycles=RESPONDER_GUARD)
        self.override = {"mon": self.mon.cyc, "w": self.wcyc, "ns": _now()}
        self._use("dmi")
        self._use("ic_reset")
        await self._dr(
            DTP_IR_IC_RESET,
            SEP_STAGED,
            SMU_IC_RESET_LEN,
            "s4_sep_staged_resume",
            sep_request=pack_dmi(DMCONTROL, DMACTIVE | RESUMEREQ, op=DMI_OP_WRITE),
            idle=DMI_IDLE_TCKS,
        )
        await self._until(
            "s4_egress_store_aw",
            lambda: _val(out.awvalid) == 1 and _val(out.awaddr) == EGRESS_HELD,
            EGRESS_BOUND,
        )
        egress_aw = self.mon.cyc
        self._use("ic_reset")
        _, sep_cap = await self._dr(DTP_IR_IC_RESET, SEP_HELD, SMU_IC_RESET_LEN, "s4_sep_held")
        _, _, resume_status = unpack_dmi(sep_cap)
        await self._until("s4_sep_reset_fall", lambda: rec["fall"] is not None, LEVEL_BOUND)
        await self._until("s4_watch_fall", lambda: h["fall"] is not None, FALL_SEEN_BOUND)
        fall = rec["fall"]
        ext = self._unanswered_ext(self.load["mk"], fall)
        jw, jr = self.load["j2a"]
        dtp_ids = self._dtp_unanswered(h["fall"])
        store = [e for e in self.taps["xbar_sep_out"].ev["aw"] if e["awaddr"] == EGRESS_HELD]
        store_b = [
            e
            for e in self.taps["xbar_sep_out"].ev["b"]
            if store and e["bid"] == store[0]["awid"] and e["cyc"] > store[0]["cyc"]
        ]
        sep_out = int(not store_b)
        got = {"smu_in": len(ext), "dtp_dbg": len(dtp_ids), "sep_out": sep_out}
        self.log.info(
            "INFO-G2B-OUTSTANDING: t=%dns step=S4 at the fall (cycle %d) smu_in=%d ids=%s "
            "dtp_dbg=%d ids=%s j2a_wr_status=%d j2a_rd_status=%d sep_out=%d store_awvalid@%d "
            "store_aw_handshake=%s resume_dmi_status=%d plan=%s",
            _now(),
            fall,
            len(ext),
            {_hx(k): v for k, v in sorted(ext.items())},
            len(dtp_ids),
            dtp_ids,
            jw["status"],
            jr["status"],
            sep_out,
            egress_aw,
            [e["cyc"] for e in store] or "none",
            resume_status,
            OUTSTANDING_PLAN,
        )
        self.load.update(at_fall=got, ext_at_fall=ext, dtp_at_fall=dtp_ids)
        below = {p: got[p] for p, n in OUTSTANDING_PLAN.items() if got[p] < n}
        if below:
            # A missing store AW is the SEP's; a response past a withheld READY is the bench's.
            cls = "design-side" if "sep_out" in below and not store else "bench-side"
            self._classify(
                "load-below-plan",
                cls,
                f"outstanding at the fall {got} against the plan {OUTSTANDING_PLAN}",
            )
            raise AssertionError(f"S4 LOAD below its planned count at the fall: {below}")
        self.mem.disable_backpressure()
        self._responder_stall()
        self._ext_readies(False)
        self.obs["aperture_held"] = self._ports()
        j = await self._j2a_obs(
            J2A_OP_READ, DURING_ADDR, 0, "s4_j2a_sep_aperture_rd", J2A_OBS_CAPTURES
        )
        self.obs["reset_read"] = j
        await self._until("s4_sep_in_trace", lambda: lv["after"] >= TRACE_SPAN, TRACE_SPAN + 2)
        self._fence(h["low"])
        self.steps["S4"] = True

    def _dtp_unanswered(self, until: int) -> list[str]:
        mks = self.load["j2a"][0]["mks"]
        out = []
        for ch, rch, key, rkey in (("aw", "b", "awid", "bid"), ("ar", "r", "arid", "rid")):
            for e in self._tsince(mks, "dtp_dbg", ch):
                resp = [
                    x
                    for x in self._tsince(mks, "dtp_dbg", rch)
                    if x[rkey] == e[key] and x["cyc"] > e["cyc"] and x["cyc"] <= until
                ]
                if not resp:
                    out.append(f"{ch}:{_hx(e[key])}@{e['cyc']}")
        return out

    async def _s5_nonsep(self) -> None:
        dut = self.dut
        mon = self.mon
        lv = self.lv
        h = self.h
        rec = self.holds[HOLD]
        self._enter("NONSEP_DURING_RESET", "S5", "JTAG2AXI to ext_out and ext_in to the SMC")
        pre = _val(dut.sep_reset_n_o)
        jw = await self._j2a_obs(
            J2A_OP_WRITE, EXT_J2A_S5, W_S5_EXT_OUT, "s5_j2a_ext_wr", J2A_OBS_CAPTURES
        )
        jr = await self._j2a_obs(J2A_OP_READ, EXT_J2A_S5, 0, "s5_j2a_ext_rd", J2A_OBS_CAPTURES)
        spm = self._smc_view(SPM_S5)
        mk = mon.mark()
        t0 = _now()
        self._issue_write(spm, W_S5_SPM.to_bytes(8, "little"), 3, S5_IDS[0])
        self._use("ext_in")
        bw = await self._obs_until(
            "s5_ext_spm_wr", lambda: bool(self._since(mk, "b", {S5_IDS[0]}, "bid")), OBS_BOUND
        )
        t1 = _now()
        self._issue_read(spm, 8, 3, S5_IDS[1])
        self._use("ext_in")
        rw = await self._obs_until(
            "s5_ext_spm_rd", lambda: bool(self._since(mk, "r", {S5_IDS[1]}, "rid")), OBS_BOUND
        )
        b = self._since(mk, "b", {S5_IDS[0]}, "bid")
        r = self._since(mk, "r", {S5_IDS[1]}, "rid")
        during = _val(dut.sep_reset_n_o)
        self.log.info(
            "OBS-G2B-NONSEP-DURING: sep_reset_n_o before=%s after=%s j2a_ext_wr=(met %d, status "
            "%d, captures %d) j2a_ext_rd=(met %d, status %d, rdata %s, captures %d) "
            "ext_in_spm_wr=%s in %s cycles from %dns ext_in_spm_rd=%s in %s cycles from %dns; "
            "observation only, SF-001, SF-022",
            _hx(pre),
            _hx(during),
            jw["met"],
            jw["status"],
            jw["captures"],
            jr["met"],
            jr["status"],
            _hx(jr["rdata"]),
            jr["captures"],
            [(_rn(x["bresp"]), _hx(x["bid"])) for x in b] or "none",
            bw,
            t0,
            [(_rn(x["rresp"]), _hx(x["rid"]), _hx(x["rdata"])) for x in r] or "none",
            rw,
            t1,
        )
        if pre != 0 or during != 0:
            self.failures.append(
                f"S5 sep_reset_n_o was not low around the accesses: {pre}/{during}"
            )
        self.obs["nonsep"] = {"j2a": (jw, jr), "b": b, "r": r}
        self._step("S5", "release: reset_enable 1 first, then reset_control 1")
        lv["held"] = None
        lv["rising"] = HOLD
        self._use("ic_reset")
        await self._ic_reset(SEP_STAGED, "s5_release_enable")
        await self._until("s5_sep_reset_rise", lambda: rec["rise"] is not None, LEVEL_BOUND)
        await self._until("s5_expect_window_close", lambda: lv["win"] == 0, WINDOW_CLOSE_BOUND)
        lv["in_hold"] = None
        self._use("ic_reset")
        await self._ic_reset(ALL_ONES, "s5_release_control")
        h["on"] = False
        if (axi_mon := smu_axi_monitor("ext_in")) is not None:
            for arid in LOAD_ARIDS:
                axi_mon.forget_pending_reads(arid)
        self._fence(self.used[self.term]["j2a"] + self.used[self.term]["ext_in"])
        self.steps["S5"] = True

    async def _s6_liveness(self) -> None:
        sb = self.sb
        self._enter("RELEASE_LIVENESS", "S6", "bring-up, halt, stub, fresh routes; no cold reset")
        await self._tlr()
        self._use("dmi", 2)
        dmactive = await self._activate_debug_module("s6")
        await self._halt("s6")
        await self._install_stub("s6")
        ports = await self._aperture("s6")
        await self._program_egress("s6")
        sb.expect_eq(
            "S6 debug module active and the SEP aperture placed after the release",
            (dmactive, _hx(ports["sep_base"]), _hx(ports["sep_size"])),
            (1, _hx(SEP_WIN_BASE), _hx(SEP_WIN_SIZE)),
        )
        okay = _rn(RESP_OKAY)
        got, want = {}, {}
        res = await self._ext_route("s6_ext_sep", SEP_S6_EXT, W_S6_EXT, S6_IDS["sep"])
        got["ext_in->sep_sram"] = self._ext_ok(res)
        want["ext_in->sep_sram"] = self._ext_want(W_S6_EXT)
        spm = self._smc_view(SPM_S6)
        res = await self._ext_route("s6_ext_spm", spm, W_S6_SPM, S6_IDS["spm"])
        got["ext_in->smc_spm"] = self._ext_ok(res)
        want["ext_in->smc_spm"] = self._ext_want(W_S6_SPM)
        await self._j2a_idle("s6_j2a_port_idle")
        j2a_ok = {"status": J2A_STATUS_SUCCESS, "requests": 1, "responses": 1, "issued_id": 1}
        w = await self._j2a(J2A_OP_WRITE, SEP_S6_J2A, W_S6_J2A, "s6_j2a->sep_sram_wr")
        rb = await self._ext_read("s6_j2a_sep_readback", SEP_S6_J2A, S6_J2A_READBACK_ARID)
        got["j2a->sep_sram"] = (self._j2a_view(w), rb["r_done"], rb["rresp"], rb["rdata"])
        want["j2a->sep_sram"] = (j2a_ok, True, [okay], [_hx(W_S6_J2A)])
        w = await self._j2a(J2A_OP_WRITE, EGRESS_J2A_S6, W_S6_EXT_OUT, "s6_j2a->ext_out_wr")
        sba = await self._sba_access(EGRESS_J2A_S6, "s6_j2a_ext_out_readback")
        sbv = self._sep_view(sba)
        got["j2a->ext_out"] = (
            self._j2a_view(w),
            sba["link"],
            sba["sberror"],
            sbv["one_response_issued_id"],
            sbv["resp"],
            _hx(self.mem.read_int(EGRESS_J2A_S6, 8)),
            _hx(sba["value"]),
        )
        want["j2a->ext_out"] = (
            j2a_ok,
            "xbar_sep_out",
            0,
            True,
            [okay],
            _hx(W_S6_EXT_OUT),
            _hx(W_S6_EXT_OUT & 0xFFFF_FFFF),
        )
        st, ld = await self._stub_pair(EGRESS_S6, "s6_stub_ext", BYTE["s6_ext"])
        sv, lw = self._sep_view(st), self._sep_view(ld)
        got["stub->ext_out"] = (
            st["link"],
            sv["one_response_issued_id"],
            sv["resp"],
            lw["one_response_issued_id"],
            lw["resp"],
            _hx(lw["lane"]),
            _hx(self.mem.read_int(EGRESS_S6, 1)),
        )
        want["stub->ext_out"] = (
            "xbar_sep_out",
            True,
            [okay],
            True,
            [okay],
            _hx(BYTE["s6_ext"]),
            _hx(BYTE["s6_ext"]),
        )
        smc_st, smc_ld = await self._stub_pair(spm, "s6_stub_smc", BYTE["s6_smc"])
        self._sep2smc_obs([smc_st, smc_ld], "S6")
        j = await self._j2a_obs(J2A_OP_READ, SEP_S6_J2A, 0, "s6_j2a_sep_rd", J2A_OBS_CAPTURES)
        self._j2a_read_after_obs(j)
        self.routes["s6"] = got
        self.routes["s6_want"] = want
        self.routes["s6_smc"] = (smc_st, smc_ld)
        self._fence(len(got) + 1)
        self.steps["S6"] = True

    # ------------------------------------------------------------------ verdicts

    def _valid_low_grade(self) -> None:
        h = self.h
        entry = h["entry"]
        edges = [h["edges"][link] for link in GRADED]
        e_lo, e_hi = (min(edges), max(edges)) if edges else (0, 0)
        x_graded = [x for x in h["high"] if x[3] is None]
        high = [x for x in h["high"] if x[3] is not None]
        if entry is not None:
            c, levels, sin = entry
            watcher = all(v == 0 for sv in levels.values() for v in sv.values())
            self.log.info(
                "OBS-G2B-ENTRY-EDGE: cycle=%d (first clk_smu_i edge sampling sep_reset_n low) "
                "levels=%s sep_in=%s reading=checker window holds (one-edge synchronous-reset "
                "entry window); watcher no-window %s; VALID_RESET_LOW fires of "
                "u_xbar_sep_in_sep_rst_axi_sva and u_sep_to_smc_sep_rst_axi_sva at this edge: 0 "
                "(MASTER_SYNC_RESET admits it); observation only, SF-005, SF-006, SF-007",
                c,
                levels,
                sin,
                "holds" if watcher else "does not hold",
            )
        else:
            self.log.info(
                "OBS-G2B-ENTRY-EDGE: no edge sampled sep_reset_n low; SF-005, SF-006, SF-007"
            )
        low = h["low"]
        sepin = {s: len(v) for s, v in h["sepin_high"].items()}
        self.log.info(
            "OBS-G2B-SEPIN-VALID: edges_low=%d high_edges=%s first_last=%s x_samples=%d "
            "(crossbar-driven AW/W/AR toward the held SEP, B/R on sep_in); observation only, "
            "SF-005, SF-006",
            low,
            sepin,
            {s: (v[0], v[-1]) for s, v in h["sepin_high"].items() if v},
            h["sepin_x"],
        )
        for sig in ("awvalid", "wvalid", "arvalid"):
            later = [c for c in h["sepin_high"][sig] if entry is None or c != entry[0]]
            if later:
                self._classify(
                    "checker-fire",
                    "checker-side",
                    f"u_xbar_sep_in_sep_rst_axi_sva {sig.upper()[:2]}_VALID_RESET_LOW predicted on "
                    f"{len(later)} edges from {later[0]} inside the expectation window (a reset "
                    "outside the driver's reset, SF-005, SF-006); OBS-G2B-RULING-2891",
                    "xbar_sep_in",
                )
        s2s = [x for x in high if x[1] == "sep_to_smc"]
        if s2s:
            self._classify(
                "checker-fire",
                "checker-side",
                f"u_sep_to_smc_sep_rst_axi_sva VALID_RESET_LOW predicted on {len(s2s)} edges "
                f"from {s2s[0]}; the bench window of tb_wrapper_top.sv (sep_in override "
                "expectation window) takes no rule of this instance off, SF-005 and SF-006; "
                "OBS-G2B-RULING-2891",
                "sep_to_smc",
            )
        self.obs["sep2smc_fire"] = len(s2s)
        observed = {
            "sep_reset_n_low": low >= 1,
            "every_link_sampled_after_entry": e_lo > 0,
            "valid_high_after_entry": len(high),
            "x_on_graded": len(x_graded),
            "x_on_sep_reset_n": len(h["x"]),
        }
        expected = {
            "sep_reset_n_low": True,
            "every_link_sampled_after_entry": True,
            "valid_high_after_entry": 0,
            "x_on_graded": 0,
            "x_on_sep_reset_n": 0,
        }
        if high:
            self._info(f"G2B-VALID-HIGH first={high[:8]}")
        self._verdict(
            "CHK-G2B-SEP-VALID-LOW",
            observed,
            expected,
            f"CHK-G2B-SEP-VALID-LOW: links={len(GRADED)} edges_sampled={e_lo}..{e_hi} "
            f"valid_high_after_entry={len(high)}",
        )

    def _dtp_fate(self, rec: dict) -> dict:
        """The read's dtp_dbg AR and every R with its ID before the next dtp_dbg AR."""
        ars = self._tsince(rec["mks"], "dtp_dbg", "ar")
        if not ars:
            return {"ar": None, "r": []}
        ar = ars[0]
        nxt = [e["cyc"] for e in self.taps["dtp_dbg"].ev["ar"] if e["cyc"] > ar["cyc"]]
        end = min(nxt) if nxt else None
        rs = [
            e
            for e in self.taps["dtp_dbg"].ev["r"]
            if e["rid"] == ar["arid"] and e["cyc"] > ar["cyc"] and (end is None or e["cyc"] < end)
        ]
        return {"ar": ar, "r": rs}

    def _reset_ends_obs(self) -> None:
        h = self.h
        j = self.obs.get("reset_read", {})
        quiet = {}
        for link in GRADED:
            quiet[link] = "quiet" if not [x for x in h["high"] if x[1] == link] else "VALID high"
        sepin = "VALID high" if any(h["sepin_high"].values()) else "quiet"
        fall, rise = h["fall"], h["rise"]
        held_ars = [
            f"arid={_hx(e['arid'])} araddr={_hx(e['araddr'])}@{e['cyc']}"
            for e in self.taps["xbar_sep_in"].ev["ar"]
            if fall is not None and e["cyc"] >= fall and (rise is None or e["cyc"] < rise)
        ]
        fate = self._dtp_fate(j) if j else {"ar": None, "r": []}
        ar = fate["ar"]
        before = [e for e in fate["r"] if rise is None or e["cyc"] < rise]
        s5 = [
            (r["label"], r["met"], r["status"]) for r in self.obs.get("nonsep", {}).get("j2a", ())
        ]
        self.log.info(
            "OBS-G2B-RESET-ENDS: sep_reset_n low for %d edges; obs_sep_rst_n_o (rst_ni) and the "
            "primary reset not high on %d of them; from the second edge %s, sep_in %s; "
            "aperture ports while held %s; JTAG2AXI read at %s during the reset: met=%s status=%s "
            "rdata=%s captures=%s, dtp_dbg AR %s, sep_in AR handshakes while sep_reset_n low %s, "
            "R before the release %s, R by the end %s; bridge (met, status) of the S5 operations %s; "
            "observation only, the SEP, SF-003, SF-005, SF-001",
            h["low"],
            len(h["nets_bad"]),
            quiet,
            sepin,
            self.obs.get("aperture_held"),
            _hx(DURING_ADDR),
            j.get("met"),
            j.get("status"),
            _hx(j.get("rdata")),
            j.get("captures"),
            f"arid={_hx(ar['arid'])}@{ar['cyc']}" if ar else "none",
            held_ars or "none",
            [(_hx(e["rid"]), _rn(e["rresp"])) for e in before] or "none",
            [(_hx(e["rid"]), _rn(e["rresp"])) for e in fate["r"]] or "none",
            s5,
        )
        if ar is not None and not fate["r"]:
            self._classify(
                "unanswered-transaction",
                "design-side",
                f"JTAG2AXI read at {_hx(DURING_ADDR)} accepted while sep_reset_n is low, no R to "
                "the end; no pinned source states an answer, SF-003; graded=no, OBS-G2B-RESET-ENDS",
                "dtp_dbg",
            )

    def _j2a_read_after_obs(self, rec: dict) -> None:
        fate = self._dtp_fate(rec)
        ar = fate["ar"]
        self.log.info(
            "OBS-G2B-J2A-READ-AFTER-HOLD: JTAG2AXI read at %s after the bridge write of %s: met=%s "
            "status=%s rdata=%s captures=%s; dtp_dbg AR %s, R %s; the SEP, open owner question "
            "SF-003 (must a request forwarded to sep_in while the IC_RESET override holds "
            "sep_reset_n be answered), observation only, never compared, SF-005",
            _hx(SEP_S6_J2A),
            _hx(W_S6_J2A),
            rec["met"],
            rec["status"],
            _hx(rec["rdata"]),
            rec["captures"],
            f"arid={_hx(ar['arid'])}@{ar['cyc']}" if ar else "none",
            [(_hx(e["rid"]), _rn(e["rresp"]), _hx(e["rdata"])) for e in fate["r"]] or "none",
        )
        if rec["status"] == J2A_STATUS_BUSY:
            self._classify(
                "unanswered-transaction",
                "design-side",
                f"JTAG2AXI read at {_hx(SEP_S6_J2A)} after the hold reports op={rec['status']}; "
                "SF-003; graded=no, OBS-G2B-J2A-READ-AFTER-HOLD",
                "dtp_dbg",
            )

    def _outcome_obs(self) -> None:
        rec = self.holds.get(HOLD, {})
        fall, rise = rec.get("fall"), rec.get("rise")
        mk = self.load.get("mk")
        rows = []
        if mk is not None:
            for ch, rch, ids, key, rkey in (
                ("ar", "r", LOAD_ARIDS, "arid", "rid"),
                ("aw", "b", LOAD_AWIDS, "awid", "bid"),
            ):
                for ident in ids:
                    ends = [
                        x
                        for x in self._since(mk, rch, {ident}, rkey)
                        if rch == "b" or x["rlast"] == 1
                    ]
                    if not ends:
                        fate = "withdrawn (no response to the end)"
                    elif fall is not None and ends[0]["cyc"] <= fall:
                        fate = "completed before the reset"
                    elif rise is not None and ends[0]["cyc"] > rise:
                        fate = "answered after release"
                    else:
                        fate = "answered during the reset"
                    codes = [_rn(x["rresp" if rch == "r" else "bresp"]) for x in ends]
                    rows.append(f"smu_in {ch}id={_hx(ident)}: {fate} {codes}")
        wfall, wrise = self.h["fall"], self.h["rise"]
        for jrec in self.load.get("j2a", ()):
            write = jrec["op"] == J2A_OP_WRITE
            ch, rch, key, rkey = ("aw", "b", "awid", "bid") if write else ("ar", "r", "arid", "rid")
            reqs = self._tsince(jrec["mks"], "dtp_dbg", ch)[:1]
            fate = "no request handshake on dtp_dbg (ignored by the busy port)"
            for e in reqs:
                ends = [
                    x
                    for x in self.taps["dtp_dbg"].ev[rch]
                    if x[rkey] == e[key] and x["cyc"] > e["cyc"] and (rch == "b" or x["rlast"])
                ]
                if not ends:
                    fate = "withdrawn (no response to the end)"
                elif wfall is not None and ends[0]["cyc"] <= wfall:
                    fate = "completed before the reset"
                elif wrise is not None and ends[0]["cyc"] > wrise:
                    fate = "answered after release"
                else:
                    fate = "answered during the reset"
                fate = f"{ch}id={_hx(e[key])}: {fate}"
            rows.append(
                f"dtp_dbg {jrec['label']} {fate} met={jrec['met']} last_status={jrec['status']}"
            )
        store = [e for e in self.taps["xbar_sep_out"].ev["aw"] if e["awaddr"] == EGRESS_HELD]
        if store:
            b = [
                x
                for x in self.taps["xbar_sep_out"].ev["b"]
                if x["bid"] == store[0]["awid"] and x["cyc"] > store[0]["cyc"]
            ]
            fate = (
                "withdrawn (no B to the end)" if not b else f"B {_rn(b[0]['bresp'])} @{b[0]['cyc']}"
            )
            rows.append(f"sep_out store awid={_hx(store[0]['awid'])}: {fate}")
        else:
            rows.append("sep_out store: no AW handshake on sep_out")
        rows.append(f"ext_out held store byte={_hx(self.mem.read_int(EGRESS_HELD, 1))}")
        self.log.info(
            "OBS-G2B-OUTCOME: fall@%s rise@%s (ext_in cycles) %s; observation only, SF-003",
            fall,
            rise,
            "; ".join(rows),
        )

    def _ruling_obs(self) -> None:
        rec = self.holds.get(HOLD, {})
        trace = rec.get("trace", [])
        fall = rec.get("fall")
        before = next((r for r in reversed(trace) if fall is not None and r["cyc"] < fall), {})
        at = next((r for r in trace if r["cyc"] == fall), {})
        withdrawn = (
            before.get("rvalid") == 1 and before.get("rready") == 0 and at.get("rvalid") != 1
        )
        if withdrawn:
            self._classify(
                "checker-fire",
                "checker-side",
                "u_xbar_sep_in_axi_sva and u_iwc_sep_axi_sva R_VALID_HELD at the fall, inside "
                "the expectation window; ruling #2891",
                "xbar_sep_in",
            )
        sepin_later = sum(
            len(
                [
                    c
                    for c in self.h["sepin_high"][s]
                    if self.h["entry"] is None or c != self.h["entry"][0]
                ]
            )
            for s in ("awvalid", "wvalid", "arvalid")
        )
        wfall, wrise = self.h["fall"], self.h["rise"]
        stale = []
        for name in TAPPED:
            tap = self.taps[name]
            for rch, ch, key, rkey in (("b", "aw", "awid", "bid"), ("r", "ar", "arid", "rid")):
                for e in tap.ev[rch]:
                    if wfall is None or wrise is None or e["cyc"] <= wrise:
                        continue
                    prior = [
                        q["cyc"] for q in tap.ev[ch] if q[key] == e[rkey] and q["cyc"] < e["cyc"]
                    ]
                    if prior and max(prior) < wfall:
                        stale.append(f"{name}:{rch}{_hx(e[rkey])}@{e['cyc']}")
        self.log.info(
            "OBS-G2B-RULING-2891: sep_in R at the fall rvalid_before=%s rvalid_at=%s rready=%s "
            "rid=%s withdrawn=%s; crossbar-driven sep_in AW/W/AR high on %d edges after the entry "
            "edge (u_xbar_sep_in_sep_rst_axi_sva rules inside the window), SEP-to-SMC VALID high "
            "on %d (u_sep_to_smc_sep_rst_axi_sva); responses after release with no request "
            "issued after it: %s; accepted under ruling #2891, never a failure; SF-031",
            before.get("rvalid"),
            at.get("rvalid"),
            before.get("rready"),
            _hx(before.get("rid")),
            withdrawn,
            sepin_later,
            self.obs.get("sep2smc_fire", 0),
            stale or "none",
        )

    def _phantom_grade(self, cut_mon: int, cut_w: int) -> None:
        """No B or R on smu_in or dtp_dbg for an ID with nothing outstanding in the issue log."""
        logged = 0
        phantom = []
        x_ids = 0
        streams = {
            "smu_in": (
                self.mon.events,
                self.override["mon"],
                cut_mon,
                ("awid", "bid", "arid", "rid"),
            ),
            "dtp_dbg": (
                self.taps["dtp_dbg"].ev,
                self.override["w"],
                cut_w,
                ("awid", "bid", "arid", "rid"),
            ),
        }
        per_link = {}
        for name, (ev, start, cut, (awk, bk, ark, rk)) in streams.items():
            items = []
            for ch, rank in (("aw", 0), ("ar", 0), ("b", 1), ("r", 1)):
                items += [(e["cyc"], rank, ch, e) for e in ev[ch] if e["cyc"] <= cut]
            items.sort(key=lambda x: (x[0], x[1]))
            wr: Counter = Counter()
            rd: Counter = Counter()
            n = 0
            for cyc, _, ch, e in items:
                if ch == "aw":
                    wr[e[awk]] += 1
                elif ch == "ar":
                    rd[e[ark]] += 1
                elif ch == "b":
                    ident = e[bk]
                    if cyc > start:
                        n += 1
                        x_ids += ident is None
                        if wr[ident] <= 0:
                            phantom.append(f"{name}:b{_hx(ident)}@{cyc}")
                    wr[ident] -= 1
                else:
                    ident = e[rk]
                    if cyc > start:
                        n += 1
                        x_ids += ident is None
                        if rd[ident] <= 0:
                            phantom.append(f"{name}:r{_hx(ident)}@{cyc}")
                    if e.get("rlast") == 1:
                        rd[ident] -= 1
            per_link[name] = n
            logged += n
        sep_out = []
        for rch, key in (("b", "bid"), ("r", "rid")):
            sep_out += [
                f"{rch}{_hx(e[key])}:{_rn(e[rch + 'resp'])}@{e['cyc']}"
                for e in self.taps["xbar_sep_out"].ev[rch]
                if self.override["w"] < e["cyc"] <= cut_w
            ]
        self._info(
            f"G2B-RESPONSES since the override: per link {per_link}; sep_out {sep_out or 'none'}"
        )
        self._verdict(
            "CHK-G2B-NO-PHANTOM",
            {"responses_logged_nonzero": logged > 0, "phantom": phantom, "x_ids": x_ids},
            {"responses_logged_nonzero": True, "phantom": [], "x_ids": 0},
            f"CHK-G2B-NO-PHANTOM: responses_logged={logged} phantom={len(phantom)}",
        )

    def _liveness_grade(self) -> None:
        got = self.routes.get("s6", {})
        want = self.routes.get("s6_want", {})
        okay = sum(1 for k in want if k in got and got[k] == want[k])
        match = 0
        for k in want:
            g = got.get(k)
            if g is not None and g[-1] == want[k][-1]:
                match += 1
        self._verdict(
            "CHK-G2B-LIVENESS",
            got,
            want,
            f"CHK-G2B-LIVENESS: routes={len(got)}/{len(self.routes['s1'])} okay={okay} "
            f"data_match={match}",
        )

    def _sep2smc_grade(self) -> None:
        smc = [r for r in self.accesses if r["term"] == "SEP2SMC"] + list(
            self.routes.get("s6_smc", ())
        )
        rows = {}
        for rec in smc:
            view = self._sep_view(rec)
            rows[rec["label"]] = (
                view["requests"],
                view["one_response_issued_id"],
                rec["id"] is not None,
            )
        ok = sum(1 for v in rows.values() if v == (1, True, True))
        self.log.info("%s", DMA_NOT_DRIVABLE)
        self._verdict(
            "CHK-G2B-SEP2SMC",
            {"accesses": len(rows), "rows": rows},
            {"accesses": 5, "rows": {k: (1, True, True) for k in rows}},
            f"CHK-G2B-SEP2SMC: accesses={len(rows)} one_response_issued_id={ok} "
            "dma_cell=INFO-CELL-NOT-DRIVABLE",
        )

    def _window_grade(self) -> None:
        lv = self.lv
        rec = self.holds.get(HOLD, {})
        fall, rise = rec.get("fall"), rec.get("rise")
        opens = [c for c, label, _ in lv["opens"] if label == HOLD]
        closes = [c for c, label, _ in lv["closes"] if label == HOLD]
        outside = [(c, w) for c, label, w in lv["opens"] + lv["closes"] if label is None]
        opened = int(len(opens) == 1 and fall is not None and 0 <= opens[0] - fall <= 1)
        closed = int(
            len(closes) == 1
            and rise is not None
            and abs(closes[0] - rise - WINDOW_CLOSE_MARGIN) <= 1
        )
        at_end = _val(self.dut.obs_sep_in_expect_window_open)
        count = _val(self.dut.obs_sep_in_expect_window_count)
        prim = len(self.h["prim_fall_inside"])
        self._info(
            f"G2B-WINDOW fall={fall} rise={rise} open={opens} close={closes} outside={outside} "
            f"count={count} open_at_end={at_end} rst_ni_not_high={len(lv['rst_ni_bad'])} "
            f"nets_bad_in_hold={self.h['nets_bad'][:4]}"
        )
        self._verdict(
            "CHK-G2B-WINDOW",
            {
                "holds": count,
                "opened": opened,
                "closed": closed,
                "open_at_end": at_end,
                "primary_fall_inside": prim,
                "edges_outside_hold": outside,
                "rst_ni_and_primary_not_high_in_hold": len(self.h["nets_bad"]),
                "rst_ni_not_high_outside_cold_reset": len(lv["rst_ni_bad"]),
            },
            {
                "holds": 1,
                "opened": 1,
                "closed": 1,
                "open_at_end": 0,
                "primary_fall_inside": 0,
                "edges_outside_hold": [],
                "rst_ni_and_primary_not_high_in_hold": 0,
                "rst_ni_not_high_outside_cold_reset": 0,
            },
            f"CHK-G2B-WINDOW: holds={count} opened={opened} closed={closed} open_at_end={at_end} "
            f"primary_fall_inside={prim}",
        )

    def _nonvac_grade(self) -> None:
        order = [f[0] for f in self.fence]
        times = [f[1] for f in self.fence]
        counts_ok = all(c > 0 and c >= p for _, _, c, p in self.fence)
        used = {t: {k: self.used[t][k] for k in KINDS} for t in FENCE}
        self._verdict(
            "CHK-NONVAC",
            {
                "order": order,
                "times_increasing": all(a < b for a, b in zip(times, times[1:])),
                "counts_at_plan": counts_ok,
                "budget_used": used,
            },
            {
                "order": list(FENCE),
                "times_increasing": True,
                "counts_at_plan": True,
                "budget_used": BUDGET,
            },
            "CHK-NONVAC: "
            + " < ".join(
                f"{t}@{ns}ns(count={c}/{p} "
                + " ".join(f"{k}={self.used[t][k]}/{BUDGET[t][k]}" for k in KINDS)
                + ")"
                for t, ns, c, p in self.fence
            )
            + f"; outside the step budget: {dict(self.config)}",
        )

    def _timeout_grade(self) -> None:
        kinds: dict[tuple, list] = {}
        for s in self.sites:
            kinds.setdefault((s["kind"], s["bound"], s["unit"]), []).append(s)
        for (kind, bound, unit), recs in sorted(kinds.items(), key=str):
            self._info(
                f"G2B-WAIT: {kind} bound={bound} {unit} count={len(recs)} "
                f"max_used={max(r['used'] for r in recs)} last_state={recs[-1]['last']} "
                "on_expiry=fail+INFO-CLASSIFY"
            )
        for win in self.windows:
            self._info(
                f"WINDOW-RECORD {win['label']}: length={win['length']} outcome={win['outcome']} "
                "graded=no"
            )
        expired = [s["label"] for s in self.sites if s["expired"]]
        unbounded = [s["label"] for s in self.sites if not s["bound"]]
        no_last = [s["label"] for s in self.sites if not s["last"]]
        self._verdict(
            "CHK-TIMEOUT-PATHS",
            {
                "sites_nonzero": len(self.sites) > 0,
                "expired": expired,
                "unbounded": unbounded,
                "without_last_state": no_last,
            },
            {"sites_nonzero": True, "expired": [], "unbounded": [], "without_last_state": []},
            f"CHK-TIMEOUT-PATHS: {len(self.sites)} bounded waits, bound and last state per wait, "
            f"{len(expired)} expired; {len(self.windows)} observation windows listed",
        )

    async def run(self) -> None:
        try:
            await self._s1_setup()
            await self._s2_sep2smc()
            await self._s3_load()
            await self._s4_sep_reset()
            await self._s5_nonsep()
            self._valid_low_grade()
            await self._s6_liveness()
        except AssertionError as exc:
            if self.steps.get("S5"):
                self._reset_ends_obs()
            if str(exc).startswith("TIMEOUT"):
                self._classify("unanswered-transaction", "design-side", str(exc), "dtp_dbg")
                self._info(
                    f"G2B-LAST-SEP-LINKS {self._last('xbar_sep_out')} {self._last('sep_to_smc')}"
                )
            raise
        self._reset_ends_obs()
        cut_mon, cut_w = self.mon.cyc, self.wcyc
        self._phantom_grade(cut_mon, cut_w)
        self._liveness_grade()
        self._sep2smc_grade()
        self._outcome_obs()
        self._ruling_obs()
        self._step("S6", "the one cold reset of the leaf")
        self.lv["cold"] = True
        await self._cold_reset("s6")
        self.lv["cold"] = False
        self.lv["on"] = False
        self.watch_on = False
        self._window_grade()
        self._step("S7", "bounded waits and observation windows")
        self.steps["S7"] = True
        self._nonvac_grade()
        self._timeout_grade()
        if self.failures:
            raise AssertionError(f"{len(self.failures)} checker compare(s) failed: {self.failures}")
        self.done = True
