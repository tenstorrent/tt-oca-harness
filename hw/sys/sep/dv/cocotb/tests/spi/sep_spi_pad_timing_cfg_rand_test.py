# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The SPI host CONFIGOPTS fields set the sck idle level, period, chip-select timing and data edge.

Contract (``vendor/lowRISC/opentitan/overlay/regs/spi_controller/regs/gen/adoc/spi_controller.adoc``,
CONFIGOPTS; ``hw/sys/sep/doc/clk_rst.adoc`` for the core clock):

* sck idles at the CPOL level.
* The sck period is 2*(CLKDIV+1) core clocks; a half sck cycle is CLKDIV+1.
* Chip select falls (CSNLEAD+1) half cycles before the first sck edge, rises
  (CSNTRAIL+1) half cycles after the last sck edge, and stays high at least
  (CSNIDLE+1) half cycles between commands.
* Tx data changes on the trailing sck edge when CPHA=0 and on the leading edge
  when CPHA=1.

Every seed grades two mode cells (CPOL x CPHA x FULLCYC): a drawn cell and the
cell with the other CPOL and the other CPHA. Each cell draws its lane width
(x1, x2 or x4); every segment of the cell runs at that width (COMMAND.SPEED).
Per mode cell the leaf runs a control pair (a Tx segment of 16 bytes with an Rx
COMMAND of 1 to 8 bytes queued while the Tx segment is active, CSNIDLE=0) that
gives the natural chip-select gap g0, raises CSNIDLE until its minimum is above
g0, runs the graded pair, then a ratio leg of two 4-byte Tx segments at CLKDIV a
and b. A test-side sampler (``env/sep_spi_pad_sampler.py``) reads
``spi_sck_o``, ``spi_cs_n_o`` and ``spi_mosi_o`` (lane 0) on each core clock.
The lane responder (``env/sep_spi_lane_responder.py``, plusarg
``+sep_spi_four_lane``) drives seeded bytes on the response lanes in each Rx
segment, in the mode of the cell. ``_LateResponder`` of this file gives the same
responder late beats at CPHA 1 also, for CHK-SPI-FULLCYC. The shared SPI monitor
(``env/sep_spi_wire_monitor.py``) grades the same pads in the mode of each
cell: SCK at CPOL at every chip-select edge and while chip select is high, a
driven lane never changing on a sample edge or between a sample edge and the
next shift edge, the data lane output enables, and no X/Z (``CHK-SPI-WIRE``,
both cells' modes with graded frames).

Data (OpenTitan SPI_HOST "Input and Output Byte Ordering", ``ByteOrder = 1``):
the first byte on the wire is TXDATA[7:0] and the first byte received lands in
RXDATA[7:0]; most significant bits first; in x2 and x4 the least significant
bit of each pair or nibble is on ``sd[0]``; in x1 the host sends on ``sd[0]``
and receives on ``sd[1]``. Tx data is seeded; the first two bytes of each Tx
segment hold lane 0 at 1, 0, 1, 0 on successive clocks, so the data-edge check
has its changes by construction.

Checks (one PASS line per mode cell, each with ``mode=<cpol><cpha><fullcyc>``):

* CHK-SPI-IDLE-LEVEL: sck sits at CPOL in every chip-select-high window of the
  graded pair that starts after the first transaction ends. Control: sck
  toggles in the chip-select-low windows of the same pair.
* CHK-SPI-CTRL-OE: with CONTROL.OUTPUT_EN = 1, ``spi_cs_oe_o`` = 1 and
  ``spi_sck_oe_o`` = 1 on every sampled clock of the two chip-select-low
  windows of the graded pair and of every chip-select-high window after the
  first of them (gap and the windows that follow). Source
  ``vendor/lowRISC/opentitan/upstream/hw/ip/spi_host/data/spi_host.hjson:222-224``
  (CONTROL.OUTPUT_EN): "Enable the SPI host output buffers for the sck, csb,
  and sd lines." Control: before the bring-up CONTROL write sets OUTPUT_EN,
  both enables read 0 (``doc/integrator/src/smu-sep.adoc:275-276``: the host
  "drives no pad until software sets its ``CONTROL.OUTPUT_EN``"), else
  CTRL-MISSING.
* CHK-SPI-PERIOD: every sck period of the graded pair is 2*(CLKDIV+1) clocks.
* CHK-SPI-RATIO: period_a*(b+1) equals period_b*(a+1).
* CHK-SPI-CSN: lead and trail of each graded transaction are at least
  (CSNLEAD+1) and (CSNTRAIL+1) times (CLKDIV+1) clocks, and the chip-select-high
  gap at least (CSNIDLE+1) times (CLKDIV+1). The register text gives the + 1
  value: CSNLEAD "Indicates the number of half sck cycles, CSNLEAD+1, to leave
  between the falling edge of cs_n and the first edge of sck", CSNTRAIL
  "Indicates the number of half sck cycles, CSNTRAIL+1, to leave between last
  edge of sck and the rising edge of cs_n", CSNIDLE "the minimum number of sck
  half-cycles to hold cs_n high between commands"
  (``vendor/lowRISC/opentitan/overlay/regs/spi_controller/regs/gen/adoc/spi_controller.adoc:165-175``,
  CONFIGOPTS). The OpenTitan theory of operation states the three as minimum
  bounds: "These settings are all minimum bounds, and delays in the FSM
  implementation may create more margin in each of these timing constraints."
  (``vendor/lowRISC/opentitan/upstream/hw/ip/spi_host/doc/theory_of_operation.md:287``). So the minimum is
  graded, and ``OBS-SPI-CSN-EXACT`` logs the lead and trail excess over each
  minimum. The chip-select and clock output enables in the frames and the gap
  are CHK-SPI-CTRL-OE. Control: the idle minimum is above g0 of the control
  pair.
* CHK-SPI-FULLCYC: at x1, x2 and x4 (drawn order, drawn CPOL and CLKDIV 1 to
  15), first at CPHA 0 and then at CPHA 1, an Rx segment from a late responder
  (each beat one core clock after its sample edge) reads the seeded bytes with
  FULLCYC = 1: the host samples a full cycle after its shift edge. Source
  ``vendor/lowRISC/opentitan/upstream/hw/ip/spi_host/data/spi_host.hjson:373-380``
  (CONFIGOPTS.FULLCYC): "Rather than sampling the SD bus a half cycle after
  shifting out data, the data is sampled a full cycle after shifting data out.
  ... If CPHA = 1, data is shifted and sampled with the trailing edge, also
  separated by a full cycle." The OpenTitan spi_host theory of operation
  (``vendor/lowRISC/opentitan/upstream/hw/ip/spi_host/doc/theory_of_operation.md:42``) states the CPHA 1
  sample edge: "if ``CPHA = 1`` data is always
  asserted on the leading edge of ``SCK`` and sampled on the trailing edge of
  ``SCK``." At CPHA 1 the late change of beat k is one clock after trailing
  edge k; both a sample at the next leading edge and one at the next trailing
  edge lie after that change and not after the change of beat k+1 (CLKDIV 1
  or more), so the graded bytes do not depend on which of the two points the
  host uses. Control: the same frame with FULLCYC = 0 reads every beat one
  beat late (``late_sample_edge_bytes``: beat k reads beat k-1, beat 0 reads
  the lane level 0 before the first late change), else CTRL-MISSING; the
  FULLCYC = 0 sample point is the sample edge (``spi_host.hjson:374-375``,
  "sampling the SD bus a half cycle after shifting out data"). The wire
  monitor is stopped for this leg (it samples at the sample edge); RXDATA is
  the graded side.
* CHK-SPI-CPHA: at CLKDIV 1 or more every Tx data change after the first bit
  lies in the half sck period that starts at the stated edge. A change counts
  only with the lane 0 output enable on; a ``spi_mosi_o`` change in the graded
  Tx window with the enable off fails, since it does not reach the pad.
  Control: at least two counted changes. The cell CPHA=1 with FULLCYC=1 logs
  ``OBS-SPI-CPHA`` and is not graded: the FULLCYC register text says that at
  CPHA = 1 "data is shifted and sampled with the trailing edge", and the
  theory of operation says that at CPHA = 1 data is asserted on the leading
  edge (``theory_of_operation.md:42``) and that FULLCYC "has no effect on any
  of the signals transmitted" (``theory_of_operation.md:298``). The second cell inverts the CPHA of the first, so each seed has
  one CPHA=0 cell that is graded.
* CHK-SPI-SB-FRAME (``env/sep_spi_scoreboard.py``, one scoreboard per cell):
  every Tx and Rx frame of the cell (control pairs, graded pair, ratio leg) at
  the width of the cell; Tx bytes queued against the monitor's wire decode, Rx
  bytes the responder drove against the wire decode and the RXDATA words the
  DUT delivered. Each frame logs an ``SPI-SB FRAME`` line with its mode, width
  and leg.
* CHK-SPI-LANE-DATA: one line per cell with ``width=`` and the Tx and Rx frame
  and byte counts, after CHK-SPI-SB-FRAME of the cell passed. Control: the cell
  graded at least one Tx frame and one Rx frame.
* CHK-SPI-CELL-FRAMES: the monitor frames of the cell are exactly the frames
  the cell registered with its scoreboard. A frame with no expectation, a
  registered frame the monitor did not see, or a monitor tally difference in
  the mode of the cell that is not equal to the registered count fails.
* CHK-SPI-RX-WORDS: after each pair the RXDATA drain (reads until
  RXEMPTY=1) gives exactly ceil(n/4) words for an Rx segment of n bytes, and no
  word when the Rx COMMAND was not written. A surplus or a missing word fails.

Every CHK line carries ``width=x1|x2|x4``.

Graded window: owner code of this test for the graded pair, the ratio leg and
the data-edge grade; closed for bring-up and every control pair.

Run mode: ``no_cpu``, ``lsu_stub_all_live``, ``+skip_fuse_sense``,
``+sep_spi_four_lane``, no ``rst_ni`` pulse. Every random value is a pure function of the seed (``SepSeededRng``).
"""

from __future__ import annotations

from dataclasses import dataclass

import cocotb
import pyuvm
from cocotb.triggers import FallingEdge, ReadOnly, RisingEdge
from env.sep_fcov_gate import close_graded_window, fcov_present, open_graded_window
from env.sep_field_compare import field_compare
from env.sep_seeded_rng import SepSeededRng
from env.sep_spi_lane_responder import (
    SepSpiLaneResponder,
    late_sample_edge_bytes,
    pack_tx_words,
    spi_lane_fcov,
    unpack_rx_words,
)
from env.sep_spi_pad_sampler import CsWindow, SepSpiPadSampler
from env.sep_spi_scoreboard import SepSpiScoreboard
from env.sep_spi_wire_monitor import SepSpiWireMonitor
from sep_base_test import sep_base_test
from sep_reg_meta import SPI_CONTROLLER
from seq_lib.sep_spi_host_csr_seq import (
    COMMAND,
    CONTROL,
    CSID,
    CTRL_OUTPUT_EN,
    CTRL_RESET,
    CTRL_SPIEN,
    CTRL_SW_RST,
    ERR_STATUS_MASK,
    ERROR_STATUS,
)
from seq_lib.sep_spi_host_ops import DIR_RX, DIR_TX, SepSpiHostOps, command_word, configopts_word

TEST = "sep_spi_pad_timing_cfg_rand_test"

CTRL_TX_BYTES = 16
RX_BYTES_MAX = 8
RATIO_TX_BYTES = 4
# Lane widths a cell draws from, and COMMAND.SPEED per width.
WIDTHS = (1, 2, 4)
SPEED = {1: 0, 2: 1, 4: 2}
# Leading bytes of each Tx segment that hold lane 0 at 1, 0, 1, 0 per clock.
TOGGLE_BYTES = 2
MAX_DOUBLINGS = 3
# The walked CLKDIV range is a stimulus choice (0 to 15); the CSN ranges are
# the full CONFIGOPTS field ranges from the generated register metadata.
CLKDIV_DRAW_MAX = 15
CSNLEAD_MAX = (1 << SPI_CONTROLLER.field_width("CONFIGOPTS", "csnlead")) - 1
CSNTRAIL_MAX = (1 << SPI_CONTROLLER.field_width("CONFIGOPTS", "csntrail")) - 1
CSNIDLE_MAX = (1 << SPI_CONTROLLER.field_width("CONFIGOPTS", "csnidle")) - 1
# Scratch mutation hooks; both are 0 in the shipped leaf. RX_EXTRA_BYTES > 0
# lengthens each Rx COMMAND past its expected bytes (CHK-SPI-RX-WORDS fails);
# EXTRA_TX_FRAMES > 0 issues that many unregistered Tx frames at the end of
# each cell (CHK-SPI-CELL-FRAMES fails).
RX_EXTRA_BYTES = 0
EXTRA_TX_FRAMES = 0
# (spi_cs_oe_o, spi_sck_oe_o) with CONTROL.OUTPUT_EN = 1 (CHK-SPI-CTRL-OE), and
# before the first CONTROL write that sets it (the control).
EXP_CTRL_OE = (1, 1)
EXP_PRE_ENABLE_OE = (0, 0)

# Bounds. Each expiry fails the check that the wait feeds.
QUEUE_POLLS = 64
PAIR_BOUND_CLKS = 400_000


@dataclass
class Cell:
    cpol: int
    cpha: int
    fullcyc: int
    a: int = 0
    lead: int = 0
    trail: int = 0
    idle: int = 0
    b: int = 0
    width: int = 1

    @property
    def mode(self) -> str:
        return f"{self.cpol}{self.cpha}{self.fullcyc}"

    def cfg(self, *, clkdiv: int, csnidle: int) -> int:
        return configopts_word(
            clkdiv=clkdiv,
            csnidle=csnidle,
            csntrail=self.trail,
            csnlead=self.lead,
            fullcyc=self.fullcyc,
            cpha=self.cpha,
            cpol=self.cpol,
        )


def _val(sig) -> int | None:
    v = sig.value
    return int(v) if v.is_resolvable else None


def _oe_violations(wins: list, now: int) -> tuple[int, int, int]:
    """(sampled clocks, cs_oe clocks not at EXP_CTRL_OE, sck_oe clocks not at EXP_CTRL_OE)."""
    n = cs_bad = sck_bad = 0
    for w in wins:
        clks = (w.end if w.end is not None else now + 1) - w.start
        n += clks
        cs_bad += w.cs_oe_off if EXP_CTRL_OE[0] else clks - w.cs_oe_off
        sck_bad += w.sck_oe_off if EXP_CTRL_OE[1] else clks - w.sck_oe_off
    return n, cs_bad, sck_bad


class _LateResponder(SepSpiLaneResponder):
    """The lane responder with late beats at CPHA 0 and CPHA 1.

    The base late path puts beat ``k`` one core clock after sample edge ``k``
    for either CPHA (the sample edge is the trailing edge at CPHA 1); this
    class only accepts ``set_late(True)`` at CPHA 1 too. At CPHA 1 no beat is
    driven at the chip-select fall, so the lanes hold 0 until one clock after
    the first trailing edge.
    """

    def set_late(self, late: bool) -> None:
        self._late = bool(late)


def _draw_edge(rng: SepSeededRng, top: int) -> int:
    """0 to top, weighted toward 0 and top."""
    roll = rng.randrange(4)
    if roll == 0:
        return 0
    if roll == 1:
        return top
    return rng.randrange(1, top)


@pyuvm.test()
class sep_spi_pad_timing_cfg_rand_test(sep_base_test):
    """Two mode cells per seed: sck idle level, period, ratio, chip-select timing, data edge."""

    required_evidence = (
        "CHK-SPI-IDLE-LEVEL",
        "CHK-SPI-PERIOD",
        "CHK-SPI-RATIO",
        "CHK-SPI-CSN",
        "CHK-SPI-CPHA",
        "CHK-SPI-SB-FRAME",
        "CHK-SPI-LANE-DATA",
        "CHK-SPI-CELL-FRAMES",
        "CHK-SPI-RX-WORDS",
        "CHK-SPI-FULLCYC",
        "CHK-SPI-CTRL-OE",
    )

    def _plan(self, seed: int) -> list[Cell]:
        # Tx and Rx data draws follow the plan draws on the same stream.
        rng = self.rng = SepSeededRng(seed)
        first = rng.randrange(8)
        c1 = Cell((first >> 2) & 1, (first >> 1) & 1, first & 1)
        c2 = Cell(1 - c1.cpol, 1 - c1.cpha, rng.randrange(2))
        cells = [c1, c2]
        if rng.randrange(2):
            cells.reverse()
        for c in cells:
            c.a = _draw_edge(rng, CLKDIV_DRAW_MAX)
            c.lead = _draw_edge(rng, CSNLEAD_MAX)
            c.trail = _draw_edge(rng, CSNTRAIL_MAX)
            c.idle = _draw_edge(rng, CSNIDLE_MAX)
            c.b = rng.choice([v for v in range(CLKDIV_DRAW_MAX + 1) if v != c.a])
        for c in cells:
            c.width = rng.choice(WIDTHS)
        self.logger.info(
            "PLAN seed=%d cells=%s",
            seed,
            " ".join(
                f"[mode={c.mode} width=x{c.width} a={c.a} csnlead={c.lead} "
                f"csntrail={c.trail} csnidle={c.idle} b={c.b}]"
                for c in cells
            ),
        )
        return cells

    # ---- helpers ----------------------------------------------------------
    async def _err_status(self) -> int:
        return int(await self.ops.rd(ERROR_STATUS)) & 0xFFFF_FFFF

    def _tx_data(self, n: int, width: int) -> bytes:
        """Seeded Tx bytes; the first TOGGLE_BYTES hold lane 0 at 1, 0, 1, 0 per clock."""
        data = bytearray(self.rng.getrandbits(8) for _ in range(n))
        shifts = range(8 - width, -1, -width)
        mask = sum(1 << s for s in shifts)
        ones = sum(1 << s for j, s in enumerate(shifts) if j % 2 == 0)
        for i in range(min(TOGGLE_BYTES, n)):
            data[i] = (data[i] & ~mask & 0xFF) | ones
        return bytes(data)

    def _rx_data(self, width: int) -> bytes:
        """Seeded Rx bytes, 1 to RX_BYTES_MAX; the low lane group of byte 0 reads 0..01."""
        n = self.rng.randrange(1, RX_BYTES_MAX + 1)
        data = bytearray(self.rng.getrandbits(8) for _ in range(n))
        data[0] = (data[0] & ~((1 << width) - 1) & 0xFF) | 1
        return bytes(data)

    def _expect(self, mark: int, seg: tuple, *, delivered: bytes = b"", leg: str) -> None:
        """Register one single-segment frame with the cell scoreboard."""
        lanes, kind, value = seg
        self.sb.expect_frame(
            mark,
            [seg],
            delivered=delivered,
            label=f"mode={self.cell.mode} width=x{lanes} leg={leg} dir={kind}",
        )
        self.tally[kind][0] += 1
        self.tally[kind][1] += len(value)
        self.marks.add(mark)

    def _rx_words(self, words: list[int], n: int, *, tag: str) -> None:
        """CHK-SPI-RX-WORDS: the drain gave exactly the words of ``n`` Rx bytes."""
        exp = (n + 3) // 4
        line = (
            f"seed={self.seed} mode={self.cell.mode} width=x{self.cell.width} {tag} "
            f"rx_bytes={n} words={len(words)} expect={exp}"
        )
        if len(words) != exp:
            raise AssertionError(f"CHK-SPI-RX-WORDS FAIL {line}")
        self.logger.info("CHK-SPI-RX-WORDS PASS %s", line)
        self.ran.add("CHK-SPI-RX-WORDS")

    async def _arm_rx_window(self, segs: list[tuple[str, int, int]]) -> None:
        """Give the responder the Rx layout once the Tx window of the pair has started."""
        dut = cocotb.top
        await FallingEdge(dut.spi_cs_n_o)
        # The responder takes its layout at the chip-select fall; one clock later
        # the layout applies to the next window, the Rx segment.
        await RisingEdge(dut.clk_i)
        self.rsp.expect_segments(segs)

    async def _pair(self, cfg: int, cpol: int, tx_bytes: int, width: int, *, tag: str):
        """Tx segment with the Rx COMMAND queued while it is active.

        Returns ``(mark, windows)``, or ``None`` when a STATUS read shows READY=1
        and ACTIVE=0 before the Rx COMMAND is written.
        """
        ops, pads = self.ops, self.pads
        speed = SPEED[width]
        await ops.write_configopts(cfg)
        pads.set_idle_level(cpol)
        tx = self._tx_data(tx_bytes, width)
        rx = self._rx_data(width)
        for word in pack_tx_words(tx):
            await ops.push_tx(word)
        self.rsp.queue_rx(rx, width)
        arm = cocotb.start_soon(self._arm_rx_window([("rx", width, len(rx))]))
        fmark = self.sb.frame_mark()
        mark = pads.mark()
        await ops.issue_command(command_word(tx_bytes - 1, speed=speed, direction=DIR_TX))
        queued = None
        for _ in range(QUEUE_POLLS):
            st = await ops.read_status()
            if st.ready and st.active:
                await ops.wr(
                    COMMAND,
                    command_word(len(rx) - 1 + RX_EXTRA_BYTES, speed=speed, direction=DIR_RX),
                )
                queued = st
                break
            if st.ready and not st.active:
                break
        if queued is None:
            await ops.wait_segment_done(pads, mark, windows=1, bound_clks=PAIR_BOUND_CLKS)
            self._rx_words(await ops.drain_rx(), 0, tag=f"{tag}_tx_only")
            arm.cancel()
            self.rsp.clear()
            self._expect(fmark, (width, "tx", tx), leg=f"{tag}_tx_only")
            self.logger.info(
                "%s LOG seed=%d tx_bytes=%d rx_queued_while_active=0 width=x%d",
                tag,
                self.seed,
                tx_bytes,
                width,
            )
            return None
        wins = await ops.wait_segment_done(pads, mark, windows=2, bound_clks=PAIR_BOUND_CLKS)
        words = await ops.drain_rx()
        if not arm.done():
            arm.cancel()
            self.rsp.clear()
            raise AssertionError(
                f"CTRL-MISSING seed={self.seed} mode={self.cell.mode} width=x{width} "
                f"{tag}: the Rx layout was not armed before the Rx window"
            )
        self._rx_words(words, len(rx), tag=tag)
        delivered = unpack_rx_words(words, len(rx))
        self._expect(fmark, (width, "tx", tx), leg=f"{tag}_tx")
        self._expect(fmark + 1, (width, "rx", rx), delivered=delivered, leg=f"{tag}_rx")
        return mark, wins

    async def _single_tx(self, cfg: int, cpol: int, width: int, *, leg: str | None) -> CsWindow:
        """One Tx segment; with ``leg=None`` the frame is not registered."""
        ops, pads = self.ops, self.pads
        await ops.write_configopts(cfg)
        pads.set_idle_level(cpol)
        tx = self._tx_data(RATIO_TX_BYTES, width)
        for word in pack_tx_words(tx):
            await ops.push_tx(word)
        fmark = self.sb.frame_mark()
        mark = pads.mark()
        await ops.issue_command(
            command_word(RATIO_TX_BYTES - 1, speed=SPEED[width], direction=DIR_TX)
        )
        wins = await ops.wait_segment_done(pads, mark, windows=1, bound_clks=PAIR_BOUND_CLKS)
        if leg is not None:
            self._expect(fmark, (width, "tx", tx), leg=leg)
        return wins[0]

    @staticmethod
    def _cpha_split(win: CsWindow, cpha: int) -> tuple[int, int, int]:
        """Lane 0 enabled data changes after the first bit: (stated half, other half, exempt)."""
        edges = win.edges
        if not edges:
            return 0, 0, len(win.mosi_changes_oe_on)
        first = edges[0][0]
        stated = other = exempt = 0
        for c in win.mosi_changes_oe_on:
            if c < first:
                exempt += 1
                continue
            last = [lvl for clk, lvl in edges if clk <= c][-1]
            leading = last != win.idle_level
            if leading == bool(cpha):
                stated += 1
            else:
                other += 1
        return stated, other, exempt

    # ---- one mode cell ----------------------------------------------------
    async def _mode_cell(self, c: Cell) -> None:
        seed = self.seed
        pads = self.pads
        half = c.a + 1
        w = c.width
        self.cell = c
        self.sb = SepSpiScoreboard(self.wire, None, self.logger, seed=seed)
        self.tally = {"tx": [0, 0], "rx": [0, 0]}
        self.marks: set[int] = set()
        first = self.sb.frame_mark()
        mode_tally0 = self.wire.tally[(c.cpol, c.cpha)]
        # Every CONFIGOPTS write of the cell carries this CPOL and CPHA.
        self.wire.set_mode(c.cpol, c.cpha)
        self.rsp.set_mode(c.cpol, c.cpha)

        # Control pair: CSNIDLE=0, window closed.
        close_graded_window(self.logger)
        tx_bytes = CTRL_TX_BYTES
        ctrl = None
        for _ in range(MAX_DOUBLINGS + 1):
            ctrl = await self._pair(
                c.cfg(clkdiv=c.a, csnidle=0), c.cpol, tx_bytes, w, tag="CTL-SPI-QUEUE"
            )
            if ctrl is not None:
                break
            tx_bytes *= 2
        if ctrl is None:
            raise AssertionError(
                f"CTRL-MISSING seed={seed} mode={c.mode} width=x{w} CHK-SPI-CSN: the Rx "
                f"COMMAND never queued while the Tx segment was active "
                f"(last tx_bytes={tx_bytes // 2})"
            )
        cmark, cwins = ctrl
        g0 = cwins[1].start - cwins[0].end
        self.logger.info(
            "CTL-SPI-CSN LOG seed=%d mode=%s width=x%d clkdiv=%d tx_bytes=%d control_gap=%d "
            "windows=%s",
            seed,
            c.mode,
            w,
            c.a,
            tx_bytes,
            g0,
            [w.fmt() for w in cwins],
        )

        # Raise CSNIDLE above the control gap. Chip select stays high for at
        # least CSNIDLE+1 half sck cycles (spi_host theory_of_operation.md:272).
        idle = c.idle
        if (idle + 1) * half <= g0:
            fits = [v for v in range(CSNIDLE_MAX + 1) if (v + 1) * half > g0]
            if not fits:
                raise AssertionError(
                    f"CTRL-MISSING seed={seed} mode={c.mode} CHK-SPI-CSN: no CSNIDLE "
                    f"gives a minimum above control_gap={g0} at clkdiv={c.a}"
                )
            idle = fits[0]
        idle_min = (idle + 1) * half
        self.logger.info(
            "DRAW seed=%d mode=%s csnidle_drawn=%d csnidle_graded=%d min=%d control_gap=%d",
            seed,
            c.mode,
            c.idle,
            idle,
            idle_min,
            g0,
        )

        # Graded pair.
        open_graded_window(TEST, self.logger)
        graded = await self._pair(
            c.cfg(clkdiv=c.a, csnidle=idle), c.cpol, tx_bytes, w, tag="CHK-SPI-CSN"
        )
        if graded is None:
            close_graded_window(self.logger)
            raise AssertionError(
                f"CTRL-MISSING seed={seed} mode={c.mode} CHK-SPI-CSN: the Rx COMMAND did "
                f"not queue while the Tx segment was active in the graded pair"
            )
        gmark, (w1, w2) = graded
        highs = [h for h in pads.high_windows_since(gmark) if h.start >= w1.end]
        levels = set().union(*(h.sck_levels for h in highs)) if highs else set()
        toggles = (w1.toggles, w2.toggles)

        line = (
            f"seed={seed} mode={c.mode} width=x{w} cpol={c.cpol} level={sorted(levels)} "
            f"windows={len(highs)} control_toggles={min(toggles)}"
        )
        if min(toggles) < 1:
            raise AssertionError(f"CTRL-MISSING CHK-SPI-IDLE-LEVEL {line}")
        if len(highs) < 2 or levels != {c.cpol}:
            raise AssertionError(f"CHK-SPI-IDLE-LEVEL FAIL {line}")
        # CONTROL.OUTPUT_EN = 1 enables the sck, csb and sd output buffers, so
        # both enables are 1 with chip select low and high.
        now = pads.now()
        n_low, cs_low_bad, sck_low_bad = _oe_violations([w1, w2], now)
        n_high, cs_high_bad, sck_high_bad = _oe_violations(highs, now)
        line_oe = (
            f"seed={seed} mode={c.mode} width=x{w} expect_cs_oe={EXP_CTRL_OE[0]} "
            f"expect_sck_oe={EXP_CTRL_OE[1]} cs_low_clks={n_low} cs_high_clks={n_high} "
            f"high_windows={len(highs)} cs_oe_bad_low={cs_low_bad} "
            f"sck_oe_bad_low={sck_low_bad} cs_oe_bad_high={cs_high_bad} "
            f"sck_oe_bad_high={sck_high_bad} pre_enable_cs_oe={self.pre_oe[0]} "
            f"pre_enable_sck_oe={self.pre_oe[1]}"
        )
        if not n_low or not n_high:
            raise AssertionError(f"CTRL-MISSING CHK-SPI-CTRL-OE {line_oe}")
        if cs_low_bad or sck_low_bad or cs_high_bad or sck_high_bad:
            raise AssertionError(f"CHK-SPI-CTRL-OE FAIL {line_oe}")
        self.logger.info("CHK-SPI-CTRL-OE PASS %s", line_oe)
        self.ran.add("CHK-SPI-CTRL-OE")
        self.logger.info(
            "CHK-SPI-IDLE-LEVEL PASS seed=%d cpol=%d level=%d windows=%d control_toggles=%d "
            "mode=%s width=x%d",
            seed,
            c.cpol,
            c.cpol,
            len(highs),
            min(toggles),
            c.mode,
            w,
        )

        periods = w1.periods + w2.periods
        exp_p = 2 * half
        bad = sorted(set(p for p in periods if p != exp_p))
        line = (
            f"seed={seed} clkdiv={c.a} periods={len(periods)} "
            f"period_clk={sorted(set(periods))} expect={exp_p} mode={c.mode} width=x{w}"
        )
        if not periods or bad:
            raise AssertionError(f"CHK-SPI-PERIOD FAIL {line}")
        self.logger.info(
            "CHK-SPI-PERIOD PASS seed=%d clkdiv=%d periods=%d period_clk=%d expect=%d mode=%s "
            "width=x%d",
            seed,
            c.a,
            len(periods),
            exp_p,
            exp_p,
            c.mode,
            w,
        )

        # CSNLEAD, CSNTRAIL and CSNIDLE are minimum bounds; FSM delays may add
        # margin (spi_host theory_of_operation.md:287).
        exp_lead = (c.lead + 1) * half
        exp_trail = (c.trail + 1) * half
        gap = w2.start - w1.end
        # The lead, trail and gap are pad timing only while the host drives
        # chip select and the clock: both output enables on in both frames
        # and in the gap between them.
        gap_wins = [h for h in highs if h.start == w1.end and h.end == w2.start]
        oe_off = sum(w.cs_oe_off + w.sck_oe_off for w in (w1, w2, *gap_wins))
        line = (
            f"seed={seed} clkdiv={c.a} lead={w1.lead},{w2.lead}/{exp_lead} "
            f"trail={w1.trail},{w2.trail}/{exp_trail} idle_gap={gap} min={idle_min} "
            f"control_gap={g0} csnlead={c.lead} csntrail={c.trail} csnidle={idle} "
            f"gap_windows={len(gap_wins)} cs_sck_oe_off={oe_off} mode={c.mode} "
            f"width=x{w}"
        )
        ok = (
            len(gap_wins) == 1
            and min(w1.lead, w2.lead) >= exp_lead
            and min(w1.trail, w2.trail) >= exp_trail
            and gap >= idle_min
            and idle_min > g0
        )
        # A CSN failure is raised after the ratio and data-edge checks of this
        # mode cell, so the log carries every check of the cell.
        csn_fail = None
        if ok:
            self.logger.info("CHK-SPI-CSN PASS %s", line)
            # CSNLEAD, CSNTRAIL and CSNIDLE are minimum bounds that FSM delays
            # may exceed (spi_host theory_of_operation.md:287); the excess is logged.
            self.logger.info(
                "OBS-SPI-CSN-EXACT seed=%d mode=%s clkdiv=%d half=%d lead_excess=%d,%d "
                "trail_excess=%d,%d idle_gap=%d csnidle_plus_one=%d width=x%d",
                seed,
                c.mode,
                c.a,
                half,
                w1.lead - exp_lead,
                w2.lead - exp_lead,
                w1.trail - exp_trail,
                w2.trail - exp_trail,
                gap,
                (idle + 1) * half,
                w,
            )
        else:
            csn_fail = f"CHK-SPI-CSN FAIL {line}"
            self.logger.error(csn_fail)

        # Ratio leg.
        cfg_a = c.cfg(clkdiv=c.a, csnidle=idle)
        cfg_b = c.cfg(clkdiv=c.b, csnidle=idle)
        win_a = await self._single_tx(cfg_a, c.cpol, w, leg="ratio_a")
        win_b = await self._single_tx(cfg_b, c.cpol, w, leg="ratio_b")
        pa_set, pb_set = set(win_a.periods), set(win_b.periods)
        pa = min(pa_set) if pa_set else 0
        pb = min(pb_set) if pb_set else 0
        lhs, rhs = pa * (c.b + 1), pb * (c.a + 1)
        line = (
            f"seed={seed} a={c.a} b={c.b} period_a={pa} period_b={pb} lhs={lhs} rhs={rhs} "
            f"mode={c.mode} width=x{w}"
        )
        if len(pa_set) != 1 or len(pb_set) != 1 or lhs != rhs or c.a == c.b:
            raise AssertionError(
                f"CHK-SPI-RATIO FAIL {line} periods_a={sorted(pa_set)} periods_b={sorted(pb_set)}"
            )
        self.logger.info("CHK-SPI-RATIO PASS %s", line)

        # Data edge. At CPHA 1 with FULLCYC 1 the OpenTitan texts give two Tx
        # edges (FULLCYC register text: shifted with the trailing edge;
        # theory_of_operation.md:42 and :298: asserted on the leading edge,
        # FULLCYC changes no transmitted signal), so that cell is logged and
        # not graded.
        if c.cpha == 1 and c.fullcyc == 1:
            self.logger.info(
                "OBS-SPI-CPHA seed=%d cpha=1 fullcyc=1 graded=0 ambiguous=1 mode=%s width=x%d",
                seed,
                c.mode,
                w,
            )
        else:
            run, div = (w1, c.a) if c.a >= 1 else (win_b, c.b)
            stated, other, exempt = self._cpha_split(run, c.cpha)
            edge = "leading" if c.cpha else "trailing"
            line = (
                f"seed={seed} cpha={c.cpha} clkdiv={div} edge={edge} in_stated_half={stated} "
                f"in_other_half={other} exempt_first={exempt} mosi_xz={run.mosi_xz} "
                f"changes_oe_off={len(run.mosi_changes_oe_off)} mode={c.mode} width=x{w}"
            )
            if run.mosi_xz or run.mosi_changes_oe_off:
                raise AssertionError(f"CHK-SPI-CPHA FAIL {line}")
            if stated + other < 2:
                raise AssertionError(f"CTRL-MISSING CHK-SPI-CPHA {line}")
            if other:
                raise AssertionError(f"CHK-SPI-CPHA FAIL {line}")
            self.logger.info("CHK-SPI-CPHA PASS %s", line)
            self.ran.add("CHK-SPI-CPHA")
        close_graded_window(self.logger)
        if csn_fail:
            raise AssertionError(csn_fail)
        self.ran.update(("CHK-SPI-IDLE-LEVEL", "CHK-SPI-PERIOD", "CHK-SPI-RATIO", "CHK-SPI-CSN"))

        err = field_compare(await self._err_status(), 0, ERR_STATUS_MASK)
        if not err.ok:
            raise AssertionError(
                f"SPI-ERROR FAIL seed={seed} mode={c.mode} width=x{w} error_status {err.fields()}"
            )

        for _ in range(EXTRA_TX_FRAMES):
            await self._single_tx(c.cfg(clkdiv=c.a, csnidle=idle), c.cpol, w, leg=None)

        # Every monitor frame of the cell has one expectation.
        end = self.sb.frame_mark()
        mode_frames = self.wire.tally[(c.cpol, c.cpha)] - mode_tally0
        unexpected = [i for i in range(first, end) if i not in self.marks]
        unseen = sorted(m for m in self.marks if not first <= m < end)
        line = (
            f"seed={seed} mode={c.mode} width=x{w} first={first} frames={end - first} "
            f"mode_tally={mode_frames} registered={len(self.marks)} "
            f"unexpected={unexpected[:5]} unseen={unseen[:5]}"
        )
        if unexpected or unseen or mode_frames != len(self.marks) or not self.marks:
            raise AssertionError(f"CHK-SPI-CELL-FRAMES FAIL {line}")
        self.logger.info("CHK-SPI-CELL-FRAMES PASS %s", line)
        self.ran.add("CHK-SPI-CELL-FRAMES")

        # Data of every frame of the cell, at the width of the cell.
        self.sb.finish()
        (tx_frames, tx_bytes_n), (rx_frames, rx_bytes_n) = self.tally["tx"], self.tally["rx"]
        line = (
            f"seed={seed} mode={c.mode} width=x{w} tx_frames={tx_frames} tx_bytes={tx_bytes_n} "
            f"rx_frames={rx_frames} rx_bytes={rx_bytes_n}"
        )
        if not tx_frames or not rx_frames:
            raise AssertionError(f"CTRL-MISSING CHK-SPI-LANE-DATA {line}")
        self.logger.info("CHK-SPI-LANE-DATA PASS %s", line)
        self.ran.update(("CHK-SPI-SB-FRAME", "CHK-SPI-LANE-DATA"))
        await spi_lane_fcov(TEST, "data", lanes=w, rx=False)
        await spi_lane_fcov(TEST, "data", lanes=w, rx=True)

    # ---- FULLCYC sampling point -------------------------------------------
    async def _fullcyc_rx(
        self, cpol: int, cpha: int, clkdiv: int, fullcyc: int, data: bytes, w: int
    ):
        """One Rx segment of ``data`` from the late responder; return the RXDATA bytes."""
        ops, pads = self.ops, self.pads
        cfg = configopts_word(clkdiv=clkdiv, fullcyc=fullcyc, cpha=cpha, cpol=cpol)
        await ops.write_configopts(cfg)
        pads.set_idle_level(cpol)
        self.rsp.load([(w, "rx", data)])
        mark = pads.mark()
        await ops.issue_command(command_word(len(data) - 1, speed=SPEED[w], direction=DIR_RX))
        await ops.wait_segment_done(pads, mark, windows=1, bound_clks=PAIR_BOUND_CLKS)
        words = await ops.drain_rx()
        if len(words) != (len(data) + 3) // 4:
            raise AssertionError(
                f"CHK-SPI-FULLCYC FAIL seed={self.seed} width=x{w} cpha={cpha} fullcyc={fullcyc} "
                f"rx_bytes={len(data)} words={len(words)}"
            )
        return unpack_rx_words(words, len(data))

    async def _fullcyc_cell(self, w: int, cpha: int) -> None:
        """One CHK-SPI-FULLCYC frame pair at width ``w`` and ``cpha``, late responder."""
        seed, rng = self.seed, self.rng
        cpol = rng.randrange(2)
        clkdiv = rng.randrange(1, CLKDIV_DRAW_MAX + 1)
        data = bytearray(self._rx_data(w))
        # Beat 0 is 0..01 on the lanes, so the late read differs from
        # the seeded bytes by construction.
        top = ((1 << w) - 1) << (8 - w)
        data[0] = (data[0] & ~top & 0xFF) | (1 << (8 - w))
        data = bytes(data)
        late = late_sample_edge_bytes(data, w)
        graded_first = rng.randrange(2)
        self.rsp.set_mode(cpol, cpha)
        self.rsp.set_late(True)
        got: dict[int, bytes] = {}
        for fullcyc in (1, 0) if graded_first else (0, 1):
            if fullcyc:
                open_graded_window(TEST, self.logger)
            got[fullcyc] = await self._fullcyc_rx(cpol, cpha, clkdiv, fullcyc, data, w)
            close_graded_window(self.logger)
        self.rsp.set_late(False)
        line = (
            f"seed={seed} width=x{w} cpol={cpol} cpha={cpha} clkdiv={clkdiv} "
            f"rx_bytes={len(data)} expected={data.hex()} fullcyc1={got[1].hex()} "
            f"fullcyc0={got[0].hex()} late_expected={late.hex()}"
        )
        if got[0] != late:
            raise AssertionError(f"CTRL-MISSING CHK-SPI-FULLCYC {line}")
        if got[1] != data:
            raise AssertionError(f"CHK-SPI-FULLCYC FAIL {line}")
        self.logger.info("CHK-SPI-FULLCYC PASS %s", line)

    async def _fullcyc_leg(self) -> None:
        """CHK-SPI-FULLCYC at x1, x2 and x4, CPHA 0 then CPHA 1, with a late responder.

        The responder puts each beat one core clock after its sample edge. A
        host that samples a full cycle after its shift edge (FULLCYC = 1)
        reads the seeded bytes; with FULLCYC = 0 it reads each beat one beat
        late (control). The CPHA 1 draws follow every CPHA 0 draw.
        """
        seed, rng = self.seed, self.rng
        widths = list(WIDTHS)
        rng.shuffle(widths)
        # The wire monitor samples at the sample edge, so it would decode the
        # late beats one beat late; this leg grades RXDATA only.
        await self.wire.monitor.stop()
        try:
            for w in widths:
                await self._fullcyc_cell(w, 0)
                await spi_lane_fcov(TEST, "fullcyc", lanes=w, rx=True)
            widths1 = list(WIDTHS)
            rng.shuffle(widths1)
            for w in widths1:
                await self._fullcyc_cell(w, 1)
            self.ran.add("CHK-SPI-FULLCYC")
            err = field_compare(await self._err_status(), 0, ERR_STATUS_MASK)
            if not err.ok:
                raise AssertionError(
                    f"SPI-ERROR FAIL seed={seed} leg=fullcyc error_status {err.fields()}"
                )
        finally:
            self.rsp.set_late(False)
            close_graded_window(self.logger)

    # ---- scenario ---------------------------------------------------------
    async def run_scenario(self) -> None:
        self.seed = self.random_seed()
        cells = self._plan(self.seed)
        self.ran: set[str] = set()
        close_graded_window()

        try:
            await self.bring_up_no_cpu()
            self.suppress_host_axi_transaction_info()
            self.wire = SepSpiWireMonitor(cocotb.top)
            # Every frame here is a raw segment frame, not a flash command; the
            # command-format oe_data check does not apply to it.
            self.wire.monitor.set_raw_frames(True)
            await self.wire.start()
            self.rsp = await _LateResponder(cocotb.top).start()
            self.pads = SepSpiPadSampler()
            self.pads.start()
            self.ops = SepSpiHostOps(self, clock=self.pads.now)

            # Control of CHK-SPI-CTRL-OE: no pad enable before OUTPUT_EN is set.
            dut = cocotb.top
            await RisingEdge(dut.clk_i)
            await ReadOnly()
            self.pre_oe = (_val(dut.spi_cs_oe_o), _val(dut.spi_sck_oe_o))
            await RisingEdge(dut.clk_i)
            if self.pre_oe != EXP_PRE_ENABLE_OE:
                raise AssertionError(
                    f"CTRL-MISSING CHK-SPI-CTRL-OE seed={self.seed} before OUTPUT_EN: "
                    f"cs_oe={self.pre_oe[0]} sck_oe={self.pre_oe[1]} "
                    f"expect={EXP_PRE_ENABLE_OE}"
                )
            ctrl = (CTRL_RESET & ~CTRL_SW_RST) | CTRL_SPIEN | CTRL_OUTPUT_EN
            await self.ops.wr(CONTROL, ctrl)
            await self.ops.wr(CSID, 0)
            err0 = field_compare(await self._err_status(), 0, ERR_STATUS_MASK)
            if not err0.ok:
                raise AssertionError(
                    f"CTL-SPI-BRINGUP FAIL seed={self.seed} error_status {err0.fields()}"
                )
            self.logger.info(
                "CTL-SPI-BRINGUP LOG seed=%d control=0x%08x error_status=0x%02x fcov=%d",
                self.seed,
                ctrl,
                err0.got & err0.mask,
                int(fcov_present()),
            )
            for c in cells:
                await self._mode_cell(c)
            await self._fullcyc_leg()
            await self.pads.stop()
            await self.wire.finish(
                self.logger, seed=self.seed, modes=[(c.cpol, c.cpha) for c in cells]
            )
        finally:
            close_graded_window()
            if getattr(self, "rsp", None) is not None:
                await self.rsp.stop()

        missing = [x for x in self.required_evidence if x not in self.ran]
        if missing:
            raise AssertionError(f"CTRL-MISSING seed={self.seed} checks not run: {missing}")
        self.result_pass(TEST, self.seed, len(self.ran))
