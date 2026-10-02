# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Unsupported-access refusal on drbg_axil64_lane_adapter.

Contract (hw/ip/drbg/rtl/drbg_axil64_lane_adapter.sv header and
hw/ip/drbg/doc/architecture.adoc "Bus Protocol Adaptation"): a read must be
4-byte aligned; a write must be 4-byte aligned with WSTRB exactly 0x0F for the
lower lane or 0xF0 for the upper lane, selected by address bit 2. Every other
access is answered AXI SLVERR and emits no downstream request.

Two drivers:

* ``RefusalVehicle`` presents one access pin-level at the TB-owned instance
  ``u_tbadp_vehicle`` and records the response code, the read data and every
  cycle in which the adapter drove a request on its AXI-Lite-32 side
  (``tbadp_fwd_o``). The vehicle reaches every refusal condition, including
  the strobe patterns a single AXI master transfer cannot produce.
* ``SepDrbgLaneRefusal`` reaches the DUT's own CSRNG and EDN adapters as
  ordinary CSR traffic over s_axi. There the "no downstream request" half is
  graded on the lane adapter's own AXI-Lite-32 request (``drbg_csrng_fwd_o`` /
  ``drbg_edn_fwd_o``, sampled every cycle of the access by ``FwdWatch``), and
  through two DUT-visible consequences: the target register keeps its value,
  and the lane's ``PERIPH_BUS_ERR_STATUS`` bit (the bridge's sticky TL-UL
  error, hw/sys/sep/doc/crypto.adoc "Crypto Register-Bridge Faults") stays
  clear.

A probe value that is X or Z is counted, never read as "nothing forwarded".
"""

from __future__ import annotations

from dataclasses import dataclass

import cocotb
from cocotb.triggers import ClockCycles, RisingEdge
from env.sep_axi_agent import SepAxiOp
from env.sep_seeded_rng import SepSeededRng
from env.sep_spec_tables import AXI_BUS_BYTES, axi_lane_strobe
from sep_reg_meta import CSRNG, EDN, SEP_CPU_CTRL, sym

from seq_lib.sep_axi_access_seq import SepAxiAccessSeq, capture_addr_handshake, take_handshake
from seq_lib.sep_drbg_adapter_port_seq import (
    AR_READY,
    AR_VALID,
    AW_READY,
    AW_VALID,
    RESP_OKAY,
    RETIRE_TIMEOUT_CYCLES,
    W_READY,
    W_VALID,
    AdapterPortVehicle,
)

RESP_SLVERR = 2

# The word the vehicle's always-ready AXI-Lite-32 responder returns on every
# read (tb/tb_top.sv, tbadp_rsp32.r.data). A forwarded read answers it in the
# lane its address selects.
TBADP_RESPONDER_RDATA = 0xA5A5_1234

# tbadp_fwd_o bit positions.
FWD_WRITE, FWD_READ = 1 << 0, 1 << 1

# Cycles sampled after the response handshake, so a request the adapter
# raised late is still seen.
POST_RESP_CYCLES = 4

LANE_BYTES = 4
LOWER_LANE = 0x0
UPPER_LANE = LANE_BYTES

# Refused vehicle cells: (name, op, addr, strobe). Strobes are AMBA's
# (sep_spec_tables.axi_lane_strobe), not the adapter's own predicate, so each
# cell states the protocol meaning of what it presents.
VEHICLE_REFUSED: tuple[tuple[str, SepAxiOp, int, int], ...] = (
    *(
        (f"rd-misaligned-{base:x}+{off}", SepAxiOp.READ, base + off, 0)
        for base in (LOWER_LANE, UPPER_LANE)
        for off in range(1, LANE_BYTES)
    ),
    ("wr-lower-addr-upper-strb", SepAxiOp.WRITE, LOWER_LANE, axi_lane_strobe(UPPER_LANE)),
    ("wr-upper-addr-lower-strb", SepAxiOp.WRITE, UPPER_LANE, axi_lane_strobe(LOWER_LANE)),
    ("wr-full-beat", SepAxiOp.WRITE, LOWER_LANE, axi_lane_strobe(LOWER_LANE, AXI_BUS_BYTES)),
    ("wr-lower-byte", SepAxiOp.WRITE, LOWER_LANE, axi_lane_strobe(LOWER_LANE, 1)),
    ("wr-upper-halfword", SepAxiOp.WRITE, UPPER_LANE, axi_lane_strobe(UPPER_LANE, 2)),
    ("wr-zero-strb", SepAxiOp.WRITE, LOWER_LANE, 0),
    ("wr-misaligned-lower", SepAxiOp.WRITE, LOWER_LANE + 1, axi_lane_strobe(LOWER_LANE)),
    ("wr-misaligned-upper", SepAxiOp.WRITE, UPPER_LANE + 1, axi_lane_strobe(UPPER_LANE)),
)

VEHICLE_WDATA = 0x0123_4567_89AB_CDEF


class FwdWatch:
    """OR of a ``{ar_valid, aw_valid | w_valid}`` probe over every cycle of a window.

    ``unknown`` counts the cycles on which the probe is X or Z. Such a cycle
    cannot be graded as "nothing forwarded", so a caller requires it to be 0.
    """

    def __init__(self, signal) -> None:
        self.signal = signal
        self.bits = 0
        self.unknown = 0
        self.cycles = 0
        self._task = None

    async def _run(self) -> None:
        clk = cocotb.top.clk_i
        while True:
            await RisingEdge(clk)
            self.cycles += 1
            try:
                self.bits |= int(self.signal.value)
            except ValueError:
                self.unknown += 1

    def start(self) -> FwdWatch:
        self._task = cocotb.start_soon(self._run())
        return self

    async def stop(self) -> FwdWatch:
        """Sample ``POST_RESP_CYCLES`` more cycles, then stop."""
        await ClockCycles(cocotb.top.clk_i, POST_RESP_CYCLES)
        if hasattr(self._task, "cancel"):
            self._task.cancel()
        else:
            self._task.kill()
        return self

    def describe(self) -> str:
        return f"fwd=0b{self.bits:02b} over {self.cycles} cycles ({self.unknown} X/Z)"


class RefusalVehicle(AdapterPortVehicle):
    """One access at a time on ``u_tbadp_vehicle``, with the downstream probe."""

    async def access(self, name: str, op: SepAxiOp, addr: int, strb: int = 0) -> dict:
        """Present one access, hold each VALID to its handshake, return the observation."""
        d = self.dut
        is_wr = op is SepAxiOp.WRITE
        obs = {
            "name": name,
            "op": op.value,
            "addr": addr,
            "strb": strb,
            "resp": None,
            "rdata": None,
            "fwd": 0,
            "fwd_x": 0,
            "retired": False,
            "cycles": None,
        }
        if is_wr:
            d.tbadp_aw_addr_i.value = addr
            d.tbadp_w_data_i.value = VEHICLE_WDATA
            d.tbadp_w_strb_i.value = strb
            d.tbadp_aw_valid_i.value = 1
            d.tbadp_w_valid_i.value = 1
            pending = AW_VALID | W_VALID
        else:
            d.tbadp_ar_addr_i.value = addr
            d.tbadp_ar_valid_i.value = 1
            pending = AR_VALID
        post = None
        for cyc in range(RETIRE_TIMEOUT_CYCLES):
            await RisingEdge(d.clk_i)
            try:
                obs["fwd"] |= int(d.tbadp_fwd_o.value)
            except ValueError:
                obs["fwd_x"] += 1
            chan = self._chan() or 0
            for vbit, rbit, pin in (
                (AW_VALID, AW_READY, d.tbadp_aw_valid_i),
                (W_VALID, W_READY, d.tbadp_w_valid_i),
                (AR_VALID, AR_READY, d.tbadp_ar_valid_i),
            ):
                if pending & vbit and chan & vbit and chan & rbit:
                    pending &= ~vbit
                    pin.value = 0
            if post is not None:
                post -= 1
                if post == 0:
                    break
                continue
            if is_wr and int(d.tbadp_b_valid_o.value):
                obs["resp"] = int(d.tbadp_b_resp_o.value)
            elif not is_wr and int(d.tbadp_r_valid_o.value):
                obs["resp"] = int(d.tbadp_r_resp_o.value)
                obs["rdata"] = int(d.tbadp_r_data_o.value)
            if obs["resp"] is not None:
                obs["retired"] = True
                obs["cycles"] = cyc
                post = POST_RESP_CYCLES
        d.tbadp_aw_valid_i.value = 0
        d.tbadp_w_valid_i.value = 0
        d.tbadp_ar_valid_i.value = 0
        return obs

    @staticmethod
    def describe(obs: dict) -> str:
        data = "" if obs["rdata"] is None else f" rdata=0x{obs['rdata']:016x}"
        return (
            f"{obs['name']}: {obs['op']} addr=0x{obs['addr']:x} strb=0x{obs['strb']:02x} "
            f"resp={obs['resp']}{data} fwd=0b{obs['fwd']:02b} fwd_xz_cycles={obs['fwd_x']} "
            f"retired={obs['retired']} at cycle {obs['cycles']}"
        )


def legal_partner(op: SepAxiOp, addr: int) -> tuple[SepAxiOp, int, int]:
    """The supported access of the same kind on the lane ``addr`` falls in."""
    base = addr - addr % LANE_BYTES
    return op, base, axi_lane_strobe(base) if op is SepAxiOp.WRITE else 0


def lane_word(rdata: int, addr: int) -> tuple[int, int]:
    """(addressed 32-bit lane, other lane) of a 64-bit read beat."""
    lo, hi = rdata & 0xFFFF_FFFF, rdata >> 32
    return (hi, lo) if addr & LANE_BYTES else (lo, hi)


@dataclass(frozen=True)
class DutLane:
    """One DUT lane adapter, reached through its block's INTR_ENABLE register."""

    name: str
    block: object
    status_field: str

    @property
    def fwd_signal(self):
        """The lane adapter's AXI-Lite-32 request probe in tb/tb_top.sv."""
        return getattr(cocotb.top, f"drbg_{self.name}_fwd_o")

    @property
    def reg_addr(self) -> int:
        return sym(f"{self.block.block}_INTR_ENABLE_REG_ADDR")

    @property
    def mask(self) -> int:
        return self.block.mask("INTR_ENABLE")

    @property
    def status_bit(self) -> int:
        return SEP_CPU_CTRL.field_mask("PERIPH_BUS_ERR_STATUS", self.status_field)


DUT_LANES: tuple[DutLane, ...] = (
    DutLane("csrng", CSRNG, "csrng"),
    DutLane("edn", EDN, "edn"),
)
PERIPH_STATUS_ADDR = SEP_CPU_CTRL.addr("PERIPH_BUS_ERR_STATUS")

# AxSIZE for a 1- or 2-byte transfer.
SIZE_OF_BYTES = {1: 0, 2: 1, 4: 2}


@dataclass(frozen=True)
class DutLanePlan:
    """The seeded stimulus for one DUT lane."""

    rd_offset: int  # byte offset of the misaligned single-byte read
    wr_bytes: int  # width of the narrow write
    pattern: int  # value the refused write carries and the control writes


def plan_for(lane: DutLane, rng: SepSeededRng, baseline: int) -> DutLanePlan:
    """Seeded offsets and a pattern that differs from ``baseline`` in an implemented bit."""
    flip = rng.randrange(1, lane.mask + 1) & lane.mask
    if not flip:
        flip = lane.mask & -lane.mask
    return DutLanePlan(
        rd_offset=rng.randrange(1, LANE_BYTES),
        wr_bytes=rng.choice((1, 2)),
        pattern=(baseline ^ flip) & lane.mask,
    )


async def _capture_w(prefix: str = "s_axi") -> int:
    """WSTRB of the next W handshake on a TB master port."""
    dut = cocotb.top
    while True:
        await RisingEdge(dut.clk_i)
        if (
            getattr(dut, f"{prefix}_wvalid").value == 1
            and getattr(dut, f"{prefix}_wready").value == 1
        ):
            return int(getattr(dut, f"{prefix}_wstrb").value)


class SepDrbgLaneRefusal:
    """Refused and legal CSR accesses to one DUT lane adapter over s_axi."""

    def __init__(self, test) -> None:
        self.test = test

    async def _seq(self, name: str, **kw) -> SepAxiAccessSeq:
        seq = SepAxiAccessSeq(name, **kw)
        await self.test.start_seq(seq)
        return seq

    async def read32(self, name: str, addr: int) -> int:
        seq = await self._seq(name, op=SepAxiOp.READ, addr=addr, length=4, size=2)
        if seq.resp_code != RESP_OKAY:
            raise AssertionError(f"{name}: aligned read 0x{addr:08x} resp={seq.resp_code}")
        return seq.rdata & 0xFFFF_FFFF

    async def write32(self, name: str, addr: int, data: int) -> int:
        seq = await self._seq(name, op=SepAxiOp.WRITE, addr=addr, wdata=data, length=4, size=2)
        return seq.resp_code

    async def periph_status(self) -> int:
        return await self.read32("periph_bus_err_status_rd", PERIPH_STATUS_ADDR)

    async def watched_read32(self, name: str, lane: DutLane) -> tuple[int, FwdWatch]:
        """Aligned read of the lane's register, with its forward probe sampled."""
        watch = FwdWatch(lane.fwd_signal).start()
        value = await self.read32(name, lane.reg_addr)
        return value, await watch.stop()

    async def watched_write32(self, name: str, lane: DutLane, data: int) -> tuple[int, FwdWatch]:
        """Aligned write of the lane's register, with its forward probe sampled."""
        watch = FwdWatch(lane.fwd_signal).start()
        resp = await self.write32(name, lane.reg_addr, data)
        return resp, await watch.stop()

    async def misaligned_read(
        self, lane: DutLane, offset: int
    ) -> tuple[int, dict | None, FwdWatch]:
        """One single-byte read at ``offset`` into the word.

        Returns (RRESP, presented AR, forward probe over the access).
        """
        addr = lane.reg_addr + offset
        watch = FwdWatch(lane.fwd_signal).start()
        ar = cocotb.start_soon(capture_addr_handshake("ar"))
        seq = await self._seq(
            f"{lane.name}_rd_misaligned",
            op=SepAxiOp.READ,
            addr=addr,
            length=1,
            size=0,
            expect_error=True,
        )
        await ClockCycles(cocotb.top.clk_i, 1)
        return seq.resp_code, take_handshake(ar), await watch.stop()

    async def narrow_write(
        self, lane: DutLane, nbytes: int, data: int
    ) -> tuple[int, int | None, FwdWatch]:
        """One ``nbytes`` write at the aligned word.

        Returns (BRESP, presented WSTRB, forward probe over the access).
        """
        watch = FwdWatch(lane.fwd_signal).start()
        w = cocotb.start_soon(_capture_w())
        seq = await self._seq(
            f"{lane.name}_wr_narrow",
            op=SepAxiOp.WRITE,
            addr=lane.reg_addr,
            wdata=data,
            length=nbytes,
            size=SIZE_OF_BYTES[nbytes],
            expect_error=True,
        )
        await ClockCycles(cocotb.top.clk_i, 1)
        return seq.resp_code, take_handshake(w), await watch.stop()
