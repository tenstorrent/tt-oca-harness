# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SEP OpenTitan-SPI DMA-TX test (PyUVM, cpu-firmware, randomized).

SPI DMA-TX breadth: the TX complement of
`sep_spi_ot_dma_rx_test` (SPI RX FIFO -> DMA -> SRAM). Here SRAM -> Secure DMA (hardware
handshake) -> OT SPI host TX FIFO -> flash: the OT SPI TX watermark drives
lsio_trigger, which refills the TX FIFO from SRAM a 16-byte chunk at a time. RX is
held quiescent so the single lsio_trigger (= tx_wm | rx_wm) is TX-watermark-driven.

Beyond the reference spi_ot_dma_tx_test (raw-byte stream, done+no-error
only): the DMA feeds a REAL flash PAGE PROGRAM stream (opcode 0x02 + 24-bit addr +
data) from SRAM; the firmware then reads the flash back over SPI and value-checks
it; and an independent cocotb BFM golden confirms the flash memory == the SRAM
source. DISTINCT from `sep_spi_ot_dma_rx_test` (RX direction) -- reuses that
test's lsio_trigger / DMA hardware-handshake bring-up.

Randomization ([RAND-REP], SINGLE source of truth): SepSpiDmaTxCfg walks all
required discrete DMA length / trigger cells in one run (nwords={7,11,15}, all
multi-chunk transfers) and randomizes only legal page-aligned flash addresses and
payload words from the runner seed. The resolved table is patched into the
firmware g_spi3_params block in the staged DTCM image and logged.

Checks:
  firmware self-check (each logs a PASS line):
    CHK-TRIGGER   : the TX-watermark source of lsio_trigger (STATUS.TXWM) tracks
                    TXQD across TX_WATERMARK (empty->1, fill->0, SW_RST drain->1,
                    values logged). EVENT_ENABLE.TXWM is programmed.
    CHK-DMA-DONE  : DMA STATUS.done, error==0, ERROR_CODE==0; done still set on a
                    second read, then STATUS RW1C clears.
                    Handshake mode does not raise STATUS.chunk_done (RTL: only when
                    hardware handshake is off); that status is `dma_basic_test`.
    CHK-SPI-IDLE  : OT SPI reaches idle, ERROR_STATUS==0.
    CHK-DMA-TX    : flash read-back == the DMA-fed data (SRAM->DMA->TXFIFO->flash).
    CHK-NONVAC    : the programmed data differs from the erased 0xFF (data landed).
    CHK-ERR-OVERFLOW : a TXDATA write past STATUS.TXFULL latches exactly
                    ERROR_STATUS.OVERFLOW; CTRL.SW_RST + W1C releases the host and
                    a flash RDSR round trip proves it runs again. This is the TX
                    flow-control edge the watermark-paced DMA never reaches, so
                    nothing else in the test proves the host reports it.
  cocotb golden cross-check:
    CHK-TRIGGER/BFM : the BFM saw WREN then PAGE PROGRAM at the random addr with the
                      random data; BFM memory == the SRAM source pattern.
    CHK-MULTICHUNK  : every PAGE PROGRAM the device received was longer on the bus
                      than one 16-byte DMA chunk, so the TX-watermark refill loop
                      really iterated. The byte count is read off the bus, not off
                      the scenario table, and compared against the chunk literal.

main() returns the error count; start.S emits PASS (0xCAFEBABE) / FAIL (0xDEADBEEF).

cpu / +skip_fuse_sense.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path

import cocotb
import pyuvm
from env.sep_boot_scoreboard import SepBootScoreboard
from env.sep_dtcm_param_patch import patch_param_block
from env.sep_seeded_rng import SepSeededRng
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

_PARAM_MAGIC = 0x5A11D00E  # mirror g_spi3_params[0] in spi_ot_dma_tx_test.c
_PAGE_SIZE = 256
_SECTOR_SIZE = 4096
_FLASH_PAGES = 32 * (_SECTOR_SIZE // _PAGE_SIZE)
_MAX_WORDS = 16
# nword counts whose (1+n)*4 byte total is a multiple of the 16-byte DMA chunk AND
# exceeds one chunk -> the TX-watermark refill loop provably iterates (>= 2 chunks),
# so every seed exercises the dynamic CHK-TRIGGER handshake (n=3 -> exactly 1 chunk,
# excluded).
_LEGAL_NWORDS = [7, 11, 15]
# Literal floor for the breadth claim. Independent of _LEGAL_NWORDS so a
# shrunken list fails rather than shrinking the check with it.
_BREADTH_FLOOR = 3
# One Secure-DMA chunk, in bytes; mirrors DMA_CHUNK in spi_ot_dma_tx_test.c. A
# PAGE PROGRAM that the flash saw as MORE than this many bytes can only have been
# assembled from more than one chunk, so the TX-watermark refill loop ran more
# than once. Literal, and independent of _LEGAL_NWORDS: shrinking the stimulus to
# a single-chunk transfer fails this instead of quietly shrinking the claim.
_DMA_CHUNK_BYTES = 16


@dataclass(frozen=True)
class SepSpiDmaTxCase:
    """One deterministic length cell with randomized legal address/data."""

    idx: int
    addr: int
    nwords: int
    data: list[int]

    @property
    def chunks(self) -> int:
        total_bytes = (1 + self.nwords) * 4
        return (total_bytes + 15) // 16

    def param_words(self) -> list[int]:
        return [self.addr, self.nwords] + self.data + [0] * (_MAX_WORDS - self.nwords)


@dataclass(frozen=True)
class SepSpiDmaTxCfg:
    """Single source of truth for SPI DMA-TX breadth randomized-representative policy."""

    seed: int
    cases: list[SepSpiDmaTxCase]

    @classmethod
    def from_seed(cls, seed: int) -> "SepSpiDmaTxCfg":
        rng = SepSeededRng(seed)
        page_indices = rng.sample(range(_FLASH_PAGES), len(_LEGAL_NWORDS))
        cases = []
        for idx, (nwords, page_idx) in enumerate(zip(_LEGAL_NWORDS, page_indices)):
            data = [rng.getrandbits(32) for _ in range(nwords)]
            if all(word == 0xFFFF_FFFF for word in data):
                data[0] = 0
            cases.append(
                SepSpiDmaTxCase(
                    idx=idx,
                    addr=page_idx * _PAGE_SIZE,
                    nwords=nwords,
                    data=data,
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
    """Boot VeeR EL2 and run the OT SPI DMA-TX firmware against the flash BFM."""

    build_env = False

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
                "SPI DMA-TX breadth RAND-REP case[%d]: addr=0x%06x nwords=%d chunks=%d data=%s",
                case.idx,
                case.addr,
                case.nwords,
                case.chunks,
                [f"0x{w:08x}" for w in case.data],
            )
        return patched, cfg, cfg.cases

    async def run_scenario(self) -> None:
        dut = cocotb.top
        logging.getLogger("sep_spi3_flash").setLevel(logging.DEBUG)
        flash = OcahSpiFlash(
            dut.spi_cs_n_o,
            dut.spi_sck_o,
            mosi=dut.spi_mosi_o,
            miso=dut.spi_miso_i,
            name="sep_spi3_flash",
            verbose=True,
        )
        await flash.start()
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
        finally:
            await flash.stop()

    def _golden_check(self, flash, cfg, cases) -> None:
        txns = flash.get_transactions()
        opcodes = [t.get("opcode") for t in txns]
        self.logger.info(
            "SPI DMA-TX breadth diag: %d BFM txns, opcodes=%s",
            len(txns),
            [f"0x{o:02x}" for o in opcodes],
        )
        pp_txns = [t for t in txns if t.get("opcode") == 0x02]
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

        # CHK-MULTICHUNK: every DMA-fed PAGE PROGRAM the device saw was longer
        # than one DMA chunk, so the TX-watermark refill loop provably iterated.
        # The length is counted off the bus (what the host actually clocked out),
        # not off the scenario table, and it is compared against the literal chunk
        # size. A DMA that delivered only its first chunk lands here.
        # Count PAYLOAD bytes only. Adding the 4 opcode/address header bytes and
        # comparing against the payload chunk size lets the very defect this
        # names through: a DMA that delivered exactly one 16-byte chunk and
        # stopped reaches the device as 20 bus bytes, which clears a 16-byte bar.
        on_bus = [len(bytes(t.get("data_in") or b"")) for t in pp_txns]
        short = [n for n in on_bus if n <= _DMA_CHUNK_BYTES]
        if short:
            raise AssertionError(
                f"SPI DMA-TX breadth CHK-MULTICHUNK: {len(short)} PAGE PROGRAM(s) fit "
                f"in one {_DMA_CHUNK_BYTES}-byte DMA chunk (payload byte counts "
                f"{on_bus}), "
                "so the TX-watermark refill loop did not have to iterate"
            )
        self.logger.info(
            "CHK-MULTICHUNK PASS: %d DMA-fed PAGE PROGRAM(s) reached the device "
            "carrying %s payload bytes, every one past the %d-byte DMA chunk, so "
            "the refill loop iterated at least %d time(s)",
            len(on_bus),
            on_bus,
            _DMA_CHUNK_BYTES,
            2,
        )
        for case in cases:
            exp = b"".join(w.to_bytes(4, "little") for w in case.data)
            match = next(
                (
                    t
                    for t in pp_txns
                    if t.get("addr") == case.addr and bytes(t.get("data_in") or b"") == exp
                ),
                None,
            )
            if match is None:
                raise AssertionError(
                    f"SPI DMA-TX breadth golden case[{case.idx}]: missing PP addr=0x{case.addr:06x} "
                    f"data={exp.hex()}"
                )
            mem = flash.read_memory(case.addr, case.nwords * 4)
            if mem != exp:
                raise AssertionError(
                    f"SPI DMA-TX breadth golden case[{case.idx}]: BFM mem {mem.hex()} != source {exp.hex()}"
                )
            self.logger.info(
                "SPI DMA-TX breadth GOLDEN PASS case[%d]: DMA-fed PP@0x%06x %dB reached flash "
                "(BFM mem == SRAM source, chunks=%d)",
                case.idx,
                case.addr,
                case.nwords * 4,
                case.chunks,
            )
        self.logger.info(
            "SPI DMA-TX breadth RAND-REP GOLDEN PASS: walked length_cells=%s with seed=%d",
            [case.nwords for case in cases],
            cfg.seed,
        )
