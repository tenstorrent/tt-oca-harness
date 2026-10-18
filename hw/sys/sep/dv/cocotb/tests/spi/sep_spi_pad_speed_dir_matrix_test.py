# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The SPI host COMMAND speed and direction cells give the stated sck count, lane data, lane enables and errors.

Contract (``vendor/lowRISC/opentitan/overlay/regs/spi_controller/regs/gen/adoc/spi_controller.adoc``,
COMMAND and ERROR_STATUS; ``hw/sys/sep/doc/spi.adoc``, Features;
``doc/integrator/src/smu-sep.adoc``, "SEP SPI Host Pin Assignment"; OpenTitan
SPI_HOST theory of operation,
``vendor/lowRISC/opentitan/upstream/hw/ip/spi_host/doc/theory_of_operation.md``,
short name ``ToO`` below):

* SPEED 0, 1 and 2 move LEN+1 bytes on 1, 2 and 4 data lines at one bit per
  line per sck cycle, so a data segment takes (LEN+1)*8/lanes sck cycles. A
  dummy segment (DIRECTION 0) takes LEN+1 sck cycles and moves no data.
* CSAAT=1 keeps chip select low into the next segment. Each segment of a
  chain has its own speed, direction and length.
* SPEED 3, and DIRECTION 3 at SPEED 1 or 2, set ERROR_STATUS.CMDINVAL.
* Lane n is ``sd[n]``. An x1 segment sends on ``sd[0]`` and receives on
  ``sd[1]`` ("the host transmits data on `SD[0]`, and always receives data on
  `SD[1]`", ``ToO:138``); an x2 or x4 segment moves one pair or nibble per sck
  cycle with its least significant bit on ``sd[0]`` ("the least significant
  bit in any instantaneous pair or nibble is transmitted or received on
  `SD[0]`", ``ToO:422``). The most significant bits of a byte go first
  ("*within a given byte*, the most significant bits are transmitted and
  received first.", ``ToO:421``). The first byte on the wire is TXDATA[7:0]
  and the first byte received lands in RXDATA[7:0] (ByteOrder 1: "By default
  (`ByteOrder = 1`, for Little-Endian processors), the LSB of `TXDATA` (i.e
  bits 7 though 0) is transmitted first", ``ToO:416``; "the first byte
  received is always packed into either the most- or least-significant byte
  read from the `RXDATA` memory window", ``ToO:539``; STATUS.BYTEORDER is
  "The value of the ByteOrder parameter",
  ``vendor/lowRISC/opentitan/overlay/regs/spi_controller/regs/spi_controller.rdl:124``;
  the ``ByteOrder`` parameter default is 1,
  ``vendor/lowRISC/opentitan/upstream/hw/ip/spi_host/data/spi_host.hjson:76-84``,
  and the SEP SPI host is the unmodified OpenTitan IP,
  ``doc/trm/src/revision.adoc:191``).
  At the end of a TX segment the unused bytes of its last TXDATA word are
  dropped ("unused bytes from the latest TX FIFO word are simply ignored at
  the end of a segment.", ``ToO:484``), and each RX segment starts
  word-aligned in RXDATA ("The first byte for each read segment is always
  word-aligned in the RXFIFO", ``ToO:736``).
* Data lane output enables per segment, on the lanes the segment uses: x1 TX
  and x1 bidirectional drive lane 0 and not lane 1 (lanes 1:0 = 0b01); x2 TX
  drives lanes 1:0; x4 TX drives lanes 3:0; x2 RX drives neither of lanes 1:0
  and x4 RX no lane (a lane the host receives on is not driven). No source
  states lanes 3:2 at x1 or x2; the leaf logs them as OBS-SPI-OE-UNUSED. The
  spec states no pattern for an x1 RX-only or a dummy segment; the leaf logs
  them as OBS-SPI-OE-X1RX and OBS-SPI-OE-DUMMY.

The leaf walks the 10 legal SPEED x DIRECTION cells as single segments, a dummy
segment between FIFO reads, CSAAT chains that change speed or direction, the
seed-drawn long dummy segment and the 6 illegal cells. A test-side sampler
(``env/sep_spi_pad_sampler.py``) reads ``spi_sck_o`` and ``spi_cs_n_o`` on each
core clock and counts one sck cycle at each leading edge while chip select is
low. The lane responder (``env/sep_spi_lane_responder.py``) drives the seeded
RX bytes of each graded frame on ``spi_sd_i[3:0]``, which the DUT receives
with ``+sep_spi_four_lane``. ``SepSpiWireMonitor``
(``env/sep_spi_wire_monitor.py``) records the lanes the DUT drives, their
output enables and the lanes the DUT receives at each sample edge; the
scoreboard (``env/sep_spi_scoreboard.py``) decodes them.

Checks:

* CHK-SPI-CELL: per legal cell, the sck count of the one chip-select-low window
  equals the stated count, and ERROR_STATUS reads 0 after the segment.
* CHK-SPI-RXCNT: for DIRECTION 1 and 3, the RXDATA words read (in the segment
  plus drained after it) equal ceil((LEN+1)/4), the words drained equal RXQD
  at the segment end, and the words read in the segment plus RXQD equal the
  same count. Source for a LEN+1 that is not a multiple of 4: "For RX (or
  Bidirectional) segments, if the last few bytes received do not fill an
  entire DATA word, the partial word will be zero-padded and inserted into the
  RX FIFO once the segment is completed."
  (``vendor/lowRISC/opentitan/upstream/hw/ip/spi_host/doc/theory_of_operation.md:485``).
  The pad byte position
  depends on ByteOrder and is not graded here. Control: every Tx-only and
  dummy cell starts with RXEMPTY=1 and leaves RXQD at 0.
* CHK-SPI-DUMMY: a dummy segment leaves TXQD and RXQD unchanged and runs LEN+1
  sck cycles. Control: both
  are at least 1 before the segment.
* CHK-SPI-CHAIN: a CSAAT chain of 2 to 6 segments shows one chip-select-low
  window, its sck count is the sum of the segment counts, and chip select is
  high at the end. Control: two back-to-back CSAAT=0 dummy commands show a
  chip-select rise between them. Each seed runs a chain at one width, a chain
  whose data segments change width, and a lane chain: an x1 command byte, an
  x2 or x4 address of 3 bytes, a dummy segment and x4 data in one
  chip-select window.
* CHK-SPI-SB-FRAME (``SepSpiScoreboard.expect_frame``): each graded frame
  (every legal cell, the dummy segment of the FIFO leg, every chain) has
  exactly the sample edges of its segments; the wire decode of each TX
  segment equals its seeded bytes, the wire decode of each RX segment equals
  the seeded bytes given to the responder, and the bytes read from RXDATA
  equal them. A bidirectional segment is graded as TX and as RX on the same
  sample edges.
* CHK-SPI-LANE-DATA: one line per data segment and direction, with its width
  and byte count, after the frame passed CHK-SPI-SB-FRAME: the TX line
  compares the monitor decode and the RX line the RXDATA bytes with the seeded
  bytes. Control: x1, x2 and x4 are each graded in both directions.
* CHK-SPI-OE-SEG: in each graded frame, the data lane output enables at every
  sample edge of a segment equal the pattern of that segment. Control: every
  pattern row (x1 TX, x1 bidirectional, x2 TX, x2 RX, x4 TX, x4 RX) is
  graded. x1 RX-only and dummy segments are logged as OBS lines.
* CHK-SPI-ILLEGAL: each of the 5 graded illegal cells sets ERROR_STATUS to
  CMDINVAL only, and a legal control command after the SPI clean state reads
  ERROR_STATUS 0. SPEED 3 with DIRECTION 2 runs as the control
  ``CTL-SPI-ILLEGAL LOG`` and prints no CHK line. The illegal COMMAND is written
  with the core held (CONTROL.SPIEN=0), so the reserved cell never runs on the
  pads, and the SW_RST of the SPI clean state empties the command queue.
* CHK-SPI-LONGDUMMY: on a seed that draws it (1 in 4), LEN 0xFFFFF at CLKDIV 0
  gives 1,048,576 sck cycles in exactly one chip-select-low window; every
  window after the command counts. The wire monitor and the responder are
  stopped for this leg, so it runs at the cost of the sampler alone. Other
  seeds do not run it.
* CHK-SPI-WIRE: the wire checks of ``SepSpiWireMonitor`` over the leaf.

FCOV: after a frame passes, the leaf writes one ``spi_lane_fcov`` data record
per width and direction it graded, and one chain record per chain (0 one
width, 1 the data width changes).

Graded window: owner code of this test around each graded segment; closed for
bring-up, the SPI clean state, the SW_RST helper and every control leg.

Run mode: ``no_cpu``, ``lsu_stub_all_live``, ``+skip_fuse_sense``,
``+sep_spi_four_lane``, no ``rst_ni`` pulse. Every random value is a pure
function of the seed (``SepSeededRng``).
"""

from __future__ import annotations

from collections import deque
from collections.abc import Sequence
from dataclasses import dataclass

import cocotb
import pyuvm
from env.sep_fcov_gate import close_graded_window, fcov_present, open_graded_window
from env.sep_field_compare import field_compare
from env.sep_seeded_rng import SepSeededRng
from env.sep_spi_lane_responder import (
    SepSpiLaneResponder,
    pack_tx_words,
    spi_lane_fcov,
    unpack_rx_words,
)
from env.sep_spi_pad_sampler import SepSpiPadSampler
from env.sep_spi_scoreboard import SepSpiScoreboard
from env.sep_spi_wire_monitor import SepSpiWireMonitor
from ocah_spi_vip import lanes_to_bytes
from sep_base_test import sep_base_test
from seq_lib.sep_spi_host_csr_seq import (
    COMMAND,
    CONTROL,
    CSID,
    CTRL_OUTPUT_EN,
    CTRL_RESET,
    CTRL_SPIEN,
    CTRL_SW_RST,
    ERR_CMDINVAL,
    ERR_STATUS_MASK,
    ERROR_STATUS,
    INTR_STATE,
    INTR_STATE_MASK,
    RXDATA,
    TXDATA,
)
from seq_lib.sep_spi_host_ops import (
    DIR_BIDIR,
    DIR_DUMMY,
    DIR_RX,
    DIR_TX,
    SepSpiHostOps,
    command_word,
    configopts_word,
)

TEST = "sep_spi_pad_speed_dir_matrix_test"

LANES = {0: 1, 1: 2, 2: 4}
LEGAL = [(s, d) for s in (0, 1, 2) for d in (0, 1, 2, 3) if not (d == DIR_BIDIR and s != 0)]
ILLEGAL = [(3, 0), (3, 1), (3, 2), (3, 3), (1, 3), (2, 3)]
CONTROL_ILLEGAL = (3, 2)

LEN_CLASSES = ("len0", "sub_word", "word_multiple", "non_multiple")
LEN_WEIGHTS = (3, 1, 3, 2)
CLKDIV_CLASSES = {"zero": (0, 0), "small": (1, 3), "mid": (4, 7)}

LONG_DUMMY_LEN = 0xFFFFF
LONG_DUMMY_CYCLES = LONG_DUMMY_LEN + 1

# Output-enable pattern rows the leaf must grade. The x1 RX-only and dummy rows
# have no stated pattern; the leaf logs them as OBS-SPI-OE-X1RX and OBS-SPI-OE-DUMMY.
OE_ROWS = ("x1_tx", "x1_bidir", "x2_tx", "x2_rx", "x4_tx", "x4_rx")

# Bounds. Each expiry fails the check that the wait feeds.
SERVICE_READS = 50_000
SEG_BOUND_CLKS = 400_000
LONG_BOUND_CLKS = 2 * LONG_DUMMY_CYCLES + 100_000
ERR_POLLS = 200

# Scratch mutation hooks: each is 0 in the leaf; a scratch edit sets one to 1.
MUT_X4_RX_LANE_SWAP = 0  # responder drives the x4 RX cell with lanes 2 and 3 swapped
MUT_X2_TX_DROP_BYTE = 0  # golden of the x2 TX cell lacks its last byte
MUT_X4_TX_OE = 0  # graded OE pattern of an x4 TX segment is 0b0011
MUT_X1_RX_BIT_FLIP = 0  # responder drives the x1 RX cell with bit 0 of byte 0 inverted
MUT_LONG_DUMMY_EXTRA_WIN = 0  # long dummy runs on every seed and expects 2 windows
MUT_CHAIN_X4_DROP_BYTE = 0  # golden of the x4 data segment of the lane chain lacks its last byte


def sck_expect(speed: int, direction: int, len_field: int) -> int:
    """The stated sck cycle count of one segment."""
    if direction == DIR_DUMMY:
        return len_field + 1
    return (len_field + 1) * 8 // LANES[speed]


def oe_expect(speed: int, direction: int) -> tuple[int, int] | None:
    """The stated (pattern, graded lanes) of one segment's data lane enables, or None.

    Only the lanes the segment uses are graded: lanes 1:0 at x1 and x2, all
    four at x4. No source states lanes 3:2 at x1 or x2; the leaf logs them.
    """
    if direction == DIR_DUMMY:
        return None
    if speed == 0:
        return None if direction == DIR_RX else (0b0001, 0b0011)
    if direction == DIR_RX:
        return (0b0000, 0b0011 if speed == 1 else 0b1111)
    if speed == 2:
        return (0b0011 if MUT_X4_TX_OE else 0b1111, 0b1111)
    return (0b0011, 0b0011)


def _swap_lanes_23(byte: int) -> int:
    """``byte`` with lanes 2 and 3 of each x4 nibble swapped."""
    return (byte & 0x33) | ((byte & 0x44) << 1) | ((byte & 0x88) >> 1)


def _decode(beats: Sequence[tuple], field_index: int, lanes: int, shift: int) -> bytes:
    """Bytes of one beat field on ``lanes`` lanes, lane ``shift`` least significant."""
    values = [((beat[field_index] or 0) >> shift) for beat in beats]
    return bytes(lanes_to_bytes(values, lanes)[0])


def _fmt_oe(values: set) -> str:
    return "/".join(
        "x" if v is None else f"{v:04b}"
        for v in sorted(values, key=lambda v: -1 if v is None else v)
    )


@dataclass
class Seg:
    speed: int
    direction: int
    len_field: int
    csaat: int = 0
    len_class: str = ""
    tx_bytes: bytes = b""
    rx_bytes: bytes = b""

    @property
    def cmd(self) -> int:
        return int(
            command_word(
                self.len_field, speed=self.speed, direction=self.direction, csaat=self.csaat
            )
        )

    @property
    def is_rx(self) -> bool:
        return self.direction in (DIR_RX, DIR_BIDIR)

    @property
    def is_tx(self) -> bool:
        return self.direction in (DIR_TX, DIR_BIDIR)

    @property
    def nbytes(self) -> int:
        return self.len_field + 1

    @property
    def lanes(self) -> int:
        return LANES[self.speed]

    @property
    def clocks(self) -> int:
        return sck_expect(self.speed, self.direction, self.len_field)

    @property
    def expect(self) -> int:
        return self.clocks

    @property
    def tx_words(self) -> list[int]:
        """TXDATA words of this segment alone (ByteOrder 1)."""
        return pack_tx_words(self.tx_bytes) if self.is_tx else []

    @property
    def oe_row(self) -> str:
        if self.direction == DIR_DUMMY:
            return "dummy"
        kind = {DIR_TX: "tx", DIR_RX: "rx", DIR_BIDIR: "bidir"}[self.direction]
        return f"x{self.lanes}_{kind}"

    def fmt(self) -> str:
        return f"s{self.speed}d{self.direction}L{self.len_field}c{self.csaat}"


@pyuvm.test()
class sep_spi_pad_speed_dir_matrix_test(sep_base_test):
    """Every legal cell gives the stated sck count, lane data and lane enables; every illegal cell sets CMDINVAL."""

    # ---- plan -------------------------------------------------------------
    def _draw_len(self, rng: SepSeededRng, cls: str, dummy: bool) -> int:
        if cls == "len0":
            return 0
        if cls == "sub_word":
            return 1
        if cls == "word_multiple":
            return int(rng.choice((3, 15, 31, 0x3FF) if dummy else (3, 15, 31)))
        pick = rng.randrange(4)
        if pick < 3:
            return (4, 16, 32)[pick]
        return int(rng.choice([v for v in range(2, 64) if (v + 1) % 4]))

    def _draw_class(self, rng: SepSeededRng) -> str:
        roll = rng.randrange(sum(LEN_WEIGHTS))
        for cls, w in zip(LEN_CLASSES, LEN_WEIGHTS):
            if roll < w:
                return cls
            roll -= w
        raise AssertionError("unreachable")

    def _draw_clkdiv(self, rng: SepSeededRng) -> tuple[str, int]:
        cls = rng.choice(tuple(CLKDIV_CLASSES))
        lo, hi = CLKDIV_CLASSES[cls]
        return cls, rng.randrange(lo, hi + 1)

    @staticmethod
    def _fill_data(rng: SepSeededRng, seg: Seg) -> None:
        """Seeded TX bytes and RX bytes of a data segment."""
        if seg.is_tx:
            seg.tx_bytes = bytes(rng.getrandbits(8) for _ in range(seg.nbytes))
        if seg.is_rx:
            seg.rx_bytes = bytes(rng.getrandbits(8) for _ in range(seg.nbytes))

    def _draw_chain(
        self, rng: SepSeededRng, cells: list[tuple[int, int]], pool: list[tuple[int, int]]
    ) -> list[Seg]:
        if all(c == cells[0] for c in cells):
            cells[-1] = rng.choice([c for c in pool if c != cells[0]])
        segs = []
        for i, (speed, direction) in enumerate(cells):
            if direction == DIR_DUMMY:
                cls = self._draw_class(rng)
                ln = self._draw_len(rng, cls, True)
            else:
                cls = "word_multiple"
                ln = 4 * rng.randrange(1, 17) - 1
            seg = Seg(speed, direction, ln, int(i < len(cells) - 1), cls)
            self._fill_data(rng, seg)
            segs.append(seg)
        return segs

    def _plan(self, seed: int) -> None:
        rng = SepSeededRng(seed)
        order = LEGAL + ILLEGAL
        rng.shuffle(order)
        self.legal_order = [c for c in order if c in LEGAL]
        self.illegal_order = [c for c in order if c in ILLEGAL]

        classes = {c: self._draw_class(rng) for c in self.legal_order}
        # DIRECTION 3 is legal only at SPEED 0, so that one cell is word_multiple.
        classes[(0, DIR_BIDIR)] = "word_multiple"
        rx1 = [c for c in self.legal_order if c[1] == DIR_RX]
        if not any(classes[c] == "word_multiple" for c in rx1):
            classes[rng.choice(rx1)] = "word_multiple"

        self.cells: list[tuple[Seg, str, int]] = []
        for speed, direction in self.legal_order:
            cls = classes[(speed, direction)]
            seg = Seg(speed, direction, 0, 0, cls)
            seg.len_field = self._draw_len(rng, cls, direction == DIR_DUMMY)
            ck_cls, clkdiv = self._draw_clkdiv(rng)
            self._fill_data(rng, seg)
            if MUT_X4_RX_LANE_SWAP and (speed, direction) == (2, DIR_RX):
                # Byte 0 has lane 2 != lane 3, so the swap changes it.
                seg.rx_bytes = bytes([(seg.rx_bytes[0] & ~0x0C) | 0x04]) + seg.rx_bytes[1:]
            self.cells.append((seg, ck_cls, clkdiv))

        dcls = self._draw_class(rng)
        self.dummy_seg = Seg(rng.randrange(3), DIR_DUMMY, 0, 0, dcls)
        self.dummy_seg.len_field = self._draw_len(rng, dcls, True)
        self.fifo_tx_word = rng.getrandbits(32)

        self.chain_ctl_lens = (rng.randrange(16), rng.randrange(16))
        # (clkdiv, data width changes, golden scope, segments)
        self.chains: list[tuple[int, int, str, list[Seg]]] = []
        same_speed = rng.randrange(3)
        for width_changes in (0, 1):
            _, clkdiv = self._draw_clkdiv(rng)
            nseg = rng.randrange(2, 7)
            pool = LEGAL if width_changes else [c for c in LEGAL if c[0] == same_speed]
            cells = [rng.choice(pool) for _ in range(nseg)]
            if width_changes and len({s for s, d in cells if d != DIR_DUMMY}) < 2:
                i, j = rng.sample(range(nseg), 2)
                cells[i] = (0, rng.choice((DIR_RX, DIR_TX, DIR_BIDIR)))
                cells[j] = (rng.choice((1, 2)), rng.choice((DIR_RX, DIR_TX)))
            self.chains.append((clkdiv, width_changes, "chain", self._draw_chain(rng, cells, pool)))

        # Lane chain: x1 command byte, x2 or x4 address, dummy, x4 data.
        _, clkdiv = self._draw_clkdiv(rng)
        lane = [
            Seg(0, DIR_TX, 0, 1, "lane"),
            Seg(rng.choice((1, 2)), DIR_TX, 2, 1, "lane"),
            Seg(rng.randrange(3), DIR_DUMMY, rng.randrange(1, 8), 1, "lane"),
            Seg(2, rng.choice((DIR_RX, DIR_TX)), 4 * rng.randrange(1, 9) - 1, 0, "lane"),
        ]
        for seg in lane:
            self._fill_data(rng, seg)
        self.chains.append((clkdiv, 1, "lane", lane))

        self.long_dummy = int(rng.randrange(4) == 0 or bool(MUT_LONG_DUMMY_EXTRA_WIN))
        self.illegal_lens = {c: rng.randrange(64) for c in self.illegal_order}
        self.illegal_ctl_lens = {c: rng.randrange(16) for c in self.illegal_order}

        cell_txt = " ".join(
            f"s{s.speed}d{s.direction}:{s.len_class}/L{s.len_field}/{ck}{cd}"
            for s, ck, cd in self.cells
        )
        chain_txt = " ".join(
            f"[{where} clkdiv={cd} width_changes={wc} " + ",".join(s.fmt() for s in segs) + "]"
            for cd, wc, where, segs in self.chains
        )
        csaat_dirs = [[s.direction for s in segs if s.csaat] for _, _, _, segs in self.chains]
        self.logger.info(
            "PLAN seed=%d cells=%s illegal=%s dummy_leg=s%dd0:%s/L%d chains=%s "
            "chain_csaat1_dirs=%s long_dummy=%d",
            seed,
            cell_txt,
            ",".join(f"s{s}d{d}" for s, d in self.illegal_order),
            self.dummy_seg.speed,
            self.dummy_seg.len_class,
            self.dummy_seg.len_field,
            chain_txt,
            csaat_dirs,
            self.long_dummy,
        )
        self.logger.info(
            "DRAW seed=%d chain_ctl_lens=%s illegal_lens=%s illegal_ctl_lens=%s "
            "fifo_tx_word=0x%08x",
            seed,
            self.chain_ctl_lens,
            [self.illegal_lens[c] for c in self.illegal_order],
            [self.illegal_ctl_lens[c] for c in self.illegal_order],
            self.fifo_tx_word,
        )

    # ---- helpers ----------------------------------------------------------
    def _graded(self) -> None:
        open_graded_window(TEST, self.logger)

    def _ungraded(self) -> None:
        close_graded_window(self.logger)

    async def _sw_rst(self) -> None:
        self._ungraded()
        await self.ops.sw_rst()

    async def _clean_state(self) -> None:
        self._ungraded()
        await self.ops.clean_state()

    async def _err_status(self) -> int:
        return int(await self.ops.rd(ERROR_STATUS)) & 0xFFFF_FFFF

    async def _configopts(self, clkdiv: int) -> None:
        assert not self.pads.cs_low(), "CONFIGOPTS write with chip select low"
        await self.ops.write_configopts(configopts_word(clkdiv=clkdiv))

    @staticmethod
    def _drive_bytes(seg: Seg, where: str) -> bytes:
        """RX bytes the responder drives for ``seg``."""
        data = seg.rx_bytes
        if where == "cell" and MUT_X4_RX_LANE_SWAP and (seg.speed, seg.direction) == (2, DIR_RX):
            data = bytes(_swap_lanes_23(b) for b in data)
        if where == "cell" and MUT_X1_RX_BIT_FLIP and (seg.speed, seg.direction) == (0, DIR_RX):
            data = bytes([data[0] ^ 0x01]) + data[1:]
        return data

    @staticmethod
    def _golden(seg: Seg, where: str, kind: str, last: bool) -> bytes:
        """Seeded bytes the frame grade expects for ``seg`` in direction ``kind``."""
        data = seg.tx_bytes if kind == "tx" else seg.rx_bytes
        if where == "cell" and MUT_X2_TX_DROP_BYTE and kind == "tx" and seg.speed == 1:
            data = data[:-1]
        if where == "lane" and MUT_CHAIN_X4_DROP_BYTE and last:
            data = data[:-1]
        return data

    def _load(self, segs: list[Seg], where: str) -> None:
        """Give the responder the layout and the RX bytes of the next frame."""
        layout: list[tuple[str, int, int]] = []
        for seg in segs:
            if seg.direction == DIR_DUMMY:
                layout.append(("dummy", seg.lanes, seg.nbytes))
                continue
            if seg.is_rx:
                self.rsp.queue_rx(self._drive_bytes(seg, where), seg.lanes)
            kind = {DIR_TX: "tx", DIR_RX: "rx", DIR_BIDIR: "bidir"}[seg.direction]
            layout.append((kind, seg.lanes, seg.nbytes))
        self.rsp.expect_segments(layout)

    async def _grade_frame(
        self,
        sb: SepSpiScoreboard,
        mark: int,
        segs: list[Seg],
        words: list[int],
        *,
        where: str,
        label: str,
    ) -> None:
        """Grade the frame at ``mark``: data (scoreboard), lane data lines and lane enables."""
        seed = self.seed
        # RX bytes the DUT delivered, per segment, each RX segment from its
        # own word-aligned RXDATA words.
        delivered: list[bytes] = []
        pos = 0
        for seg in segs:
            if seg.is_rx:
                count = (seg.nbytes + 3) // 4
                delivered.append(unpack_rx_words(words[pos : pos + count], seg.nbytes))
                pos += count
            else:
                delivered.append(b"")
        if pos != len(words):
            raise AssertionError(
                f"CHK-SPI-SB-FRAME FAIL seed={seed} {label} rx_words={len(words)} expect={pos}"
            )

        last = len(segs) - 1
        has_bidir = any(s.direction == DIR_BIDIR for s in segs)
        for bidir_as in ("tx", "rx") if has_bidir else ("tx",):
            view: list[tuple[int, str, bytes | int]] = []
            dlv = bytearray()
            for i, (seg, got) in enumerate(zip(segs, delivered)):
                if seg.direction == DIR_DUMMY:
                    view.append((seg.lanes, "dummy", seg.clocks))
                    continue
                kind = {DIR_TX: "tx", DIR_RX: "rx"}.get(seg.direction, bidir_as)
                view.append((seg.lanes, kind, self._golden(seg, where, kind, i == last)))
                if kind == "rx":
                    dlv += got
            sb.expect_frame(
                mark,
                view,
                delivered=bytes(dlv),
                label=f"{label} bidir_as={bidir_as}" if has_bidir else label,
            )
        sb.finish()
        self.ran.add("CHK-SPI-SB-FRAME")

        beats = tuple(self.wire.monitor.get_transactions()[mark]["beats"])
        pos = 0
        oe_rows: list[str] = []
        oe_ok = True
        graded: set[tuple[int, bool]] = set()
        for i, (seg, got) in enumerate(zip(segs, delivered)):
            seg_beats = beats[pos : pos + seg.clocks]
            pos += seg.clocks
            exp = oe_expect(seg.speed, seg.direction)
            seen = {b[1] for b in seg_beats}
            if exp is None:
                obs = "OBS-SPI-OE-DUMMY" if seg.direction == DIR_DUMMY else "OBS-SPI-OE-X1RX"
                self.logger.info("%s seed=%s %s seg=%d oe=%s", obs, seed, label, i, _fmt_oe(seen))
                oe_rows.append(f"{i}:{seg.oe_row}:{_fmt_oe(seen)}/obs")
            else:
                exp_oe, used = exp
                oe_rows.append(f"{i}:{seg.oe_row}:{_fmt_oe(seen)}/exp{exp_oe:04b}/lanes{used:04b}")
                oe_ok = oe_ok and {v & used for v in seen} == {exp_oe}
                if used != 0b1111:
                    self.logger.info(
                        "OBS-SPI-OE-UNUSED seed=%s %s seg=%d row=%s lanes_3_2=%s",
                        seed,
                        label,
                        i,
                        seg.oe_row,
                        ",".join(sorted({f"{(v >> 2) & 3:02b}" for v in seen})),
                    )
            if seg.direction == DIR_DUMMY:
                continue
            if seg.is_tx:
                gold = self._golden(seg, where, "tx", i == last)
                wire = _decode(seg_beats, 0, seg.lanes, 0)
                line = (
                    f"seed={seed} {label} seg={i} dir=tx width=x{seg.lanes} bytes={len(wire)} "
                    f"expect_bytes={len(gold)} wire={wire.hex()}"
                )
                if wire != gold:
                    raise AssertionError(f"CHK-SPI-LANE-DATA FAIL {line} expected={gold.hex()}")
                self.logger.info("CHK-SPI-LANE-DATA PASS %s", line)
                graded.add((seg.lanes, False))
            if seg.is_rx:
                gold = self._golden(seg, where, "rx", i == last)
                wire = _decode(seg_beats, 2, seg.lanes, 1 if seg.lanes == 1 else 0)
                line = (
                    f"seed={seed} {label} seg={i} dir=rx width=x{seg.lanes} bytes={len(got)} "
                    f"expect_bytes={len(gold)} rxdata={got.hex()} wire={wire.hex()}"
                )
                if got != gold or wire != gold:
                    raise AssertionError(f"CHK-SPI-LANE-DATA FAIL {line} expected={gold.hex()}")
                self.logger.info("CHK-SPI-LANE-DATA PASS %s", line)
                graded.add((seg.lanes, True))
        oe_line = f"seed={seed} {label} beats={len(beats)} segments={','.join(oe_rows)}"
        if not oe_ok or pos != len(beats):
            raise AssertionError(f"CHK-SPI-OE-SEG FAIL {oe_line}")
        self.logger.info("CHK-SPI-OE-SEG PASS %s", oe_line)
        self.oe_graded.update(seg.oe_row for seg in segs)
        if graded:
            self.ran.add("CHK-SPI-LANE-DATA")
        self.ran.add("CHK-SPI-OE-SEG")
        self.lane_graded |= graded
        for lanes, rx in sorted(graded):
            await spi_lane_fcov(TEST, "data", lanes=lanes, rx=rx)

    async def _run_segments(self, segs: list[Seg], *, tag: str) -> dict:
        """Write each COMMAND after a READY=1 read, service TX and RX, wait until done.

        TX words of a segment go out after its COMMAND, each after a STATUS read
        with TXFULL=0. One RXDATA word is read after each STATUS read with
        RXFULL=1. Done: every chip-select-low window since the first COMMAND is
        closed, and a STATUS read taken after the last chip-select rise shows
        ACTIVE=0 and CMDQD=0.
        """
        ops, pads = self.ops, self.pads
        mark = pads.mark()
        pending: deque[int] = deque()
        idx = 0
        rx_words: list[int] = []
        pre = None
        any_rx = any(s.is_rx for s in segs)
        for _ in range(SERVICE_READS):
            st = await ops.read_status()
            if idx < len(segs) and st.ready:
                if idx == 0:
                    pre = st
                await ops.wr(COMMAND, segs[idx].cmd)
                pending.extend(segs[idx].tx_words)
                idx += 1
                continue
            if pending and not st.txfull:
                await ops.wr(TXDATA, pending.popleft())
                continue
            if any_rx and st.rxfull:
                rx_words.append(int(await ops.rd(RXDATA)))
                continue
            if idx < len(segs) or pending:
                continue
            wins = pads.windows_since(mark, complete_only=False)
            if not wins:
                if not any_rx:
                    await pads.wait_windows(1, mark, SEG_BOUND_CLKS)
                continue
            if not wins[-1].complete:
                if not any_rx:
                    n_done = sum(1 for w in wins if w.complete)
                    await pads.wait_windows(n_done + 1, mark, SEG_BOUND_CLKS)
                continue
            if st.clk0 is not None and st.clk0 >= wins[-1].end and not st.active and not st.cmdqd:
                return {
                    "wins": wins,
                    "rx_read": len(rx_words),
                    "rx_words": rx_words,
                    "pre": pre,
                    "done": st,
                }
        raise AssertionError(
            f"{tag} FAIL: segment not done after {SERVICE_READS} STATUS reads "
            f"(commands {idx}/{len(segs)}, tx pending {len(pending)}, "
            f"windows {len(pads.windows_since(mark, complete_only=False))})"
        )

    def _scoreboard(self) -> SepSpiScoreboard:
        return SepSpiScoreboard(self.wire, None, self.logger, seed=self.seed)

    # ---- legs -------------------------------------------------------------
    async def _single_cells(self) -> None:
        seed = self.seed
        rx_rows = []
        nonrx_rxqd: list[int] = []
        for seg, ck_cls, clkdiv in self.cells:
            self._ungraded()
            await self._configopts(clkdiv)
            sb = self._scoreboard()
            mark = sb.frame_mark()
            self._load([seg], "cell")
            self._graded()
            res = await self._run_segments([seg], tag="CHK-SPI-CELL")
            wins = res["wins"]
            pre = res["pre"]
            if seg.direction in (DIR_DUMMY, DIR_TX) and not pre.rxempty:
                raise AssertionError(
                    f"CTRL-MISSING seed={seed} CHK-SPI-RXCNT: RXEMPTY=0 before the "
                    f"s{seg.speed}d{seg.direction} COMMAND ({pre.fmt()})"
                )
            st = await self.ops.read_status()
            rxqd = st.rxqd
            drained_words = await self.ops.drain_rx()
            drained = len(drained_words)
            got = sum(w.leading_edges for w in wins)
            exp = seg.expect
            err = field_compare(await self._err_status(), 0, ERR_STATUS_MASK)
            line = (
                f"seed={seed} speed={seg.speed} dir={seg.direction} len={seg.len_field} "
                f"csaat={seg.csaat} clkdiv={clkdiv} sck_cycles={got} expect={exp} "
                f"err_status=0x{err.got & err.mask:02x} err_mask=0x{err.mask:02x} "
                f"windows={len(wins)} len_class={seg.len_class} clkdiv_class={ck_cls}"
            )
            if len(wins) != 1 or got != exp or not err.ok:
                raise AssertionError(f"CHK-SPI-CELL FAIL {line}")
            self.logger.info("CHK-SPI-CELL PASS %s", line)

            if seg.is_rx:
                rx_rows.append((seg, res["rx_read"], rxqd, drained))
            else:
                nonrx_rxqd.append(rxqd)
                if rxqd or drained:
                    raise AssertionError(
                        f"CHK-SPI-RXCNT FAIL seed={seed} control: s{seg.speed}d{seg.direction} "
                        f"started with RXEMPTY=1 and left rxqd={rxqd} drained={drained}"
                    )
            await self._grade_frame(
                sb,
                mark,
                [seg],
                [int(w) for w in res["rx_words"] + drained_words],
                where="cell",
                label=f"cell=s{seg.speed}d{seg.direction}",
            )
            await self._sw_rst()

        dirs = {r[0].direction for r in rx_rows}
        if DIR_RX not in dirs or DIR_BIDIR not in dirs or not nonrx_rxqd:
            raise AssertionError(
                f"CTRL-MISSING seed={seed} CHK-SPI-RXCNT: graded Rx directions {sorted(dirs)}, "
                f"non-Rx controls {len(nonrx_rxqd)}"
            )
        for seg, in_seg, rxqd, drained in rx_rows:
            nbytes = seg.len_field + 1
            words = in_seg + drained
            row = (
                f"seed={seed} speed={seg.speed} dir={seg.direction} bytes={nbytes} "
                f"words={words} rxqd={rxqd} in_segment={in_seg} drained={drained}"
            )
            exp = (nbytes + 3) // 4
            line = (
                f"{row} expect={exp} partial_word={int(bool(nbytes % 4))} "
                f"control_nonrx_rxqd={max(nonrx_rxqd)}"
            )
            if drained != rxqd or words != exp or in_seg + rxqd != exp:
                raise AssertionError(f"CHK-SPI-RXCNT FAIL {line}")
            self.logger.info("CHK-SPI-RXCNT PASS %s", line)
        self.ran.update(("CHK-SPI-CELL", "CHK-SPI-RXCNT"))

    async def _dummy_fifo_leg(self) -> None:
        seed = self.seed
        await self._sw_rst()
        await self._configopts(0)
        await self.ops.push_tx(self.fifo_tx_word)
        rx = Seg(0, DIR_RX, 3)
        mark = self.pads.mark()
        await self.ops.issue_command(rx.cmd)
        await self.ops.wait_segment_done(self.pads, mark, bound_clks=SEG_BOUND_CLKS)
        before = await self.ops.read_status()
        if before.txqd < 1 or before.rxqd < 1:
            raise AssertionError(
                f"CTRL-MISSING seed={seed} CHK-SPI-DUMMY: txqd={before.txqd} "
                f"rxqd={before.rxqd} before the dummy segment"
            )
        self.logger.info(
            "CTL-SPI-DUMMY LOG seed=%d txqd_before=%d rxqd_before=%d",
            seed,
            before.txqd,
            before.rxqd,
        )
        seg = self.dummy_seg
        sb = self._scoreboard()
        frame = sb.frame_mark()
        self._load([seg], "dummy")
        self._graded()
        mark = self.pads.mark()
        await self.ops.issue_command(seg.cmd)
        wins = await self.ops.wait_segment_done(self.pads, mark, bound_clks=SEG_BOUND_CLKS)
        after = await self.ops.read_status()
        self._ungraded()
        got = sum(w.leading_edges for w in wins)
        line = (
            f"seed={seed} txqd_before={before.txqd} txqd_after={after.txqd} "
            f"rxqd_before={before.rxqd} rxqd_after={after.rxqd} speed={seg.speed} "
            f"len={seg.len_field} len_class={seg.len_class} sck_cycles={got} expect={seg.expect}"
        )
        if before.txqd != after.txqd or before.rxqd != after.rxqd or got != seg.expect:
            raise AssertionError(f"CHK-SPI-DUMMY FAIL {line}")
        self.logger.info("CHK-SPI-DUMMY PASS %s", line)
        self.ran.add("CHK-SPI-DUMMY")
        await self._grade_frame(sb, frame, [seg], [], where="dummy", label="dummy_fifo")
        await self.ops.drain_rx()
        await self._sw_rst()

    async def _chain_leg(self) -> None:
        seed = self.seed
        ops, pads = self.ops, self.pads
        self._ungraded()
        await self._configopts(0)
        mark = pads.mark()
        for ln in self.chain_ctl_lens:
            await ops.issue_command(Seg(0, DIR_DUMMY, ln).cmd)
        wins = await ops.wait_segment_done(pads, mark, windows=2, bound_clks=SEG_BOUND_CLKS)
        gaps = pads.gaps_since(mark)
        rise = int(len(wins) >= 2 and bool(gaps) and gaps[0] > 0)
        if not rise:
            raise AssertionError(
                f"CTRL-MISSING seed={seed} CHK-SPI-CHAIN: no chip-select rise between two "
                f"CSAAT=0 commands (windows={[w.fmt() for w in wins]} gaps={gaps})"
            )
        self.logger.info(
            "CTL-SPI-CHAIN LOG seed=%d control_cs_rise_between_csaat0=1 gap_clks=%d",
            seed,
            gaps[0],
        )

        widths_seen: set[int] = set()
        for n, (clkdiv, width_changes, where, segs) in enumerate(self.chains):
            changes = sum(
                1
                for a, b in zip(segs, segs[1:])
                if (a.speed, a.direction) != (b.speed, b.direction)
            )
            data_speeds = {s.speed for s in segs if s.direction != DIR_DUMMY}
            if len(segs) < 2 or changes < 1 or int(len(data_speeds) > 1) != width_changes:
                raise AssertionError(
                    f"CTRL-MISSING seed={seed} CHK-SPI-CHAIN: segs={len(segs)} changes={changes} "
                    f"data_speeds={sorted(data_speeds)} width_changes={width_changes}"
                )
            self._ungraded()
            await self._configopts(clkdiv)
            sb = self._scoreboard()
            frame = sb.frame_mark()
            self._load(segs, where)
            self._graded()
            res = await self._run_segments(segs, tag="CHK-SPI-CHAIN")
            self._ungraded()
            wins = res["wins"]
            drained_words = await ops.drain_rx()
            got = sum(w.leading_edges for w in wins)
            exp = sum(s.expect for s in segs)
            cs_high_after = int(not pads.cs_low())
            err = field_compare(await self._err_status(), 0, ERR_STATUS_MASK)
            line = (
                f"seed={seed} segs={len(segs)} sck_cycles_in_chain={got} expect={exp} "
                f"cs_dropped_mid={len(wins) - 1} cs_high_after={cs_high_after} "
                f"control_cs_rise_between_csaat0={rise} clkdiv={clkdiv} changes={changes} "
                f"width_changes={width_changes} chain={','.join(s.fmt() for s in segs)} "
                f"rx_words={res['rx_read'] + len(drained_words)} "
                f"err_status=0x{err.got & err.mask:02x} err_mask=0x{err.mask:02x}"
            )
            if len(wins) != 1 or got != exp or not cs_high_after or not err.ok:
                raise AssertionError(f"CHK-SPI-CHAIN FAIL {line}")
            self.logger.info("CHK-SPI-CHAIN PASS %s", line)
            await self._grade_frame(
                sb,
                frame,
                segs,
                [int(w) for w in res["rx_words"] + drained_words],
                where=where,
                label=f"{where}={n} width_changes={width_changes}",
            )
            await spi_lane_fcov(TEST, "chain", chain=width_changes)
            widths_seen.add(width_changes)
            await self._sw_rst()
        if widths_seen != {0, 1}:
            raise AssertionError(
                f"CTRL-MISSING seed={seed} CHK-SPI-CHAIN: width patterns {sorted(widths_seen)}"
            )
        self.ran.add("CHK-SPI-CHAIN")

    async def _long_dummy_leg(self) -> None:
        seed = self.seed
        # The monitor and the responder would follow each of the 2,097,152 sck
        # edges; this leg grades the sck count and the window count only, on
        # windows whose chip select and sck output enables are on.
        await self.wire.monitor.stop()
        await self.rsp.stop()
        self._ungraded()
        await self._configopts(0)
        self._graded()
        mark = self.pads.mark()
        await self.ops.issue_command(Seg(0, DIR_DUMMY, LONG_DUMMY_LEN).cmd)
        await self.ops.wait_segment_done(self.pads, mark, bound_clks=LONG_BOUND_CLKS)
        self._ungraded()
        wins = self.pads.windows_since(mark, complete_only=False, require_oe=True)
        got = sum(w.leading_edges for w in wins)
        exp_wins = 1 + MUT_LONG_DUMMY_EXTRA_WIN
        line = (
            f"seed={seed} cycles={got} expect={LONG_DUMMY_CYCLES} windows={len(wins)} "
            f"expect_windows={exp_wins}"
        )
        if len(wins) != exp_wins or got != LONG_DUMMY_CYCLES:
            raise AssertionError(f"CHK-SPI-LONGDUMMY FAIL {line}")
        self.logger.info("CHK-SPI-LONGDUMMY PASS %s", line)
        self.ran.add("CHK-SPI-LONGDUMMY")
        await self._sw_rst()
        await self.rsp.start()
        await self.wire.monitor.start()

    async def _illegal_leg(self) -> None:
        seed = self.seed
        await self._configopts(0)
        for speed, direction in self.illegal_order:
            control = (speed, direction) == CONTROL_ILLEGAL
            await self._clean_state()
            # The core is held (SPIEN=0) while the illegal COMMAND is written, so
            # the reserved cell is refused at the register interface and never
            # runs on the pads. The SW_RST of the next clean state empties the
            # command queue before the core is enabled again.
            await self.ops.wr(CONTROL, self.ctrl & ~CTRL_SPIEN)
            await self.ops.wait_ready()
            # Control: a legal COMMAND written with SPIEN=0 raises no error, so
            # the CMDINVAL below comes from the cell and not from SPIEN=0.
            await self.ops.wr(COMMAND, Seg(0, DIR_DUMMY, 0).cmd)
            pre = field_compare(await self._err_status(), 0, ERR_STATUS_MASK)
            if not pre.ok:
                raise AssertionError(
                    f"CTRL-MISSING seed={seed} CHK-SPI-ILLEGAL: legal COMMAND with SPIEN=0 "
                    f"gave err_status=0x{pre.got:02x}"
                )
            await self.ops.wait_ready()
            if not control:
                self._graded()
            await self.ops.wr(
                COMMAND,
                command_word(
                    self.illegal_lens[(speed, direction)], speed=speed, direction=direction
                ),
            )
            err_v = 0
            for _ in range(ERR_POLLS):
                err_v = await self._err_status()
                if err_v & ERR_CMDINVAL:
                    break
            self._ungraded()
            err = field_compare(err_v, ERR_CMDINVAL, ERR_STATUS_MASK)
            if control:
                line = (
                    f"seed={seed} speed={speed} dir={direction} "
                    f"err_status=0x{err.got & err.mask:02x} err_mask=0x{err.mask:02x}"
                )
                if not err.ok:
                    raise AssertionError(f"CTL-SPI-ILLEGAL FAIL {line}")
                self.logger.info("CTL-SPI-ILLEGAL LOG %s", line)
            # Legal control command after the SPI clean state.
            await self._clean_state()
            await self.ops.wr(CONTROL, self.ctrl)
            flushed = await self.ops.read_status()
            if flushed.cmdqd or flushed.active:
                raise AssertionError(
                    f"CTRL-MISSING seed={seed} CHK-SPI-ILLEGAL: command queue not empty "
                    f"after the SPI clean state ({flushed.fmt()})"
                )
            mark = self.pads.mark()
            await self.ops.issue_command(
                Seg(0, DIR_DUMMY, self.illegal_ctl_lens[(speed, direction)]).cmd
            )
            await self.ops.wait_segment_done(self.pads, mark, bound_clks=SEG_BOUND_CLKS)
            ctl = field_compare(await self._err_status(), 0, ERR_STATUS_MASK)
            if control:
                if not ctl.ok:
                    raise AssertionError(
                        f"CTL-SPI-ILLEGAL FAIL seed={seed} control_err_status=0x{ctl.got:02x}"
                    )
                continue
            line = (
                f"seed={seed} speed={speed} dir={direction} "
                f"err_status=0x{err.got & err.mask:02x} "
                f"control_err_status=0x{ctl.got & ctl.mask:02x} "
                f"spien0_legal_err_status=0x{pre.got & pre.mask:02x} err_mask=0x{err.mask:02x} "
                f"len={self.illegal_lens[(speed, direction)]}"
            )
            if not err.ok or not ctl.ok:
                raise AssertionError(f"CHK-SPI-ILLEGAL FAIL {line}")
            self.logger.info("CHK-SPI-ILLEGAL PASS %s", line)
        self.ran.add("CHK-SPI-ILLEGAL")
        await self._clean_state()

    # ---- scenario ---------------------------------------------------------
    async def run_scenario(self) -> None:
        self.seed = self.random_seed()
        self._plan(self.seed)
        required = ["CHK-SPI-CELL", "CHK-SPI-RXCNT", "CHK-SPI-DUMMY", "CHK-SPI-CHAIN"]
        required += ["CHK-SPI-SB-FRAME", "CHK-SPI-LANE-DATA", "CHK-SPI-OE-SEG"]
        required += ["CHK-SPI-ILLEGAL", "CHK-SPI-WIRE"]
        if self.long_dummy:
            required.append("CHK-SPI-LONGDUMMY")
        self.required_evidence = tuple(required)
        self.ran: set[str] = set()
        self.lane_graded: set[tuple[int, bool]] = set()
        self.oe_graded: set[str] = set()
        close_graded_window()

        dut = cocotb.top
        self.rsp = SepSpiLaneResponder(dut)
        self.wire = SepSpiWireMonitor(dut, name="sep_spi_matrix_wire")
        # Every frame here is a raw segment frame, not a flash command; the
        # command-format oe_data check does not apply to it.
        self.wire.monitor.set_raw_frames(True)
        try:
            await self.bring_up_no_cpu()
            self.suppress_host_axi_transaction_info()
            self.pads = SepSpiPadSampler(keep_edges=False)
            self.pads.set_idle_level(0)
            self.pads.start()
            self.ops = SepSpiHostOps(self, clock=self.pads.now)
            await self.rsp.start()
            await self.wire.start()

            ctrl = (CTRL_RESET & ~CTRL_SW_RST) | CTRL_SPIEN | CTRL_OUTPUT_EN
            self.ctrl = ctrl
            await self.ops.wr(CONTROL, ctrl)
            await self.ops.wr(CSID, 0)
            err0 = field_compare(await self._err_status(), 0, ERR_STATUS_MASK)
            intr0 = field_compare(int(await self.ops.rd(INTR_STATE)), 0, INTR_STATE_MASK)
            if not err0.ok or not intr0.ok:
                raise AssertionError(
                    f"CTL-SPI-BRINGUP FAIL seed={self.seed} error_status {err0.fields()} "
                    f"intr_state {intr0.fields()}"
                )
            self.logger.info(
                "CTL-SPI-BRINGUP LOG seed=%d control=0x%08x error_status=0x%02x "
                "intr_state=0x%x fcov=%d",
                self.seed,
                ctrl,
                err0.got & err0.mask,
                intr0.got & intr0.mask,
                int(fcov_present()),
            )

            await self._single_cells()
            await self._dummy_fifo_leg()
            await self._chain_leg()
            if self.long_dummy:
                await self._long_dummy_leg()
            else:
                self.logger.info("OBS-SPI-LONGDUMMY seed=%d long_dummy=0 graded=0", self.seed)
            await self._illegal_leg()
            self._ungraded()
            await self.pads.stop()
            await self.wire.finish(self.logger, seed=self.seed)
            self.ran.add("CHK-SPI-WIRE")
        finally:
            close_graded_window()
            await self.rsp.stop()

        need_data = {(lanes, rx) for lanes in (1, 2, 4) for rx in (False, True)}
        miss_data = sorted(need_data - self.lane_graded)
        miss_oe = sorted(set(OE_ROWS) - self.oe_graded)
        if miss_data or miss_oe:
            raise AssertionError(
                f"CTRL-MISSING seed={self.seed} CHK-SPI-LANE-DATA width/rx not graded {miss_data}; "
                f"CHK-SPI-OE-SEG rows not graded {miss_oe}"
            )
        self.logger.info(
            "CTL-SPI-LANES LOG seed=%d data_graded=%s oe_rows=%s",
            self.seed,
            ",".join(f"x{lanes}{'rx' if rx else 'tx'}" for lanes, rx in sorted(self.lane_graded)),
            ",".join(sorted(self.oe_graded)),
        )
        missing = [c for c in self.required_evidence if c not in self.ran]
        if missing:
            raise AssertionError(f"CTRL-MISSING seed={self.seed} checks not run: {missing}")
        self.result_pass(TEST, self.seed, len(self.ran))
