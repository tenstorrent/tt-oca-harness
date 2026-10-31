# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SPI-to-DMA hardware handshake: the trigger mask, GO persistence, the stop and no CHUNK_DONE.

The Secure DMA copies the SPI receive data register (``0x10B0_0024``, WRAP) to
SEP SRAM (INCREMENT) in hardware handshake mode, one chunk of CHUNK_DATA_SIZE
per SPI trigger (``hw/sys/sep/doc/dma.adoc``, OCAH Modifications;
``secure_dma.adoc``, CONTROL.HARDWARE_HANDSHAKE_ENABLE, CONTROL.GO,
STATUS.CHUNK_DONE, HANDSHAKE_INTR_ENABLE). The SPI trigger is the registered OR
of ``TXQD < TX_WATERMARK`` and ``RXQD >= RX_WATERMARK`` and does not depend on
EVENT_ENABLE or INTR_ENABLE (``hw/sys/sep/doc/spi.adoc``, DMA Trigger). Every
run except the TX-term cell sets TX_WATERMARK 0, so only the RX term raises the
trigger there.

The SPI responder is ``OcahSpiFlash`` bound on four lanes (``mode="quad_io"``,
``dq_out`` = ``spi_sd_o``, ``dq_in`` = ``spi_sd_i``); the testlist entry
passes ``+sep_spi_four_lane`` so the DUT receives ``spi_sd_i`` on every lane
(``tb/tb_top.sv``), and the leaf fails at start without it. The flash holds
unique words at address 0 for the READ (0x03) of the handshake runs, and
seeded data at three seeded addresses for the lane reads. Every RX byte packs
into RXDATA with ``ByteOrder = 1``: the first byte received lands in
RXDATA[7:0] (OpenTitan spi_host, Input and Output Byte Ordering).

Runs, each from a cold reset (``rst_ni`` pulse, bounded wait for
``dbg_sep_reset_n_o``), since CFG_REGWEN locks the DMA configuration while a
handshake run keeps GO set:

* depth check (control): an Rx segment of 4*(W+1) bytes with no reader must not
  fill the RX FIFO; the leaf then drains the words;
* reference run (control): the host reads the flash stream through RXDATA; the
  sentinel is drawn as a word that equals no reference word;
* trigger cell: RX_WATERMARK = W_eq, drawn 1..4, with the chunk C = 4*W_eq
  bytes (C/4 == W); the host receives W_eq-1 words, then one more word;
* lane reads: one read at x1, x2 and x4, in a seeded order (READ 0x03, a drawn
  one of 0x3B/0xBB, a drawn one of 0x6B/0xEB), seeded address and length;
* normal-mode control: a 4096-byte memory-to-memory copy in chunks of 1024
  (no SPI traffic, no session), before the handshake run;
* handshake run, mask bit 0 set: the poll for the last word of chunk n sets
  t_fill, the window length of every later run (never an expected value);
* masked run, mask bit 0 clear and the drawn upper bits; the leaf drains the
  words after the check;
* stop run: n_stop chunks move; with GO still 1, a second Rx segment of W+1
  words after the trigger fell moves the next chunk; firmware clears GO, more
  Rx data arrives; the leaf drains the words after the check;
* interrupt-clear run, mask bit 0 set, CLEAR_INTR_SRC bit 0 = 1 and
  CLEAR_INTR_BUS bit 0 = 1, INTR_SRC_ADDR_0 a SEP SRAM word outside the
  destination, INTR_SRC_WR_VAL_0 a drawn word that differs from the word the
  leaf writes there first; the same copy as the handshake run;
* second masked run: MASK 0 when the drawn upper bits are not 0, else a second
  drawn non-zero upper mask with bit 0 clear, so both masked classes run on
  every seed;
* TX-term cell: SPIEN 0, RX_WATERMARK 1 with RXQD 0, EVENT_ENABLE 0,
  INTR_ENABLE 0, TX_WATERMARK W_tx drawn 1..4; the host writes W_tx TXDATA
  words one at a time;
* clear-range run: the interrupt-clear run with RANGE_BASE at the destination,
  so INTR_SRC_ADDR_0 lies below the enabled memory range;
* clear-bus run: the interrupt-clear run with CLEAR_INTR_BUS bit 0 = 0 (the
  CTN/System fabric, tied off in SEP).

Wire monitor sessions: ``SepSpiWireMonitor`` (with the output-enable taps)
runs in each run with SPI traffic, except the clear-range and clear-bus runs,
whose RX bytes no rule states. It starts after the ``rst_ni`` release and
stops, with the bus idle, before the next ``rst_ni`` pulse. Each session
starts with an empty flash record and an empty monitor history, so the record
index and the monitor frame index stay aligned, and has its own
``SepSpiScoreboard``. The normal-mode run has no SPI traffic and no session.

FCOV gate (``env/sep_fcov_gate.py``): a handshake run opens the graded window
right before its GO write; the trigger cell, the lane reads and the TX-term
cell open it after their SPI set-up. A window closes after the last check of
its run passed; set-up, drains and the GO clear that leaves the engine idle run
with it closed. The pass label ``hs_mask_pass`` starts at 0 at each GO. The
sampler holds the cells of a run at their DUT events; after every check of the
run passed (handshake run: CHK-HS-DATA, CHK-HS-NOCHUNK, CHK-HS-GO leg total;
masked runs: CHK-HS-MASKED; stop run: CHK-HS-GO leg between_chunks,
CHK-HS-STOP; interrupt-clear run: CHK-HS-CLR) the leaf writes the bits of
that run, holds them LABEL_CLKS clocks and writes 0, then closes the window.
Bit 0 releases ``cp_hs_mask``, bit 1 ``cp_intr_clear`` (interrupt-clear run
only), bit 2 the other cells (not in the interrupt-clear run, which grades no
CHUNK_DONE). A FAIL raises with the window open; the close in the clean-up
then drops the held cells. The clear-range and clear-bus runs write no
``hs_mask_pass`` bit: after their CTRL line passed, each writes its
``open_value_leg_pass`` leg for LABEL_CLKS clocks instead.

Checkers:
  CHK-HS-MASKED   mask bit 0 clear (both masked runs, ``run=``): the destination
                  keeps its sentinel while the trigger probe is high. Handshake
                  input 0 is the only connected input (``hw/sys/sep/doc/dma.adoc``,
                  "Only handshake input 0 is connected"), and MASK holds the
                  "Enable bits for incoming handshake interrupt wires"
                  (``secure_dma.rdl``, HANDSHAKE_INTR_ENABLE). CONTROL.GO at
                  the end of the window is logged (``OBS-HS-GO-MASKED``): no
                  text states GO while every enabled trigger stays low.
  CHK-HS-GO       In handshake operation the engine keeps GO set across chunks
                  and clears it, setting STATUS.DONE, once TOTAL_DATA_SIZE
                  bytes have been transferred (secure_dma.adoc, CONTROL.GO).
                  Leg between_chunks (stop run, before the firmware clear):
                  GO reads 1 with at least one and fewer than all chunks moved.
                  Leg total (handshake run): after the destination holds
                  TOTAL_DATA_SIZE bytes and a further wait as long as t_fill,
                  GO reads 0 and STATUS.DONE reads 1 (handshake run), and with
                  INTR_ENABLE.DMA_DONE=1 PIC source 9 (bit 8 of
                  ``sep_internal_interrupts_probe_o``) rises once, after the
                  last AW of the DMA master to the destination, and is high at
                  the end of the wait ("An interrupt is raised when the entire
                  data transfer (as defined by `TOTAL_DATA_SIZE`) is
                  complete.", ``vendor/lowRISC/opentitan/upstream/hw/ip/dma/
                  doc/programmers_guide.md:34``). The
                  text states no clock for the clear, so GO and DONE read as
                  soon as the destination holds the total are logged only
                  (OBS-HS-GO-TOTAL). Controls: the normal-mode copy ends with
                  GO=0 and raises PIC source 9, a poll of the handshake run
                  before the total reads DONE=0, INTR_ENABLE reads back with
                  DMA_DONE=1, and the tap saw the destination writes.
  CHK-HS-STOP     re-trigger leg, GO=1: after the trigger fell, a second Rx
                  segment raises it again and the engine moves at least one more
                  chunk; the moved chunks equal the RX stream (the first segment,
                  then the second, each from flash address 0) and the words after
                  them keep their sentinel. "In response to the assertion of an
                  enabled bit of the `lsio_trigger_i` input, the DMA controller
                  will proceed to transfer an entire chunk of data from the
                  source to the destination." and "Whilst the `lsio_trigger_i`
                  input is not asserted, the DMA controller will remain in its
                  Idle state awaiting instruction to proceed with the next chunk
                  of the transfer." (``vendor/lowRISC/opentitan/upstream/hw/ip/
                  dma/doc/theory_of_operation.md:461,463``). Controls: the
                  trigger probe reads low before the second segment and rises in
                  it. Stop leg: after the GO clear the words after the moved
                  chunks keep their sentinel while the trigger probe is high,
                  the moved chunks keep the words read before the clear, and
                  CONTROL.GO reads 0 after the clear ("Firmware clears the go
                  bit to stop the hardware handshake operation earlier.",
                  secure_dma.adoc, CONTROL.GO).
  CHK-HS-NOCHUNK  STATUS.CHUNK_DONE reads 0 at every poll of the handshake run,
                  and with INTR_ENABLE.DMA_CHUNK_DONE=1 PIC source 10 (bit 9 of
                  ``sep_internal_interrupts_probe_o``) stays low at every clock
                  from before GO to the end of the t_fill wait, so a CHUNK_DONE
                  pulse between two polls also fails.
  CHK-HS-DATA     handshake run: the n chunks the DMA moved, read from the
                  destination over the frontdoor, equal the flash bytes at
                  address 0 packed with ``ByteOrder = 1``, word for word and in
                  order. Control: the reference words are distinct
                  (``ref_distinct``), so a chunk in the wrong place fails.
  CHK-HS-TRIG-EQ  trigger cell: with RXQD = W_eq-1 the trigger probe is low and
                  did not rise; the next word makes RXQD = W_eq, and the probe
                  rises once, after the last sample edge of that word, and reads
                  high (``RXQD >= RX_WATERMARK``, spi.adoc DMA Trigger).
                  Controls: STATUS.RXQD reads W_eq-1 and then W_eq.
  CHK-HS-TRIG-TX  TX-term cell: the trigger is ``TXQD < TX_WATERMARK`` with the
                  RX term false (spi.adoc DMA Trigger). The TX_WATERMARK write
                  with TXQD 0 raises the probe; after each of the first
                  W_tx-1 TXDATA words the probe reads 1 and has not fallen;
                  the W_tx-th word makes TXQD = W_tx and the probe falls once
                  and reads 0. Each state is read after a settle of
                  TX_SETTLE_CLKS clocks. Controls: STATUS.TXQD reads the number
                  of words written at each state (else CTRL-MISSING), and the
                  probe reads 0 before the TX_WATERMARK write. The clocks from
                  the TX_WATERMARK write to the rise and from the last
                  TXDATA write to the fall are logged
                  (``OBS-HS-TRIG-TX-LAT``): the text states a registered OR and
                  no clock count, so the rise and the fall are graded inside
                  TRIG_RISE_CLKS only.
  CHK-HS-LANE-RX  lane reads: the RXDATA bytes of each read equal the seeded
                  flash bytes at its address (``width=``, ``bytes=``).
  CHK-SPI-SESSION-FRAMES  per session: the monitor saw at least one frame, and
                  every frame carries one scoreboard expectation whose bytes
                  cover the frame's RX segment (the handshake frame: the moved
                  chunks).
  CHK-SPI-SB-RX   per session (``SepSpiScoreboard.expect_rx``): the bytes the DUT
                  delivered == the flash ``data_out`` prefix == the monitor wire
                  decode at the command's lane width.
  CHK-SPI-WIRE    per session: no wire or output-enable rule violation
                  (``SepSpiWireMonitor``), with the flash ledger and frame
                  shape.

  CHK-HS-CLR      interrupt-clear run: at least one AW on the DMA master tap
                  (``dma_axi_req_probe_o``, ``env/sep_dma_tap.py``) carries the
                  address INTR_SRC_ADDR_0, and that SRAM word reads
                  INTR_SRC_WR_VAL_0 over the frontdoor after the run. The tap
                  carries no write data, so the data comes from that readback.
                  Contract: "configure `CLEAR_INTR_SRC`, `CLEAR_INTR_BUS`,
                  `INTR_SRC_ADDR` and `INTR_SRC_WR_VAL` for the connected host
                  port (`CLEAR_INTR_BUS` bit 0 = 1)"
                  (``doc/programmer/src/sep-programming.adoc:800-803``); "DMA
                  issues writes with address from INTR_SRC_ADDR and write value
                  from INTR_SRC_WR_VAL corresponding to each bit set in this
                  register" (``vendor/lowRISC/opentitan/upstream/hw/ip/dma/data/
                  dma.hjson:756-757``, CLEAR_INTR_SRC). Control: the handshake run
                  (CLEAR_INTR_SRC = 0 from reset) moves its chunks with no AW to
                  that address. The clock of each clear write, the count of clear
                  writes and the WSTRB of the paired W beat are logged
                  (``OBS-HS-CLR``): the text says only "when ... lsio_trigger
                  becomes set".
  OBS-DMA-CLR-RANGE clear-range and clear-bus runs (``variant=``): the AWs
                  of the DMA master tap at INTR_SRC_ADDR_0 and their B
                  responses, that SRAM word after the run, the chunks moved,
                  STATUS, ERROR_CODE and CONTROL.GO, logged. No text states a
                  range check of the clear write or the route of bus 0 in
                  SEP. Control (``CTRL-DMA-CLR-RANGE``, else CTRL-MISSING):
                  CLEAR_INTR_SRC, CLEAR_INTR_BUS, INTR_SRC_ADDR_0, RANGE_BASE
                  and HANDSHAKE_INTR_ENABLE read back as written before GO,
                  and the trigger probe is high in the window.

Controls: RX depth above W+1; mask=1 run fills the destination; trigger high in
each "never" window; 1 <= n_moved, and the chunks moved before the GO clear are
fewer than chunks_total; the normal-mode copy reads GO=0 at DONE, shows
CHUNK_DONE in a poll, and shows a rise of PIC source 10 (bit 9 of
``sep_internal_interrupts_probe_o``), so a dead or mis-bound bit-9 tap fails
the control of the line leg of CHK-HS-NOCHUNK; INTR_ENABLE reads back with
DMA_CHUNK_DONE=1 in the handshake run (``CTRL-HS-INTR-EN``). A missing control logs
CTRL-MISSING and fails the leaf.

Probes: ``spi_lsio_trigger_probe_o``, ``dma_busy_probe_o``, ``spi_tx_qd_probe_o``
(logged), ``dma_axi_req_probe_o`` (handshake and interrupt-clear runs), ``dbg_sep_reset_n_o``, ``sep_internal_interrupts_probe_o`` bit 9, the
SPI pad ports and lane taps, and the register frontdoor over ``s_axi``.

Run mode: no_cpu (``lsu_stub_all_live``), real fuse sense, both simulators,
``+sep_spi_four_lane``. Every draw comes from ``SepSeededRng`` and the run seed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles, RisingEdge
from env.sep_bit_watch import BitWatchTimeout, SepBitWatch
from env.sep_dma_tap import SepDmaTap
from env.sep_efuse_image import SepEfuseImage
from env.sep_fcov_gate import (
    HS_MASK_PASS_INTR_CLEAR,
    HS_MASK_PASS_MASK,
    HS_MASK_PASS_RUN,
    close_graded_window,
    open_graded_window,
    set_hs_mask_pass,
    set_open_value_leg_pass,
)
from env.sep_field_compare import field_compare
from env.sep_seeded_rng import SepSeededRng
from env.sep_spi_lane_responder import spi_lane_fcov
from env.sep_spi_pad_sampler import SepSpiPadSampler, SpiPadTimeout
from env.sep_spi_scoreboard import SepSpiScoreboard
from env.sep_spi_wire_monitor import SepSpiWireMonitor
from ocah_spi_vip import OcahSpiFlash
from sep_base_test import sep_base_test
from sep_reg_meta import sym
from seq_lib.sep_dma_ops import (
    CFG_REGWEN as DMA_CFG_REGWEN,
)
from seq_lib.sep_dma_ops import (
    CONTROL as DMA_CONTROL,
)
from seq_lib.sep_dma_ops import (
    ERROR_CODE,
    HANDSHAKE_INTR_ENABLE,
    INTR_ENABLE,
    OP_COPY,
    RANGE_BASE,
    SECURE_DMA,
    DmaStatus,
    SepDmaOps,
    SepMemWords,
    asid_word,
)
from seq_lib.sep_dma_ops import (
    STATUS as DMA_STATUS,
)
from seq_lib.sep_spi_host_csr_seq import (
    CONTROL as SPI_CONTROL,
)
from seq_lib.sep_spi_host_csr_seq import (
    CSID,
    CTRL_OUTPUT_EN,
    CTRL_SPIEN,
    EVENT_ENABLE,
    RXDATA,
    SPI_CONTROLLER,
)
from seq_lib.sep_spi_host_csr_seq import (
    INTR_ENABLE as SPI_INTR_ENABLE,
)
from seq_lib.sep_spi_host_ops import (
    DIR_DUMMY,
    DIR_RX,
    DIR_TX,
    SPEED_DUAL,
    SPEED_QUAD,
    SPEED_STD,
    SepSpiHostOps,
    command_word,
    configopts_word,
)

TEST = "sep_spi_dma_handshake_rand_test"

M32 = 0xFFFF_FFFF
SRAM_BASE = sym("SEP_SRAM_MEM_BASE_ADDR")
SRAM_SIZE = sym("SEP_SRAM_MEM_SIZE")
# Handshake range: the SRAM base to the end of the SPI window (memory_map.adoc).
HS_RANGE_BASE = SRAM_BASE
HS_RANGE_LIMIT = 0x10BF_FFFF
# Normal-mode range: the SEP SRAM.
NM_RANGE_LIMIT = SRAM_BASE + SRAM_SIZE - 1
ASID = asid_word(7, 7)

# Destination of the handshake runs and the normal-mode footprints (SRAM).
HS_DST = SRAM_BASE + 0x1000
# INTR_SRC_ADDR_0 of the interrupt-clear run: an SRAM word below HS_DST, inside
# the handshake range and outside every destination.
CLR_ADDR = SRAM_BASE + 0x800
CLEAR_INTR_SRC = SECURE_DMA.addr("CLEAR_INTR_SRC")
CLEAR_INTR_BUS = SECURE_DMA.addr("CLEAR_INTR_BUS")
INTR_SRC_ADDR_0 = sym("SECURE_DMA_INTR_SRC_ADDR_0_0__REG_ADDR")
INTR_SRC_WR_VAL_0 = sym("SECURE_DMA_INTR_SRC_WR_VAL_0_0__REG_ADDR")
# Clear-range and clear-bus runs: their own draw stream, the variants with the
# RANGE_BASE and CLEAR_INTR_BUS each writes, and the fixture leg of each.
CLR_SALT = 0x434C_5252
CLR_VARIANTS = (
    ("outside_range", HS_DST, 0x1, "dma_clr_outside_range"),
    ("bus0", HS_RANGE_BASE, 0x0, "dma_clr_bus0"),
)
NM_SRC = SRAM_BASE + 0x8000
NM_DST = SRAM_BASE + 0x10000
NM_TOTAL = 4096
NM_CHUNK = 1024

CTRL_RX_WM_LSB = SPI_CONTROLLER.field_lsb("CONTROL", "rx_watermark")
CTRL_TX_WM_LSB = SPI_CONTROLLER.field_lsb("CONTROL", "tx_watermark")
GO_MASK = SECURE_DMA.field_mask("CONTROL", "go")
INTR_EN_CHUNK = SECURE_DMA.field_mask("INTR_ENABLE", "dma_chunk_done")
INTR_EN_DONE = SECURE_DMA.field_mask("INTR_ENABLE", "dma_done")
HS_MASK_FIELD = SECURE_DMA.field_mask("HANDSHAKE_INTR_ENABLE", "mask")

# OcahSpiFlash READ: opcode 0x03 then a 24-bit address, sent low byte of the
# TXDATA word first. Address 0.
FLASH_READ = 0x03
FLASH_ADDR = 0
READ_CMD_WORD = FLASH_READ
READ_CMD_BYTES = 4
FLASH_WORDS = 64

# Flash read commands per lane width, and their shape: the address lane count
# and the dummy clocks between the address and the data (the 0x3B, 0x6B, 0xBB
# and 0xEB formats of the four-lane flash model; READ has no dummy clock).
LANE_OPCODES = {1: (0x03,), 2: (0x3B, 0xBB), 4: (0x6B, 0xEB)}
LANE_SHAPE = {0x03: (1, 0), 0x3B: (1, 8), 0x6B: (1, 8), 0xBB: (2, 4), 0xEB: (4, 6)}
SPEED = {1: SPEED_STD, 2: SPEED_DUAL, 4: SPEED_QUAD}
FOUR_LANE_PLUSARG = "sep_spi_four_lane"

# The committed default OTP image: the harness disable vectors, never randomized.
EFUSE_IMAGE = (
    Path(__file__).resolve().parents[3] / "tb" / "efuse_preloads" / "sep_efuse_default.hex"
)

# Bounds.
SENSE_CYCLES = 20_000
STABLE_READS = 8
TRIG_RISE_CLKS = 200
CS_HIGH_CLKS = 2_000
# TX-term cell: clocks from a TXQD/TX_WATERMARK change to the level read, and
# the STATUS reads allowed for TXQD to show a written word.
TX_SETTLE_CLKS = 16
TX_QD_READS = 50
# Clocks the pass label is held before it returns to 0.
LABEL_CLKS = 2


def unique_words(rng: SepSeededRng, k: int, *, exclude: set[int] | None = None) -> list[int]:
    """``k`` distinct 32-bit words drawn in order from ``rng``, none in ``exclude``."""
    seen = set(exclude or ())
    out: list[int] = []
    while len(out) < k:
        w = rng.getrandbits(32)
        if w not in seen:
            seen.add(w)
            out.append(w)
    return out


def words_bytes(words: list[int]) -> bytes:
    """RXDATA words as the received byte stream (``ByteOrder = 1``)."""
    return b"".join((w & M32).to_bytes(4, "little") for w in words)


class _Cfg:
    """Every draw of the leaf, from the run seed."""

    def __init__(self, seed: int) -> None:
        self.seed = seed
        self.rng = SepSeededRng(seed)
        r = self.rng
        self.chunk = 4 * r.randrange(1, 5)  # C: 4..16, multiple of 4
        self.n = r.randrange(2, 9)  # chunk count 2..8
        self.mask_hi = r.getrandbits(10)  # HANDSHAKE_INTR_ENABLE.MASK bits 10:1
        self.n_stop = r.randrange(1, self.n)  # 1..n-1
        self.clkdiv = r.randrange(0, 8)
        self.wm = r.randrange(self.chunk // 4, 8)  # W: C/4..7
        self.flash_words = unique_words(r, FLASH_WORDS)
        # Normal-mode control data: unique source words and a sentinel outside them.
        self.nm_src = unique_words(r, NM_TOTAL // 4)
        self.nm_sentinel = unique_words(r, 1, exclude=set(self.nm_src))[0]
        # Trigger cell: RX_WATERMARK W_eq and the chunk C_eq = 4 * W_eq bytes (C/4 == W).
        self.eq_wm = r.randrange(1, 5)
        # Lane reads: one per width, in a seeded order, each in its own 4 KiB
        # sector (sector 0 holds the handshake words).
        self.lane_order = [1, 2, 4]
        r.shuffle(self.lane_order)
        sectors = r.sample(range(1, 4096), 3)
        self.lane_reads: dict[int, tuple[int, int, bytes]] = {}
        for lanes, sector in zip((1, 2, 4), sectors):
            opcode = r.choice(LANE_OPCODES[lanes])
            addr = (sector << 12) | r.randrange(0, 0x400)
            data = bytearray(r.getrandbits(8) for _ in range(4 * r.randrange(2, 9)))
            if data[1] == data[0]:
                data[1] ^= 0xFF  # at least two distinct bytes by construction
            self.lane_reads[lanes] = (opcode, addr, bytes(data))

    @property
    def eq_chunk(self) -> int:
        return 4 * self.eq_wm

    @property
    def cw(self) -> int:
        return self.chunk // 4

    @property
    def mask_on(self) -> int:
        return 0x001 | (self.mask_hi << 1)

    @property
    def mask_off(self) -> int:
        return self.mask_hi << 1

    @property
    def extra_bytes(self) -> int:
        return 4 * (self.wm + 1)

    @property
    def chunks_total_stop(self) -> int:
        # Room for the first segment, the re-trigger segment and one unmoved chunk.
        return self.n_stop + 2 * -(-self.extra_bytes // self.chunk) + 1

    def flash_bytes(self) -> bytes:
        return b"".join(w.to_bytes(4, "little") for w in self.flash_words)

    def seg_clks(self, rx_bytes: int) -> int:
        """Clock bound of one Tx+Rx frame: 8 bits per byte, 2*(CLKDIV+1) clocks per bit."""
        return 4 * (READ_CMD_BYTES + rx_bytes) * 8 * 2 * (self.clkdiv + 1) + 50_000


@dataclass
class _RxExpect:
    """One frame's RX expectation of a monitor session."""

    lanes: int
    opcode: int
    got: int  # bytes registered with the scoreboard
    want: int  # bytes of the frame's RX segment the expectation covers
    label: str


@dataclass
class _Session:
    """One wire monitor session: from an ``rst_ni`` release to the next pulse."""

    tag: str
    tally0: int
    sb: SepSpiScoreboard
    rx: list[_RxExpect] = field(default_factory=list)


@pyuvm.test()
class sep_spi_dma_handshake_rand_test(sep_base_test):
    """SPI-to-DMA hardware handshake: mask, GO, stop, chunk, data and trigger rules."""

    required_evidence = (
        "CHK-HS-MASKED",
        "CHK-HS-GO",
        "CHK-HS-STOP",
        "CHK-HS-NOCHUNK",
        "CHK-HS-DATA",
        "CHK-HS-TRIG-EQ",
        "CHK-HS-TRIG-TX",
        "CHK-HS-LANE-RX",
        "CHK-HS-CLR",
        "CHK-SPI-SESSION-FRAMES",
        "CHK-SPI-SB-RX",
        "CHK-SPI-WIRE",
    )

    # The open wire monitor session; None between sessions.
    sess: _Session | None = None

    # ---- logging helpers ---------------------------------------------------
    def _fail(self, chk: str, line: str) -> None:
        msg = f"{chk} FAIL seed={self.cfg_.seed} {line}"
        self.logger.error(msg)
        raise AssertionError(msg)

    def _ctrl_missing(self, chk: str, line: str) -> None:
        msg = f"CTRL-MISSING {chk} seed={self.cfg_.seed} {line}"
        self.logger.error(msg)
        raise AssertionError(msg)

    def _pass(self, chk: str, line: str) -> None:
        self.logger.info("%s PASS seed=%d %s", chk, self.cfg_.seed, line)
        self.n_checks += 1

    # ---- wire monitor sessions ---------------------------------------------
    async def _session_begin(self, tag: str) -> None:
        """Clear the flash record and the monitor history together, then start the monitor."""
        self.flash.clear_transactions()
        self.wire.monitor.clear_history()
        sb = SepSpiScoreboard(self.wire, self.flash, self.logger, seed=self.cfg_.seed)
        self.sess = _Session(tag, sum(self.wire.tally.values()), sb)
        # MUTATION hook (step 14, item 7): skip the next line for one tag; the
        # zero-frame rule of CHK-SPI-SESSION-FRAMES fails.
        await self.wire.monitor.start()

    def _expect_rx(self, opcode: int, lanes: int, data: bytes, *, want: int, label: str) -> None:
        """Register the bytes the DUT delivered for one frame of the open session."""
        sess = self.sess
        if sess is None:
            raise AssertionError(f"{label}: RX expectation outside a monitor session")
        full = f"{sess.tag}:{label} width=x{lanes}"
        sess.sb.expect_rx(opcode, data, source="dut", label=full)
        sess.rx.append(_RxExpect(lanes, opcode, len(data), want, full))

    async def _session_end(self) -> None:
        """Bus idle, monitor stop, then the session checks; returns with no session open."""
        cfg = self.cfg_
        sess = self.sess
        assert sess is not None
        await self.spi.poll_status(
            lambda s: s.active == 0 and s.cmdqd == 0, 2_000, f"session {sess.tag}: bus idle"
        )
        for _ in range(CS_HIGH_CLKS):
            if not self.pads.cs_low():
                break
            await ClockCycles(cocotb.top.clk_i, 1)
        else:
            self._fail("CHK-SPI-SESSION-FRAMES", f"session={sess.tag} chip select still low")
        await ClockCycles(cocotb.top.clk_i, 4)
        await self.wire.monitor.stop()
        frames = sum(self.wire.tally.values()) - sess.tally0
        short = [e.label for e in sess.rx if e.got != e.want]
        line = (
            f"session={sess.tag} frames={frames} expectations={len(sess.rx)} "
            f"widths={','.join(f'x{e.lanes}' for e in sess.rx) or '-'} "
            f"bytes={sum(e.got for e in sess.rx)} short={','.join(short) or '-'}"
        )
        if frames == 0 or frames != len(sess.rx) or short:
            self._fail("CHK-SPI-SESSION-FRAMES", line)
        await self.wire.finish(self.logger, seed=cfg.seed, flash=self.flash)
        sess.sb.finish()
        self._pass("CHK-SPI-SESSION-FRAMES", line)
        for e in sess.rx:
            await spi_lane_fcov(TEST, "data", lanes=e.lanes, rx=True)
        self.sess = None

    # ---- reset and SPI -----------------------------------------------------
    async def _cold_reset(self, tag: str, *, session: bool = True) -> None:
        """Non-graded cold reset: session end, window closed, rst_ni pulse, SEP reset release."""
        if self.sess is not None:
            await self._session_end()
        close_graded_window(self.logger)
        await self.flash.stop()
        rel = await self.pulse_rst_ni(max_sense_cycles=SENSE_CYCLES)
        self.flash.init_signals()
        await self.flash.start()
        self.logger.info(
            "INFO-RESET LOG run=%s release_clks=%d sep_reset_n_at_hold_end=%d",
            tag,
            rel["release_clks"],
            rel["sep_reset_n_at_hold_end"],
        )
        if session:
            await self._session_begin(tag)

    async def _spi_config(self, wm: int) -> None:
        cfg = self.cfg_
        spi = self.spi
        await spi.wr(SPI_CONTROL, CTRL_SPIEN | CTRL_OUTPUT_EN | (wm << CTRL_RX_WM_LSB))
        await spi.wr(EVENT_ENABLE, 0)
        await spi.wr(SPI_INTR_ENABLE, 0)
        await spi.wr(CSID, 0)
        await spi.write_configopts(configopts_word(clkdiv=cfg.clkdiv))

    async def _spi_sequence(self, rx_bytes: int, *, wm: int | None = None):
        """The READ (0x03, address 0) of every run; returns the pad mark taken before it."""
        spi = self.spi
        await self._spi_config(self.cfg_.wm if wm is None else wm)
        await spi.push_tx(READ_CMD_WORD)
        mark = self.pads.mark()
        await spi.issue_command(
            command_word(READ_CMD_BYTES - 1, speed=SPEED_STD, direction=DIR_TX, csaat=1)
        )
        await spi.issue_command(
            command_word(rx_bytes - 1, speed=SPEED_STD, direction=DIR_RX, csaat=0)
        )
        return mark

    async def _drain_words(self, want: int, mark, what: str) -> list[int]:
        """Read RXDATA until the frame after ``mark`` ended and the RX FIFO is empty."""
        words: list[int] = []
        bound = self.cfg_.seg_clks(4 * want)
        t0 = self.tw.clk
        while True:
            if self.tw.clk - t0 > bound:
                self._fail(
                    "CHK-SPI-SESSION-FRAMES",
                    f"{what}: RX drain did not end in {bound} clocks "
                    f"({len(words)} of {want} words)",
                )
            st = await self.spi.read_status()
            if not st.rxempty:
                words.append(await self.spi.rd(RXDATA) & M32)
                continue
            if self.pads.windows_since(mark) and st.active == 0 and st.cmdqd == 0:
                return words

    # ---- DMA ---------------------------------------------------------------
    async def _hs_start(
        self,
        *,
        mask: int,
        total: int,
        dst_words: int,
        rx_bytes: int,
        range_base: int = HS_RANGE_BASE,
    ):
        """Step 5: program the handshake copy, open the graded window, GO, then the SPI sequence.

        The window opens after the set-up and before the GO write, with the
        pass label at 0. Returns the clock of the GO write and the pad mark of
        the SPI frame.
        """
        cfg = self.cfg_
        dma = self.dma
        await dma.program_range(range_base, HS_RANGE_LIMIT)
        await dma.wr(SECURE_DMA.addr("ADDR_SPACE_ID"), ASID)
        await self.mem.fill(HS_DST, [self.sentinel] * dst_words)
        await dma.program_transfer(
            src=RXDATA,
            dst=HS_DST,
            total=total,
            chunk=cfg.chunk,
            width_enc=2,
            src_inc=False,
            src_wrap=True,
            dst_inc=True,
            dst_wrap=False,
        )
        await dma.wr(HANDSHAKE_INTR_ENABLE, mask & HS_MASK_FIELD)
        open_graded_window(TEST, self.logger)
        set_hs_mask_pass(0, self.logger)
        t_go = self.tw.clk
        await dma.go(opcode=OP_COPY, hs=1, initial=1)
        mark = await self._spi_sequence(rx_bytes)
        return t_go, mark

    async def _release(self, bits: int) -> None:
        """Every check of the run passed: the pass label releases the held cells."""
        clk = cocotb.top.clk_i
        await RisingEdge(clk)
        set_hs_mask_pass(bits, self.logger)
        await ClockCycles(clk, LABEL_CLKS)
        set_hs_mask_pass(0, self.logger)

    def _probe_log(self, tag: str) -> None:
        self.logger.info(
            "INFO-PROBE LOG run=%s dma_busy_probe_o=%s spi_tx_qd_probe_o=%s",
            tag,
            self.busy.level(),
            self.rd(cocotb.top.spi_tx_qd_probe_o, allow_unknown=True),
        )

    def _go_cmp(self, raw: int):
        return field_compare(raw, GO_MASK, GO_MASK)

    async def _wait_clocks(self, until: int) -> None:
        if until > self.tw.clk:
            await ClockCycles(cocotb.top.clk_i, until - self.tw.clk)

    async def _stable_image(self, n_words: int, t_fill: int, what: str) -> list[int]:
        """Destination words once two reads ``t_fill`` clocks apart are equal."""
        img1 = await self.mem.read(HS_DST, n_words)
        for _ in range(STABLE_READS):
            await self._wait_clocks(self.tw.clk + t_fill)
            img2 = await self.mem.read(HS_DST, n_words)
            if img2 == img1:
                return img1
            img1 = img2
        self._ctrl_missing(
            "CHK-HS-STOP", f"{what}: destination not stable after {STABLE_READS} reads"
        )
        raise AssertionError  # unreachable: _ctrl_missing raises

    def _filled(self, img: list[int], n_chunks: int) -> list[bool]:
        """Per chunk of ``img``: True when no word of the chunk holds the sentinel."""
        cw = self.cfg_.cw
        return [
            all(w != self.sentinel for w in img[c * cw : (c + 1) * cw]) for c in range(n_chunks)
        ]

    # ---- runs --------------------------------------------------------------
    async def _clear_run(
        self, nw: int, rx_bytes: int, t_fill: int, hs_clr_aw: int, hs_aw: int
    ) -> None:
        """CHK-HS-CLR: the source 0 clear write reaches INTR_SRC_ADDR_0 on the DMA master.

        The handshake run (CLEAR_INTR_SRC = 0) is the control: ``hs_aw`` AWs and
        ``hs_clr_aw`` of them at CLR_ADDR. The wait after the last word lands is
        ``t_fill``, the clocks the handshake run took from GO to its last word.
        """
        cfg = self.cfg_
        dma = self.dma
        await self._cold_reset("clear")
        # Appended draw: the clear value, never the word written there first.
        clr_val = unique_words(cfg.rng, 1, exclude={self.sentinel})[0]
        self.logger.info(
            "INFO-DRAW seed=%d clear_addr=0x%08x clear_wr_val=0x%08x clear_pre=0x%08x",
            cfg.seed,
            CLR_ADDR,
            clr_val,
            self.sentinel,
        )
        await self.mem.fill(CLR_ADDR, [self.sentinel])
        await dma.wr(CLEAR_INTR_SRC, 0x1)
        await dma.wr(CLEAR_INTR_BUS, 0x1)
        await dma.wr(INTR_SRC_ADDR_0, CLR_ADDR)
        await dma.wr(INTR_SRC_WR_VAL_0, clr_val)
        self.dtap.start()
        m_tap = self.dtap.mark()
        t_go, _ = await self._hs_start(
            mask=cfg.mask_on, total=cfg.n * cfg.chunk, dst_words=nw, rx_bytes=rx_bytes
        )
        bound = cfg.seg_clks(rx_bytes)
        last_addr = HS_DST + 4 * (nw - 1)
        polls = 0
        while (await self.mem.read(last_addr, 1))[0] == self.sentinel:
            polls += 1
            if self.tw.clk - t_go > bound:
                self._fail(
                    "CHK-HS-CLR",
                    f"last word of chunk {cfg.n} still holds the sentinel {bound} clocks "
                    f"after GO (polls={polls})",
                )
        t_last = self.tw.clk
        await self._wait_clocks(t_last + t_fill)
        ev = self.dtap.since(m_tap)
        clr_rb = (await self.mem.read(CLR_ADDR, 1))[0]
        dest = await self.mem.read(HS_DST, nw)
        clr_idx = [i for i, b in enumerate(ev.aw) if b.addr == CLR_ADDR]
        self.logger.info(
            "OBS-HS-CLR LOG seed=%d clear_aw=%d aw_total=%d clear_aw_clks=%s "
            "clear_aw_size=%s clear_w_strb=%s go_tap_clk=%d last_word_clks_after_go=%d",
            cfg.seed,
            len(clr_idx),
            len(ev.aw),
            ",".join(str(ev.aw[i].clk - m_tap.clk) for i in clr_idx) or "-",
            ",".join(str(ev.aw[i].size) for i in clr_idx) or "-",
            ",".join(f"0x{ev.w[i].strb:x}" if i < len(ev.w) else "-" for i in clr_idx) or "-",
            m_tap.clk,
            t_last - t_go,
        )
        self._probe_log("clear")
        line = (
            f"clear_addr=0x{CLR_ADDR:08x} clear_aw={len(clr_idx)} "
            f"readback=0x{clr_rb:08x} expect=0x{clr_val:08x} pre=0x{self.sentinel:08x} "
            f"clear_src=0x1 clear_bus=0x1 control_hs_aw={hs_aw} "
            f"control_hs_clear_aw={hs_clr_aw} window_clks={t_fill}"
        )
        if hs_aw < 1 or hs_clr_aw != 0:
            self._ctrl_missing("CHK-HS-CLR", line)
        if not clr_idx or clr_rb != clr_val:
            self._fail("CHK-HS-CLR", line)
        self._pass("CHK-HS-CLR", line)
        await self._release(HS_MASK_PASS_MASK | HS_MASK_PASS_INTR_CLEAR)
        close_graded_window(self.logger)
        # Leave GO clear for the next run, also on a DUT that kept it set.
        await dma.wr(DMA_CONTROL, dma.last_control & ~GO_MASK)
        await self.dtap.stop()
        self._expect_rx(FLASH_READ, 1, words_bytes(dest), want=4 * nw, label="clear")

    async def _depth_check(self) -> None:
        cfg = self.cfg_
        await self._cold_reset("depth")
        rx_bytes = cfg.extra_bytes
        mark = await self._spi_sequence(rx_bytes)
        try:
            await self.pads.wait_windows(1, mark, cfg.seg_clks(rx_bytes))
        except SpiPadTimeout as exc:
            self._ctrl_missing("CHK-HS-DEPTH", f"segment of {rx_bytes} bytes did not end: {exc}")
        st = await self.spi.poll_status(lambda s: s.active == 0, 2_000, "depth: ACTIVE=0")
        self.logger.info(
            "CTRL-HS-DEPTH LOG seed=%d rx_bytes=%d rxqd=%d rxfull=%d",
            cfg.seed,
            rx_bytes,
            st.rxqd,
            st.rxfull,
        )
        if st.rxfull:
            self._ctrl_missing(
                "CHK-HS-DEPTH", f"RXFULL=1 after {rx_bytes // 4} words; RX depth is not above W+1"
            )
        words = await self.spi.drain_rx()
        self._expect_rx(FLASH_READ, 1, words_bytes(words), want=rx_bytes, label="depth")

    async def _reference_run(self) -> list[int]:
        cfg = self.cfg_
        await self._cold_reset("reference")
        rx_bytes = cfg.n * cfg.chunk + cfg.extra_bytes
        n_words = rx_bytes // 4
        mark = await self._spi_sequence(rx_bytes)
        words: list[int] = []
        bound = cfg.seg_clks(rx_bytes)
        t0 = self.tw.clk
        while True:
            if self.tw.clk - t0 > bound:
                self._ctrl_missing(
                    "CHK-HS-DATA",
                    f"reference read did not end in {bound} clocks ({len(words)} words)",
                )
            st = await self.spi.read_status()
            if not st.rxempty:
                words.append(await self.spi.rd(RXDATA) & M32)
                continue
            if self.pads.windows_since(mark) and st.active == 0 and st.cmdqd == 0:
                break
        if len(words) != n_words:
            self._ctrl_missing(
                "CHK-HS-DATA", f"reference stream has {len(words)} words, segment holds {n_words}"
            )
        self._expect_rx(FLASH_READ, 1, words_bytes(words), want=rx_bytes, label="reference")
        return words

    async def _trigger_cell(self) -> None:
        """CHK-HS-TRIG-EQ: the trigger rises at RXQD == RX_WATERMARK (C/4 == W)."""
        cfg = self.cfg_
        w = cfg.eq_wm
        await self._cold_reset("trigger")
        # Spec rule: trigger = RXQD >= RX_WATERMARK (TX_WATERMARK 0 keeps the TX term low).
        # MUTATION hook (step 14, item 5): set ``rule_wm = w + 1``; the level
        # expected at RXQD == W turns 0 and CHK-HS-TRIG-EQ fails.
        rule_wm = w
        exp_below = int(w - 1 >= rule_wm)
        exp_at = int(w >= rule_wm)
        await self._spi_config(w)
        open_graded_window(TEST, self.logger)
        m_below = self.trig.mark()
        below_bytes = 4 * (w - 1)
        if below_bytes:
            mark_a = await self._spi_sequence(below_bytes, wm=w)
            await self.spi.wait_segment_done(
                self.pads, mark_a, bound_clks=cfg.seg_clks(below_bytes)
            )
        await ClockCycles(cocotb.top.clk_i, 4)
        st_below = await self.spi.read_status()
        lvl_below = self.tw.level()
        rises_below = self.trig.rises_since(m_below)
        m_at = self.trig.mark()
        mark_b = await self._spi_sequence(4, wm=w)
        wins = await self.spi.wait_segment_done(self.pads, mark_b, bound_clks=cfg.seg_clks(4))
        try:
            rise = await self.trig.wait_rise(m_at, TRIG_RISE_CLKS)
        except BitWatchTimeout:
            rise = None
        st_at = await self.spi.read_status()
        lvl_at = self.tw.level()
        rises_at = self.trig.rises_since(m_at)
        # Both watchers count the same clk_i edges, so the offset converts a
        # trigger clock to a pad clock.
        offset = self.tw.clk - self.pads.now()
        last_edge = wins[0].leading_edge_clks[-1] if wins[0].leading_edge_clks else None
        rise_pad = None if rise is None else rise - offset
        after_last_bit = int(
            rise_pad is not None and last_edge is not None and rise_pad > last_edge
        )
        line = (
            f"width=x1 bytes={4 * w} wm={w} chunk={cfg.eq_chunk} "
            f"rxqd_below={st_below.rxqd} trig_below={lvl_below} rises_below={rises_below} "
            f"rxqd_at={st_at.rxqd} trig_at={lvl_at} rises_at={rises_at} "
            f"rise_pad_clk={rise_pad} last_sample_edge_clk={last_edge} "
            f"after_last_bit={after_last_bit} expect_below={exp_below} expect_at={exp_at}"
        )
        if st_below.rxqd != w - 1 or st_at.rxqd != w:
            self._ctrl_missing("CHK-HS-TRIG-EQ", line)
        ok_below = lvl_below == exp_below and rises_below == exp_below
        ok_at = lvl_at == exp_at and rises_at == exp_at and bool(after_last_bit) == bool(exp_at)
        if not (ok_below and ok_at):
            self._fail("CHK-HS-TRIG-EQ", line)
        self._pass("CHK-HS-TRIG-EQ", line)
        await spi_lane_fcov(TEST, "trigger")
        close_graded_window(self.logger)
        words = await self.spi.drain_rx()
        if below_bytes:
            self._expect_rx(
                FLASH_READ,
                1,
                words_bytes(words[: w - 1]),
                want=below_bytes,
                label="trigger_below",
            )
        self._expect_rx(FLASH_READ, 1, words_bytes(words[w - 1 :]), want=4, label="trigger_at")

    async def _masked_run(
        self, tag: str, mask: int, nw: int, rx_bytes: int, t_fill: int, mask1_filled: int
    ) -> None:
        """CHK-HS-MASKED: with MASK bit 0 clear the engine moves nothing while the trigger is high."""
        cfg = self.cfg_
        await self._cold_reset(tag)
        m_trig = self.trig.mark()
        t_go, masked_mark = await self._hs_start(
            mask=mask, total=cfg.n * cfg.chunk, dst_words=nw, rx_bytes=rx_bytes
        )
        masked_written = 0
        polls = 0
        while self.tw.clk - t_go < t_fill:
            img = await self.mem.read(HS_DST, nw)
            polls += 1
            masked_written += sum(1 for w in img if w != self.sentinel)
        img = await self.mem.read(HS_DST, nw)
        end_written = sum(1 for w in img if w != self.sentinel)
        trig_high = self.trig.high_clocks_since(m_trig)
        go_masked = self._go_cmp(await self.dma.rd(DMA_CONTROL))
        self._probe_log(tag)
        # Negative-control hook: ``masked_written += 1`` here; CHK-HS-MASKED fails.
        line = (
            f"run={tag} dest_sentinel_kept={int(masked_written == 0 and end_written == 0)} "
            f"control_mask1_filled={mask1_filled} trigger_high_clk={trig_high} "
            f"window_clks={t_fill} dest_polls={polls} words_written_end={end_written} "
            f"mask=0x{mask & HS_MASK_FIELD:03x}"
        )
        if trig_high < 1:
            self._ctrl_missing("CHK-HS-MASKED", line)
        self.logger.info(
            "OBS-HS-GO-MASKED LOG seed=%d run=%s go=%d %s",
            cfg.seed,
            tag,
            int(go_masked.ok),
            go_masked.fields(),
        )
        if masked_written or end_written:
            self._fail("CHK-HS-MASKED", line)
        self._pass("CHK-HS-MASKED", line)
        await self._release(HS_MASK_PASS_MASK | HS_MASK_PASS_RUN)
        close_graded_window(self.logger)
        # The masked frame's words stay in the RX FIFO; the host reads them out.
        masked_words = await self._drain_words(rx_bytes // 4, masked_mark, f"{tag} run")
        self._expect_rx(FLASH_READ, 1, words_bytes(masked_words), want=rx_bytes, label=tag)

    async def _clear_obs_run(
        self, variant: str, range_base: int, bus: int, leg: str, rng: SepSeededRng, t_fill: int
    ) -> None:
        """OBS-DMA-CLR-RANGE: the handshake copy with a clear write the text does not cover."""
        cfg = self.cfg_
        dma = self.dma
        nw = cfg.n * cfg.cw
        rx_bytes = cfg.n * cfg.chunk + cfg.extra_bytes
        await self._cold_reset(f"clear_{variant}", session=False)
        clr_val = unique_words(rng, 1, exclude={self.sentinel})[0]
        await self.mem.fill(CLR_ADDR, [self.sentinel])
        await dma.wr(CLEAR_INTR_SRC, 0x1)
        await dma.wr(CLEAR_INTR_BUS, bus)
        await dma.wr(INTR_SRC_ADDR_0, CLR_ADDR)
        await dma.wr(INTR_SRC_WR_VAL_0, clr_val)
        self.dtap.start()
        m_tap = self.dtap.mark()
        m_trig = self.trig.mark()
        t_go, _ = await self._hs_start(
            mask=cfg.mask_on,
            total=cfg.n * cfg.chunk,
            dst_words=nw,
            rx_bytes=rx_bytes,
            range_base=range_base,
        )
        rb = {
            "clear_intr_src": await dma.rd(CLEAR_INTR_SRC),
            "clear_intr_bus": await dma.rd(CLEAR_INTR_BUS),
            "intr_src_addr_0": await dma.rd(INTR_SRC_ADDR_0),
            "range_base": await dma.rd(RANGE_BASE),
            "hs_mask": await dma.rd(HANDSHAKE_INTR_ENABLE),
        }
        want = {
            "clear_intr_src": 0x1,
            "clear_intr_bus": bus,
            "intr_src_addr_0": CLR_ADDR,
            "range_base": range_base,
            "hs_mask": cfg.mask_on & HS_MASK_FIELD,
        }
        # Twice the clocks the handshake run took from GO to its last word.
        await self._wait_clocks(t_go + 2 * t_fill)
        trig_high = self.trig.high_clocks_since(m_trig)
        ev = self.dtap.since(m_tap)
        st = await dma.read_status()
        ecode = await dma.rd(ERROR_CODE)
        go = int(bool(await dma.rd(DMA_CONTROL) & GO_MASK))
        clr_rb = (await self.mem.read(CLR_ADDR, 1))[0]
        moved = sum(self._filled(await self.mem.read(HS_DST, nw), cfg.n))
        clr_idx = [i for i, b in enumerate(ev.aw) if b.addr == CLR_ADDR]
        line = (
            f"variant={variant} "
            + " ".join(f"{k}=0x{rb[k]:x}/0x{want[k]:x}" for k in rb)
            + f" trigger_high_clk={trig_high} window_clks={2 * t_fill}"
        )
        if rb != want or trig_high < 1:
            self._ctrl_missing("CTRL-DMA-CLR-RANGE", line)
        self.logger.info("CTRL-DMA-CLR-RANGE PASS seed=%d %s", cfg.seed, line)
        set_open_value_leg_pass(leg, self.logger)
        await ClockCycles(cocotb.top.clk_i, LABEL_CLKS)
        set_open_value_leg_pass(None, self.logger)
        close_graded_window(self.logger)
        self.logger.info(
            "OBS-DMA-CLR-RANGE LOG seed=%d variant=%s clear_addr=0x%08x range_base=0x%08x "
            "clear_bus=%d clear_aw=%d clear_b_resp=%s aw_total=%d clear_word=0x%08x "
            "clear_wr_val=0x%08x pre=0x%08x chunks_moved=%d/%d go=%d error_code=0x%x %s",
            cfg.seed,
            variant,
            CLR_ADDR,
            range_base,
            bus,
            len(clr_idx),
            ",".join(str(ev.b[i].resp) if i < len(ev.b) else "-" for i in clr_idx) or "-",
            len(ev.aw),
            clr_rb,
            clr_val,
            self.sentinel,
            moved,
            cfg.n,
            go,
            ecode,
            st.fmt(),
        )
        await dma.wr(DMA_CONTROL, dma.last_control & ~GO_MASK)
        await self.dtap.stop()

    async def _tx_cell(self, w: int) -> None:
        """CHK-HS-TRIG-TX: the TX term of the trigger, ``TXQD < TX_WATERMARK``."""
        cfg = self.cfg_
        spi = self.spi
        await self._cold_reset("tx_term", session=False)
        # Set-up, window closed: SPIEN 0 (the TX FIFO keeps its words, no
        # command runs), RX_WATERMARK 1 with RXQD 0 (RX term false),
        # TX_WATERMARK 0, EVENT_ENABLE 0, INTR_ENABLE 0.
        ctrl0 = 1 << CTRL_RX_WM_LSB
        await spi.wr(EVENT_ENABLE, 0)
        await spi.wr(SPI_INTR_ENABLE, 0)
        await spi.wr(SPI_CONTROL, ctrl0)
        await ClockCycles(cocotb.top.clk_i, TX_SETTLE_CLKS)
        st0 = await spi.read_status()
        lvl0 = self.tw.level()
        pre = f"pre_txqd={st0.txqd} pre_rxqd={st0.rxqd} pre_trig={lvl0}"
        if st0.txqd != 0 or st0.rxqd != 0 or lvl0 != 0:
            self._ctrl_missing("CHK-HS-TRIG-TX", f"wm={w} {pre}")
        # Spec rule: trigger = TXQD < TX_WATERMARK while the RX term is false.
        # Negative-control hook: ``txqd <= w``; the state at TXQD = W expects 1 and
        # CHK-HS-TRIG-TX fails there.

        def rule(txqd: int) -> int:
            return int(txqd < w)

        # Negative-control hook: write W + 1 (or 0) while the rule keeps W; the state
        # at TXQD = W (or TXQD = 0) fails and its cell is not sampled.
        wm_written = w
        open_graded_window(TEST, self.logger)
        m_cell = self.trig.mark()
        t_wr = self.tw.clk
        await spi.wr(SPI_CONTROL, ctrl0 | (wm_written << CTRL_TX_WM_LSB))
        states: list[str] = []
        ctrl_bad: list[str] = []
        bad: list[str] = []
        t_edge: dict[str, int | None] = {"rise": None, "fall": None}
        t_last = None
        for k in range(w + 1):
            if k:
                await spi.push_tx(k)
                t_last = self.tw.clk
            exp = rule(k)
            # The first state raises the probe, the state at TXQD = W lowers it;
            # each wait is bounded and a miss fails below.
            want = "rise" if k == 0 else ("fall" if k == w else None)
            if want == "rise" and exp:
                try:
                    t_edge["rise"] = await self.trig.wait_rise(m_cell, TRIG_RISE_CLKS)
                except BitWatchTimeout:
                    bad.append(f"k={k}:no_rise")
            elif want == "fall" and not exp:
                try:
                    t_edge["fall"] = await self.trig.wait_level(0, TRIG_RISE_CLKS)
                except BitWatchTimeout:
                    bad.append(f"k={k}:no_fall")
            st = None
            for _ in range(TX_QD_READS):
                st = await spi.read_status()
                if st.txqd == k:
                    break
            await ClockCycles(cocotb.top.clk_i, TX_SETTLE_CLKS)
            lvl = self.tw.level()
            falls = len(self.trig.fall_clks_since(m_cell))
            rises = self.trig.rises_since(m_cell)
            states.append(f"{k}:txqd={st.txqd},trig={lvl},exp={exp},rises={rises},falls={falls}")
            if st.txqd != k or st.rxqd != 0:
                ctrl_bad.append(f"k={k}")
            # The state at TXQD 0 raises the probe once; it falls only at a
            # state the rule makes 0.
            if lvl != exp or rises != 1 or falls != int(not exp):
                bad.append(f"k={k}")
            if bad or ctrl_bad:
                break
        lat_rise = None if t_edge["rise"] is None else t_edge["rise"] - t_wr
        lat_fall = None if None in (t_edge["fall"], t_last) else t_edge["fall"] - t_last
        self.logger.info(
            "OBS-HS-TRIG-TX-LAT LOG seed=%d wm=%d rise_clks_after_wm_write=%s "
            "fall_clks_after_last_word=%s",
            cfg.seed,
            w,
            lat_rise,
            lat_fall,
        )
        line = (
            f"wm={w} wm_written={wm_written} rx_watermark=1 spien=0 {pre} "
            f"states={';'.join(states)} bad={','.join(bad) or '-'}"
        )
        if ctrl_bad:
            self._ctrl_missing("CHK-HS-TRIG-TX", f"{line} txqd_mismatch={','.join(ctrl_bad)}")
        if bad:
            self._fail("CHK-HS-TRIG-TX", line)
        self._pass("CHK-HS-TRIG-TX", line)
        close_graded_window(self.logger)

    async def _lane_read(self, lanes: int, opcode: int, addr: int, nbytes: int) -> bytes:
        """One flash read at ``lanes`` lanes; returns the RXDATA bytes (``ByteOrder = 1``)."""
        spi = self.spi
        addr_lanes, dummy = LANE_SHAPE[opcode]
        a = addr.to_bytes(3, "big")
        if addr_lanes == 1:
            tx_segs = [(1, bytes([opcode]) + a)]
        else:
            tx_segs = [(1, bytes([opcode])), (addr_lanes, a)]
        # Each TX segment takes its own TXDATA words: the host drops the unused
        # bytes of a word at the end of a segment.
        for _, seg in tx_segs:
            padded = seg + b"\0" * (-len(seg) % 4)
            for j in range(0, len(padded), 4):
                await spi.push_tx(int.from_bytes(padded[j : j + 4], "little"))
        mark = self.pads.mark()
        for seg_lanes, seg in tx_segs:
            await spi.issue_command(
                command_word(len(seg) - 1, speed=SPEED[seg_lanes], direction=DIR_TX, csaat=1)
            )
        if dummy:
            await spi.issue_command(
                command_word(dummy - 1, speed=SPEED[lanes], direction=DIR_DUMMY, csaat=1)
            )
        await spi.issue_command(
            command_word(nbytes - 1, speed=SPEED[lanes], direction=DIR_RX, csaat=0)
        )
        words = await self._drain_words(nbytes // 4, mark, f"lane read x{lanes}")
        return words_bytes(words)

    async def _lane_leg(self) -> None:
        """CHK-HS-LANE-RX: one read at x1, x2 and x4, in the seeded order."""
        cfg = self.cfg_
        await self._cold_reset("lanes")
        # The rst_ni pulse clears the SPI host configuration (SPIEN, CONFIGOPTS).
        await self._spi_config(cfg.wm)
        open_graded_window(TEST, self.logger)
        for lanes in cfg.lane_order:
            opcode, addr, data = cfg.lane_reads[lanes]
            delivered = await self._lane_read(lanes, opcode, addr, len(data))
            line = (
                f"width=x{lanes} opcode=0x{opcode:02x} addr=0x{addr:06x} bytes={len(data)} "
                f"expected={data.hex()} delivered={delivered.hex()}"
            )
            if delivered != data:
                self._fail("CHK-HS-LANE-RX", line)
            self._pass("CHK-HS-LANE-RX", line)
            # MUTATION hook (step 14, item 11d): for lanes == 2 register
            # ``delivered`` with one byte flipped (XOR 0xFF); the byte count
            # stays the same, so CHK-SPI-SB-RX fails on the x2 byte compare.
            self._expect_rx(opcode, lanes, delivered, want=len(data), label=f"lane_x{lanes}")
        close_graded_window(self.logger)

    async def run_scenario(self) -> None:
        self.cfg_ = cfg = _Cfg(self.random_seed())
        self.n_checks = 0
        self.sess = None
        dut = cocotb.top
        if FOUR_LANE_PLUSARG not in cocotb.plusargs:
            raise AssertionError(
                f"{TEST} needs +{FOUR_LANE_PLUSARG}: the DUT must receive spi_sd_i on every lane"
            )
        self.logger.info(
            "INFO-PLAN seed=%d runs=depth,reference,trigger,lanes,normal,handshake,masked,stop,clear,"
            "masked_alt,tx_term,clear_outside_range,clear_bus0 graded=trigger,lanes,handshake,masked,stop,clear,"
            "masked_alt,tx_term checks=CHK-HS-MASKED,CHK-HS-GO,CHK-HS-STOP,CHK-HS-NOCHUNK,"
            "CHK-HS-DATA,CHK-HS-TRIG-EQ,CHK-HS-TRIG-TX,CHK-HS-LANE-RX,CHK-HS-CLR,"
            "CHK-SPI-SESSION-FRAMES,CHK-SPI-SB-RX,CHK-SPI-WIRE",
            cfg.seed,
        )
        self.logger.info(
            "INFO-DRAW seed=%d chunk=%d n=%d mask_hi=0x%03x n_stop=%d clkdiv=%d wm=%d "
            "chunks_total_stop=%d eq_wm=%d eq_chunk=%d",
            cfg.seed,
            cfg.chunk,
            cfg.n,
            cfg.mask_hi,
            cfg.n_stop,
            cfg.clkdiv,
            cfg.wm,
            cfg.chunks_total_stop,
            cfg.eq_wm,
            cfg.eq_chunk,
        )
        self.logger.info(
            "INFO-DRAW seed=%d flash_addr=0x%06x flash_words=%s",
            cfg.seed,
            FLASH_ADDR,
            ",".join(f"{w:08x}" for w in cfg.flash_words),
        )
        self.logger.info(
            "INFO-DRAW seed=%d lane_order=%s lane_reads=%s",
            cfg.seed,
            ",".join(f"x{lanes}" for lanes in cfg.lane_order),
            " ".join(
                f"x{lanes}:op=0x{op:02x},addr=0x{addr:06x},bytes={len(data)}"
                for lanes, (op, addr, data) in sorted(cfg.lane_reads.items())
            ),
        )
        self.logger.info(
            "INFO-DRAW seed=%d nm_sentinel=0x%08x nm_src_words=%d",
            cfg.seed,
            cfg.nm_sentinel,
            len(cfg.nm_src),
        )

        self.write_efuse_image(SepEfuseImage().load(str(EFUSE_IMAGE)))
        await self.bring_up_no_cpu(max_cycles=SENSE_CYCLES)
        self.suppress_host_axi_transaction_info()
        self.tw = SepBitWatch(dut.spi_lsio_trigger_probe_o, {"trig": 0}).start()
        self.trig = self.tw
        self.busy = SepBitWatch(dut.dma_busy_probe_o, {"busy": 0}).start()
        self.irq = SepBitWatch(dut.sep_internal_interrupts_probe_o, {"chunk": 9, "done": 8}).start()
        self.pads = SepSpiPadSampler(keep_edges=False).start()
        self.spi = SepSpiHostOps(self, clock=self.pads.now)
        self.dma = SepDmaOps(self)
        self.mem = SepMemWords(self)
        # Runs only inside the handshake and interrupt-clear runs, never across
        # an rst_ni pulse.
        self.dtap = SepDmaTap(dut)
        self.wire = SepSpiWireMonitor(dut, name="sep_spi_hs_wire")
        self.flash = OcahSpiFlash(
            dut.spi_cs_n_o,
            dut.spi_sck_o,
            dq_out=dut.spi_sd_o,
            dq_in=dut.spi_sd_i,
            mode="quad_io",
            name="sep_spi_hs_flash",
        )
        self.flash.write_memory(FLASH_ADDR, cfg.flash_bytes())
        for _, addr, data in cfg.lane_reads.values():
            self.flash.write_memory(addr, data)
        self.flash.init_signals()
        await self.flash.start()
        try:
            await self._body()
        finally:
            close_graded_window(self.logger)
            if self.sess is not None:
                # Only after an earlier failure: stop without grading.
                self.sess = None
                try:
                    await self.wire.monitor.stop()
                except AssertionError as exc:
                    self.logger.error("SPI wire monitor stop after a failure: %s", exc)
            await self.flash.stop()
            for w in (self.tw, self.busy, self.irq):
                await w.stop()
            await self.dtap.stop()
            await self.pads.stop()
        self.result_pass(TEST, cfg.seed, self.n_checks)

    async def _normal_control(self) -> dict:
        """Normal-mode control (no SPI traffic, no monitor session): a memory-to-memory copy."""
        cfg = self.cfg_
        await self._cold_reset("normal", session=False)
        dma = self.dma
        await dma.program_range(SRAM_BASE, NM_RANGE_LIMIT)
        await dma.wr(SECURE_DMA.addr("ADDR_SPACE_ID"), ASID)
        await self.mem.fill(NM_SRC, cfg.nm_src)
        await self.mem.fill(NM_DST, [cfg.nm_sentinel] * (NM_TOTAL // 4))
        await dma.program_transfer(
            src=NM_SRC, dst=NM_DST, total=NM_TOTAL, chunk=NM_CHUNK, width_enc=2
        )
        await dma.wr(INTR_ENABLE, INTR_EN_CHUNK | INTR_EN_DONE)
        m_irq = self.irq.mark()
        await dma.go(opcode=OP_COPY, hs=0, initial=1)
        res = await dma.run_to_done(NM_TOTAL, busy=self.busy, w1c_chunk_done=True)
        st = res.status
        statuses = list(res.statuses)
        if st.busy:
            st = await dma.poll_status(lambda s: s.busy == 0, 2_000, "normal mode: BUSY=0")
            statuses.append(st)
        irq_rises = self.irq.rises_since(m_irq, "chunk")
        nm_done_rises = self.irq.rises_since(m_irq, "done")
        nm_chunk_polls = sum(s.chunk_done for s in statuses)
        go_nm = self._go_cmp(await dma.rd(DMA_CONTROL))
        nm_img = await self.mem.read(NM_DST, NM_TOTAL // 4)
        self.logger.info(
            "CTRL-HS-NORMAL LOG seed=%d done=%d error=%d polls=%d polls_with_chunk_done=%d "
            "chunk_irq_rises=%d go_writes=%d go=%d image_equal=%d",
            cfg.seed,
            st.done,
            st.error,
            len(statuses),
            nm_chunk_polls,
            irq_rises,
            res.go_writes,
            int(bool(go_nm.got & GO_MASK)),
            int(nm_img == cfg.nm_src),
        )
        if not st.done or st.error:
            self._ctrl_missing("CHK-HS-GO", f"normal-mode copy did not end in DONE: {st.fmt()}")
        return {
            "polls": len(statuses),
            "chunk_polls": nm_chunk_polls,
            "chunk_irq_rises": irq_rises,
            "done_irq_rises": nm_done_rises,
            "go": int(bool(go_nm.got & GO_MASK)),
        }

    def _grade_nochunk(self, hs_polls, hs_irq_rises: int, hs_irq_high: int, hs_intr_en: int, nm):
        """CHK-HS-NOCHUNK on the handshake run, with the normal-mode controls."""
        hs_chunk_polls = sum(st.chunk_done for st in hs_polls)
        line = (
            f"polls_with_chunk_done={hs_chunk_polls} polls={len(hs_polls)} "
            f"chunk_irq_rises={hs_irq_rises} chunk_irq_high_clks={hs_irq_high} "
            f"control_normal_polls={nm['polls']} control_chunk_irq_rises={nm['chunk_irq_rises']} "
            f"control_normal_polls_with_chunk_done={nm['chunk_polls']} "
            f"control_hs_intr_enable=0x{hs_intr_en:08x}"
        )
        # The poll leg and the line leg each need their own control: a dead or
        # mis-bound bit-9 tap reads 0 here, and so does a handshake run whose
        # INTR_ENABLE.DMA_CHUNK_DONE write did not land.
        if nm["chunk_polls"] < 1 or nm["chunk_irq_rises"] < 1 or not hs_intr_en & INTR_EN_CHUNK:
            self._ctrl_missing("CHK-HS-NOCHUNK", line)
        if hs_chunk_polls or hs_irq_rises or hs_irq_high:
            self._fail("CHK-HS-NOCHUNK", line)
        self._pass("CHK-HS-NOCHUNK", line)

    def _grade_go_total(
        self,
        *,
        ctl_total: int,
        st_total: DmaStatus,
        ctl_after: int,
        st_after: DmaStatus,
        done_before_total: list[int],
        hs_done_rises: list[int],
        hs_done_level: int,
        hs_dst_aw: list[int],
        hs_intr_en: int,
        nm,
        t_fill: int,
    ) -> None:
        """CHK-HS-GO, leg ``total`` (handshake run).

        "For hardware handshake operation, the DMA engine keeps the `go` bit
        set across chunks and clears it, setting `status.done`, once
        `total_data_size` bytes have been transferred." (secure_dma.adoc,
        CONTROL.GO): GO=0 with DONE=1 after the t_fill wait that follows the
        total. "An interrupt is raised when the entire data transfer (as
        defined by `TOTAL_DATA_SIZE`) is complete." (dma programmers_guide.md,
        Transfer Completion): with INTR_ENABLE.DMA_DONE=1, PIC source 9 (bit 8
        of sep_internal_interrupts_probe_o) rises once, after the last write to
        the destination, and is high at the end of the wait. The text states
        no clock for the clear, so CONTROL and STATUS read as soon as the
        destination holds the total are logged only.
        """
        cfg = self.cfg_
        go_at_total = int(bool(ctl_total & GO_MASK))
        go_after_total = int(bool(ctl_after & GO_MASK))
        last_dst_aw = max(hs_dst_aw) if hs_dst_aw else None
        done_irq_after_last_write = int(
            len(hs_done_rises) == 1 and last_dst_aw is not None and hs_done_rises[0] > last_dst_aw
        )
        line = (
            f"leg=total go_after_total={go_after_total} "
            f"done_after_total={st_after.done} control_after_total=0x{ctl_after:08x} "
            f"done_irq_rises={len(hs_done_rises)} done_irq_level={hs_done_level} "
            f"done_irq_after_last_write={done_irq_after_last_write} "
            f"control_normal_go={nm['go']} "
            f"control_done_before_total={int(0 in done_before_total)} "
            f"control_normal_done_irq_rises={nm['done_irq_rises']} "
            f"control_dst_aw={len(hs_dst_aw)}"
        )
        # Controls: the normal-mode copy ends with GO=0 and raises the done
        # line (a dead or mis-bound bit-8 tap fails), a poll of the handshake
        # run before the total reads DONE=0 (a DONE bit that reads 1 regardless
        # fails), INTR_ENABLE.DMA_DONE reads back set, and the tap saw the
        # destination writes the done rise is ordered against.
        if (
            nm["go"] != 0
            or 0 not in done_before_total
            or nm["done_irq_rises"] < 1
            or not hs_intr_en & INTR_EN_DONE
            or not hs_dst_aw
        ):
            self._ctrl_missing("CHK-HS-GO", line)
        self.logger.info(
            "OBS-HS-GO-TOTAL seed=%d go_at_total=%d done_at_total=%d control_at_total=0x%08x "
            "t_fill=%d",
            cfg.seed,
            go_at_total,
            st_total.done,
            ctl_total,
            t_fill,
        )
        if (
            go_after_total != 0
            or st_after.done != 1
            or not done_irq_after_last_write
            or hs_done_level != 1
        ):
            self._fail("CHK-HS-GO", line)
        self._pass("CHK-HS-GO", line)

    def _grade_go_between(self, go_before: int, n_moved: int, n_re: int, n_tot: int) -> None:
        """CHK-HS-GO, leg ``between_chunks`` (stop run): GO reads 1 below the total."""
        line = (
            f"leg=between_chunks go_held_between_chunks={go_before} "
            f"chunks_moved={n_re} chunks_total={n_tot}"
        )
        # Control: at least one chunk moved and fewer than the total.
        if n_moved < 1 or n_re >= n_tot:
            self._ctrl_missing("CHK-HS-GO", line)
        if go_before != 1:
            self._fail("CHK-HS-GO", line)
        self._pass("CHK-HS-GO", line)

    async def _body(self) -> None:
        cfg = self.cfg_
        nw = cfg.n * cfg.cw

        # Steps 1-3: depth check (control).
        await self._depth_check()

        # Step 4: reference run (control) and the sentinel.
        ref = await self._reference_run()
        ref_set = set(ref)
        self.sentinel = unique_words(cfg.rng, 1, exclude=ref_set)[0]
        ref_distinct = int(len(set(ref[:nw])) == nw)
        # Golden of CHK-HS-DATA: the flash bytes at address 0, packed with
        # ByteOrder = 1 (the first byte received lands in RXDATA[7:0]).
        fb = cfg.flash_bytes()
        golden = [int.from_bytes(fb[4 * i : 4 * i + 4], "little") for i in range(nw)]
        # MUTATION hook (step 14, item 2): reverse the chunk order of ``golden``
        # (chunks of cfg.cw words); CHK-HS-DATA fails.
        ref_match = sum(1 for i in range(nw) if ref[i] == golden[i])
        self.logger.info(
            "CTRL-HS-REF LOG seed=%d words=%d ref_distinct=%d ref_match_golden=%d/%d "
            "sentinel=0x%08x ref=%s",
            cfg.seed,
            len(ref),
            ref_distinct,
            ref_match,
            nw,
            self.sentinel,
            ",".join(f"{w:08x}" for w in ref),
        )

        # Trigger cell and lane reads.
        await self._trigger_cell()
        await self._lane_leg()

        # Steps 10-12: normal-mode control, before the handshake run so that
        # CHK-HS-NOCHUNK and CHK-HS-GO grade inside the handshake window.
        nm = await self._normal_control()

        # Steps 5-6: handshake run, mask bit 0 set.
        await self._cold_reset("handshake")
        rx_bytes = cfg.n * cfg.chunk + cfg.extra_bytes
        bound = cfg.seg_clks(rx_bytes)
        await self.dma.wr(INTR_ENABLE, INTR_EN_CHUNK | INTR_EN_DONE)
        # Control of the line legs of CHK-HS-NOCHUNK and CHK-HS-GO: INTR_ENABLE
        # resets to 0, so a lost write would also keep bits 9 and 8 low.
        hs_intr_en = await self.dma.rd(INTR_ENABLE)
        self.logger.info(
            "CTRL-HS-INTR-EN LOG seed=%d intr_enable=0x%08x chunk_en=%d done_en=%d",
            cfg.seed,
            hs_intr_en,
            int(bool(hs_intr_en & INTR_EN_CHUNK)),
            int(bool(hs_intr_en & INTR_EN_DONE)),
        )
        m_hs_irq = self.irq.mark()
        self.dtap.start()
        m_hs_tap = self.dtap.mark()
        t_go, _ = await self._hs_start(
            mask=cfg.mask_on, total=cfg.n * cfg.chunk, dst_words=nw, rx_bytes=rx_bytes
        )
        hs_polls: list[DmaStatus] = []
        last_addr = HS_DST + 4 * (nw - 1)
        while True:
            if self.tw.clk - t_go > bound:
                msg = (
                    f"FAIL-DMA-TIMEOUT seed={cfg.seed}: last word of chunk {cfg.n} still holds the "
                    f"sentinel {bound} clocks after GO (polls={len(hs_polls)})"
                )
                self.logger.error(msg)
                raise AssertionError(msg)
            hs_polls.append(await self.dma.read_status())
            if (await self.mem.read(last_addr, 1))[0] != self.sentinel:
                break
        t_fill = self.tw.clk - t_go
        dest = await self.mem.read(HS_DST, nw)
        mismatch = [i for i in range(nw) if dest[i] != golden[i]]
        line = (
            f"width=x1 bytes={4 * nw} words={nw} chunks={cfg.n} chunk={cfg.chunk} wm={cfg.wm} "
            f"mask=0x{cfg.mask_on:03x} mismatch={len(mismatch)} "
            f"first_mismatch_word={mismatch[0] if mismatch else '-'} ref_distinct={ref_distinct} "
            f"dest={','.join(f'{w:08x}' for w in dest)}"
        )
        if not ref_distinct:
            self._ctrl_missing("CHK-HS-DATA", line)
        if mismatch:
            self._fail("CHK-HS-DATA", line)
        self._pass("CHK-HS-DATA", line)
        self._expect_rx(FLASH_READ, 1, words_bytes(dest), want=4 * nw, label="handshake")
        self.logger.info(
            "INFO-T-FILL LOG seed=%d t_fill_clks=%d polls=%d", cfg.seed, t_fill, len(hs_polls)
        )
        # CHK-HS-GO at the total: CONTROL and STATUS once the destination holds
        # TOTAL_DATA_SIZE bytes (logged), and again after a further t_fill wait
        # (graded).
        n_polls_before_total = len(hs_polls)
        ctl_total = await self.dma.rd(DMA_CONTROL)
        st_total = await self.dma.read_status()
        t1 = self.tw.clk
        while self.tw.clk - t1 < t_fill:
            hs_polls.append(await self.dma.read_status())
        ctl_after = await self.dma.rd(DMA_CONTROL)
        st_after = await self.dma.read_status()
        hs_done_rises = self.irq.rise_clks_since(m_hs_irq, "done")
        hs_done_level = self.irq.level("done")
        hs_ev = self.dtap.since(m_hs_tap)
        # The tap and the interrupt watch count the same clk_i edges from
        # marks taken at one time step, so a tap clock maps onto the watch.
        tap_to_irq = m_hs_irq.clk - m_hs_tap.clk
        hs_dst_aw = [
            b.clk + tap_to_irq
            for b in hs_ev.aw
            if b.addr is not None and HS_DST <= b.addr < HS_DST + 4 * nw
        ]
        # Control of CHK-HS-CLR: CLEAR_INTR_SRC = 0 from reset.
        hs_clr_aw = sum(1 for b in hs_ev.aw if b.addr == CLR_ADDR)
        hs_aw = len(hs_ev.aw)
        hs_irq_rises = self.irq.rises_since(m_hs_irq, "chunk")
        hs_irq_high = self.irq.high_clocks_since(m_hs_irq, "chunk")
        self._probe_log("handshake")
        for i, st in enumerate(hs_polls):
            self.logger.debug("INFO-HS-POLL %d %s", i, st.fmt())
        hs_chunk_polls = sum(st.chunk_done for st in hs_polls)
        self.logger.info(
            "INFO-HS-POLL LOG seed=%d polls=%d polls_with_chunk_done=%d chunk_irq_rises=%d "
            "chunk_irq_high_clks=%d last=%s",
            cfg.seed,
            len(hs_polls),
            hs_chunk_polls,
            hs_irq_rises,
            hs_irq_high,
            hs_polls[-1].fmt(),
        )
        self._grade_nochunk(hs_polls, hs_irq_rises, hs_irq_high, hs_intr_en, nm)
        self._grade_go_total(
            ctl_total=ctl_total,
            st_total=st_total,
            ctl_after=ctl_after,
            st_after=st_after,
            done_before_total=[p.done for p in hs_polls[:n_polls_before_total]],
            hs_done_rises=hs_done_rises,
            hs_done_level=hs_done_level,
            hs_dst_aw=hs_dst_aw,
            hs_intr_en=hs_intr_en,
            nm=nm,
            t_fill=t_fill,
        )
        await self._release(HS_MASK_PASS_MASK | HS_MASK_PASS_RUN)
        close_graded_window(self.logger)
        # Leave GO clear for the next run, also on a DUT that kept it set.
        await self.dma.wr(DMA_CONTROL, self.dma.last_control & ~GO_MASK)
        await self.dtap.stop()
        mask1_filled = 1  # the poll above ended on a non-sentinel last word

        # Step 7: masked run, mask bit 0 clear.
        await self._masked_run("masked", cfg.mask_off, nw, rx_bytes, t_fill, mask1_filled)

        # Step 8: stop run.
        await self._cold_reset("stop")
        n_tot = cfg.chunks_total_stop
        tot_words = n_tot * cfg.cw
        rx_stop = cfg.n_stop * cfg.chunk + cfg.extra_bytes
        t_go, pad_mark = await self._hs_start(
            mask=cfg.mask_on, total=n_tot * cfg.chunk, dst_words=tot_words, rx_bytes=rx_stop
        )
        await self.spi.wait_segment_done(self.pads, pad_mark, bound_clks=cfg.seg_clks(rx_stop))
        img1 = await self._stable_image(tot_words, t_fill, "first segment")
        filled = self._filled(img1, n_tot)
        n_moved = sum(filled)
        self.logger.info(
            "INFO-STOP-PRE LOG seed=%d n_moved=%d chunks_total=%d filled=%s",
            cfg.seed,
            n_moved,
            n_tot,
            "".join(str(int(f)) for f in filled),
        )
        # Engine state while GO is 1 and the trigger is low: STATUS.BUSY,
        # CFG_REGWEN and the DMA busy output, read before the re-trigger.
        wait_st = DmaStatus(await self.dma.rd(DMA_STATUS))
        wait_regwen = await self.dma.rd(DMA_CFG_REGWEN)
        self.logger.info(
            "OBS-DMA-HS-WAIT LOG seed=%d busy=%d cfg_regwen=0x%x busy_probe=%s",
            cfg.seed,
            wait_st.busy,
            wait_regwen,
            self.busy.level(),
        )
        # Re-trigger leg, GO still 1: the DMA drained RXQD below RX_WATERMARK, so
        # the trigger is low; a second segment of W+1 words raises it again and
        # the engine moves the next chunk (OpenTitan DMA theory of operation:
        # an assertion of an enabled trigger moves an entire chunk; while it is
        # not asserted the engine waits for the next chunk).
        # Stream of the RX FIFO: the first segment, then the second segment;
        # each segment is a READ at flash address 0.
        stream = cfg.flash_words[: rx_stop // 4] + cfg.flash_words[: cfg.extra_bytes // 4]
        re_low_before = int(self.tw.level() == 0)
        m_re = self.trig.mark()
        mark_re = await self._spi_sequence(cfg.extra_bytes)
        await self.spi.wait_segment_done(
            self.pads, mark_re, bound_clks=cfg.seg_clks(cfg.extra_bytes)
        )
        img_re = await self._stable_image(tot_words, t_fill, "re-trigger segment")
        re_rises = self.trig.rises_since(m_re)
        filled_re = self._filled(img_re, n_tot)
        n_re = sum(filled_re)
        re_words = n_re * cfg.cw
        re_data = int(
            img_re[:re_words] == stream[:re_words]
            and all(w == self.sentinel for w in img_re[re_words:])
        )
        self.logger.info(
            "OBS-STOP-RETRIG LOG seed=%d n_moved_retrigger=%d filled=%s trigger_low_before=%d "
            "trigger_rises=%d",
            cfg.seed,
            n_re,
            "".join(str(int(f)) for f in filled_re),
            re_low_before,
            re_rises,
        )
        # Step 9: GO clear, more Rx data.
        # Control: GO still reads 1 before the clear, so the stop is caused by
        # the firmware write and not by an engine that cleared GO itself.
        go_before = int(bool(await self.dma.rd(DMA_CONTROL) & GO_MASK))
        self._grade_go_between(go_before, n_moved, n_re, n_tot)
        stop_ctrl = self.dma.last_control & ~GO_MASK
        m_trig = self.trig.mark()
        await self.dma.wr(DMA_CONTROL, stop_ctrl)
        t_clr = self.tw.clk
        mark_more = await self._spi_sequence(cfg.extra_bytes)
        await self._wait_clocks(t_clr + t_fill)
        trig_high = self.trig.high_clocks_since(m_trig)
        # "Firmware clears the go bit to stop the hardware handshake operation
        # earlier." (secure_dma.adoc, CONTROL.GO): GO reads 0 after the clear.
        go_after_clear = int(bool(await self.dma.rd(DMA_CONTROL) & GO_MASK))
        img3 = await self.mem.read(HS_DST, tot_words)
        after = img3[re_words:]
        after_kept = int(all(w == self.sentinel for w in after))
        moved_kept = int(img3[:re_words] == img_re[:re_words])
        self._probe_log("stop")
        line = (
            f"n_stop={cfg.n_stop} n_moved={n_moved} n_moved_retrigger={n_re} "
            f"chunks_total={n_tot} re_data_match={re_data} "
            f"control_re_trigger_low_before={re_low_before} "
            f"control_re_trigger_rises={re_rises} "
            f"dest_after_clear_sentinel={after_kept} trigger_high_clk={trig_high} "
            f"window_clks={t_fill} go_before_clear={go_before} "
            f"control_after_clear=0x{stop_ctrl:08x} go_after_clear={go_after_clear} "
            f"moved_unchanged={moved_kept}"
        )
        # GO=1 before the clear is graded by CHK-HS-GO (leg=between_chunks) above.
        if n_moved < 1 or n_re >= n_tot or trig_high < 1:
            self._ctrl_missing("CHK-HS-STOP", line)
        if not re_low_before or re_rises < 1:
            self._ctrl_missing("CHK-HS-STOP", line)
        # With GO=1 the trigger that rises again moves the next chunk.
        if n_re <= n_moved or not re_data:
            self._fail("CHK-HS-STOP", line)
        if not (after_kept and moved_kept) or go_after_clear != 0:
            self._fail("CHK-HS-STOP", line)
        self._pass("CHK-HS-STOP", line)
        await self._release(HS_MASK_PASS_MASK | HS_MASK_PASS_RUN)
        close_graded_window(self.logger)
        # The words the DMA left in the RX FIFO (rest of the first two frames,
        # then the third frame) go out through RXDATA.
        moved = img3[:re_words]
        held = rx_stop // 4 + cfg.extra_bytes // 4
        rest = await self._drain_words(
            held - len(moved) + cfg.extra_bytes // 4, mark_more, "stop run after the GO clear"
        )
        got = moved + rest
        f1, f2 = rx_stop // 4, held
        self._expect_rx(FLASH_READ, 1, words_bytes(got[:f1]), want=rx_stop, label="stop_first")
        self._expect_rx(
            FLASH_READ, 1, words_bytes(got[f1:f2]), want=cfg.extra_bytes, label="stop_retrigger"
        )
        self._expect_rx(
            FLASH_READ, 1, words_bytes(got[f2:]), want=cfg.extra_bytes, label="stop_more"
        )

        # Interrupt-clear run: the handshake copy with the source 0 clear write.
        await self._clear_run(nw, rx_bytes, t_fill, hs_clr_aw, hs_aw)

        # Appended draws: the second masked run and the TX-term cell. The
        # second masked run takes the masked class the first one did not.
        alt_hi = 1 + cfg.rng.randrange(HS_MASK_FIELD >> 1)
        mask_alt = 0 if cfg.mask_hi else alt_hi << 1
        tx_wm = cfg.rng.randrange(1, 5)
        self.logger.info(
            "INFO-DRAW seed=%d alt_hi=0x%03x mask_alt=0x%03x tx_wm=%d",
            cfg.seed,
            alt_hi,
            mask_alt,
            tx_wm,
        )
        await self._masked_run("masked_alt", mask_alt, nw, rx_bytes, t_fill, mask1_filled)
        await self._tx_cell(tx_wm)

        # Clear-range and clear-bus runs.
        clr_rng = SepSeededRng(cfg.seed ^ CLR_SALT)
        for variant, range_base, bus, leg in CLR_VARIANTS:
            await self._clear_obs_run(variant, range_base, bus, leg, clr_rng, t_fill)
