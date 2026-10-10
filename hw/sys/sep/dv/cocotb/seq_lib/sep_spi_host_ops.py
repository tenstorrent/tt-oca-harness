# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""OpenTitan SPI host register operations over the CPU-LSU splice.

Builds on ``seq_lib/sep_spi_host_csr_seq.py`` (``SepSpiHost`` read/write and
the register addresses). Every field position below comes from the generated
register export through ``sep_reg_meta``; no offset or mask is retyped.

Contents:

* ``command_word`` and ``configopts_word``: COMMAND and CONFIGOPTS encoders.
* ``EVT_*``: EVENT_ENABLE bits. ``SpiStatus``: a decoded STATUS read.
* ``SepSpiHostOps``: bounded STATUS polls, the SW_RST helper, the SPI clean
  state, the segment-done wait, TX push and RX pop with their STATUS gates, and
  the 8-byte strobed write. Every STATUS read is appended to ``status_log`` with
  the pad-sampler clocks before and after it, so a leaf can place a read inside
  or outside a chip-select-low window.

Definitions (shared rules of the SPI entries):

* SW_RST helper: write CONTROL.SW_RST=1 with the other fields kept, poll STATUS
  until TXEMPTY=1 and RXEMPTY=1, then write CONTROL.SW_RST=0.
* SPI clean state: write 1 to every bit of ERROR_STATUS and to
  INTR_STATE.ERROR, write CSID=0, then run the SW_RST helper.
* A segment is done when the pad sampler has shown chip select low and then
  high (the given number of times) and a later STATUS read shows ACTIVE=0 and
  CMDQD=0.

Every wait is bounded; an expired bound raises ``AssertionError`` naming the
wait.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from env.sep_axi_agent import SepAxiOp
from sep_reg_meta import SPI_CONTROLLER

from seq_lib.sep_axi_access_seq import SepAxiAccessSeq
from seq_lib.sep_spi_host_csr_seq import (
    COMMAND,
    CONFIGOPTS,
    CONTROL,
    CSID,
    CTRL_SW_RST,
    ERR_STATUS_MASK,
    ERROR_STATUS,
    INTR_ERROR,
    INTR_STATE,
    RXDATA,
    STATUS,
    TXDATA,
    SepSpiHost,
)

_R = SPI_CONTROLLER


def _put(reg: str, fld: str, value: int) -> int:
    """``value`` placed in field ``fld`` of ``reg``; out-of-range values raise."""
    mask = _R.field_mask(reg, fld)
    lsb = _R.field_lsb(reg, fld)
    if value < 0 or (value << lsb) & ~mask:
        raise ValueError(f"{reg}.{fld}={value} does not fit the field (mask 0x{mask:x})")
    return int(value << lsb)


def _get(raw: int, reg: str, fld: str) -> int:
    return int((raw & _R.field_mask(reg, fld)) >> _R.field_lsb(reg, fld))


# COMMAND.DIRECTION and COMMAND.SPEED encodings (spi_controller.adoc, COMMAND).
DIR_DUMMY, DIR_RX, DIR_TX, DIR_BIDIR = 0, 1, 2, 3
SPEED_STD, SPEED_DUAL, SPEED_QUAD = 0, 1, 2
CMD_LEN_MAX = _R.field_mask("COMMAND", "len") >> _R.field_lsb("COMMAND", "len")


def command_word(len_field: int, *, speed: int = 0, direction: int = 0, csaat: int = 0) -> int:
    """COMMAND value; ``len_field`` is the LEN field (segment bytes minus 1)."""
    return (
        _put("COMMAND", "len", len_field)
        | _put("COMMAND", "speed", speed)
        | _put("COMMAND", "direction", direction)
        | _put("COMMAND", "csaat", csaat)
    )


def configopts_word(
    *,
    clkdiv: int = 0,
    csnidle: int = 0,
    csntrail: int = 0,
    csnlead: int = 0,
    fullcyc: int = 0,
    cpha: int = 0,
    cpol: int = 0,
) -> int:
    """CONFIGOPTS value from its fields."""
    return (
        _put("CONFIGOPTS", "clkdiv", clkdiv)
        | _put("CONFIGOPTS", "csnidle", csnidle)
        | _put("CONFIGOPTS", "csntrail", csntrail)
        | _put("CONFIGOPTS", "csnlead", csnlead)
        | _put("CONFIGOPTS", "fullcyc", fullcyc)
        | _put("CONFIGOPTS", "cpha", cpha)
        | _put("CONFIGOPTS", "cpol", cpol)
    )


EVT_RXFULL = _R.field_mask("EVENT_ENABLE", "rxfull")
EVT_TXEMPTY = _R.field_mask("EVENT_ENABLE", "txempty")
EVT_RXWM = _R.field_mask("EVENT_ENABLE", "rxwm")
EVT_TXWM = _R.field_mask("EVENT_ENABLE", "txwm")
EVT_READY = _R.field_mask("EVENT_ENABLE", "ready")
EVT_IDLE = _R.field_mask("EVENT_ENABLE", "idle")

_STATUS_FIELDS = (
    "txqd",
    "rxqd",
    "cmdqd",
    "rxwm",
    "byteorder",
    "rxstall",
    "rxempty",
    "rxfull",
    "txwm",
    "txstall",
    "txempty",
    "txfull",
    "active",
    "ready",
)


@dataclass(frozen=True)
class SpiStatus:
    """One decoded STATUS read. ``clk0``/``clk1``: pad-sampler clocks around the read."""

    raw: int
    clk0: int | None = None
    clk1: int | None = None

    def __getattr__(self, name: str) -> int:
        if name in _STATUS_FIELDS:
            return _get(self.raw, "STATUS", name)
        raise AttributeError(name)

    def flags(self) -> dict[str, int]:
        return {f: _get(self.raw, "STATUS", f) for f in _STATUS_FIELDS}

    def fmt(self) -> str:
        return f"STATUS=0x{self.raw:08x} " + " ".join(f"{k}={v}" for k, v in self.flags().items())


class SepSpiHostOps:
    """Bounded SPI host operations for a no_cpu leaf."""

    def __init__(self, test, *, clock: Callable[[], int] | None = None) -> None:
        self.test = test
        self.spi = SepSpiHost(test)
        # Returns the current pad-sampler clock, e.g. SepSpiPadSampler.now.
        self.clock = clock
        self.status_log: list[SpiStatus] = []

    async def wr(self, addr: int, data: int) -> None:
        await self.spi.wr(addr, data)

    async def rd(self, addr: int) -> int:
        return int(await self.spi.rd(addr))

    # ---- STATUS -----------------------------------------------------------
    async def read_status(self) -> SpiStatus:
        c0 = self.clock() if self.clock else None
        raw = await self.spi.rd(STATUS)
        c1 = self.clock() if self.clock else None
        st = SpiStatus(raw, c0, c1)
        self.status_log.append(st)
        return st

    async def poll_status(
        self, pred: Callable[[SpiStatus], bool], bound: int, what: str
    ) -> SpiStatus:
        """Read STATUS until ``pred`` holds, at most ``bound`` reads."""
        st = None
        for _ in range(bound):
            st = await self.read_status()
            if pred(st):
                return st
        raise AssertionError(
            f"SPI wait '{what}' expired after {bound} STATUS reads "
            f"(last {st.fmt() if st else 'none'})"
        )

    async def wait_ready(self, bound: int = 2_000) -> SpiStatus:
        return await self.poll_status(lambda s: s.ready == 1, bound, "READY=1")

    # ---- commands and data ------------------------------------------------
    async def issue_command(self, cmd: int, *, bound: int = 2_000) -> SpiStatus:
        """Write COMMAND after a STATUS read that shows READY=1; return that read."""
        st = await self.wait_ready(bound)
        await self.spi.wr(COMMAND, cmd)
        return st

    async def push_tx(self, word: int, *, bound: int = 2_000) -> SpiStatus:
        """Write one TXDATA word after a STATUS read that shows TXFULL=0."""
        st = await self.poll_status(lambda s: s.txfull == 0, bound, "TXFULL=0")
        await self.spi.wr(TXDATA, word & 0xFFFF_FFFF)
        return st

    async def pop_rx(self, *, bound: int = 2_000) -> int:
        """Read one RXDATA word after a STATUS read that shows RXEMPTY=0."""
        await self.poll_status(lambda s: s.rxempty == 0, bound, "RXEMPTY=0")
        return int(await self.spi.rd(RXDATA))

    async def drain_rx(self, *, limit: int = 512) -> list[int]:
        """Read RXDATA, each after a STATUS read with RXEMPTY=0, until RXEMPTY=1."""
        words: list[int] = []
        for _ in range(limit):
            st = await self.read_status()
            if st.rxempty:
                return words
            words.append(await self.spi.rd(RXDATA))
        raise AssertionError(f"SPI RX drain: RXEMPTY=0 after {limit} RXDATA reads")

    # ---- helpers of the shared rules --------------------------------------
    async def sw_rst(self, *, bound: int = 2_000) -> SpiStatus:
        """SW_RST helper: SW_RST=1 (other fields kept), TXEMPTY=1 and RXEMPTY=1, SW_RST=0."""
        ctrl = await self.spi.rd(CONTROL)
        await self.spi.wr(CONTROL, ctrl | CTRL_SW_RST)
        st = await self.poll_status(
            lambda s: s.txempty == 1 and s.rxempty == 1, bound, "SW_RST: TXEMPTY=1 and RXEMPTY=1"
        )
        await self.spi.wr(CONTROL, ctrl & ~CTRL_SW_RST)
        return st

    async def clean_state(self, *, bound: int = 2_000) -> SpiStatus:
        """SPI clean state: W1C ERROR_STATUS and INTR_STATE.ERROR, CSID=0, SW_RST helper."""
        await self.spi.wr(ERROR_STATUS, ERR_STATUS_MASK)
        await self.spi.wr(INTR_STATE, INTR_ERROR)
        await self.spi.wr(CSID, 0)
        return await self.sw_rst(bound=bound)

    async def write_configopts(self, value: int, *, bound: int = 2_000) -> None:
        """Write CONFIGOPTS after a STATUS read that shows ACTIVE=0."""
        await self.poll_status(lambda s: s.active == 0, bound, "ACTIVE=0 before CONFIGOPTS")
        await self.spi.wr(CONFIGOPTS, value)

    async def wait_segment_done(
        self, sampler, mark, *, windows: int = 1, bound_clks: int = 500_000, bound: int = 2_000
    ) -> list[Any]:
        """Wait for ``windows`` chip-select-low windows after ``mark``, then ACTIVE=0, CMDQD=0.

        Returns the windows. The STATUS read that ends the wait is taken after
        the sampler shows the last chip-select rise, so a read taken before the
        command starts cannot end it.
        """
        wins = await sampler.wait_windows(windows, mark, bound_clks)
        await self.poll_status(
            lambda s: s.active == 0 and s.cmdqd == 0, bound, "segment done: ACTIVE=0 and CMDQD=0"
        )
        return list(wins)

    # ---- 8-byte strobed write ---------------------------------------------
    async def wr_strobed64(self, pair_addr: int, value64: int, strb: int) -> int:
        """One 64-bit beat (AxSIZE 3) at the 8-byte-aligned ``pair_addr`` with WSTRB ``strb``.

        ``strb`` is a contiguous byte-lane mask (0x0F, 0xF0 or 0xFF for the two
        register halves); the AXI master sets WSTRB from the start address and
        the byte count. Returns BRESP; the caller grades it.
        """
        if pair_addr % 8:
            raise ValueError(f"pair address 0x{pair_addr:x} is not 8-byte aligned")
        if not 0 < strb <= 0xFF:
            raise ValueError(f"strobe 0x{strb:x} is empty or wider than 8 lanes")
        lo = (strb & -strb).bit_length() - 1
        span = strb >> lo
        if span & (span + 1):
            raise ValueError(f"strobe 0x{strb:x} is not contiguous")
        n = span.bit_length()
        data = (value64 >> (8 * lo)) & ((1 << (8 * n)) - 1)
        seq = SepAxiAccessSeq(
            f"spi_wr64_0x{pair_addr + lo:08x}_s{strb:02x}",
            op=SepAxiOp.WRITE,
            addr=pair_addr + lo,
            wdata=data,
            length=n,
            size=3,
            allow_unverified_write_resp=True,
        )
        await self.test.start_seq(seq)
        return int(seq.resp_code)
