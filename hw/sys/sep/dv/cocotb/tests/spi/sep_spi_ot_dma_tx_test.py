# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SRAM data reaches the flash through the Secure DMA and SPI TX FIFO, paced by the TX watermark.

SPI DMA-TX breadth: the TX complement of
`sep_spi_ot_dma_rx_test` (SPI RX FIFO -> DMA -> SRAM). Here SRAM -> Secure DMA (hardware
handshake) -> OT SPI host TX FIFO -> flash: the OT SPI TX watermark drives
lsio_trigger, which refills the TX FIFO from SRAM a 16-byte chunk at a time. RX is
held quiescent so the single lsio_trigger (= tx_wm | rx_wm) is TX-watermark-driven.

The DMA feeds a real flash program stream (opcode + 24-bit addr + data) from SRAM;
the firmware then reads the flash back over SPI and value-checks it; and an
independent cocotb BFM golden confirms the flash memory == the SRAM source. Distinct
from `sep_spi_ot_dma_rx_test` (RX direction) -- reuses that test's lsio_trigger /
DMA hardware-handshake bring-up.

Each case programs at one lane width: PAGE PROGRAM 0x02 (one standard TX segment)
or QUAD PAGE PROGRAM 0x32 (opcode and address in a standard TX segment with CS
held, then the data in a quad TX segment). Every run has at least one case of
each. The flash model has no dual program, so x2 TX data is graded elsewhere.
The flash model sits on all four data lanes (``mode="quad_io"``, ``dq_out`` =
``spi_sd_o``, ``dq_in`` = ``spi_sd_i``) and the testlist passes
``+sep_spi_four_lane``.

Randomization ([RAND-REP], single source of truth): SepSpiDmaTxCfg walks all
required discrete DMA length / trigger cells in one run (nwords={7,11,15}, all
multi-chunk transfers) and randomizes legal page-aligned flash addresses, payload
words and the program opcode of each case from the runner seed: one case takes
0x02, one takes 0x32, and the third is drawn; the seed shuffles the order. The
resolved table is patched into the firmware g_spi3_params block in the staged
DTCM image and logged.

Checks:
  firmware self-check (each logs a PASS line):
    CHK-TRIGGER   : the TX-watermark source of lsio_trigger (STATUS.TXWM) tracks
                    TXQD across TX_WATERMARK (empty->1, fill->0, SW_RST drain->1,
                    values logged). EVENT_ENABLE.TXWM is programmed.
    CHK-DMA-DONE  : DMA STATUS.done, error==0, ERROR_CODE==0; done still set on a
                    second read, then STATUS RW1C clears.
                    Handshake mode does not raise STATUS.chunk_done (RTL: only when
                    hardware handshake is off); sep_dma_basic_test covers that status.
    CHK-SPI-IDLE  : OT SPI reaches idle, ERROR_STATUS==0.
    CHK-DMA-TX    : flash read-back == the DMA-fed data (SRAM->DMA->TXFIFO->flash),
                    and the device accepted each program (its frame ended on a
                    byte boundary). One PASS line per case names its opcode,
                    width and byte count; the leaf requires them in case order.
    CHK-NONVAC    : the programmed data differs from the erased 0xFF (data landed).
    CHK-ERR-OVERFLOW : ERROR_STATUS.OVERFLOW is still clear when STATUS.TXFULL
                    first reads 1, and the next TXDATA write latches exactly
                    ERROR_STATUS.OVERFLOW; CTRL.SW_RST + W1C releases the host and
                    a flash RDSR round trip proves it runs again. This is the TX
                    flow-control edge the watermark-paced DMA never reaches, so
                    nothing else in the test proves the host reports it.
  cocotb golden cross-check:
    BFM golden (logged as "SPI DMA-TX breadth GOLDEN PASS"): the BFM saw at least
                      _BREADTH_FLOOR WREN and program transactions, one program
                      with the case's opcode at each random addr with that case's
                      data, and BFM memory == the SRAM source pattern.
    CHK-SPI-SB-TX   : per case, the SRAM source bytes equal the monitor's wire
                      decode at the case's lane width and the flash record's
                      ``data_in``.
    CHK-MULTICHUNK  : the TX watermark paced every DMA transfer. A watch-only
                      probe samples the DMA input trigger and the SPI TX FIFO depth
                      (TXQD) on each clock while DMA STATUS.busy is set. Per case,
                      the DMA saw at least `chunks` (and at least 2) separate
                      trigger assertions, and TXQD never went above
                      TX_WATERMARK - 1 + one chunk (7 words). A trigger held high,
                      or a DMA that refills without waiting for the watermark,
                      fills the FIFO past that bound in one burst.

main() returns the error count; fw/startup/crt0.s emits PASS (0xCAFEBABE) / FAIL (0xDEADBEEF).

Run mode: cpu with +skip_fuse_sense.
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path

import cocotb
import pyuvm
from cocotb.triggers import FallingEdge, RisingEdge
from env.sep_boot_scoreboard import SepBootScoreboard
from env.sep_dtcm_param_patch import patch_param_block
from env.sep_log_error_counter import attach_error_counter
from env.sep_seeded_rng import SepSeededRng
from env.sep_spi_lane_responder import spi_lane_fcov
from env.sep_spi_scoreboard import SepSpiScoreboard
from env.sep_spi_wire_monitor import SepSpiWireMonitor
from ocah_spi_vip import OcahSpiFlash
from sep_base_test import sep_base_test
from sep_reg_meta import sym

_DV_ROOT = str(Path(__file__).resolve().parents[3])
_FW_DIR = os.path.join(_DV_ROOT, "fw", "build", "tests", "spi_ot_dma_tx_test")
_ITCM_HEX = os.path.join(_FW_DIR, "spi_ot_dma_tx_test.itcm.hex")
_DTCM_HEX = os.path.join(_FW_DIR, "spi_ot_dma_tx_test.dtcm.hex")

_ICCM_BASE = sym("SEP_ICCM_MEM_BASE_ADDR")
_MAX_RUN_CYCLES = 3_000_000
_NO_BOOT_CYCLES = 80_000
_PROGRESS_EVERY = 5_000
_BANNER = "SEP SPI OT DMA TX test"
_TEST = "sep_spi_ot_dma_tx_test"

_PARAM_MAGIC = 0x5A11D00E  # mirror g_spi3_params[0] in spi_ot_dma_tx_test.c
_PAGE_SIZE = 256
_SECTOR_SIZE = 4096
_FLASH_PAGES = 32 * (_SECTOR_SIZE // _PAGE_SIZE)
_MAX_WORDS = 16
# nword counts whose (1+n)*4 byte total is a multiple of the 16-byte DMA chunk AND
# exceeds one chunk, so every transfer needs >= 2 watermark-triggered refills and
# every seed gives CHK-MULTICHUNK a pacing sequence to grade (n=3 -> exactly 1
# chunk, excluded).
_LEGAL_NWORDS = [7, 11, 15]
# Literal floor for the breadth claim. Independent of _LEGAL_NWORDS so a
# shrunken list fails rather than shrinking the check with it.
_BREADTH_FLOOR = 3
# One Secure-DMA chunk, in bytes; mirrors DMA_CHUNK in spi_ot_dma_tx_test.c.
_DMA_CHUNK_BYTES = 16
# TX watermark in words; mirrors TX_WATERMARK in spi_ot_dma_tx_test.c. The SPI
# host sets TXWM, and so the DMA trigger, while TXQD < TX_WATERMARK. The DMA
# starts a chunk only on the trigger, so a chunk starts with at most
# TX_WATERMARK - 1 words queued and adds one chunk of words on top.
_TX_WATERMARK_WORDS = 4
_PACED_TXQD_MAX = _TX_WATERMARK_WORDS - 1 + _DMA_CHUNK_BYTES // 4
# Literal floor on trigger assertions per DMA transfer. Independent of
# _LEGAL_NWORDS: a stimulus that shrinks to a single-chunk transfer fails this
# instead of quietly shrinking the pacing claim.
_MIN_TRIGGERS = 2
# Program opcodes and their data lanes (fw/drivers/sep_spi.h SEP_SPI_OP_PP/_QPP).
_PROGRAM_LANES = {0x02: 1, 0x32: 4}
_FW_TX_LINE = re.compile(
    r"CHK-DMA-TX PASS: .*? op=0x([0-9a-f]{8}) width=x(\d) bytes=0x([0-9a-f]{8})"
)
_FW_OVERFLOW_TOKEN = "CHK-ERR-OVERFLOW PASS: OVERFLOW clear at STATUS.TXFULL"

# Scratch-mutation hook (False in the committed leaf): drop the last byte of the
# expected TX bytes of the first x4 program case.
MUT_DROP_X4_TX_BYTE = False


@dataclass(frozen=True)
class SepSpiDmaTxCase:
    """One deterministic length cell with randomized legal address/data."""

    idx: int
    addr: int
    nwords: int
    data: list[int]
    opcode: int

    @property
    def lanes(self) -> int:
        return _PROGRAM_LANES[self.opcode]

    @property
    def chunks(self) -> int:
        total_bytes = (1 + self.nwords) * 4
        return (total_bytes + 15) // 16

    def source(self) -> bytes:
        """The data bytes in wire order: least significant byte of each word first."""
        return b"".join(w.to_bytes(4, "little") for w in self.data)

    def param_words(self) -> list[int]:
        return [self.addr, self.nwords, self.opcode] + self.data + [0] * (_MAX_WORDS - self.nwords)


@dataclass
class _DmaTxWindow:
    """Probe record of one DMA transfer: STATUS.busy high to low."""

    trigger_at_start: int
    peak_txqd: int
    rises: int = 0
    cycles: int = 0

    @property
    def assertions(self) -> int:
        """Separate trigger-high periods the DMA saw during the transfer."""
        return self.trigger_at_start + self.rises


@dataclass(frozen=True)
class SepSpiDmaTxCfg:
    """Single source of truth for SPI DMA-TX breadth randomized-representative policy."""

    seed: int
    cases: list[SepSpiDmaTxCase]

    @classmethod
    def from_seed(cls, seed: int) -> "SepSpiDmaTxCfg":
        rng = SepSeededRng(seed)
        page_indices = rng.sample(range(_FLASH_PAGES), len(_LEGAL_NWORDS))
        # Every run programs at x1 and at x4; the third case draws its width.
        opcodes = [0x02, 0x32, rng.choice(tuple(_PROGRAM_LANES))]
        rng.shuffle(opcodes)
        cases = []
        for idx, (nwords, page_idx, opcode) in enumerate(zip(_LEGAL_NWORDS, page_indices, opcodes)):
            data = [rng.getrandbits(32) for _ in range(nwords)]
            if all(word == 0xFFFF_FFFF for word in data):
                data[0] = 0
            cases.append(
                SepSpiDmaTxCase(
                    idx=idx,
                    addr=page_idx * _PAGE_SIZE,
                    nwords=nwords,
                    data=data,
                    opcode=opcode,
                )
            )
        return cls(seed=seed, cases=cases)

    def param_words(self) -> list[int]:
        words = [_PARAM_MAGIC, len(self.cases)]
        for case in self.cases:
            words.extend(case.param_words())
        return words


@pyuvm.test()
class sep_spi_ot_dma_tx_test(sep_base_test):
    """Each DMA-fed PAGE PROGRAM lands in the flash BFM, paced by the TX watermark."""

    build_env = False
    required_evidence = ("CHK-FW-CONSOLE", "CHK-MULTICHUNK")

    def build_phase(self) -> None:
        super().build_phase()
        self.sb = SepBootScoreboard("sb", self)

    def _stage_dtcm(self) -> tuple:
        cfg = SepSpiDmaTxCfg.from_seed(self.random_seed())
        patched = os.path.join(os.getcwd(), "sep_dtcm_spi3.hex")
        patch_param_block(_DTCM_HEX, patched, _PARAM_MAGIC, cfg.param_words())
        self.logger.info(
            "SPI DMA-TX breadth RAND-REP cfg: seed=%d length_cells=%s cases=%d",
            cfg.seed,
            _LEGAL_NWORDS,
            len(cfg.cases),
        )
        for case in cfg.cases:
            self.logger.info(
                "SPI DMA-TX breadth RAND-REP case[%d]: op=0x%02x width=x%d addr=0x%06x "
                "nwords=%d chunks=%d data=%s",
                case.idx,
                case.opcode,
                case.lanes,
                case.addr,
                case.nwords,
                case.chunks,
                [f"0x{w:08x}" for w in case.data],
            )
        return patched, cfg, cfg.cases

    async def run_scenario(self) -> None:
        dut = cocotb.top
        if "sep_spi_four_lane" not in cocotb.plusargs:
            raise AssertionError(
                "sep_spi_ot_dma_tx_test needs +sep_spi_four_lane: the flash model answers "
                "on spi_sd_i, which the host reads only with that plusarg"
            )
        logging.getLogger("sep_spi3_flash").setLevel(logging.DEBUG)
        flash = OcahSpiFlash(
            dut.spi_cs_n_o,
            dut.spi_sck_o,
            dq_out=dut.spi_sd_o,
            dq_in=dut.spi_sd_i,
            mode="quad_io",
            name="sep_spi3_flash",
            verbose=True,
        )
        # An error inside the BFM fails the leaf through the error counter and
        # flash.stop(); a frame the BFM refused for its shape, a wire-check
        # violation, or a frame missing from the BFM records fails it through
        # the wire monitor.
        bfm_errors = attach_error_counter(flash.log)
        wire = await SepSpiWireMonitor(dut).start()
        sb = SepSpiScoreboard(wire, flash, self.logger, seed=self.random_seed())
        await flash.start()
        windows: list[_DmaTxWindow] = []
        cocotb.start_soon(self._watch_dma_pacing(dut, windows))
        dtcm_hex, cfg, cases = self._stage_dtcm()
        try:
            self.sb.expected_line = _BANNER
            await self.boot_firmware(
                self.sb,
                _ITCM_HEX,
                dtcm_hex,
                rst_vec=_ICCM_BASE >> 1,
                max_run_cycles=_MAX_RUN_CYCLES,
                no_boot_cycles=_NO_BOOT_CYCLES,
                progress_every=_PROGRESS_EVERY,
            )
            self._golden_check(flash, cfg, cases)
            self._firmware_check(cfg, cases)
            dropped = False
            for case in cases:
                # The SPI host sends the least significant byte of each TXDATA word
                # first (ByteOrder 1, the OpenTitan default the wrapper keeps).
                source = case.source()
                if MUT_DROP_X4_TX_BYTE and case.lanes == 4 and not dropped:
                    source, dropped = source[:-1], True
                sb.expect_tx(
                    case.addr,
                    source,
                    label=f"case[{case.idx}] op=0x{case.opcode:02x} width=x{case.lanes}",
                    opcode=case.opcode,
                )
            self._pacing_check(windows, cases)
            assert not bfm_errors.records, (
                f"SPI-BFM FAIL: the flash model logged {len(bfm_errors.records)} error(s): "
                f"{bfm_errors.records[:3]}"
            )
        finally:
            await flash.stop()
        await wire.finish(self.logger, seed=self.random_seed(), flash=flash)
        sb.finish()
        # FCOV records only after every check above passed.
        for case in cases:
            await spi_lane_fcov(_TEST, "data", lanes=case.lanes, rx=False)

    def _firmware_check(self, cfg, cases) -> None:
        """One CHK-DMA-TX PASS line per case, in case order, and the TXFULL overflow check."""
        console = self.sb.console_text()
        seen = [
            (int(op, 16), int(width), int(nbytes, 16))
            for op, width, nbytes in _FW_TX_LINE.findall(console)
        ]
        want = [(c.opcode, c.lanes, c.nwords * 4) for c in cases]
        if seen != want:
            raise AssertionError(
                f"CHK-DMA-TX FAIL seed={cfg.seed}: firmware PASS lines {seen} != cases "
                f"{want}. Console was:\n{console}"
            )
        for case in cases:
            self.logger.info(
                "CHK-DMA-TX PASS seed=%d case[%d] op=0x%02x width=x%d bytes=%d "
                "(firmware read-back compare)",
                cfg.seed,
                case.idx,
                case.opcode,
                case.lanes,
                case.nwords * 4,
            )
        if _FW_OVERFLOW_TOKEN not in console:
            raise AssertionError(
                f"CHK-ERR-OVERFLOW FAIL seed={cfg.seed}: firmware console has no "
                f"{_FW_OVERFLOW_TOKEN!r} line. Console was:\n{console}"
            )

    @staticmethod
    async def _watch_dma_pacing(dut, windows: list[_DmaTxWindow]) -> None:
        """Record the trigger and TXQD on each clock of each DMA transfer.

        Sampled on the falling clock edge, where every flop is stable. Only the
        DMA-TX cases start the secure DMA in this test, so each busy window is one
        case, in firmware order.
        """
        busy = dut.dma_busy_probe_o
        trig = dut.spi_lsio_trigger_probe_o
        txqd = dut.spi_tx_qd_probe_o
        while True:
            await RisingEdge(busy)
            await FallingEdge(dut.clk_i)
            prev = int(trig.value)
            win = _DmaTxWindow(trigger_at_start=prev, peak_txqd=int(txqd.value))
            while int(busy.value):
                await FallingEdge(dut.clk_i)
                now = int(trig.value)
                if now and not prev:
                    win.rises += 1
                prev = now
                win.peak_txqd = max(win.peak_txqd, int(txqd.value))
                win.cycles += 1
            windows.append(win)

    def _pacing_check(self, windows: list[_DmaTxWindow], cases) -> None:
        """CHK-MULTICHUNK: the TX watermark paced each DMA transfer."""
        if len(windows) != len(cases):
            raise AssertionError(
                f"SPI DMA-TX CHK-MULTICHUNK: the probe saw {len(windows)} DMA busy "
                f"window(s) for {len(cases)} case(s)"
            )
        for case, win in zip(cases, windows):
            need = max(case.chunks, _MIN_TRIGGERS)
            self.logger.info(
                "SPI DMA-TX pacing case[%d]: chunks=%d trigger_at_start=%d rises=%d "
                "assertions=%d peak_txqd=%d busy_cycles=%d",
                case.idx,
                case.chunks,
                win.trigger_at_start,
                win.rises,
                win.assertions,
                win.peak_txqd,
                win.cycles,
            )
            if win.assertions < need:
                raise AssertionError(
                    f"SPI DMA-TX CHK-MULTICHUNK case[{case.idx}]: the DMA saw "
                    f"{win.assertions} trigger assertion(s) for a {case.chunks}-chunk "
                    f"transfer, need >= {need}; the watermark did not pace the refill"
                )
            if win.peak_txqd > _PACED_TXQD_MAX:
                raise AssertionError(
                    f"SPI DMA-TX CHK-MULTICHUNK case[{case.idx}]: TXQD peaked at "
                    f"{win.peak_txqd} words, above the paced bound {_PACED_TXQD_MAX} "
                    f"(TX_WATERMARK {_TX_WATERMARK_WORDS} - 1 + "
                    f"{_DMA_CHUNK_BYTES // 4}-word chunk); the DMA refilled without "
                    "waiting for the watermark"
                )
        self.logger.info(
            "CHK-MULTICHUNK PASS: %d DMA-TX transfer(s) watermark-paced: "
            "trigger assertions=%s for chunks=%s (floor %d), peak TXQD=%s <= %d words",
            len(windows),
            [w.assertions for w in windows],
            [c.chunks for c in cases],
            _MIN_TRIGGERS,
            [w.peak_txqd for w in windows],
            _PACED_TXQD_MAX,
        )

    def _golden_check(self, flash, cfg, cases) -> None:
        txns = flash.get_transactions()
        opcodes = [t.get("opcode") for t in txns]
        self.logger.info(
            "SPI DMA-TX breadth diag: %d BFM txns, opcodes=%s",
            len(txns),
            [f"0x{o:02x}" for o in opcodes],
        )
        pp_txns = [t for t in txns if t.get("opcode") in _PROGRAM_LANES]
        wren_count = opcodes.count(0x06)
        # Floor against a literal, not against len(cases): `cases` is built from
        # _LEGAL_NWORDS, so comparing the observed traffic to its length moves
        # with the stimulus and cannot fail on a shrunken sweep.
        if wren_count < _BREADTH_FLOOR or len(pp_txns) < _BREADTH_FLOOR:
            raise AssertionError(
                f"SPI DMA-TX breadth golden: expected >= {_BREADTH_FLOOR} WREN/PP "
                f"on the bus, got WREN={wren_count} PP={len(pp_txns)} "
                f"opcodes={opcodes}"
            )
        if len(cases) < _BREADTH_FLOOR:
            raise AssertionError(
                f"SPI DMA-TX breadth: the walk built {len(cases)} case(s), below "
                f"the {_BREADTH_FLOOR} transfer sizes this entry claims"
            )

        for case in cases:
            exp = case.source()
            match = next(
                (
                    t
                    for t in pp_txns
                    if t.get("opcode") == case.opcode
                    and t.get("addr") == case.addr
                    and bytes(t.get("data_in") or b"") == exp
                ),
                None,
            )
            if match is None:
                raise AssertionError(
                    f"SPI DMA-TX breadth golden case[{case.idx}]: missing program "
                    f"op=0x{case.opcode:02x} addr=0x{case.addr:06x} data={exp.hex()}"
                )
            if not match.get("ok"):
                raise AssertionError(
                    f"SPI DMA-TX breadth golden case[{case.idx}]: the flash refused PP "
                    f"addr=0x{case.addr:06x} reason={match.get('reason')}"
                )
            mem = flash.read_memory(case.addr, case.nwords * 4)
            if mem != exp:
                raise AssertionError(
                    f"SPI DMA-TX breadth golden case[{case.idx}]: BFM mem {mem.hex()} != source {exp.hex()}"
                )
            self.logger.info(
                "SPI DMA-TX breadth GOLDEN PASS case[%d]: DMA-fed op=0x%02x width=x%d "
                "@0x%06x %dB reached flash (BFM mem == SRAM source, chunks=%d)",
                case.idx,
                case.opcode,
                case.lanes,
                case.addr,
                case.nwords * 4,
                case.chunks,
            )
        self.logger.info(
            "SPI DMA-TX breadth RAND-REP GOLDEN PASS: walked length_cells=%s with seed=%d",
            [case.nwords for case in cases],
            cfg.seed,
        )
