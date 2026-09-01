# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SEP Secure-DMA basic-breadth firmware-boot test (PyUVM).

OSS rep DMA basic breadth. reference provenance: the uvm_tests/dma reg_rw / reg_reset /
cfg_regwen / range_regwen / addr_fixed / addr_wrap / addr_combo / mem_copy
(width sweep) / err_opcode family. Boots the VeeR EL2 core and runs the
dma_basic firmware, which drives the Secure DMA over the CPU LSU and proves the
DMA CSR + copy-datapath basic contracts on bare sep (SRAM->SRAM transfers).

Distinct from the Phase-1 DMA trio (sep_dma_hash inline SHA-256 + SRAM->DCCM +
IRQ; sep_dma_cpu_contention mid-flight BUSY + dual-master; sep_spi_ot_dma_rx
lsio handshake): DMA basic breadth adds the CSR/REGWEN breadth, the FIXED/INCR/WRAP address-
mode matrix, the 1B/2B/4B transfer-width sweep, and one opcode-error path.

SepDmaBasicCfg is the single source of truth for src/dst offsets, copy length
and fill seed. Discrete mode/width cells stay walked every invocation; the
continuous knobs come from the run seed (patched into the firmware param block).

Firmware-self-checking: the firmware returns its error count and start.S emits
the PASS (0xCAFEBABE) / FAIL (0xDEADBEEF) magic on the 0x8000_0000 mailbox, which
the boot scoreboard gates on. The firmware self-checks (each with a positive PASS
line in the console log): CHK-RESET (reset values), CHK-CFG-REGWEN (HW busy-lock),
CHK-RANGE-REGWEN (range gating + rw0c lock), CHK-COPY-MODE (FIXED/INCR/WRAP
expected images + neighbor), CHK-WIDTH (1B/2B/4B), CHK-DONE-RW1C, CHK-ERR-OPCODE
(opcode_error + recovery). The scoreboard also checks the banner + ICCM execution.

cpu / +skip_fuse_sense (no fuse data is read).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import pyuvm
from env.sep_boot_scoreboard import SepBootScoreboard
from env.sep_dtcm_param_patch import patch_param_block
from env.sep_seeded_rng import SepSeededRng
from sep_base_test import sep_base_test

_DV_ROOT = str(Path(__file__).resolve().parents[3])
_FW_DIR = os.path.join(_DV_ROOT, "fw", "build", "tests", "dma_basic_test")
_ITCM_HEX = os.path.join(_FW_DIR, "dma_basic_test.itcm.hex")
_DTCM_HEX = os.path.join(_FW_DIR, "dma_basic_test.dtcm.hex")

_ICCM_BASE = 0xC000_0000
_SRAM_BASE = 0x1000_0000
_MAX_RUN_CYCLES = 4_000_000
_NO_BOOT_CYCLES = 80_000
_PROGRESS_EVERY = 5_000
_BANNER = "SEP DMA basic test"

_PARAM_MAGIC = 0xDA0A11C0
_SRAM_SIZE = 0x40000
_BUSY_LEN = 0x100


@dataclass(frozen=True)
class SepDmaBasicCfg:
    """Single source of truth for DMA basic-breadth continuous knobs.

    Discrete cells (INCR/FIXED/WRAP x 1B/2B/4B) are walked every invocation.
    src/dst offsets, copy length and fill seed come from the run seed.
    """

    seed: int
    src_off: int
    dst_off: int
    nbytes: int
    fill_seed: int

    @classmethod
    def from_seed(cls, seed: int) -> "SepDmaBasicCfg":
        # Seed-reproducible by requirement: a failing leaf is replayed with
        # `--stage sim --seed N`, so the stimulus is a pure function of the
        # seed. These pick DMA offsets for a simulated DUT -- never a key,
        # token, or access decision.
        rng = SepSeededRng(seed)
        nbytes = rng.choice((16, 32))
        src_off = rng.randrange(0, 0x10000, 16)
        dst_off = rng.randrange(0x20000, 0x30000, 16)
        fill = rng.getrandbits(32) or 0x1234567
        return cls(seed=seed, src_off=src_off, dst_off=dst_off, nbytes=nbytes, fill_seed=fill)

    def param_words(self) -> list[int]:
        return [_PARAM_MAGIC, self.src_off, self.dst_off, self.nbytes, self.fill_seed]


@pyuvm.test()
class sep_dma_basic_test(sep_base_test):
    """Boot VeeR EL2 and run the Secure-DMA basic-breadth firmware."""

    build_env = False

    def build_phase(self) -> None:
        super().build_phase()
        self.sb = SepBootScoreboard("sb", self)

    def _stage_dtcm(self) -> str:
        cfg = SepDmaBasicCfg.from_seed(self.random_seed())
        assert cfg.src_off + _BUSY_LEN <= _SRAM_SIZE
        assert cfg.dst_off + _BUSY_LEN <= _SRAM_SIZE
        patched = os.path.join(os.getcwd(), "sep_dtcm_dma.hex")
        patch_param_block(_DTCM_HEX, patched, _PARAM_MAGIC, cfg.param_words())
        self.logger.info(
            "DMA basic RANDCFG seed=%d src_off=0x%x dst_off=0x%x nbytes=%d fill=0x%08x",
            cfg.seed,
            cfg.src_off,
            cfg.dst_off,
            cfg.nbytes,
            cfg.fill_seed,
        )
        self._dma_cfg = cfg
        return patched

    async def run_scenario(self) -> None:
        # Override the boot scoreboard's expected banner here (after its own
        # build_phase, which resets it to the hello_world default).
        self.sb.expected_line = _BANNER
        dtcm = self._stage_dtcm()
        await self.boot_firmware(
            self.sb,
            _ITCM_HEX,
            dtcm,
            rst_vec=_ICCM_BASE >> 1,
            max_run_cycles=_MAX_RUN_CYCLES,
            no_boot_cycles=_NO_BOOT_CYCLES,
            progress_every=_PROGRESS_EVERY,
        )
        cfg = self._dma_cfg
        needle = (
            f"SCENARIO src=0x{_SRAM_BASE + cfg.src_off:08x} "
            f"dst=0x{_SRAM_BASE + cfg.dst_off:08x} "
            f"nbytes=0x{cfg.nbytes:08x} "
            f"fill=0x{cfg.fill_seed:08x}"
        )
        console = self.sb.console_text()
        if needle not in console:
            raise AssertionError(
                "firmware did not consume the patched DMA cfg "
                f"(missing {needle!r} in console; patch was inert or the image is stale)"
            )
        self.logger.info(
            "CHK-RAND-REP PASS: walked INCR/FIXED/WRAP x 1B/2B/4B; seed=%d nbytes=%d",
            cfg.seed,
            cfg.nbytes,
        )
