# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Reference model and scoreboard for one axi_lite_to_ahb instance.

The expected behaviour is written from the converter's specification (the
header of hw/common/axi/axi_lite_to_ahb.sv and the ABR access-size rules in
hw/sys/sep/doc/adams_bridge.adoc), not from its RTL.

The converter has one transaction in flight, so every AXI request the monitor
sees accepted is followed by at most one AHB transfer and then by its own
response, before the next request is accepted. The scoreboard pairs them in
that order and checks each against:

* ``expected_write`` for writes: whether an AHB transfer is issued, its HSIZE
  and HADDR[1:0], and the response of a write that issues none;
* for reads, a word transfer at the word-aligned address, returning the
  reference memory's word;
* ``expected_hprot`` for HPROT, HBURST = SINGLE and HMASTLOCK = 0;
* the slave's HRESP for the response of every transfer that is issued.

The reference memory applies each write's WSTRB bytes when its AHB transfer
completes with OKAY; the slave model applies HWDATA on the lanes HADDR and
HSIZE select. ``compare_memory`` checks that the two agree byte for byte.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from .ahb_lite_slave import (
    HSIZE_BYTE,
    HSIZE_HALF,
    HSIZE_WORD,
    HTRANS_NONSEQ,
    AhbLiteSlaveModel,
    AhbTransfer,
    default_byte,
)
from .axil_agents import RESP_NAMES, RESP_OKAY, RESP_SLVERR, AxilMonitor, AxilObservation


@dataclass(frozen=True)
class ConverterCfg:
    """One elaborated parameter set of the converter under test."""

    name: str
    ahb_data_width: int
    allow_sub_word_write: bool
    ack_zero_strobe_write: bool

    def describe(self) -> str:
        return (
            f"cfg {self.name.upper()} (AHB_DATA_WIDTH={self.ahb_data_width}, "
            f"AllowSubWordWrite={int(self.allow_sub_word_write)}, "
            f"AckZeroStrobeWrite={int(self.ack_zero_strobe_write)})"
        )


@dataclass(frozen=True)
class WriteExpect:
    """What a write with a given WSTRB must do."""

    transfer: bool
    hsize: int = HSIZE_WORD
    offset: int = 0
    local_resp: int | None = None


_SUB_WORD_STROBES = {
    0b0001: (HSIZE_BYTE, 0),
    0b0010: (HSIZE_BYTE, 1),
    0b0100: (HSIZE_BYTE, 2),
    0b1000: (HSIZE_BYTE, 3),
    0b0011: (HSIZE_HALF, 0),
    0b1100: (HSIZE_HALF, 2),
}


def expected_write(cfg: ConverterCfg, strb: int) -> WriteExpect:
    if strb == 0:
        return WriteExpect(
            False, local_resp=RESP_OKAY if cfg.ack_zero_strobe_write else RESP_SLVERR
        )
    if strb == 0b1111:
        return WriteExpect(True, HSIZE_WORD, 0)
    if cfg.allow_sub_word_write and strb in _SUB_WORD_STROBES:
        return WriteExpect(True, *_SUB_WORD_STROBES[strb])
    return WriteExpect(False, local_resp=RESP_SLVERR)


def _resp_name(resp: int | None) -> str:
    return "X/Z" if resp is None else RESP_NAMES.get(resp, str(resp))


def _hex32(value: int | None) -> str:
    return "X/Z" if value is None else f"{value:#010x}"


def expected_hprot(axprot: int) -> int:
    """HPROT[1] privileged from AxPROT[0], HPROT[0] data from !AxPROT[2]; never bufferable/cacheable."""
    return ((axprot & 1) << 1) | (0 if axprot & 0b100 else 1)


class ConverterScoreboard:
    """Pairs AXI requests with AHB transfers and checks both against the reference."""

    def __init__(self, cfg: ConverterCfg, model: AhbLiteSlaveModel, monitor: AxilMonitor) -> None:
        self.cfg = cfg
        self.model = model
        self.log = logging.getLogger(f"cocotb.sb_{cfg.name}")
        self.ref: dict[int, int] = {}
        self.violations: list[str] = []

        self.reads_checked = 0
        self.writes_checked = 0
        self.writes_with_transfer = 0
        self.writes_local = 0
        self.slverr_from_ahb = 0
        self.slverr_local = 0
        self.okay_zero_strobe = 0
        self.dropped_by_reset = 0

        self._op: AxilObservation | None = None
        self._xfer: AhbTransfer | None = None
        self._expect: WriteExpect | None = None
        self._read_value: int | None = None

        monitor.on_accept.append(self._axi_accept)
        monitor.on_response.append(self._axi_response)
        monitor.on_reset.append(self._reset)
        model.on_accept.append(self._ahb_accept)
        model.on_complete.append(self._ahb_complete)

    # ------------------------------------------------------------------
    def ref_byte(self, addr: int) -> int:
        return self.ref.get(addr, default_byte(addr))

    def ref_word(self, addr: int) -> int:
        base = addr & ~3
        return sum(self.ref_byte(base + k) << (8 * k) for k in range(4))

    def preload_word(self, addr: int, value: int) -> None:
        """Set a word in both the slave memory and the reference."""
        self.model.write_word(addr, value)
        base = addr & ~3
        for k in range(4):
            self.ref[base + k] = (value >> (8 * k)) & 0xFF

    def compare_memory(self) -> int:
        """Check slave memory against the reference; return the number of bytes compared."""
        addrs = set(self.ref) | set(self.model.mem)
        for addr in sorted(addrs):
            want = self.ref_byte(addr)
            got = self.model.read_byte(addr)
            if want != got:
                self._violation(
                    f"memory byte {addr:#010x}: slave holds {got:#04x}, reference {want:#04x}"
                )
        return len(addrs)

    @property
    def idle(self) -> bool:
        return self._op is None

    # ------------------------------------------------------------------
    def _violation(self, msg: str) -> None:
        text = f"[sb {self.cfg.name}] {msg}"
        self.violations.append(text)
        self.log.error("scoreboard: %s", text)

    def _reset(self) -> None:
        if self._op is not None:
            self.dropped_by_reset += 1
        self._op = None
        self._xfer = None
        self._expect = None

    def _axi_accept(self, obs: AxilObservation) -> None:
        if self._op is not None:
            self._violation(f"{obs.kind} #{obs.index} accepted before #{self._op.index} completed")
        self._op = obs
        self._xfer = None
        self._read_value = None
        self._expect = None
        if obs.kind == "W":
            if obs.strb is None or obs.data is None:
                self._violation(f"W #{obs.index} accepted with WDATA or WSTRB X/Z")
            else:
                self._expect = expected_write(self.cfg, obs.strb)

    def _ahb_accept(self, t: AhbTransfer) -> None:
        op = self._op
        if op is None:
            self._violation(f"AHB transfer with no AXI request outstanding: {t.describe()}")
            return
        if self._xfer is not None:
            self._violation(f"second AHB transfer for AXI {op.kind} #{op.index}: {t.describe()}")
        self._xfer = t
        if t.htrans != HTRANS_NONSEQ:
            self._violation(f"transfer not NONSEQ: {t.describe()}")
        if t.hburst != 0 or t.hmastlock != 0:
            self._violation(f"HBURST/HMASTLOCK not SINGLE/0: {t.describe()}")
        if t.hprot != expected_hprot(op.prot):
            self._violation(
                f"HPROT {t.hprot:#x} for AxPROT {op.prot:#x}, expected "
                f"{expected_hprot(op.prot):#x}: {t.describe()}"
            )
        if op.kind == "R":
            want_addr = op.addr & ~3
            if t.hwrite or t.hsize != HSIZE_WORD or t.haddr != want_addr:
                self._violation(
                    f"read araddr={op.addr:#x} expected a word read at "
                    f"{want_addr:#x}: {t.describe()}"
                )
            return
        e = self._expect
        if e is None:
            return
        if not e.transfer:
            self._violation(f"write with WSTRB={op.strb:04b} must not reach AHB: {t.describe()}")
            return
        want_addr = (op.addr & ~3) | e.offset
        if not t.hwrite or t.hsize != e.hsize or t.haddr != want_addr:
            self._violation(
                f"write awaddr={op.addr:#x} WSTRB={op.strb:04b} expected HSIZE="
                f"{e.hsize} HADDR={want_addr:#x}: {t.describe()}"
            )

    def _ahb_complete(self, t: AhbTransfer) -> None:
        op = self._op
        if op is None or t is not self._xfer:
            return
        if op.kind == "R":
            if not t.error:
                self._read_value = self.ref_word(op.addr)
                if t.lane_data != self._read_value:
                    self._violation(
                        f"slave returned {t.lane_data:#x} for {t.haddr:#x}, "
                        f"reference holds {self._read_value:#x}"
                    )
            return
        strb, data = op.strb, op.data
        if not t.error and strb is not None and data is not None:
            base = op.addr & ~3
            for k in range(4):
                if strb >> k & 1:
                    self.ref[base + k] = (data >> (8 * k)) & 0xFF

    def _axi_response(self, obs: AxilObservation) -> None:
        op, t = self._op, self._xfer
        if op is not obs:
            self._violation(
                f"response for #{obs.index} while #{op.index if op else None} is outstanding"
            )
            return
        if op.kind == "R":
            self.reads_checked += 1
            if t is None:
                self._violation(f"read araddr={op.addr:#x} completed with no AHB transfer")
                want = None
            else:
                want = RESP_SLVERR if t.error else RESP_OKAY
            if want is not None and obs.resp != want:
                self._violation(
                    f"read araddr={op.addr:#x} RRESP={_resp_name(obs.resp)}, "
                    f"expected {RESP_NAMES[want]}"
                )
            if want == RESP_OKAY and obs.rdata != self._read_value:
                self._violation(
                    f"read araddr={op.addr:#x} RDATA={_hex32(obs.rdata)}, expected "
                    f"{_hex32(self._read_value)}"
                )
            if want == RESP_SLVERR:
                self.slverr_from_ahb += 1
        else:
            self.writes_checked += 1
            e = self._expect
            if e is None:
                want = None
            elif e.transfer:
                self.writes_with_transfer += 1
                if t is None:
                    self._violation(
                        f"write awaddr={op.addr:#x} WSTRB={op.strb:04b} completed "
                        f"with no AHB transfer"
                    )
                    want = None
                else:
                    want = RESP_SLVERR if t.error else RESP_OKAY
                    self.slverr_from_ahb += t.error
            else:
                self.writes_local += 1
                want = e.local_resp
                if want == RESP_SLVERR:
                    self.slverr_local += 1
                elif op.strb == 0:
                    self.okay_zero_strobe += 1
            if want is not None and obs.resp != want:
                self._violation(
                    f"write awaddr={op.addr:#x} WSTRB={op.strb:04b} "
                    f"BRESP={_resp_name(obs.resp)}, expected {RESP_NAMES[want]}"
                )
        self._op = None
        self._xfer = None
        self._expect = None

    def summary(self) -> str:
        return (
            f"reads={self.reads_checked} writes={self.writes_checked} "
            f"(ahb={self.writes_with_transfer} local={self.writes_local}) "
            f"slverr_ahb={self.slverr_from_ahb} slverr_local={self.slverr_local} "
            f"okay_zero_strobe={self.okay_zero_strobe} reset_dropped={self.dropped_by_reset}"
        )
