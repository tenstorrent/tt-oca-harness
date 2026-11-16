# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The SMU crossbar with the smc_out and ext_in initiators against a stalling ext_out. No Force.

The smc_out initiators are the DTP JTAG2AXI bridge and the SMC iDMA it
programs; the ext_in initiator is the bench master on the ``ext_in_*`` pins.
The routing table of ``hw/sys/smu/doc/index.adoc`` sends smc_out to sep_in in
the SEP aperture, DECERR in the SMC aperture and ext_out otherwise, and ext_in
to sep_in, smc_in or DECERR. Each aperture covers [base, base + size) in a
57-bit sum. The SEP aperture registers are written over the SEP debug module's
system bus; no SEP-originated traffic is driven.

Observation is passive: every ext_in handshake on the pins, every handshake on
the ext_out responder interface ``u_axi_out_if``, the AW, AR, B and R
handshakes of the crossbar smc_out port decoded from its request and response
structs, the crossbar target-port counters (``sep_xbar_in_*``,
``smc_xbar_in_*``), the DTP debug-link counters and the aperture ports.

S1 SETUP: SMC inbound filter entry 0 and outbound entry 0 over JTAG2AXI, the
   aperture registers read back at their reset, the SEP aperture widened to
   [0, 0x1100_0000) to reach the SEP SRAM, reference patterns written, and
   CTRL-G4-OKAY: one write then read per permitted cell.
S2 STALLED_EXT_OUT: the responder withholds AWREADY/WREADY/ARREADY and delays
   B/R by seeded amounts; an iDMA copy between two ext_out ranges, JTAG2AXI
   single accesses to ext_out and ext_in requests to neither aperture run
   while it does. CTRL-G4-STALL: the iDMA waits for READY at ext_out and an
   ext_in DECERR completes inside the iDMA's ext_out span.
S3 INTERLEAVE: an iDMA copy from the SEP SRAM to ext_out while ext_in issues
   reads and writes under distinct IDs to the SEP SRAM and the SMC scratchpad,
   and a train of reads to the SEP SRAM under the ARID the iDMA used at the
   crossbar smc_out port in S2; an iDMA AR under that ARID at the smc_out port
   while a train read is outstanding is graded.
S4 ROUTE_FWD: per forwarding cell a single-beat and a 32-byte INCR read and
   write; the three target ports are sampled for every request.
S5 DECERR_CELLS: ext_in into neither aperture. The SMC input fabric sends every
   address of its GLOBAL_BASE/REGION_SIZE window, the window the crossbar
   decodes as the SMC aperture, to the SMC local fabric, so no SMC request into
   the SMC aperture reaches the crossbar. The JTAG2AXI write and read into the
   SMC aperture must leave the smc_out port idle, and the cell is printed as not
   drivable.
S6 APERTURE_RESET_SIZES: base+0x00FF_FFFF and base+0x0100_0000 of each aperture
   at its reset placement, from smc_out and from ext_in; the smc_out read inside
   the SMC aperture is the S5 cell and is not issued.
S7 APERTURE_PROGRAMMING: a SEP placement whose end passes 2^56, a 32-bit
   SEP_REGION_SIZE probed at its edge, a reprogram with a read in flight, every
   register restored and read back. SEP_REGION_SIZE.SIZE is 32 bits wide, so a
   boundary value with bits above 31 is not drivable.
S8 TIMEOUT: every wait is a bound counted in clk_smu_i edges or polls; an
   expiry fails the leaf with the last handshakes and the reset-net sample.

The bench protocol checkers and need gates grade under VCS only. On another
simulator the leaf prints INFO-RUN-MODE and its result is not this leaf's
evidence.
"""

from __future__ import annotations

import random
from collections import Counter
from pathlib import Path

import cocotb
from cocotb.triggers import ClockCycles, RisingEdge
from cocotb.utils import get_sim_time
from ocah_axi_vip import PROT_NONSECURE, AxiTimingProfile, clear_profile

from seq_lib.smu_addr_map import (
    OUTBOUND0_END,
    OUTBOUND0_FILTER_CONFIG,
    OUTBOUND0_START,
    c_header_u32,
    smc_addr,
)
from seq_lib.smu_axi_helpers import make_smu_axi_master
from seq_lib.smu_axi_out_addr_len_size_test_seq import (
    DMA_CONFIG,
    DMA_CONFIG_ENABLE_ND,
    DMA_DONE_0,
    DMA_DST_HI,
    DMA_DST_LO,
    DMA_DST_STRIDE_HI,
    DMA_DST_STRIDE_LO,
    DMA_LEN_HI,
    DMA_LEN_LO,
    DMA_NEXT_ID_0,
    DMA_REPS_HI,
    DMA_REPS_LO,
    DMA_SRC_HI,
    DMA_SRC_LO,
    DMA_SRC_STRIDE_HI,
    DMA_SRC_STRIDE_LO,
)
from seq_lib.smu_axi_smc_cool_reset_in_flight_test_seq import XBAR, _Link
from seq_lib.smu_boundary_regs import smc_base_config_u32
from seq_lib.smu_dtp_sep_dm_dmi_test_seq import DMI_OP_READ
from seq_lib.smu_dtp_sep_dm_sba_test_seq import (
    SBADDRESS0_ADDR,
    SBCS_ADDR,
    SBCS_SBACCESS_64,
    SBCS_SBERROR_W1C,
    SBCS_SBREADONADDR,
    SBDATA0_ADDR,
    SBDATA1_ADDR,
    SEP_GLOBAL_BASE_ADDR,
    SEP_GLOBAL_BASE_RESET,
    SEP_REGION_SIZE_ADDR,
    SEP_REGION_SIZE_RESET,
)
from seq_lib.smu_dtp_sep_ic_reset_effect_test_seq import CAPTURE_POLL_CLK, DMI_OP_WRITE
from seq_lib.smu_filter_helpers import PASS_ALL_END, PASS_RW_CONFIG, SMC_APERTURE_LOCAL_BASE
from seq_lib.smu_jtag_helpers import (
    DTP_DEFAULT_IDCODE,
    DTP_IR_SMC_AXI_SINGLE_OP,
    J2A_OP_READ,
    J2A_OP_WRITE,
    J2A_STATUS_BUSY,
    J2A_STATUS_DECERR,
    J2A_STATUS_SUCCESS,
    SMC_DBG_SINGLE_OP_LEN,
    pack_single_op,
    unpack_single_op,
)
from seq_lib.smu_tb_pins import smc_primary_reset
from seq_lib.smu_xbar_decerr_burst_response_test_seq import _hx, _rn, _val
from seq_lib.smu_xbar_reset_held_target_test_seq import smu_xbar_reset_held_target_test_seq

# --- registers and reset values (generated headers) ---
_SEP_ADDR_H = Path(__file__).resolve().parents[6] / "hw/sys/sep/regs/gen/c/sep_addr.h"
SRAM_LOCAL = c_header_u32(_SEP_ADDR_H, "SEP_TOP_SEP_SRAM_BASE_ADDR")
SRAM_SIZE = c_header_u32(_SEP_ADDR_H, "SEP_TOP_SEP_SRAM_SIZE")
SMC_GLOBAL_BASE_REG = smc_addr("SMC_TOP_SMC_BASE_CONFIG_GLOBAL_BASE_BASE_ADDR")
SMC_REGION_SIZE_REG = smc_addr("SMC_TOP_SMC_BASE_CONFIG_REGION_SIZE_BASE_ADDR")
SMC_GLOBAL_BASE_RESET = smc_base_config_u32("SMC_BASE_CONFIG__GLOBAL_BASE__BASE_reset")
SMC_REGION_SIZE_RESET = smc_base_config_u32("SMC_BASE_CONFIG__REGION_SIZE__SIZE_reset")
SPM_LOCAL = smc_addr("SMC_TOP_SPM_MEMORY_BASE_ADDR")

# --- SEP aperture placements (stimulus) ---
# S1-S5: base 0, size covering SEP SRAM; S6 at the RDL reset; S7 two placements.
SEP_WIDE_SIZE = SRAM_LOCAL + 0x0100_0000
CARRY_BASE = 0xFF_FFFF_FF00_0000
CARRY_SIZE = 0x0200_0000
CARRY_PROBE = 0xFF_FFFF_FFFF_FFFF
SIZE32_BASE = 0x1_0000_0000
SIZE32 = 0x1000_1000
ADDR_SPACE = 1 << 56

# --- cell addresses: the routing table rows; SEP SRAM through the S1 placement ---
SEP_SRAM = SRAM_LOCAL
SPM = SMC_GLOBAL_BASE_RESET + (SPM_LOCAL - SMC_APERTURE_LOCAL_BASE)
SEP_FILL_BYTES = 0x1000
SPM_FILL_BYTES = 0x400
NEITHER = 0x3000_0000
EXT_DMA_SRC = 0x5000_0000
EXT_DMA_DST = 0x5010_0000
EXT_J2A = 0x5040_0000
EXT_S3_DST = 0x5050_0000
EXT_S4 = 0x5060_0000
EXT_S4_DMA = 0x5070_0000
SMC_DECERR = SMC_GLOBAL_BASE_RESET + 0x1000
S2_DMA_LEN = 0x4000
S3_DMA_LEN = 0x400
S3_DMA_SRC = SEP_SRAM + 0x800
S4_DMA_LEN = 0x20

# --- bounds, clk_smu_i edges unless named ---
XFER_BOUND = 40_000
DRAIN_BOUND = 60_000
PORT_BOUND = 200
J2A_POLL_LIMIT = 32
DMA_DONE_POLLS = 32
DMA_POLL_CYCLES = 64
TRAIN_LIMIT = 2000
REPROG_HOLD = 60_000
RESPONDER_DEPTH = 4
RESP_DELAY = (8, 64)
STALL_CHOICES = (4, 8, 12, 16)

FENCE = (
    "SETUP",
    "STALLED_EXT_OUT",
    "INTERLEAVE",
    "ROUTE_FWD",
    "DECERR_CELLS",
    "APERTURE_RESET_SIZES",
    "APERTURE_PROGRAMMING",
)
CNT = {
    "sep_aw": "sep_xbar_in_aw_count_o",
    "sep_ar": "sep_xbar_in_ar_count_o",
    "smc_aw": "smc_xbar_in_aw_count_o",
    "smc_ar": "smc_xbar_in_ar_count_o",
    "dtp_aw": "dtp_smc_dbg_aw_count_o",
    "dtp_ar": "dtp_smc_dbg_ar_count_o",
    "dtp_b": "dtp_smc_dbg_b_count_o",
}
_CH = {
    "aw": ("awvalid", "awready", ("awid", "awaddr", "awlen", "awsize", "awburst", "awuser")),
    "w": ("wvalid", "wready", ("wlast",)),
    "b": ("bvalid", "bready", ("bid", "bresp", "buser")),
    "ar": ("arvalid", "arready", ("arid", "araddr", "arlen", "arsize", "arburst", "aruser")),
    "r": ("rvalid", "rready", ("rid", "rresp", "rlast", "rdata", "ruser")),
}
NOT_DRIVABLE = (
    (
        "IWC_SEP_OUT_TO_SMC_IN",
        "this leaf drives no sep_out traffic",
    ),
    (
        "IWC_SEP_OUT_TO_EXT_OUT",
        "this leaf drives no sep_out traffic",
    ),
)
SMC_OUT_SMC_NOT_DRIVABLE = (
    "INFO-CELL-NOT-DRIVABLE SMC_OUT/SMC-aperture-decerr the SMC input fabric sends every address "
    "in [GLOBAL_BASE, GLOBAL_BASE + REGION_SIZE) to its local fabric "
    "(hw/sys/smc/rtl/smc_fabric/smc_input_fabric/rtl/smc_input_fabric.sv:366-369,395-401,417) "
    "and the crossbar decodes the SMC aperture from the same two registers "
    "(hw/sys/smc/rtl/smc_base.sv:481,483; hw/sys/smu/rtl/smu.sv:1020-1021), so no SMC request "
    "into the SMC aperture reaches the smc_out port; its DECERR comes from smc_local_xbar "
    "(hw/sys/smc/rtl/crossbars/smc_local_xbar.sv:9-10)"
)
SIZE_UPPER_NOT_DRIVABLE = (
    "INFO-CELL-NOT-DRIVABLE: SEPAP/size-upper-bits SEP_REGION_SIZE.SIZE is a 32-bit field "
    "(hw/sys/sep/regs/blocks/sep_cpu_ctrl/sep_cpu_ctrl.rdl, size[31:0]) and the crossbar takes "
    "only its lower 32 bits (doc/integrator/src/smu-composition.adoc:131-132), so no boundary "
    "value with bits above 31 can be programmed; the 32-bit size edge is probed instead"
)


def _now() -> int:
    return int(get_sim_time(unit="ns"))


class _Tap:
    """Every handshake of one AXI port at the bench top, sampled on each clk_smu_i edge.

    Each AW/AR event carries the edges its VALID waited for READY. The
    ``sep_xbar_in_ar_count_o`` counter is sampled on the same edges, so a
    sep_in AR is placed in time.
    """

    def __init__(self, dut, name: str, get) -> None:
        self.name = name
        self.dut = dut
        self.cyc = 0
        self.ev: dict[str, list[dict]] = {ch: [] for ch in _CH}
        self.last: dict[str, dict] = {}
        self.pins = {
            ch: (get(v), get(r), {f: get(f) for f in fields}) for ch, (v, r, fields) in _CH.items()
        }
        self.wait_from: dict[str, int | None] = {"aw": None, "ar": None}
        self.sep_ar_cycles: list[int] = []
        self._sep_ar = dut.sep_xbar_in_ar_count_o
        self._sep_ar_last = _val(self._sep_ar)
        self.track_sep = name == "ext_in"

    def sample(self, cyc: int) -> None:
        """Take the handshakes of one clk_smu_i edge."""
        self.cyc = cyc
        for ch, (vh, rh, fields) in self.pins.items():
            v = _val(vh)
            if v != 1:
                if ch in self.wait_from:
                    self.wait_from[ch] = None
                continue
            r = _val(rh)
            if ch in self.wait_from and self.wait_from[ch] is None:
                self.wait_from[ch] = cyc
            if r != 1:
                continue
            e = {"cyc": cyc, "t": _now()}
            e.update({f: _val(h) for f, h in fields.items()})
            if ch in self.wait_from:
                e["wait"] = cyc - self.wait_from[ch]
                self.wait_from[ch] = None
            self.ev[ch].append(e)
            self.last[ch] = e
        if self.track_sep:
            n = _val(self._sep_ar)
            if n is not None and self._sep_ar_last is not None and n > self._sep_ar_last:
                self.sep_ar_cycles.extend([cyc] * (n - self._sep_ar_last))
            self._sep_ar_last = n

    def mark(self) -> dict[str, int]:
        return {ch: len(evs) for ch, evs in self.ev.items()}

    def since(self, mark: dict[str, int], ch: str) -> list[dict]:
        return self.ev[ch][mark[ch] :]

    def state(self) -> str:
        brief = {}
        for ch, e in self.last.items():
            keep = {k: (_hx(v) if isinstance(v, int) else v) for k, v in e.items() if k != "rdata"}
            brief[ch] = keep
        return f"{self.name}: cycle={self.cyc} last={brief}"


class _XbarTap:
    """AW, AR, B and R handshakes of the crossbar smc_out port, decoded from its structs."""

    REQ = (("aw", ("id", "addr", "len", "burst", "atop")), ("ar", ("id", "addr", "len", "burst")))
    RESP = (("b", ("id", "resp")), ("r", ("id", "resp")))

    def __init__(self, dut) -> None:
        self.link = _Link(dut, "xbar_smc_out", f"{XBAR}.smc_out_req_i", f"{XBAR}.smc_out_resp_o")
        self.ev: dict[str, list[dict]] = {"aw": [], "ar": [], "b": [], "r": []}

    def sample(self, cyc: int) -> None:
        """Take the smc_out AW, AR, B and R handshakes of one clk_smu_i edge."""
        link = self.link
        qs, ps = str(link.req.value), str(link.resp.value)
        hs = link.handshakes(qs, ps)
        for group, bits, pos in ((self.REQ, qs, link.q), (self.RESP, ps, link.p)):
            for ch, fields in group:
                if hs[f"{ch}_valid"] == "1" and hs[f"{ch}_ready"] == "1":
                    e = {"cyc": cyc}
                    e.update({f"{ch}{f}": link.field(bits, pos[f"{ch}_{f}"]) for f in fields})
                    if ch == "r":
                        e["rlast"] = int(link.bit(ps, link.p["r_last"]) == "1")
                    self.ev[ch].append(e)

    def mark(self) -> dict[str, int]:
        return {ch: len(evs) for ch, evs in self.ev.items()}

    def since(self, mark: dict[str, int], ch: str) -> list[dict]:
        return self.ev[ch][mark[ch] :]


class smu_axi_concurrent_initiators_stall_test_seq(smu_xbar_reset_held_target_test_seq):
    """smc_out and ext_in through the crossbar with a stalling ext_out, routing and apertures."""

    def __init__(self, test) -> None:
        super().__init__(test)
        self.rng = random.Random(self.seed ^ 0x6C4C_0004)
        self.fence: list[tuple[str, int, int, int]] = []
        self.waits: list[tuple[str, int, str, int, str]] = []
        self.j2a_count = 0
        self.sba_count = 0
        self.dma_id: int | None = None
        self.dma_arids: list[int] = []
        self.xbar_dma_arids: list[int] = []
        self.decerr_beats: list[str] = []
        self.users: list[str] = []
        self.ports_seen: dict[str, str] = {}
        self.ap_obs: list[str] = []
        self.done = False

    # ------------------------------------------------------------------ log / waits

    async def _watch(self) -> None:
        """One coroutine samples both taps on every clk_smu_i edge."""
        cyc = 0
        while True:
            await RisingEdge(self.dut.clk_smu_i)
            cyc += 1
            self.ext.sample(cyc)
            self.out.sample(cyc)
            self.xbar.sample(cyc)

    def _raw(self, msg: str) -> None:
        self.log.info(msg)

    def _rst(self) -> str:
        return _hx(_val(smc_primary_reset(self.dut)))

    def _state(self) -> str:
        return (
            f"{self.ext.state()} {self.out.state()} counters={self._cnt()} "
            f"rst_primary_smc_clk_n_o={self._rst()}"
        )

    def _expire(self, label: str, bound: int, unit: str, what: str) -> None:
        state = self._state()
        self.waits.append((label, bound, unit, bound, f"EXPIRED {state}"))
        self._info(
            f"CLASSIFY: kind=unanswered-transaction class=design-side wait={label} bound={bound} "
            f"{unit} expired; {what}; last={state}"
        )
        raise AssertionError(f"TIMEOUT {label}: {what} not seen within {bound} {unit}; {state}")

    async def _wait(self, label: str, cond, bound: int, what: str) -> int:
        for n in range(bound):
            if cond():
                self.waits.append((label, bound, "clk_smu_i", n, what))
                return n
            await RisingEdge(self.dut.clk_smu_i)
        if cond():
            self.waits.append((label, bound, "clk_smu_i", bound, what))
            return bound
        self._expire(label, bound, "clk_smu_i", what)
        return bound

    def _cnt(self) -> dict[str, int | None]:
        return {k: _val(getattr(self.dut, n)) for k, n in CNT.items()}

    @staticmethod
    def _d(c0: dict, c1: dict) -> dict[str, int | str]:
        return {k: ("X" if c0[k] is None or c1[k] is None else c1[k] - c0[k]) for k in c0}

    def _mark(self, term: str, count: int, planned: int) -> None:
        self.fence.append((term, _now(), count, planned))
        self._info(f"G4-STEP: {term} t={_now()}ns count={count} planned={planned}")

    # ------------------------------------------------------------------ JTAG2AXI / SBA

    async def _j2a(
        self, op: int, addr: int, data: int = 0, *, size: int = 3, label: str
    ) -> tuple[int, int]:
        """One JTAG2AXI single operation; captures until it leaves busy, bounded in polls."""
        nbytes = 1 << size
        wstrb = (((1 << nbytes) - 1) << (addr & 7 & ~(nbytes - 1))) if op == J2A_OP_WRITE else 0
        raw = pack_single_op(op, addr, data, wstrb=wstrb & 0xFF, size=size)
        self.j2a_count += 1
        await self._dr(DTP_IR_SMC_AXI_SINGLE_OP, raw, SMC_DBG_SINGLE_OP_LEN, f"{label}_issue")
        used = 0
        while True:
            captured, _ = await self._dr(
                DTP_IR_SMC_AXI_SINGLE_OP,
                0,
                SMC_DBG_SINGLE_OP_LEN,
                f"{label}_c{used}",
                counted=False,
            )
            status, rdata = unpack_single_op(captured)
            used += 1
            if status != J2A_STATUS_BUSY:
                break
            if used >= J2A_POLL_LIMIT:
                self._expire(label, J2A_POLL_LIMIT, "polls", f"J2A op @0x{addr:x} leaving busy")
            await ClockCycles(self.dut.clk_smu_i, CAPTURE_POLL_CLK)
        self.waits.append((f"j2a_{label}", J2A_POLL_LIMIT, "polls", used, f"status={status}"))
        return status, rdata

    async def _wr32(self, addr: int, value: int, label: str) -> None:
        data = (value & 0xFFFF_FFFF) << (32 if addr & 4 else 0)
        st, _ = await self._j2a(J2A_OP_WRITE, addr, data, size=2, label=label)
        if st != J2A_STATUS_SUCCESS:
            raise AssertionError(f"J2A WR {label} @0x{addr:x} status={st} want SUCCESS")

    async def _rd32(self, addr: int, label: str) -> int:
        st, rd = await self._j2a(J2A_OP_READ, addr, size=2, label=label)
        if st != J2A_STATUS_SUCCESS:
            raise AssertionError(f"J2A RD {label} @0x{addr:x} status={st} want SUCCESS")
        return (rd >> (32 if addr & 4 else 0)) & 0xFFFF_FFFF

    async def _sba_read64(self, addr: int, label: str) -> int:
        self.sba_count += 1
        await self._dmi_op(
            SBCS_ADDR,
            SBCS_SBACCESS_64 | SBCS_SBREADONADDR | SBCS_SBERROR_W1C,
            DMI_OP_WRITE,
            f"{label}_sbcs",
        )
        await self._dmi_op(SBADDRESS0_ADDR, addr, DMI_OP_WRITE, f"{label}_addr")
        await self._sba_wait(label)
        high = await self._dmi_op(SBDATA1_ADDR, 0, DMI_OP_READ, f"{label}_d1")
        low = await self._dmi_op(SBDATA0_ADDR, 0, DMI_OP_READ, f"{label}_d0")
        return (high << 32) | low

    async def _sep_csr(self, which: str, value: int, label: str) -> None:
        """One SEP aperture CSR over the debug system bus; the aperture port settles, bounded."""
        self.sba_count += 1
        addr = SEP_GLOBAL_BASE_ADDR if which == "base" else SEP_REGION_SIZE_ADDR
        await self._sba_write64(addr, value, label)
        port = "sep_xbar_global_base_o" if which == "base" else "sep_xbar_region_size_o"
        want = value if which == "base" else value & 0xFFFF_FFFF
        await self._wait(
            f"{label}_port",
            lambda: _val(getattr(self.dut, port)) == want,
            PORT_BOUND,
            f"{port}==0x{want:x}",
        )

    def _sep_window(self) -> tuple[int, int]:
        return _val(self.dut.sep_xbar_global_base_o), _val(self.dut.sep_xbar_region_size_o)

    # ------------------------------------------------------------------ ext_in

    def _issue(self, *, write: bool, addr: int, nbytes: int, xid: int, size: int = 3, data=None):
        if write:
            payload = (
                data if data is not None else bytes((xid * 7 + i) & 0xFF for i in range(nbytes))
            )
            return self.master.init_write(
                addr, payload, size=size, prot=PROT_NONSECURE, burst=1, awid=xid
            )
        return self.master.init_read(
            addr, nbytes, size=size, prot=PROT_NONSECURE, burst=1, arid=xid
        )

    async def _ext(
        self, label: str, *, write: bool, addr: int, nbytes: int, xid: int, size=3, data=None
    ):
        """One ext_in transaction, bounded; its pin handshakes and the counter deltas."""
        c0 = self._cnt()
        mk = self.ext.mark()
        omk = self.out.mark()
        ev = self._issue(write=write, addr=addr, nbytes=nbytes, xid=xid, size=size, data=data)
        resp_ch = "b" if write else "r"
        key = "bid" if write else "rid"

        def answered() -> bool:
            evs = [e for e in self.ext.since(mk, resp_ch) if e[key] == xid]
            return ev.is_set() and (write or any(e["rlast"] == 1 for e in evs))

        await self._wait(f"ext_{label}", answered, XFER_BOUND, f"{resp_ch.upper()} id=0x{xid:x}")
        await ClockCycles(self.dut.clk_smu_i, 2)
        c1 = self._cnt()
        resp = self.ext.since(mk, resp_ch)
        return {
            "label": label,
            "write": write,
            "addr": addr,
            "xid": xid,
            "resp": resp,
            "mine": [e for e in resp if e[key] == xid],
            "other": [e for e in resp if e[key] != xid],
            "req": self.ext.since(mk, "aw" if write else "ar"),
            "d": self._d(c0, c1),
            "out_aw": self.out.since(omk, "aw"),
            "out_ar": self.out.since(omk, "ar"),
        }

    @staticmethod
    def _codes(t: dict) -> list[str]:
        key = "bresp" if t["write"] else "rresp"
        return [_rn(e[key]) for e in t["mine"]]

    def _rdata(self, t: dict, nbytes: int) -> bytes:
        out = b""
        for e in t["mine"]:
            out += (e["rdata"] or 0).to_bytes(8, "little")
        off = t["addr"] & 7
        return out[off : off + nbytes]

    def _one_resp(self, t: dict) -> bool:
        if t["write"]:
            return len(t["mine"]) == 1 and not t["other"]
        lasts = [e for e in t["mine"] if e["rlast"] == 1]
        return len(lasts) == 1 and not t["other"]

    # ------------------------------------------------------------------ iDMA

    async def _dma_program(self, regs: list[tuple[int, int, str]]) -> None:
        for addr, value, name in regs:
            await self._wr32(addr, value, f"DMA_{name}")

    async def _dma_launch(self, label: str) -> tuple[int, int]:
        """Read NEXT_ID (submits the descriptor); return (start_id, axi-side cycle)."""
        start_id = await self._rd32(DMA_NEXT_ID_0, f"{label}_launch")
        return start_id, self.ext.cyc

    async def _dma_done(self, label: str, start_id: int) -> int:
        done = None
        for n in range(DMA_DONE_POLLS):
            done = await self._rd32(DMA_DONE_0, f"{label}_done{n}")
            if done == start_id:
                self.waits.append(
                    (f"{label}_dma_done", DMA_DONE_POLLS, "polls", n + 1, f"done={done}")
                )
                return done
            await ClockCycles(self.dut.clk_smu_i, DMA_POLL_CYCLES)
        self._expire(
            f"{label}_dma_done", DMA_DONE_POLLS, "polls", f"DONE==0x{start_id:x} (last {done})"
        )
        return -1

    def _out_pairing(
        self, aws: list[dict], ars: list[dict], bs: list[dict], rs: list[dict]
    ) -> dict:
        """Exactly one B per AW and one RLAST per AR, per ID, in the ext_out tap."""
        aw_ids = Counter(e["awid"] for e in aws)
        b_ids = Counter(e["bid"] for e in bs)
        ar_ids = Counter(e["arid"] for e in ars)
        rl_ids = Counter(e["rid"] for e in rs if e["rlast"] == 1)
        return {"aw_b_paired": aw_ids == b_ids, "ar_rlast_paired": ar_ids == rl_ids}

    def _xbar_since(self, xmk: dict[str, int]) -> dict[str, list[dict]]:
        x = {ch: self.xbar.since(xmk, ch) for ch in ("aw", "ar", "b", "r")}
        x["rl"] = [e for e in x["r"] if e["rlast"] == 1]
        return x

    @staticmethod
    def _xbar_pairs(x: dict[str, list[dict]]) -> dict:
        """One B per AW ID and one RLAST per AR ID at the crossbar smc_out port, and the codes."""
        return {
            "b_per_aw": Counter(e["awid"] for e in x["aw"]) == Counter(e["bid"] for e in x["b"]),
            "rlast_per_ar": Counter(e["arid"] for e in x["ar"])
            == Counter(e["rid"] for e in x["rl"]),
            "codes": sorted({_rn(e["bresp"]) for e in x["b"]} | {_rn(e["rresp"]) for e in x["r"]}),
        }

    # ------------------------------------------------------------------ S1

    async def _s1_setup(self) -> None:
        dut = self.dut
        sb = self.sb
        await self.cfg.reset_done.wait()
        self.ext = _Tap(dut, "ext_in", lambda n: getattr(dut, f"ext_in_{n}"))
        self.out = _Tap(dut, "ext_out", lambda n: getattr(dut.u_axi_out_if, n))
        self.xbar = _XbarTap(dut)
        cocotb.start_soon(self._watch())
        await RisingEdge(dut.clk_smu_i)
        self.stall = self.rng.choice(STALL_CHOICES)
        self.prof = AxiTimingProfile(
            ar_delay=self.rng.randint(0, 6),
            w_delay=self.rng.randint(0, 6),
            b_ready_delay=self.rng.randint(0, 12),
            r_ready_delay=self.rng.randint(0, 12),
        )
        self._raw(
            f"INFO-SEED: RANDOM_SEED={self.seed} responder_stall={self.stall} "
            f"responder_resp_delay={RESP_DELAY} master_profile={self.prof}; the request set is fixed"
        )
        self._info("STEP S1: SETUP")
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
            st, _ = await self._j2a(J2A_OP_WRITE, addr, data, label=f"s1_outbound0_{name}")
            outb.append(st)
        smc_base = await self._rd32(SMC_GLOBAL_BASE_REG, "s1_smc_global_base")
        smc_size = await self._rd32(SMC_REGION_SIZE_REG, "s1_smc_region_size")
        dmactive = await self._activate_debug_module("s1")
        sep_base = await self._sba_read64(SEP_GLOBAL_BASE_ADDR, "s1_sep_base_rb")
        sep_size = await self._sba_read64(SEP_REGION_SIZE_ADDR, "s1_sep_size_rb")
        self.reset_rb = (sep_base, sep_size, smc_base, smc_size)
        sb.expect_eq(
            "S1 access path open and aperture registers at their RDL reset",
            (
                _hx(idcode),
                dbg,
                security,
                inb,
                outb,
                dmactive,
                _hx(sep_base),
                _hx(sep_size),
                _hx(smc_base),
                _hx(smc_size),
            ),
            (
                _hx(DTP_DEFAULT_IDCODE),
                0,
                0,
                [J2A_STATUS_SUCCESS] * 3,
                [J2A_STATUS_SUCCESS] * 3,
                1,
                _hx(SEP_GLOBAL_BASE_RESET),
                _hx(SEP_REGION_SIZE_RESET),
                _hx(SMC_GLOBAL_BASE_RESET),
                _hx(SMC_REGION_SIZE_RESET),
            ),
        )
        self._info(f"G4-SETUP: lc_state={_hx(lc)} reset readback={[_hx(v) for v in self.reset_rb]}")
        await self._sep_csr("size", SEP_WIDE_SIZE, "s1_sep_size_wide")
        self.master = await make_smu_axi_master(dut, dut.clk_smu_i, smc_primary_reset(dut))
        clear_profile(self.master.driver)
        mem = self.cfg.axi_out_mem
        sb.expect_eq("G4 responder depth", mem.max_outstanding, RESPONDER_DEPTH)
        # reference patterns: SEP SRAM, SMC scratchpad, responder memory
        self.sep_pat = bytes((0x5E + 3 * i) & 0xFF for i in range(SEP_FILL_BYTES))
        self.spm_pat = bytes((0x3C + 5 * i) & 0xFF for i in range(SPM_FILL_BYTES))
        fills = []
        for k in range(SEP_FILL_BYTES // 0x800):
            t = await self._ext(
                f"s1_fill_sep{k}",
                write=True,
                addr=SEP_SRAM + 0x800 * k,
                nbytes=0x800,
                xid=0x01,
                data=self.sep_pat[0x800 * k : 0x800 * (k + 1)],
            )
            fills.append(self._codes(t))
        t = await self._ext(
            "s1_fill_spm", write=True, addr=SPM, nbytes=SPM_FILL_BYTES, xid=0x02, data=self.spm_pat
        )
        fills.append(self._codes(t))
        sb.expect_eq("S1 reference fills OKAY", fills, [["OKAY"]] * len(fills))
        # CTRL-G4-OKAY: one write then read per permitted cell
        ok = {}
        for cell, addr, word in (
            ("smc_out->sep_in", SEP_SRAM + 0x1000 - 0x40, 0x5E50_0000_0000_0011),
            ("smc_out->ext_out", EXT_J2A + 0x80, 0xE7E7_0000_0000_0012),
        ):
            st_w, _ = await self._j2a(J2A_OP_WRITE, addr, word, label=f"s1_ok_{cell}_wr")
            st_r, rd = await self._j2a(J2A_OP_READ, addr, label=f"s1_ok_{cell}_rd")
            ok[cell] = (st_w, st_r, _hx(rd))
            if cell == "smc_out->sep_in":
                self.sep_pat = (
                    self.sep_pat[: 0x1000 - 0x40]
                    + word.to_bytes(8, "little")
                    + self.sep_pat[0x1000 - 0x38 :]
                )
        want = {
            "smc_out->sep_in": (J2A_STATUS_SUCCESS, J2A_STATUS_SUCCESS, _hx(0x5E50_0000_0000_0011)),
            "smc_out->ext_out": (
                J2A_STATUS_SUCCESS,
                J2A_STATUS_SUCCESS,
                _hx(0xE7E7_0000_0000_0012),
            ),
        }
        for cell, addr, xid in (
            ("ext_in->sep_in", SEP_SRAM + 0x1000 - 0x80, 0x03),
            ("ext_in->smc_in", SPM + SPM_FILL_BYTES + 0x40, 0x04),
        ):
            word = bytes((xid * 0x11 + i) & 0xFF for i in range(8))
            w = await self._ext(
                f"s1_ok_{cell}_wr", write=True, addr=addr, nbytes=8, xid=xid, data=word
            )
            r = await self._ext(
                f"s1_ok_{cell}_rd", write=False, addr=addr, nbytes=8, xid=xid + 0x10
            )
            ok[cell] = (self._codes(w), self._codes(r), self._rdata(r, 8).hex())
            want[cell] = (["OKAY"], ["OKAY"], word.hex())
            if cell == "ext_in->sep_in":
                off = 0x1000 - 0x80
                self.sep_pat = self.sep_pat[:off] + word + self.sep_pat[off + 8 :]
        sb.expect_eq("CTRL-G4-OKAY one write then read per permitted cell", ok, want)
        self._raw(f"CTRL-G4-OKAY: cells={len(ok)} {ok}")
        for cell, why in NOT_DRIVABLE:
            self._raw(f"INFO-CELL-NOT-DRIVABLE: {cell} {why}")
        self._mark("SETUP", len(ok), 4)

    # ------------------------------------------------------------------ S2

    async def _s2_stalled(self) -> None:
        dut = self.dut
        sb = self.sb
        mem = self.cfg.axi_out_mem
        self._info("STEP S2: STALLED_EXT_OUT")
        src_pat = bytes((0xA5 ^ (i * 13)) & 0xFF for i in range(S2_DMA_LEN))
        mem.write(EXT_DMA_SRC, src_pat)
        mem.write(EXT_DMA_DST, bytes(S2_DMA_LEN))
        await self._dma_program(
            [
                (DMA_CONFIG, DMA_CONFIG_ENABLE_ND, "CONFIG"),
                (DMA_DST_LO, EXT_DMA_DST & 0xFFFF_FFFF, "DST_LO"),
                (DMA_DST_HI, EXT_DMA_DST >> 32, "DST_HI"),
                (DMA_SRC_LO, EXT_DMA_SRC & 0xFFFF_FFFF, "SRC_LO"),
                (DMA_SRC_HI, EXT_DMA_SRC >> 32, "SRC_HI"),
                (DMA_LEN_LO, S2_DMA_LEN, "LEN_LO"),
                (DMA_LEN_HI, 0, "LEN_HI"),
                (DMA_DST_STRIDE_LO, 0, "DST_STRIDE_LO"),
                (DMA_DST_STRIDE_HI, 0, "DST_STRIDE_HI"),
                (DMA_SRC_STRIDE_LO, 0, "SRC_STRIDE_LO"),
                (DMA_SRC_STRIDE_HI, 0, "SRC_STRIDE_HI"),
                (DMA_REPS_LO, 1, "REPS_LO"),
                (DMA_REPS_HI, 0, "REPS_HI"),
            ]
        )
        baseline = await self._rd32(DMA_DONE_0, "s2_done_baseline")
        lo, hi = RESP_DELAY
        delays = iter(lambda: self.rng.randint(lo, hi), None)
        mem.set_response_delay(delays)
        mem.enable_backpressure(channels=("aw", "w", "ar"), stall_cycles=self.stall)
        self.master.driver.set_timing(self.prof)
        c0 = self._cnt()
        mk = self.ext.mark()
        omk = self.out.mark()
        xmk = self.xbar.mark()
        start_id, _ = await self._dma_launch("s2")
        # ext_in to neither aperture while the copy runs against the stalled responder
        ids_r = (0x20, 0x21, 0x22, 0x23)
        ids_w = (0x24, 0x25, 0x26, 0x27)
        reqs = []
        for n, xid in enumerate(ids_r):
            reqs.append(
                (
                    "r",
                    xid,
                    NEITHER + 0x40 * n,
                    self._issue(write=False, addr=NEITHER + 0x40 * n, nbytes=8, xid=xid),
                )
            )
        for n, xid in enumerate(ids_w):
            a = NEITHER + 0x400 + 0x40 * n
            reqs.append(("w", xid, a, self._issue(write=True, addr=a, nbytes=8, xid=xid)))
        word = 0x4A2A_0000_0000_5302
        j2a_addr = EXT_J2A + 0x100
        st_w, _ = await self._j2a(J2A_OP_WRITE, j2a_addr, word, label="s2_j2a_ext_wr")
        st_r, rd = await self._j2a(J2A_OP_READ, j2a_addr, label="s2_j2a_ext_rd")
        done = await self._dma_done("s2", start_id)
        await self._wait(
            "s2_ext_in_answered",
            lambda: all(e.is_set() for *_, e in reqs),
            XFER_BOUND,
            "every S2 ext_in B and RLAST",
        )

        def drained() -> bool:
            aws, ars = self.out.since(omk, "aw"), self.out.since(omk, "ar")
            bs = self.out.since(omk, "b")
            rl = [e for e in self.out.since(omk, "r") if e["rlast"] == 1]
            return len(bs) >= len(aws) and len(rl) >= len(ars)

        await self._wait("s2_ext_out_drain", drained, DRAIN_BOUND, "every ext_out B and RLAST")
        await ClockCycles(dut.clk_smu_i, 4)
        mem.disable_backpressure()
        mem.clear_response_delay()
        clear_profile(self.master.driver)
        c1 = self._cnt()
        aws, ars = self.out.since(omk, "aw"), self.out.since(omk, "ar")
        bs, rs = self.out.since(omk, "b"), self.out.since(omk, "r")
        dma_aw = [e for e in aws if EXT_DMA_DST <= (e["awaddr"] or 0) < EXT_DMA_DST + S2_DMA_LEN]
        dma_ar = [e for e in ars if EXT_DMA_SRC <= (e["araddr"] or 0) < EXT_DMA_SRC + S2_DMA_LEN]
        j_aw = [e for e in aws if e["awaddr"] == j2a_addr]
        j_ar = [e for e in ars if e["araddr"] == j2a_addr]
        other = [e for e in aws + ars if e not in dma_aw + dma_ar + j_aw + j_ar]
        self.dma_arids = sorted({e["arid"] for e in dma_ar if e["arid"] is not None})
        x_aw, x_ar = self.xbar.since(xmk, "aw"), self.xbar.since(xmk, "ar")
        self.xbar_dma_arids = sorted(
            {
                e["arid"]
                for e in x_ar
                if e["arid"] is not None
                and EXT_DMA_SRC <= (e["araddr"] or 0) < EXT_DMA_SRC + S2_DMA_LEN
            }
        )
        pair = self._out_pairing(aws, ars, bs, rs)
        dst = mem.read(EXT_DMA_DST, S2_DMA_LEN)
        rd_bytes = sum(((e["arlen"] or 0) + 1) << (e["arsize"] or 0) for e in dma_ar)
        wr_bytes = sum(((e["awlen"] or 0) + 1) << (e["awsize"] or 0) for e in dma_aw)
        ext = []
        for kind, xid, a, _ in reqs:
            if kind == "r":
                got = [e for e in self.ext.since(mk, "r") if e["rid"] == xid]
                ext.append((kind, xid, [(_rn(e["rresp"]), e["rlast"]) for e in got]))
            else:
                got = [e for e in self.ext.since(mk, "b") if e["bid"] == xid]
                ext.append((kind, xid, [_rn(e["bresp"]) for e in got]))
        ext_want = [(k, x, [("DECERR", 1)] if k == "r" else ["DECERR"]) for k, x, _, _ in reqs]
        neither_out = [
            e
            for e in aws + ars
            if NEITHER <= (e.get("awaddr") or e.get("araddr") or 0) < NEITHER + 0x1000
        ]
        d = self._d(c0, c1)
        observed = {
            "done": done,
            "dst_equals_src": dst == src_pat,
            "dma_bursts_incr": sorted(
                {e["awburst"] for e in dma_aw} | {e["arburst"] for e in dma_ar}
            ),
            "dma_bytes": (rd_bytes, wr_bytes),
            "pairing": pair,
            "j2a": (st_w, st_r, _hx(rd), len(j_aw), len(j_ar)),
            "ext_in": ext,
            "ext_in_at_ext_out": len(neither_out),
            "other_ext_out": len(other),
            "targets": (d["sep_aw"], d["sep_ar"], d["smc_aw"], d["smc_ar"]),
        }
        expected = {
            "done": start_id,
            "dst_equals_src": True,
            "dma_bursts_incr": [1],
            "dma_bytes": (S2_DMA_LEN, S2_DMA_LEN),
            "pairing": {"aw_b_paired": True, "ar_rlast_paired": True},
            "j2a": (J2A_STATUS_SUCCESS, J2A_STATUS_SUCCESS, _hx(word), 1, 1),
            "ext_in": ext_want,
            "ext_in_at_ext_out": 0,
            "other_ext_out": 0,
            "targets": (0, 0, 0, 0),
        }
        self._info(f"G4-S2 observed={observed} baseline_done={baseline} start_id={start_id}")
        sb.expect_eq("CHK-G4-CONC-EXTOUT", observed, expected, evidence="CHK-G4-CONC-EXTOUT")
        self._raw(
            f"CHK-G4-CONC-EXTOUT: idma_bursts={len(dma_aw) + len(dma_ar)} j2a=2 "
            f"ext_in_decerr={len(reqs)} mismatches=0"
        )
        last_dma_b = max((e["cyc"] for e in bs), default=0)
        ext_resp = self.ext.since(mk, "r") + self.ext.since(mk, "b")
        last_decerr = max((e["cyc"] for e in ext_resp), default=0)
        dma_wait = max((e["wait"] for e in dma_aw + dma_ar), default=0)
        first_dma = min((e["cyc"] for e in dma_aw + dma_ar), default=last_dma_b + 1)
        decerr_in_span = [
            e
            for e in ext_resp
            if first_dma <= e["cyc"] <= last_dma_b
            and _rn(e["rresp"] if "rresp" in e else e["bresp"]) == "DECERR"
        ]
        sb.expect_eq(
            "CTRL-G4-STALL iDMA READY wait at ext_out and an ext_in DECERR inside its ext_out span",
            (dma_wait > 0, len(decerr_in_span) > 0),
            (True, True),
        )
        self._raw(
            f"CTRL-G4-STALL: idma_ready_wait_max={dma_wait} ext_in_decerr_in_span="
            f"{len(decerr_in_span)} span=[{first_dma},{last_dma_b}] clk_smu_i"
        )
        self._raw(
            f"OBS-G4-GRANT-WAIT: ext_out max AW wait idma={max((e['wait'] for e in dma_aw), default=0)} "
            f"j2a={max((e['wait'] for e in j_aw), default=0)} max AR wait "
            f"idma={max((e['wait'] for e in dma_ar), default=0)} j2a={max((e['wait'] for e in j_ar), default=0)} "
            f"ext_in max AW wait={max((e['wait'] for e in self.ext.since(mk, 'aw')), default=0)} "
            f"AR wait={max((e['wait'] for e in self.ext.since(mk, 'ar')), default=0)} clk_smu_i; "
            f"ext_in DECERR completed during the stall={last_decerr < last_dma_b} "
            f"(last DECERR cycle {last_decerr}, last ext_out B cycle {last_dma_b}); waits on an "
            f"open spec question (the crossbar arbitration and bounded progress under a stalled "
            f"ext_out), never compared"
        )
        for e in self.ext.since(mk, "r"):
            self.decerr_beats.append(
                f"S2 rid=0x{e['rid']:x} rdata={_hx(e['rdata'])} ruser={_hx(e['ruser'])}"
            )
        for e in self.ext.since(mk, "b"):
            self.decerr_beats.append(f"S2 bid=0x{e['bid']:x} buser={_hx(e['buser'])}")
        self._raw(
            f"OBS-G4-ATOP-SMC: smc_out AWs at the crossbar port in S2={len(x_aw)} with "
            f"AWATOP={sorted({_hx(e['awatop']) for e in x_aw})} "
            f"AWBURST={sorted({_hx(e['awburst']) for e in x_aw})}; waits on an open spec question "
            f"(whether the fabric carries ATOP and how an atomic request is answered), never "
            f"compared"
        )
        self.s2_ext_out = (len(dma_aw), len(dma_ar))
        self._mark("STALLED_EXT_OUT", len(dma_aw) + len(dma_ar) + 2 + len(reqs), 2 + 2 + len(reqs))

    # ------------------------------------------------------------------ S3

    async def _s3_interleave(self) -> None:
        dut = self.dut
        sb = self.sb
        mem = self.cfg.axi_out_mem
        self._info("STEP S3: INTERLEAVE")
        width = len(dut.ext_in_arid)
        mask = (1 << width) - 1
        shared = (self.xbar_dma_arids[0] if self.xbar_dma_arids else 0) & mask
        self._raw(
            f"OBS-G4-IWC: ext_in ID width={width} smc_out ID width={self.xbar.link.idw} "
            f"ext_out ID width={len(dut.u_axi_out_if.arid)} iDMA ARIDs at smc_out="
            f"{[_hx(i) for i in self.xbar_dma_arids]} at ext_out={[_hx(i) for i in self.dma_arids]}; "
            f"the converter outputs have no observation point; waits on an open spec question "
            f"(where the ID-width converters sit and how they handle ID exhaustion), never compared"
        )
        mem.write(EXT_S3_DST, bytes(S3_DMA_LEN))
        mem.set_response_delay(iter(lambda: self.rng.randint(*RESP_DELAY), None))
        await self._dma_program(
            [
                (DMA_DST_LO, EXT_S3_DST & 0xFFFF_FFFF, "DST_LO"),
                (DMA_SRC_LO, S3_DMA_SRC & 0xFFFF_FFFF, "SRC_LO"),
                (DMA_LEN_LO, S3_DMA_LEN, "LEN_LO"),
            ]
        )
        self.master.driver.set_timing(
            AxiTimingProfile(r_ready_delay=24, b_ready_delay=self.prof.b_ready_delay)
        )
        mk = self.ext.mark()
        omk = self.out.mark()
        xmk = self.xbar.mark()
        stop = {"flag": False}
        train: dict = {"n": 0, "addrs": []}

        async def same_id_train() -> None:
            """Reads of the SEP SRAM under ``shared``, two in flight, until the copy is done."""
            pending: list = []
            for n in range(TRAIN_LIMIT):
                if stop["flag"]:
                    break
                a = SEP_SRAM + 8 * (n % 64)
                pending.append(self._issue(write=False, addr=a, nbytes=8, xid=shared))
                train["n"] += 1
                train["addrs"].append(a)
                if len(pending) == 2:
                    await self._wait(
                        f"s3_train_{n}", pending[0].is_set, XFER_BOUND, f"R id=0x{shared:x}"
                    )
                    pending.pop(0)
            for k, ev in enumerate(pending):
                await self._wait(f"s3_train_tail{k}", ev.is_set, XFER_BOUND, f"R id=0x{shared:x}")

        task = cocotb.start_soon(same_id_train())
        # distinct IDs interleaved toward both targets
        plan = []
        for n, xid in enumerate((0x30, 0x31, 0x32, 0x33)):
            plan.append(("r", xid, SEP_SRAM + 0x100 + 0x20 * n, "sep"))
        for n, xid in enumerate((0x34, 0x35, 0x36, 0x37)):
            plan.append(("r", xid, SPM + 0x100 + 0x20 * n, "spm"))
        for n, xid in enumerate((0x38, 0x39)):
            plan.append(("w", xid, SEP_SRAM + 0xC00 + 0x20 * n, "sep"))
        for n, xid in enumerate((0x3A, 0x3B)):
            plan.append(("w", xid, SPM + 0x200 + 0x20 * n, "spm"))
        evs = [
            (k, x, a, tgt, self._issue(write=k == "w", addr=a, nbytes=8, xid=x))
            for k, x, a, tgt in plan
        ]
        start_id, _ = await self._dma_launch("s3")
        done = await self._dma_done("s3", start_id)
        stop["flag"] = True
        await self._wait("s3_train_end", task.done, XFER_BOUND, "same-ID train finished")
        await self._wait(
            "s3_interleaved", lambda: all(e.is_set() for *_, e in evs), XFER_BOUND, "S3 B and RLAST"
        )

        def drained() -> bool:
            return len(self.out.since(omk, "b")) >= len(self.out.since(omk, "aw"))

        await self._wait("s3_ext_out_drain", drained, DRAIN_BOUND, "every ext_out B")
        await ClockCycles(dut.clk_smu_i, 4)
        mem.clear_response_delay()
        clear_profile(self.master.driver)
        # per-ID pairing on the ext_in pins
        issued_r: dict[int, int] = {}
        issued_w: dict[int, int] = {}
        for e in self.ext.since(mk, "ar"):
            issued_r[e["arid"]] = issued_r.get(e["arid"], 0) + 1
        for e in self.ext.since(mk, "aw"):
            issued_w[e["awid"]] = issued_w.get(e["awid"], 0) + 1
        got_r: dict[int, int] = {}
        got_w: dict[int, int] = {}
        for e in self.ext.since(mk, "r"):
            if e["rlast"] == 1:
                got_r[e["rid"]] = got_r.get(e["rid"], 0) + 1
        for e in self.ext.since(mk, "b"):
            got_w[e["bid"]] = got_w.get(e["bid"], 0) + 1
        want_ids = {x for _, x, *_ in plan} | {shared}
        wrong = sorted(
            {i for i in list(got_r) + list(got_w) if i not in want_ids},
            key=lambda v: -1 if v is None else v,
        )
        data_bad = []
        for k, x, a, tgt, _ in evs:
            if k != "r":
                continue
            beats = [e for e in self.ext.since(mk, "r") if e["rid"] == x]
            word = (beats[0]["rdata"] or 0).to_bytes(8, "little") if beats else b""
            ref = self.sep_pat if tgt == "sep" else self.spm_pat
            base = SEP_SRAM if tgt == "sep" else SPM
            if word != ref[a - base : a - base + 8] or _rn(beats[0]["rresp"]) != "OKAY":
                data_bad.append((hex(a), x, word.hex()))
        w_codes = [
            _rn(e["bresp"])
            for e in self.ext.since(mk, "b")
            if e["bid"] in {x for k, x, *_ in plan if k == "w"}
        ]
        # same ID at sep_in from both initiators: a sep_in AR beyond the train's own during one of its reads
        t_ar = [e["cyc"] for e in self.ext.since(mk, "ar") if e["arid"] == shared]
        t_r = [e["cyc"] for e in self.ext.since(mk, "r") if e["rid"] == shared]
        # the same ID value at the crossbar: an iDMA AR to the SEP SRAM under the train ARID at the
        # smc_out port while a train read (one beat each, returned in order) is outstanding
        t_rl = [e["cyc"] for e in self.ext.since(mk, "r") if e["rid"] == shared and e["rlast"] == 1]
        spans = list(zip(t_ar, t_rl))
        # the train's reads, in issue order, against its ARs at the pins and its R beats in order
        train_bad = []
        t_ar_addrs = [e["araddr"] for e in self.ext.since(mk, "ar") if e["arid"] == shared]
        t_beats = [e for e in self.ext.since(mk, "r") if e["rid"] == shared]
        if t_ar_addrs != train["addrs"] or len(t_beats) != len(train["addrs"]):
            train_bad.append(("count/order", len(train["addrs"]), len(t_ar_addrs), len(t_beats)))
        for k, (a, e) in enumerate(zip(train["addrs"], t_beats)):
            word = (e["rdata"] or 0).to_bytes(8, "little")
            ref = self.sep_pat[a - SEP_SRAM : a - SEP_SRAM + 8]
            if word != ref or _rn(e["rresp"]) != "OKAY" or e["rlast"] != 1:
                train_bad.append((k, hex(a), word.hex(), _rn(e["rresp"]), e["rlast"]))
        same_id_xbar = [
            e["cyc"]
            for e in self.xbar.since(xmk, "ar")
            if e["arid"] == shared
            and SEP_SRAM <= (e["araddr"] or 0) < SEP_SRAM + SRAM_SIZE
            and any(a <= e["cyc"] <= r for a, r in spans)
        ]
        overlap = 0
        if t_ar and t_r:
            lo, hi = t_ar[0], t_r[-1]
            sep_in_ars = len([c for c in self.ext.sep_ar_cycles if lo <= c <= hi])
            ext_sep_ars = len(
                [
                    e
                    for e in self.ext.since(mk, "ar")
                    if lo <= e["cyc"] <= hi
                    and SEP_SRAM <= (e["araddr"] or 0) < SEP_SRAM + SRAM_SIZE
                ]
            )
            overlap = sep_in_ars - ext_sep_ars
        oaws, obs = self.out.since(omk, "aw"), self.out.since(omk, "b")
        pair = self._out_pairing(oaws, [], obs, [])
        x = self._xbar_since(xmk)
        x_pairs = self._xbar_pairs(x)
        dst = mem.read(EXT_S3_DST, S3_DMA_LEN)
        src_ref = self.sep_pat[S3_DMA_SRC - SEP_SRAM : S3_DMA_SRC - SEP_SRAM + S3_DMA_LEN]
        observed = {
            "read_pairing": issued_r == got_r,
            "write_pairing": issued_w == got_w,
            "wrong_initiator": wrong,
            "data_bad": data_bad,
            "write_codes": w_codes,
            "dma_done": done,
            "dma_dst_equals_sep_sram": dst == src_ref,
            "ext_out_pairing": pair["aw_b_paired"],
            "train_reads": train["n"] > 0,
            "train_data_in_order": train_bad[:4],
            "same_id_overlap": overlap > 0,
            "same_id_at_xbar_smc_out": len(same_id_xbar) > 0,
            "smc_out_xbar_aw_ar": (len(x["aw"]) > 0, len(x["ar"]) > 0),
            "smc_out_xbar_resp": x_pairs,
        }
        expected = {
            "read_pairing": True,
            "write_pairing": True,
            "wrong_initiator": [],
            "data_bad": [],
            "write_codes": ["OKAY"] * 4,
            "dma_done": start_id,
            "dma_dst_equals_sep_sram": True,
            "ext_out_pairing": True,
            "train_reads": True,
            "train_data_in_order": [],
            "same_id_overlap": True,
            "same_id_at_xbar_smc_out": True,
            "smc_out_xbar_aw_ar": (True, True),
            "smc_out_xbar_resp": {"b_per_aw": True, "rlast_per_ar": True, "codes": ["OKAY"]},
        }
        self._info(
            f"G4-S3 observed={observed} shared_id=0x{shared:x} train={train['n']} "
            f"overlap_sep_in_ar={overlap} idma_ar_same_id_at_smc_out_cycles={same_id_xbar[:8]} "
            f"issued_r={issued_r} issued_w={issued_w} smc_out_xbar aw={len(x['aw'])} "
            f"ar={len(x['ar'])} b={len(x['b'])} rlast={len(x['rl'])}"
        )
        sb.expect_eq("CHK-G4-IWC-ID", observed, expected, evidence="CHK-G4-IWC-ID")
        responses = sum(got_r.values()) + sum(got_w.values()) + len(obs) + 1
        self._raw(
            f"CHK-G4-IWC-ID: responses={responses} id_mismatch=0 wrong_initiator=0 "
            f"smc_out_xbar_b={len(x['b'])}/aw={len(x['aw'])} "
            f"smc_out_xbar_rlast={len(x['rl'])}/ar={len(x['ar'])} "
            f"same_id_train_reads_in_order={len(t_beats)}"
        )
        self._mark("INTERLEAVE", responses, len(plan) + 2)

    # ------------------------------------------------------------------ S4

    async def _j2a_cell(self, label: str, op: int, addr: int, data: int = 0, size: int = 3) -> dict:
        """One JTAG2AXI access with the target-port counters and the ext_out tap around it."""
        c0 = self._cnt()
        omk = self.out.mark()
        xmk = self.xbar.mark()
        st, rd = await self._j2a(op, addr, data, size=size, label=label)
        await ClockCycles(self.dut.clk_smu_i, 2)
        c1 = self._cnt()
        key = "awaddr" if op == J2A_OP_WRITE else "araddr"
        ch = "aw" if op == J2A_OP_WRITE else "ar"
        return {
            "label": label,
            "st": st,
            "rd": rd,
            "d": self._d(c0, c1),
            "out_hits": [e for e in self.out.since(omk, ch) if e[key] == addr],
            "out_all": self.out.since(omk, ch),
            "out_b": self.out.since(omk, "b"),
            "out_r": self.out.since(omk, "r"),
            "x": self._xbar_since(xmk),
        }

    @staticmethod
    def _route(d: dict, out_hits: int, write: bool) -> tuple:
        k = "aw" if write else "ar"
        return (d[f"sep_{k}"], d[f"smc_{k}"], out_hits)

    async def _s4_route_fwd(self) -> None:
        sb = self.sb
        mem = self.cfg.axi_out_mem
        self._info("STEP S4: ROUTE_FWD")
        got, want = {}, {}
        users = []
        xbar_rows = []
        n_req = 0
        # ext_in SEP and ext_in SMC: single beat and INCR AxLEN 3, write then read
        for cell, base, port in (
            ("ext_in SEP", SEP_SRAM + 0xE00, "sep"),
            ("ext_in SMC", SPM + 0x600, "smc"),
        ):
            for shape, nbytes in (("single", 8), ("incr3", 32)):
                a = base + (0x40 if shape == "incr3" else 0)
                xid = 0x40 + n_req
                data = bytes((xid * 3 + i) & 0xFF for i in range(nbytes))
                w = await self._ext(
                    f"s4_{port}_{shape}_wr", write=True, addr=a, nbytes=nbytes, xid=xid, data=data
                )
                r = await self._ext(
                    f"s4_{port}_{shape}_rd", write=False, addr=a, nbytes=nbytes, xid=xid + 1
                )
                n_req += 2
                route_w = self._route(w["d"], len(w["out_aw"]), True)
                route_r = self._route(r["d"], len(r["out_ar"]), False)
                tgt = (1, 0, 0) if port == "sep" else (0, 1, 0)
                got[f"{cell} {shape}"] = (
                    route_w,
                    route_r,
                    self._codes(w),
                    sorted(set(self._codes(r))),
                    self._one_resp(w) and self._one_resp(r),
                    [e["awlen"] for e in w["req"]] + [e["arlen"] for e in r["req"]],
                    self._rdata(r, nbytes).hex(),
                )
                beats = nbytes // 8
                want[f"{cell} {shape}"] = (
                    tgt,
                    tgt,
                    ["OKAY"],
                    ["OKAY"],
                    True,
                    [beats - 1, beats - 1],
                    data.hex(),
                )
                users.append(
                    f"{cell}/{shape}: ext_in awuser={[_hx(e['awuser']) for e in w['req']]} "
                    f"aruser={[_hx(e['aruser']) for e in r['req']]} buser={[_hx(e['buser']) for e in w['mine']]} "
                    f"ruser={[_hx(e['ruser']) for e in r['mine']]} sep_in awuser={_hx(_val(self.dut.sep_xbar_in_aw_user_o))}"
                )
                if port == "sep":
                    off = a - SEP_SRAM
                    self.sep_pat = self.sep_pat[:off] + data + self.sep_pat[off + nbytes :]
        # smc_out SEP and smc_out neither: JTAG2AXI single beat
        for cell, addr, word, tgt_w, tgt_r in (
            ("smc_out SEP", SEP_SRAM + 0xF00, 0x5E5E_0000_0000_0F00, (1, 0, 0), (1, 0, 0)),
            ("smc_out neither", EXT_S4, 0xE0E0_0000_0000_6000, (0, 0, 1), (0, 0, 1)),
        ):
            w = await self._j2a_cell(f"s4_{cell}_wr", J2A_OP_WRITE, addr, word)
            r = await self._j2a_cell(f"s4_{cell}_rd", J2A_OP_READ, addr)
            n_req += 2
            got[f"{cell} single"] = (
                self._route(w["d"], len(w["out_hits"]), True),
                self._route(r["d"], len(r["out_hits"]), False),
                (w["st"], r["st"], _hx(r["rd"])),
                (w["d"]["dtp_aw"], w["d"]["dtp_b"], r["d"]["dtp_ar"]),
                (
                    [_hx(e["awaddr"]) for e in w["x"]["aw"]],
                    [_hx(e["araddr"]) for e in r["x"]["ar"]],
                ),
                (self._xbar_pairs(w["x"]), self._xbar_pairs(r["x"])),
            )
            want[f"{cell} single"] = (
                tgt_w,
                tgt_r,
                (J2A_STATUS_SUCCESS, J2A_STATUS_SUCCESS, _hx(word)),
                (1, 1, 1),
                ([_hx(addr)], [_hx(addr)]),
                (
                    {"b_per_aw": True, "rlast_per_ar": True, "codes": ["OKAY"]},
                    {"b_per_aw": True, "rlast_per_ar": True, "codes": ["OKAY"]},
                ),
            )
            xbar_rows.append(
                f"{cell}: AW id={[_hx(e['awid']) for e in w['x']['aw']]} B id="
                f"{[_hx(e['bid']) for e in w['x']['b']]} AR id={[_hx(e['arid']) for e in r['x']['ar']]} "
                f"RLAST id={[_hx(e['rid']) for e in r['x']['rl']]}"
            )
            if cell == "smc_out SEP":
                off = addr - SEP_SRAM
                self.sep_pat = (
                    self.sep_pat[:off] + word.to_bytes(8, "little") + self.sep_pat[off + 8 :]
                )
            for e in w["out_hits"] + r["out_hits"]:
                users.append(f"{cell}: ext_out axuser={_hx(e.get('awuser', e.get('aruser')))}")
        # smc_out INCR: 32-byte iDMA copies ext_out -> SEP SRAM, then SEP SRAM -> ext_out
        pat = bytes((0xC3 + 11 * i) & 0xFF for i in range(S4_DMA_LEN))
        mem.write(EXT_S4_DMA, pat)
        mem.write(EXT_S4_DMA + 0x100, bytes(S4_DMA_LEN))
        dma_rows = []
        for leg, src, dst in (
            ("to_sep", EXT_S4_DMA, SEP_SRAM + 0xF80),
            ("from_sep", SEP_SRAM + 0xF80, EXT_S4_DMA + 0x100),
        ):
            await self._dma_program(
                [
                    (DMA_DST_LO, dst & 0xFFFF_FFFF, "DST_LO"),
                    (DMA_SRC_LO, src & 0xFFFF_FFFF, "SRC_LO"),
                    (DMA_LEN_LO, S4_DMA_LEN, "LEN_LO"),
                ]
            )
            c0 = self._cnt()
            omk = self.out.mark()
            xmk = self.xbar.mark()
            start_id, _ = await self._dma_launch(f"s4_{leg}")
            done = await self._dma_done(f"s4_{leg}", start_id)
            await self._wait(
                f"s4_{leg}_drain",
                lambda: len(self.out.since(omk, "b")) >= len(self.out.since(omk, "aw")),
                DRAIN_BOUND,
                "every ext_out B",
            )
            c1 = self._cnt()
            d = self._d(c0, c1)
            oar, oaw = self.out.since(omk, "ar"), self.out.since(omk, "aw")
            x = self._xbar_since(xmk)
            x_req = (
                [(_hx(e["araddr"]), e["arlen"], e["arburst"]) for e in x["ar"]],
                [(_hx(e["awaddr"]), e["awlen"], e["awburst"]) for e in x["aw"]],
            )
            # 32 bytes of 8-byte beats: one INCR burst of AxLEN 3 on each side of the copy
            x_want = ([(_hx(src), 3, 1)], [(_hx(dst), 3, 1)])
            if leg == "to_sep":
                got_leg = (done == start_id, d["sep_aw"], d["smc_aw"], [e["araddr"] for e in oar])
                got_leg += (len(oaw),)
                want_leg = (True, 1, 0, [src], 0)
            else:
                got_leg = (done == start_id, d["sep_ar"], d["smc_ar"], [e["awaddr"] for e in oaw])
                got_leg += (len(oar),)
                want_leg = (True, 1, 0, [dst], 0)
            got[f"smc_out iDMA {leg}"] = got_leg + (x_req, self._xbar_pairs(x))
            want[f"smc_out iDMA {leg}"] = want_leg + (
                x_want,
                {"b_per_aw": True, "rlast_per_ar": True, "codes": ["OKAY"]},
            )
            n_req += 2
            dma_rows.append(
                f"{leg}: smc_out AR addr/len/burst={x_req[0]} AW addr/len/burst={x_req[1]} B id="
                f"{[_hx(e['bid']) for e in x['b']]} RLAST id={[_hx(e['rid']) for e in x['rl']]} "
                f"sep_in aw/ar delta={d['sep_aw']}/{d['sep_ar']}"
            )
        got["smc_out iDMA round trip data"] = mem.read(EXT_S4_DMA + 0x100, S4_DMA_LEN).hex()
        want["smc_out iDMA round trip data"] = pat.hex()
        self._info(f"G4-S4 crossbar smc_out port: {xbar_rows} {dma_rows}")
        sb.expect_eq("CHK-G4-ROUTE-FWD", got, want, evidence="CHK-G4-ROUTE-FWD")
        self._raw(
            f"CHK-G4-ROUTE-FWD: cells=4 requests={n_req} misrouted=0 id_mismatch=0 "
            f"smc_out_incr_len3_at_xbar=2"
        )
        self._raw(
            f"OBS-G4-USER: {users}; smc_in AxUSER and the SMC port smc_in drives have no "
            f"bench-top observation point; waits on open spec questions (whether the crossbar "
            f"forwards every USER field unchanged; whether the crossbar smc_in drives the SMC "
            f"sys_axi_in), never compared"
        )
        self._raw(
            f"OBS-G4-ADDR: SEP aperture base=0x0 size=0x{SEP_WIDE_SIZE:x} SEP SRAM global="
            f"0x{SEP_SRAM:x}..0x{SEP_SRAM + SEP_FILL_BYTES:x} (SEP-local 0x{SRAM_LOCAL:x}); SMC "
            f"scratchpad global=0x{SPM:x} (local 0x{SPM_LOCAL:x}); inbound filter entry 0 "
            f"[0x0, 0x{PASS_ALL_END:x}] config=0x{PASS_RW_CONFIG:x}; outbound entry 0 pass-all; "
            f"waits on an open spec question (which addresses and filter entries reach the SEP "
            f"SRAM and SMC scratchpad), never compared"
        )
        self._mark("ROUTE_FWD", n_req, 16)

    # ------------------------------------------------------------------ S5

    async def _s5_decerr(self) -> None:
        sb = self.sb
        self._info("STEP S5: DECERR_CELLS")
        xmk = self.xbar.mark()
        w = await self._j2a_cell(
            "s5_smc_out_smc_wr", J2A_OP_WRITE, SMC_DECERR, 0xDEC0_0000_0000_0005
        )
        r = await self._j2a_cell("s5_smc_out_smc_rd", J2A_OP_READ, SMC_DECERR)
        x = self._xbar_since(xmk)
        x_counts = tuple(len(x[ch]) for ch in ("aw", "ar", "b", "r"))
        dtp = (w["d"]["dtp_aw"], w["d"]["dtp_b"], r["d"]["dtp_ar"])
        sb.expect_eq(
            "S5 JTAG2AXI write and read in the SMC aperture enter the SMC on the DTP link and "
            "leave the crossbar smc_out port idle",
            (dtp, x_counts),
            ((1, 1, 1), (0, 0, 0, 0)),
        )
        self._raw(
            f"{SMC_OUT_SMC_NOT_DRIVABLE}; the JTAG2AXI write and read at 0x{SMC_DECERR:x} moved the "
            f"DTP link AW/B/AR by {'/'.join(map(str, dtp))}, put AW/AR/B/R="
            f"{'/'.join(map(str, x_counts))} on the crossbar smc_out port and ended "
            f"with JTAG2AXI status {w['st']}/{r['st']}; the S6 smc_out read at SMC+0x00FF_FFFF "
            f"is the same cell and is not issued"
        )
        ew = await self._ext(
            "s5_ext_in_neither_wr", write=True, addr=NEITHER + 0x800, nbytes=8, xid=0x50
        )
        er = await self._ext(
            "s5_ext_in_neither_rd", write=False, addr=NEITHER + 0x800, nbytes=8, xid=0x51
        )

        def tgt(t: dict) -> int:
            moved = sum(t["d"][k] for k in ("sep_aw", "sep_ar", "smc_aw", "smc_ar"))
            return moved + len(t["out_aw"]) + len(t["out_ar"])

        observed = {
            "ext_in neither wr": (
                self._codes(ew),
                [e["bid"] for e in ew["mine"]],
                self._one_resp(ew),
                tgt(ew),
            ),
            "ext_in neither rd": (
                [(_rn(e["rresp"]), e["rlast"], e["rid"]) for e in er["mine"]],
                self._one_resp(er),
                tgt(er),
            ),
        }
        expected = {
            "ext_in neither wr": (["DECERR"], [0x50], True, 0),
            "ext_in neither rd": ([("DECERR", 1, 0x51)], True, 0),
        }
        self._info(f"G4-S5 observed={observed}")
        sb.expect_eq("CHK-G4-ROUTE-DECERR", observed, expected, evidence="CHK-G4-ROUTE-DECERR")
        self._raw("CHK-G4-ROUTE-DECERR: cells=1 requests=2 decerr=2 target_aw_ar=0")
        for e in er["mine"]:
            self.decerr_beats.append(
                f"S5 rid=0x{e['rid']:x} rdata={_hx(e['rdata'])} ruser={_hx(e['ruser'])}"
            )
        for e in ew["mine"]:
            self.decerr_beats.append(f"S5 bid=0x{e['bid']:x} buser={_hx(e['buser'])}")
        self._raw(
            f"OBS-G4-DECERR-CONTENT: {self.decerr_beats}; a data-known fire on a DECERR beat is "
            f"checker-side; waits on open spec questions (the data, user and per-beat codes of a "
            f"crossbar DECERR; whether RDATA must be resolved on error beats), never compared"
        )
        self._mark("DECERR_CELLS", 4, 4)

    # ------------------------------------------------------------------ S6 / S7 probes

    async def _probe(
        self, label: str, init: str, addr: int, size: int, expect: str, xid: int
    ) -> tuple:
        """One single-beat read; the decoded route from the target counters and the response."""
        if init == "smc_out":
            t = await self._j2a_cell(label, J2A_OP_READ, addr, size=size)
            d, hits = t["d"], len(t["out_hits"])
            decerr = t["st"] == J2A_STATUS_DECERR
            answered = t["st"] != J2A_STATUS_BUSY and t["d"]["dtp_ar"] == 1
        else:
            t = await self._ext(label, write=False, addr=addr, nbytes=1 << size, xid=xid, size=size)
            d = t["d"]
            hits = len([e for e in t["out_ar"] if e["araddr"] == addr])
            decerr = [_rn(e["rresp"]) for e in t["mine"]] == ["DECERR"]
            answered = self._one_resp(t)
        if d["sep_ar"] == 1 and d["smc_ar"] == 0 and (hits == 0 or expect == "sep_in"):
            route = "sep_in"
        elif d["smc_ar"] == 1 and d["sep_ar"] == 0 and hits == 0:
            route = "smc_in"
        elif hits == 1 and d["sep_ar"] == 0 and d["smc_ar"] == 0:
            route = "ext_out"
        elif decerr and d["sep_ar"] == 0 and d["smc_ar"] == 0 and hits == 0:
            route = "DECERR"
        else:
            route = f"sep_ar={d['sep_ar']} smc_ar={d['smc_ar']} ext_out={hits} decerr={decerr}"
        if expect == "sep_in" and hits:
            self._info(
                f"G4-PROBE {label}: ext_out AR at 0x{addr:x} after the sep_in AR (SEP outbound)"
            )
        self._info(f"G4-PROBE {label}: init={init} addr=0x{addr:x} route={route} expect={expect}")
        return (route, answered)

    async def _s6_reset_sizes(self) -> list:
        self._info("STEP S6: APERTURE_RESET_SIZES")
        await self._sep_csr("size", SEP_REGION_SIZE_RESET, "s6_sep_size_reset")
        sep_b, sep_s = self._sep_window()
        smc_b, smc_s = _val(self.dut.smc_global_base_o), _val(self.dut.smc_region_size_o)
        rows = []
        n = 0
        for ap, base, size, inside, outside in (
            ("SEP", sep_b, sep_s, "sep_in", None),
            ("SMC", smc_b, smc_s, None, None),
        ):
            for off, where in ((0x00FF_FFFF, "in"), (0x0100_0000, "out")):
                addr = base + off
                for init in ("smc_out", "ext_in"):
                    if (ap, where, init) == ("SMC", "in", "smc_out"):
                        continue
                    if ap == "SEP":
                        exp = (
                            "sep_in"
                            if where == "in"
                            else ("ext_out" if init == "smc_out" else "DECERR")
                        )
                    else:
                        if where == "in":
                            exp = "smc_in"
                        else:
                            exp = "ext_out" if init == "smc_out" else "DECERR"
                    got = await self._probe(f"s6_{ap}_{where}_{init}", init, addr, 0, exp, 0x60 + n)
                    n += 1
                    rows.append((f"{ap}+0x{off:x} {init}", got, (exp, True)))
        self.ap_obs.append(
            f"reset SEP_GLOBAL_BASE_ADDR={_hx(self.reset_rb[0])} GLOBAL_BASE={_hx(self.reset_rb[2])} "
            f"ports sep=({_hx(sep_b)},{_hx(sep_s)}) smc=({_hx(smc_b)},{_hx(smc_s)})"
        )
        self._mark("APERTURE_RESET_SIZES", len(rows), 7)
        return rows

    async def _s7_programming(self) -> list:
        self._info("STEP S7: APERTURE_PROGRAMMING")
        rows = []
        # 57-bit carry: base + size passes 2^56
        await self._sep_csr("base", CARRY_BASE, "s7_carry_base")
        await self._sep_csr("size", CARRY_SIZE, "s7_carry_size")
        b, s = self._sep_window()
        self._info(
            f"G4-S7 carry placement ports base={_hx(b)} size={_hx(s)} end=0x{b + s:x} > 2^56={b + s > ADDR_SPACE}"
        )
        for n, init in enumerate(("smc_out", "ext_in")):
            got = await self._probe(f"s7_carry_{init}", init, CARRY_PROBE, 0, "sep_in", 0x70 + n)
            rows.append((f"carry 0x{CARRY_PROBE:x} {init}", got, ("sep_in", True)))
        # 32-bit SEP_REGION_SIZE: the last word below base+size and base+size
        self._raw(SIZE_UPPER_NOT_DRIVABLE)
        await self._sep_csr("base", SIZE32_BASE, "s7_size32_base")
        await self._sep_csr("size", SIZE32, "s7_size32_size")
        for n, (where, off, exp_s, exp_e) in enumerate(
            (("in", SIZE32 - 8, "sep_in", "sep_in"), ("edge", SIZE32, "ext_out", "DECERR"))
        ):
            for k, init in enumerate(("smc_out", "ext_in")):
                exp = exp_s if init == "smc_out" else exp_e
                got = await self._probe(
                    f"s7_size32_{where}_{init}", init, SIZE32_BASE + off, 3, exp, 0x72 + 2 * n + k
                )
                rows.append((f"size32 {where} 0x{SIZE32_BASE + off:x} {init}", got, (exp, True)))
        self._raw(
            "INFO-CELL-NOT-DRIVABLE: APERTURE_OVERLAP hw/sys/smu/doc/index.adoc states the SEP and SMC "
            "ranges must not overlap and the crossbar asserts that rule, so an overlapping "
            "configuration is not programmed; which aperture wins stays an open spec question"
        )
        # reprogram with a read in flight: the R is held while SEP_REGION_SIZE returns to reset
        inflight_addr = SIZE32_BASE + SRAM_LOCAL
        self.master.driver.set_timing(AxiTimingProfile(r_ready_delay=REPROG_HOLD))
        mk = self.ext.mark()
        ev = self._issue(write=False, addr=inflight_addr, nbytes=8, xid=0x7A)
        await self._wait(
            "s7_inflight_ar",
            lambda: any(e["arid"] == 0x7A for e in self.ext.since(mk, "ar")),
            XFER_BOUND,
            "AR id=0x7a",
        )
        await self._sep_csr("size", SEP_REGION_SIZE_RESET, "s7_reprogram_size")
        r_before = [e for e in self.ext.since(mk, "r") if e["rid"] == 0x7A]
        await self._wait("s7_inflight_r", ev.is_set, REPROG_HOLD + XFER_BOUND, "R id=0x7a")
        clear_profile(self.master.driver)
        r = [e for e in self.ext.since(mk, "r") if e["rid"] == 0x7A]
        after = await self._probe("s7_after_reprogram", "ext_in", inflight_addr, 3, "DECERR", 0x7B)
        self.ap_obs.append(
            f"in-flight read 0x{inflight_addr:x} across SEP_REGION_SIZE {_hx(SIZE32)}->"
            f"{_hx(SEP_REGION_SIZE_RESET)}: r_before_reprogram={len(r_before)} "
            f"r={[(_rn(e['rresp']), _hx(e['rdata'])) for e in r]}; same address after={after}"
        )
        # restore and read back every register
        await self._sep_csr("base", SEP_GLOBAL_BASE_RESET, "s7_restore_base")
        rb = (
            await self._sba_read64(SEP_GLOBAL_BASE_ADDR, "s7_sep_base_rb"),
            await self._sba_read64(SEP_REGION_SIZE_ADDR, "s7_sep_size_rb"),
            await self._rd32(SMC_GLOBAL_BASE_REG, "s7_smc_base_rb"),
            await self._rd32(SMC_REGION_SIZE_REG, "s7_smc_size_rb"),
        )
        rows.append(
            (
                "restored readback",
                tuple(_hx(v) for v in rb),
                tuple(
                    _hx(v)
                    for v in (
                        SEP_GLOBAL_BASE_RESET,
                        SEP_REGION_SIZE_RESET,
                        SMC_GLOBAL_BASE_RESET,
                        SMC_REGION_SIZE_RESET,
                    )
                ),
            )
        )
        self._mark("APERTURE_PROGRAMMING", len(rows), 7)
        return rows

    # ------------------------------------------------------------------ run

    async def run(self) -> None:
        sb = self.sb
        sim = cocotb.SIM_NAME or "unknown simulator"
        graded = "graded by the bench at final" if "vcs" in sim.lower() else "not graded"
        self._raw(f"INFO-RUN-MODE: {sim}, protocol gates {graded}")
        await self._s1_setup()
        await self._s2_stalled()
        await self._s3_interleave()
        await self._s4_route_fwd()
        await self._s5_decerr()
        rows = await self._s6_reset_sizes()
        rows += await self._s7_programming()
        got = {name: g for name, g, _ in rows}
        want = {name: w for name, _, w in rows}
        bad = [name for name in got if got[name] != want[name]]
        self._info(f"G4-APERTURE rows={got}")
        self._raw(
            f"OBS-G4-APERTURE: {self.ap_obs}; waits on an open spec question (the aperture reset "
            f"values and which aperture wins an overlap), never compared"
        )
        sb.expect_eq("CHK-G4-APERTURE", got, want, evidence="CHK-G4-APERTURE")
        edges = len([r for r in rows if r[0][:4] in ("SEP+", "SMC+", "carr", "size")])
        self._raw(f"CHK-G4-APERTURE: edges={edges}/13 misdecoded={len(bad)}")
        # ordered fence
        order = [f[0] for f in self.fence]
        times = [f[1] for f in self.fence]
        counts_ok = all(c > 0 and c >= p for _, _, c, p in self.fence)
        sb.expect_true(
            f"CHK-NONVAC fence order={order} counts_ok={counts_ok}",
            order == list(FENCE) and times == sorted(times) and counts_ok,
            evidence="CHK-NONVAC",
        )
        self._raw("CHK-NONVAC: " + " < ".join(f"{n}@{t}ns({c}/{p})" for n, t, c, p in self.fence))
        expired = [w for w in self.waits if str(w[4]).startswith("EXPIRED")]
        kinds: dict[tuple, list] = {}
        for name, bound, unit, used, last in self.waits:
            key = (name.rstrip("0123456789"), bound, unit)
            kinds.setdefault(key, []).append((used, last))
        sb.expect_true(
            f"CHK-TIMEOUT-PATHS waits={len(self.waits)} expired={len(expired)}",
            not expired and len(self.waits) > 0,
            evidence="CHK-TIMEOUT-PATHS",
        )
        for (name, bound, unit), uses in sorted(kinds.items(), key=str):
            self._info(
                f"G4-WAIT: {name} bound={bound} {unit} count={len(uses)} max_used="
                f"{max(u for u, _ in uses)} last_state={uses[-1][1]} on_expiry=fail+INFO-CLASSIFY"
            )
        self._raw(
            f"CHK-TIMEOUT-PATHS: {len(self.waits)} bounded waits, bound and last state per wait, "
            f"0 expired; j2a_accesses={self.j2a_count} sba_accesses={self.sba_count}"
        )
        self.done = True
