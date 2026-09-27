# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Adams Bridge aperture traffic from both TB masters, several accesses at once.

The ABR control path ends in a bridge that performs one AHB transfer at a time
(``hw/sys/sep/doc/adams_bridge.adoc``, ``[[abr-access-size]]``), while the
fabric in front of it holds several accesses outstanding. A bridge that
pipelines wrongly still answers every access OKAY -- one that streams reads and
drops HADDR[2:0] on the streamed transfers returns the word at the wrong
address from the third read of a pipeline on. Only accesses that are in flight
TOGETHER, each against a known value for its own address, can show that.

The SEP AXI sequencer awaits each item to completion, so nothing overlaps
through it. The concurrent legs call the VIP master sequence directly, the way
``sep_axi_id_routing_seq`` does, and ``AbrBusWatch`` records every request and
response handshake on the raw TB pins. That record is what proves the requests
were accepted before the first response came back, and what grades each
response by the ID it actually carried: the VIP's own per-transaction ID
capture samples the first response after issue, which under concurrency may
belong to a different request.

Register roles, all resolved from the vendored ``abr_reg.rdl``:

* Identity words (``MLDSA_NAME`` / ``MLDSA_VERSION`` / ``MLKEM_NAME`` /
  ``MLKEM_VERSION``): ``sw = r``, fixed values, the read goldens.
* ``intr_block_rf`` interrupt enables: ``sw = rw``, one to two bits, and the
  only adjacent RW pair in one 8-byte granule (``global_intr_en_r`` /
  ``error_intr_en_r``), so a 64-bit access covers two registers.
* The two ``intr_count_t`` counters: ``sw = rw`` over all 32 bits, so a write
  that lands on the wrong bytes shows in every lane. They count interrupt
  events only, and no event is raised by these tests.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import cocotb
from cocotb.task import Task
from cocotb.triggers import RisingEdge
from cocotb.utils import get_sim_time
from env.sep_axi_agent import SepAxiOp
from env.sep_spec_tables import abr_field_mask, abr_off, window

from seq_lib.sep_abr_keygen_seq import (
    ABR_ERROR_INTR_EN,
    ABR_GLOBAL_INTR_EN,
    ABR_INTR,
    ABR_NAME0,
    ABR_NAME1,
    ABR_NOTIF_INTR_EN,
    ABR_VERSION0,
    ABR_VERSION1,
    NAME0_EXP,
    NAME1_EXP,
    VER0_EXP,
    VER1_EXP,
)
from seq_lib.sep_abr_mlkem_seq import (
    KEM_NAME0_EXP,
    KEM_NAME1_EXP,
    KEM_VER0_EXP,
    KEM_VER1_EXP,
    MLKEM_NAME0,
    MLKEM_NAME1,
    MLKEM_VERSION0,
    MLKEM_VERSION1,
)
from seq_lib.sep_axi_access_seq import SepAxiAccessSeq
from seq_lib.sep_inbound_filter_rule_seq import SepInboundFilter, SepInboundFilterCfg

ABR_WINDOW = window("ABR")

RESP_OKAY = 0
RESP_SLVERR = 2
RESP_NAME = {-1: "TIMEOUT", 0: "OKAY", 1: "EXOKAY", 2: "SLVERR", 3: "DECERR"}

# AXI ID width of each TB master port (tb/sep_tb_signal_list.svh).
ID_WIDTH = {"s_axi": 3, "m_axi": 6}

# Bound on one access, in system clocks. A healthy ABR register access retires
# in tens of cycles even behind seven others; the failure this bounds is a
# wedge, which is unbounded.
ACCESS_TIMEOUT_CYCLES = 4000

_RDL = (
    Path(__file__).resolve().parents[6]
    / "vendor"
    / "chipsalliance"
    / "adams-bridge"
    / "upstream"
    / "src"
    / "abr_top"
    / "rtl"
    / "abr_reg.rdl"
)
# `intr_count_t name @0xNNN;` inside `regfile intr_block_t`, relative to
# intr_block_rf. abr_offsets() resolves only the nine packed registers.
_INTR_COUNT = re.compile(r"^\s+intr_count_t\s+(\w+)\s*@\s*(0x[0-9A-Fa-f]+)\s*;", re.M)


def _intr_count_offsets() -> dict[str, int]:
    text = _RDL.read_text(encoding="utf-8")
    start = text.find("regfile intr_block_t")
    end = text.find("intr_block_t intr_block_rf", start)
    if start < 0 or end < 0:
        raise RuntimeError(f"{_RDL} has no intr_block_t regfile")
    return {name: int(off, 16) for name, off in _INTR_COUNT.findall(text[start:end])}


_COUNTERS = _intr_count_offsets()


@dataclass(frozen=True)
class AbrWord:
    """One 32-bit register in the aperture."""

    name: str
    addr: int
    mask: int = 0xFFFF_FFFF
    value: int | None = None  # fixed value of a read-only identity word


IDENTITY_WORDS: tuple[AbrWord, ...] = (
    AbrWord("MLDSA_NAME0", ABR_NAME0, value=NAME0_EXP),
    AbrWord("MLDSA_NAME1", ABR_NAME1, value=NAME1_EXP),
    AbrWord("MLDSA_VERSION0", ABR_VERSION0, value=VER0_EXP),
    AbrWord("MLDSA_VERSION1", ABR_VERSION1, value=VER1_EXP),
    AbrWord("MLKEM_NAME0", MLKEM_NAME0, value=KEM_NAME0_EXP),
    AbrWord("MLKEM_NAME1", MLKEM_NAME1, value=KEM_NAME1_EXP),
    AbrWord("MLKEM_VERSION0", MLKEM_VERSION0, value=KEM_VER0_EXP),
    AbrWord("MLKEM_VERSION1", MLKEM_VERSION1, value=KEM_VER1_EXP),
)
IDENTITY = {w.addr: w for w in IDENTITY_WORDS}

GLOBAL_INTR_EN = AbrWord(
    "global_intr_en_r",
    ABR_GLOBAL_INTR_EN,
    abr_field_mask("global_intr_en_r", "error_en") | abr_field_mask("global_intr_en_r", "notif_en"),
)
ERROR_INTR_EN = AbrWord(
    "error_intr_en_r", ABR_ERROR_INTR_EN, abr_field_mask("error_intr_en_r", "error_internal_en")
)
NOTIF_INTR_EN = AbrWord(
    "notif_intr_en_r", ABR_NOTIF_INTR_EN, abr_field_mask("notif_intr_en_r", "notif_cmd_done_en")
)
ERROR_COUNT = AbrWord(
    "error_internal_intr_count_r", ABR_INTR + _COUNTERS["error_internal_intr_count_r"]
)
NOTIF_COUNT = AbrWord(
    "notif_cmd_done_intr_count_r", ABR_INTR + _COUNTERS["notif_cmd_done_intr_count_r"]
)
RW_WORDS: tuple[AbrWord, ...] = (
    GLOBAL_INTR_EN,
    ERROR_INTR_EN,
    NOTIF_INTR_EN,
    ERROR_COUNT,
    NOTIF_COUNT,
)
RW = {w.addr: w for w in RW_WORDS}


def lane_value(addr: int, nbytes: int, beat: int) -> int:
    """The ``nbytes`` at ``addr`` taken out of a 64-bit beat."""
    return (beat >> (8 * (addr & 7))) & ((1 << (8 * nbytes)) - 1)


def identity_bytes(addr: int, nbytes: int) -> int | None:
    """The golden for a read of ``nbytes`` at ``addr`` over identity words only."""
    out = 0
    for i in range(nbytes):
        a = addr + i
        word = IDENTITY.get(a & ~3)
        if word is None or word.value is None:
            return None
        out |= ((word.value >> (8 * (a & 3))) & 0xFF) << (8 * i)
    return out


@dataclass
class AbrAccess:
    """One read or write on one TB master, and what came back."""

    bus: str
    op: str  # "rd" or "wr"
    addr: int
    nbytes: int = 4
    size: int = 2
    axi_id: int = 0
    wdata: int = 0
    tag: str = ""
    resp: int = -1
    data: int = 0
    timed_out: bool = False
    t_issue: int = 0
    t_done: int = 0

    @property
    def resp_name(self) -> str:
        return RESP_NAME.get(self.resp, str(self.resp))

    def describe(self) -> str:
        width = 2 * self.nbytes
        body = (
            f"data=0x{self.data:0{width}x}"
            if self.op == "rd"
            else f"wdata=0x{self.wdata:0{width}x}"
        )
        return (
            f"{self.bus} {self.op} id={self.axi_id} addr=0x{self.addr:08x} "
            f"bytes={self.nbytes} size={self.size} resp={self.resp_name} {body}"
        )


@dataclass
class BusRecord:
    """Handshakes on one TB master bus while a watch is armed."""

    ar: list[tuple[int, int, int]] = field(default_factory=list)  # (cycle, id, addr)
    r: list[tuple[int, int, int, int]] = field(default_factory=list)  # (cycle, id, resp, data)
    aw: list[tuple[int, int, int]] = field(default_factory=list)
    b: list[tuple[int, int, int]] = field(default_factory=list)  # (cycle, id, resp)
    ar_before_first_r: int = 0
    max_rd_outstanding: int = 0
    max_wr_outstanding: int = 0
    max_outstanding: int = 0  # reads and writes together
    r_stall_cycles: int = 0  # RVALID held with RREADY low
    b_stall_cycles: int = 0


_WATCHED = (
    "arvalid",
    "arready",
    "arid",
    "araddr",
    "rvalid",
    "rready",
    "rid",
    "rresp",
    "rdata",
    "rlast",
    "awvalid",
    "awready",
    "awid",
    "awaddr",
    "bvalid",
    "bready",
    "bid",
    "bresp",
)


def _bit(sig) -> bool:
    try:
        return bool(int(sig.value))
    except ValueError:
        return False


def _int(sig) -> int:
    try:
        return int(sig.value)
    except ValueError:
        return -1


class AbrBusWatch:
    """Records every AR/R/AW/B handshake on the given TB master buses.

    Also counts the cycles in which every watched bus had a request
    outstanding, which is what shows two masters were in the ABR path at the
    same time rather than one after the other.
    """

    def __init__(self, buses: tuple[str, ...]) -> None:
        self.buses = tuple(buses)
        self.rec = {b: BusRecord() for b in self.buses}
        self.all_busy_cycles = 0
        self.cycles = 0
        self._task: Task[None] | None = None

    def start(self) -> None:
        self._task = cocotb.start_soon(self._run())

    def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            self._task = None

    async def _run(self) -> None:
        dut: Any = cocotb.top
        sig = {b: {n: getattr(dut, f"{b}_{n}") for n in _WATCHED} for b in self.buses}
        rd_live = {b: 0 for b in self.buses}
        wr_live = {b: 0 for b in self.buses}
        while True:
            await RisingEdge(dut.clk_i)
            self.cycles += 1
            for b in self.buses:
                s, rec = sig[b], self.rec[b]
                if _bit(s["arvalid"]) and _bit(s["arready"]):
                    rec.ar.append((self.cycles, _int(s["arid"]), _int(s["araddr"])))
                    rd_live[b] += 1
                    rec.max_rd_outstanding = max(rec.max_rd_outstanding, rd_live[b])
                if _bit(s["awvalid"]) and _bit(s["awready"]):
                    rec.aw.append((self.cycles, _int(s["awid"]), _int(s["awaddr"])))
                    wr_live[b] += 1
                    rec.max_wr_outstanding = max(rec.max_wr_outstanding, wr_live[b])
                if _bit(s["rvalid"]):
                    if _bit(s["rready"]):
                        if not rec.r:
                            rec.ar_before_first_r = len(rec.ar)
                        rec.r.append(
                            (self.cycles, _int(s["rid"]), _int(s["rresp"]), _int(s["rdata"]))
                        )
                        if _bit(s["rlast"]):
                            rd_live[b] -= 1
                    else:
                        rec.r_stall_cycles += 1
                if _bit(s["bvalid"]):
                    if _bit(s["bready"]):
                        rec.b.append((self.cycles, _int(s["bid"]), _int(s["bresp"])))
                        wr_live[b] -= 1
                    else:
                        rec.b_stall_cycles += 1
                rec.max_outstanding = max(rec.max_outstanding, rd_live[b] + wr_live[b])
            if all(rd_live[b] + wr_live[b] > 0 for b in self.buses):
                self.all_busy_cycles += 1


class SepAbrBus:
    """Direct VIP access to the ABR aperture from s_axi and m_axi."""

    def __init__(self, test) -> None:
        self.test = test
        self.log = test.logger

    def master(self, bus: str):
        """The VIP master sequence behind one TB master, bypassing the sequencer.

        Raises rather than returning None: without it nothing overlaps, and a
        walk of sequential accesses would report pipelining it never presented.
        """
        agent = self.test.env.axi_agent if bus == "s_axi" else self.test.env.ext_axi_agent
        seq = getattr(getattr(agent, "driver", None), "axi", None)
        if seq is None or not hasattr(seq, "read_bytes_result"):
            raise RuntimeError(
                f"no VIP master sequence behind the {bus} agent; the ABR walk "
                "cannot hold several accesses outstanding"
            )
        return seq

    def driver(self, bus: str):
        return self.master(bus).driver

    @property
    def timeout_ns(self) -> int:
        return int(ACCESS_TIMEOUT_CYCLES * self.test.cfg.sys_clk_period_ns)

    async def open_m_axi_window(self, *, write: bool) -> None:
        """Allow m_axi onto the whole ABR aperture through the inbound filter.

        The filter denies by default, so the rule is programmed from s_axi,
        which does not pass through it. Entry 0 only; every other entry is
        cleared first so no leftover rule widens the grant.
        """
        filt = SepInboundFilter(self.test)
        await filt.disable_all()
        rule = SepInboundFilterCfg(entry=0, allow_addr=ABR_WINDOW.base)
        await filt.program_rule(
            rule, read_allowed=True, write_allowed=write, end_addr=ABR_WINDOW.end
        )
        self.log.info(
            "inbound filter entry 0 allows m_axi %s on ABR 0x%08x..0x%08x",
            "r+w" if write else "r",
            ABR_WINDOW.base,
            ABR_WINDOW.end,
        )

    async def run(self, acc: AbrAccess) -> AbrAccess:
        """Perform one access and fill in its result fields."""
        master = self.master(acc.bus)
        acc.t_issue = int(get_sim_time("ps"))
        if acc.op == "rd":
            res = await master.read_bytes_result(
                acc.addr,
                acc.nbytes,
                size=acc.size,
                id=acc.axi_id,
                check_response=False,
                timeout_ns=self.timeout_ns,
                allow_timeout=True,
            )
            if not res.timed_out:
                acc.data = int.from_bytes(res.data_bytes, "little") if res.data_bytes else res.data
        else:
            res = await master.write_bytes_result(
                acc.addr,
                acc.wdata.to_bytes(acc.nbytes, "little"),
                size=acc.size,
                id=acc.axi_id,
                check_response=False,
                timeout_ns=self.timeout_ns,
                allow_timeout=True,
            )
        acc.t_done = int(get_sim_time("ps"))
        acc.timed_out = bool(res.timed_out)
        acc.resp = -1 if res.timed_out else int(res.resp)
        return acc

    async def one(self, acc: AbrAccess, *, refused: bool = False) -> AbrAccess:
        """One access through the bus's SEP AXI sequencer.

        The sequencer path puts the access in front of the SEP scoreboard as
        well, which fails any non-OKAY response unless ``refused`` marks it as
        an access that must be answered with an error.
        """
        seq = SepAxiAccessSeq(
            f"abr_{acc.op}",
            op=SepAxiOp.READ if acc.op == "rd" else SepAxiOp.WRITE,
            addr=acc.addr,
            wdata=acc.wdata,
            length=acc.nbytes,
            size=acc.size,
            expect_error=refused,
            axi_id=acc.axi_id,
        )
        start = self.test.start_seq if acc.bus == "s_axi" else self.test.start_ext_seq
        acc.t_issue = int(get_sim_time("ps"))
        await start(seq)
        acc.t_done = int(get_sim_time("ps"))
        acc.timed_out = seq.timed_out
        acc.resp = seq.resp_code
        if acc.op == "rd":
            acc.data = seq.rdata
        return acc

    async def read(
        self, bus: str, addr: int, *, nbytes: int = 4, size: int = 2, axi_id: int = 0
    ) -> AbrAccess:
        acc = await self.run(AbrAccess(bus, "rd", addr, nbytes, size, axi_id))
        self._raise_on_timeout([acc])
        return acc

    async def write(
        self,
        bus: str,
        addr: int,
        data: int,
        *,
        nbytes: int = 4,
        size: int = 2,
        axi_id: int = 0,
    ) -> AbrAccess:
        acc = await self.run(AbrAccess(bus, "wr", addr, nbytes, size, axi_id, wdata=data))
        self._raise_on_timeout([acc])
        return acc

    async def all_at_once(self, accs: list[AbrAccess]) -> None:
        """Start every access in the same cycle; AR/AW order is list order."""
        tasks = [cocotb.start_soon(self.run(a)) for a in accs]
        for t in tasks:
            await t
        self._raise_on_timeout(accs)

    async def stream(self, accs: list[AbrAccess], depth: int) -> None:
        """Issue in list order with at most ``depth`` accesses outstanding."""
        top: Any = cocotb.top
        clk = top.clk_i
        live: list[Task[AbrAccess]] = []
        for acc in accs:
            while sum(not t.done() for t in live) >= depth:
                await RisingEdge(clk)
            live.append(cocotb.start_soon(self.run(acc)))
        for t in live:
            await t

    def _raise_on_timeout(self, accs: list[AbrAccess]) -> None:
        stuck = [a for a in accs if a.timed_out]
        if stuck:
            raise AssertionError(
                f"{len(stuck)} of {len(accs)} ABR access(es) did not complete within "
                f"{ACCESS_TIMEOUT_CYCLES} cycles; the path is wedged and every later "
                f"access would be contaminated. First: {stuck[0].describe()}"
            )


def _selftest() -> None:
    # Pinned against the generated decoder in the vendored abr_reg.sv
    # (decoded_reg_strb.intr_block_rf.*), so a layout change fails at import.
    base = ABR_WINDOW.base
    assert base == 0x1094_0000
    assert GLOBAL_INTR_EN.addr - base == 0x8100
    assert ERROR_INTR_EN.addr - base == 0x8104
    assert NOTIF_INTR_EN.addr - base == 0x8108
    assert ERROR_COUNT.addr - base == 0x8200
    assert NOTIF_COUNT.addr - base == 0x8280
    assert (GLOBAL_INTR_EN.mask, ERROR_INTR_EN.mask, NOTIF_INTR_EN.mask) == (0x3, 0x1, 0x1)
    # The 64-bit pair: one 8-byte granule, low word first.
    assert GLOBAL_INTR_EN.addr % 8 == 0 and ERROR_INTR_EN.addr == GLOBAL_INTR_EN.addr + 4
    # The counters' upper neighbours own no register, and the 64-bit identity
    # reads start on an 8-byte boundary.
    assert ERROR_COUNT.addr % 8 == 0 and NOTIF_COUNT.addr % 8 == 0
    assert all(w.addr % 8 == 0 for w in IDENTITY_WORDS[::2])
    assert ABR_VERSION1 - base == abr_off("MLDSA_VERSION") + 4 == 0xC
    assert identity_bytes(ABR_NAME0, 8) == (NAME1_EXP << 32) | NAME0_EXP
    assert identity_bytes(ABR_VERSION1 + 1, 2) == (VER1_EXP >> 8) & 0xFFFF
    assert lane_value(0x4, 4, 0x1122_3344_5566_7788) == 0x1122_3344
    # Every identity word differs from its pair partner, so a response for the
    # wrong half of a granule is a mismatch rather than a coincidence.
    for lo, hi in zip(IDENTITY_WORDS[::2], IDENTITY_WORDS[1::2]):
        assert lo.value != hi.value, (lo.name, hi.name)


_selftest()
