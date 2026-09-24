# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Memory-backed AHB-Lite slave model.

The model answers one AHB-Lite master port. On every rising edge outside reset
it samples the master's outputs as they stood before the edge, then drives
HREADY, HRESP and HRDATA for the following cycle:

* An address phase is accepted on an edge where HTRANS is NONSEQ and HREADY is
  high. The transfer then occupies the data phase for a number of wait states
  and completes with OKAY, or with the two-cycle ERROR response (HREADY low
  with HRESP high, then both high).
* With no data phase in progress HREADY can be held low for a window, standing
  in for a shared HREADY that another slave holds low. A NONSEQ transfer
  presented inside that window waits in its address phase.
* A write commits the byte lanes HADDR and HSIZE select, taken from HWDATA as
  sampled on the completing edge; an ERROR transfer commits nothing. A read
  returns the bus-wide beat that contains HADDR, with the byte lanes outside
  the transfer filled according to ``lane_fill``.
* HRDATA carries random data in every cycle that is not the completing cycle of
  a read, so a master that samples it at the wrong time reads garbage.

Every accepted transfer is kept in ``transfers``, and every breach of an
AHB-Lite master rule the model can observe is kept in ``violations``.
"""

from __future__ import annotations

import logging
import random
from collections.abc import Callable
from dataclasses import dataclass

import cocotb
from cocotb.triggers import RisingEdge

HTRANS_IDLE = 0
HTRANS_BUSY = 1
HTRANS_NONSEQ = 2
HTRANS_SEQ = 3
HTRANS_NAMES = {
    HTRANS_IDLE: "IDLE",
    HTRANS_BUSY: "BUSY",
    HTRANS_NONSEQ: "NONSEQ",
    HTRANS_SEQ: "SEQ",
}

HSIZE_BYTE = 0
HSIZE_HALF = 1
HSIZE_WORD = 2


def default_word(word_addr: int) -> int:
    """Initial content of the 32-bit word at ``word_addr``.

    A multiplicative hash of the address, so neighbouring words and byte lanes
    hold unrelated values and a read that lands on the wrong word or lane
    returns a visibly different value.
    """
    return ((word_addr >> 2) * 0x9E37_79B1 ^ 0x5A5A_C3C3 ^ word_addr) & 0xFFFF_FFFF


def default_byte(addr: int) -> int:
    return (default_word(addr & ~3) >> (8 * (addr & 3))) & 0xFF


def sample(signal) -> int | None:
    """Integer value of ``signal``, or ``None`` while any bit is X or Z."""
    try:
        return int(signal.value)
    except ValueError:
        return None


@dataclass
class AhbTransfer:
    """One transfer from address-phase acceptance to data-phase completion."""

    index: int
    accept_cycle: int
    htrans: int
    haddr: int
    hwrite: bool
    hsize: int
    hburst: int
    hprot: int
    hmastlock: int
    addr_stall: int
    pipelined: bool
    planned_waits: int
    error: bool
    wait_left: int = 0
    wait_cycles: int = 0
    error_cycles: int = 0
    hwdata: int | None = None
    hrdata: int | None = None
    lane_data: int | None = None
    done_cycle: int | None = None
    aborted: bool = False

    @property
    def kind(self) -> str:
        return "W" if self.hwrite else "R"

    def describe(self) -> str:
        data = self.hwdata if self.hwrite else self.lane_data
        data_txt = "-" if data is None else f"{data:#x}"
        return (
            f"#{self.index} {self.kind} {HTRANS_NAMES.get(self.htrans, self.htrans)} "
            f"haddr={self.haddr:#010x} hsize={self.hsize} hprot={self.hprot:#x} "
            f"hburst={self.hburst} hmastlock={self.hmastlock} addr_stall={self.addr_stall} "
            f"waits={self.wait_cycles} {'ERROR' if self.error else 'OKAY'} data={data_txt}"
        )


class AhbLiteSlaveModel:
    """AHB-Lite slave for the master port whose signals are ``<prefix>_h*``."""

    def __init__(
        self,
        dut,
        prefix: str,
        clock,
        reset_n,
        data_width: int,
        rng: random.Random,
        name: str | None = None,
    ) -> None:
        if data_width not in (32, 64):
            raise ValueError(f"unsupported AHB data width {data_width}")
        self.name = name or prefix
        self.log = logging.getLogger(f"cocotb.{self.name}")
        self.data_width = data_width
        self.bus_bytes = data_width // 8
        self.rng = rng
        self._clock = clock
        self._reset_n = reset_n

        self._haddr = getattr(dut, f"{prefix}_haddr")
        self._hburst = getattr(dut, f"{prefix}_hburst")
        self._hmastlock = getattr(dut, f"{prefix}_hmastlock")
        self._hprot = getattr(dut, f"{prefix}_hprot")
        self._hsize = getattr(dut, f"{prefix}_hsize")
        self._htrans = getattr(dut, f"{prefix}_htrans")
        self._hwrite = getattr(dut, f"{prefix}_hwrite")
        self._hwdata = getattr(dut, f"{prefix}_hwdata")
        self._hrdata = getattr(dut, f"{prefix}_hrdata")
        self._hready_sig = getattr(dut, f"{prefix}_hready")
        self._hresp_sig = getattr(dut, f"{prefix}_hresp")

        self.mem: dict[int, int] = {}
        self.transfers: list[AhbTransfer] = []
        self.violations: list[str] = []
        self.on_accept: list[Callable[[AhbTransfer], None]] = []
        self.on_complete: list[Callable[[AhbTransfer], None]] = []

        # Stimulus knobs.
        self.data_wait_prob = 0.0
        self.data_wait_max = 0
        self.addr_wait_prob = 0.0
        self.addr_wait_max = 0
        self.error_prob = 0.0
        self.error_words: set[int] = set()
        self.lane_fill = "garbage"  # or "memory" (neighbouring bytes) or "zero"
        self._planned: list[tuple[bool, int]] = []

        # Observations.
        self.cycle = 0
        self.addr_stall_edges = 0
        self.data_wait_edges = 0
        self.error_responses = 0
        self.ctrl_nonzero_edges = 0
        self.pipelined_accepts = 0
        self.reset_aborts = 0
        self.allow_addr_change = False
        self.addr_change_seen = 0
        self.htrans_counts = {code: 0 for code in HTRANS_NAMES}

        self._dp: AhbTransfer | None = None
        self._hready = 1
        self._hresp = 0
        self._idle_low = 0
        self._stall_run = 0
        self._stalled_ctrl: tuple | None = None
        self._stalled_cancel_ok = False

        self._drive(1, 0, 0)
        cocotb.start_soon(self._run())

    # ------------------------------------------------------------------
    # Stimulus control
    # ------------------------------------------------------------------
    def set_waits(
        self, data_prob: float = 0.0, data_max: int = 0, addr_prob: float = 0.0, addr_max: int = 0
    ) -> None:
        """Random data-phase wait states and address-phase HREADY-low windows."""
        self.data_wait_prob, self.data_wait_max = data_prob, data_max
        self.addr_wait_prob, self.addr_wait_max = addr_prob, addr_max

    def plan(self, error: bool = False, waits: int = 0) -> None:
        """Fix the response of the next accepted transfer not already planned."""
        self._planned.append((error, waits))

    def hold_hready_low(self, cycles: int) -> None:
        """Hold HREADY low for ``cycles`` cycles, starting next cycle, while no data phase runs."""
        self._idle_low = cycles

    @property
    def busy(self) -> bool:
        return self._dp is not None

    # ------------------------------------------------------------------
    # Backdoor memory access
    # ------------------------------------------------------------------
    def read_byte(self, addr: int) -> int:
        return self.mem.get(addr, default_byte(addr))

    def read_word(self, addr: int) -> int:
        base = addr & ~3
        return sum(self.read_byte(base + k) << (8 * k) for k in range(4))

    def write_word(self, addr: int, value: int) -> None:
        base = addr & ~3
        for k in range(4):
            self.mem[base + k] = (value >> (8 * k)) & 0xFF

    # ------------------------------------------------------------------
    # Bus engine
    # ------------------------------------------------------------------
    def _violation(self, msg: str) -> None:
        text = f"[{self.name} cycle {self.cycle}] {msg}"
        self.violations.append(text)
        self.log.error("AHB violation: %s", text)

    def _garbage(self) -> int:
        return self.rng.getrandbits(self.data_width)

    def _drive(self, hready: int, hresp: int, hrdata: int) -> None:
        self._hready, self._hresp = hready, hresp
        self._hready_sig.value = hready
        self._hresp_sig.value = hresp
        self._hrdata.value = hrdata

    async def _run(self) -> None:
        edge = RisingEdge(self._clock)
        while True:
            await edge
            self.cycle += 1
            if sample(self._reset_n) != 1:
                self._enter_reset()
                continue
            self._step()

    def _enter_reset(self) -> None:
        if self._dp is not None:
            self._dp.aborted = True
            self.reset_aborts += 1
            self._dp = None
        self._idle_low = 0
        self._stall_run = 0
        self._stalled_ctrl = None
        self._drive(1, 0, self._garbage())

    def _step(self) -> None:
        hready, hresp = self._hready, self._hresp
        htrans = sample(self._htrans)
        ctrl = (
            sample(self._haddr),
            sample(self._hwrite),
            sample(self._hsize),
            sample(self._hburst),
            sample(self._hprot),
            sample(self._hmastlock),
        )
        hwdata = sample(self._hwdata)

        if htrans is None:
            self._violation("HTRANS is X/Z outside reset")
        else:
            self.htrans_counts[htrans] += 1
            if htrans in (HTRANS_BUSY, HTRANS_SEQ):
                self._violation(f"HTRANS={HTRANS_NAMES[htrans]} from a single-transfer master")
        if htrans == HTRANS_NONSEQ and None in ctrl:
            self._violation(f"address/control X/Z in a NONSEQ address phase: {ctrl}")
        if ctrl[3] != 0 or ctrl[5] != 0:
            self.ctrl_nonzero_edges += 1

        # An address phase presented with HREADY low holds until HREADY is high;
        # on the first ERROR cycle the master may cancel it to IDLE instead.
        if self._stalled_ctrl is not None:
            held = htrans == HTRANS_NONSEQ and ctrl == self._stalled_ctrl
            cancelled = self._stalled_cancel_ok and htrans == HTRANS_IDLE
            if not (held or cancelled):
                self.addr_change_seen += 1
                if not self.allow_addr_change:
                    self._violation(
                        f"address phase changed while HREADY low: {self._stalled_ctrl} -> "
                        f"htrans={htrans} {ctrl}"
                    )
            self._stalled_ctrl = None

        dp = self._dp
        if dp is not None and dp.hwrite:
            if dp.hwdata is None:
                dp.hwdata = hwdata
            elif hwdata != dp.hwdata:
                self._violation(
                    f"HWDATA changed in a stalled write data phase: {dp.hwdata:#x} -> {hwdata}"
                )

        if hready:
            completed = dp is not None
            if dp is not None:
                self._complete(dp)
                self._dp = None
            if htrans == HTRANS_NONSEQ:
                self._dp = self._accept(ctrl, htrans, pipelined=completed)
            self._stall_run = 0
        else:
            if dp is not None:
                self.data_wait_edges += 1
            if htrans == HTRANS_NONSEQ:
                self._stalled_ctrl = ctrl
                self._stalled_cancel_ok = hresp == 1
                self._stall_run += 1
                if dp is None:
                    self.addr_stall_edges += 1
            else:
                self._stall_run = 0

        self._respond()

    def _accept(self, ctrl: tuple, htrans: int, pipelined: bool) -> AhbTransfer:
        haddr, hwrite, hsize, hburst, hprot, hmastlock = (0 if v is None else v for v in ctrl)
        size = 1 << hsize
        if size > self.bus_bytes:
            self._violation(f"HSIZE={hsize} is wider than the {self.data_width}-bit bus")
        if haddr % size:
            self._violation(f"HADDR={haddr:#x} is not aligned to HSIZE={hsize}")
        if self._planned:
            error, waits = self._planned.pop(0)
        else:
            waits = 0
            if self.data_wait_max and self.rng.random() < self.data_wait_prob:
                waits = self.rng.randint(1, self.data_wait_max)
            error = (haddr & ~3) in self.error_words or (
                self.error_prob > 0 and self.rng.random() < self.error_prob
            )
        if pipelined:
            self.pipelined_accepts += 1
        t = AhbTransfer(
            index=len(self.transfers),
            accept_cycle=self.cycle,
            htrans=htrans,
            haddr=haddr,
            hwrite=bool(hwrite),
            hsize=hsize,
            hburst=hburst,
            hprot=hprot,
            hmastlock=hmastlock,
            addr_stall=self._stall_run,
            pipelined=pipelined,
            planned_waits=waits,
            error=error,
            wait_left=waits,
        )
        self.transfers.append(t)
        self.log.debug("accept %s", t.describe())
        for cb in self.on_accept:
            cb(t)
        return t

    def _complete(self, t: AhbTransfer) -> None:
        t.done_cycle = self.cycle
        if t.error:
            self.error_responses += 1
            if t.error_cycles != 2:
                self._violation(f"model ERROR response for #{t.index} took {t.error_cycles} cycles")
        elif t.hwrite:
            self._commit(t)
        self.log.debug("complete %s", t.describe())
        for cb in self.on_complete:
            cb(t)

    def _lanes(self, t: AhbTransfer) -> tuple[int, int, int]:
        base = t.haddr & ~(self.bus_bytes - 1)
        first = t.haddr - base
        return base, first, first + (1 << t.hsize)

    def _commit(self, t: AhbTransfer) -> None:
        if t.hwdata is None:
            self._violation(f"write #{t.index} completed with HWDATA X/Z")
            return
        base, first, last = self._lanes(t)
        for k in range(first, last):
            self.mem[base + k] = (t.hwdata >> (8 * k)) & 0xFF

    def _read_beat(self, t: AhbTransfer) -> int:
        base, first, last = self._lanes(t)
        beat = 0
        for k in range(self.bus_bytes):
            if first <= k < last or self.lane_fill == "memory":
                byte = self.read_byte(base + k)
            elif self.lane_fill == "zero":
                byte = 0
            else:
                byte = self.rng.getrandbits(8)
            beat |= byte << (8 * k)
        t.hrdata = beat
        t.lane_data = sum(self.read_byte(base + k) << (8 * (k - first)) for k in range(first, last))
        return beat

    def _respond(self) -> None:
        t = self._dp
        if t is not None:
            if t.wait_left > 0:
                t.wait_left -= 1
                t.wait_cycles += 1
                self._drive(0, 0, self._garbage())
            elif t.error:
                t.error_cycles += 1
                self._drive(1 if t.error_cycles == 2 else 0, 1, self._garbage())
            else:
                self._drive(1, 0, self._garbage() if t.hwrite else self._read_beat(t))
            return
        if self._idle_low > 0:
            self._idle_low -= 1
            self._drive(0, 0, self._garbage())
        elif self.addr_wait_max and self.rng.random() < self.addr_wait_prob:
            self._idle_low = self.rng.randint(1, self.addr_wait_max) - 1
            self._drive(0, 0, self._garbage())
        else:
            self._drive(1, 0, self._garbage())
