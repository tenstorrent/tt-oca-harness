# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SEP PIC interrupt-source map + multi-source delivery test (PyUVM).

Boots the VeeR EL2 core and runs the `pic_irq_source_map_test` firmware, which
registers PIC ISRs for every source in its catalog and proves the real
source -> PIC source-id map plus ISR delivery to the CPU:

    mailbox[0]     sep_internal_interrupts[0]  -> PIC source 1   (real FIFO push)
    OTBN done      sep_internal_interrupts[29] -> PIC source 30  (INTR_TEST)
    HMAC done      sep_internal_interrupts[17] -> PIC source 18  (INTR_TEST)
    extras         DMA done/chunk/error / HMAC-err / KMAC / CSRNG / EDN / KMAC-err

PIC source id = sep_internal_interrupts index + 1 (VeeR EL2 extintsrc_req is
1-based). The whole path is internal to bare `sep` -- no testbench injection.

SepPicSrcCfg is the single source of truth: the MUST sources and all eight
extras walk every seed, so every catalog source is graded in every run. The
seed sets only the order of the extras, which is patched into the firmware
param block. Distinct from `sep_mailbox_plic_test` (all eight mailbox channels) and from
`sep_irq_ip_to_aggregator_test` (no_cpu, aggregate vector, no ISR).

Firmware-self-checking: the firmware returns its error count and fw/startup/crt0.s emits
the PASS / FAIL magic on the 0x8000_0000 mailbox, which the boot scoreboard
gates on. Per source: CHK-DELIVER, CHK-IP-RW1C, CHK-ONEHOT; plus CHK-NONVAC,
CHK-PIC-COMPLETE, and CHK-RANDCFG (patched list echoed).

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
from sep_reg_meta import sym

_DV_ROOT = str(Path(__file__).resolve().parents[3])
_FW_DIR = os.path.join(_DV_ROOT, "fw", "build", "tests", "pic_irq_source_map_test")
_ITCM_HEX = os.path.join(_FW_DIR, "pic_irq_source_map_test.itcm.hex")
_DTCM_HEX = os.path.join(_FW_DIR, "pic_irq_source_map_test.dtcm.hex")

_ICCM_BASE = sym("SEP_ICCM_MEM_BASE_ADDR")
_MAX_RUN_CYCLES = 5_000_000
_NO_BOOT_CYCLES = 80_000
_PROGRESS_EVERY = 5_000
_BANNER = "SEP PIC IRQ source map delivery test"

_PARAM_MAGIC = 0x91C0A11C
# Matches PIC_SRC_MAX in pic_irq_source_map_test.c: the MUST trio plus every
# extra.
_SRC_MAX = 11
# MUST first, in this order, every seed: mailbox, OTBN done, HMAC done.
_MUST = (1, 30, 18)
# The rest of the firmware catalog. HMAC-err shares HMAC's INTR_ENABLE with
# MUST HMAC-done, and the three DMA sources and the two KMAC sources share
# theirs; arm_sources ORs those bits. Every extra walks every seed.
_EXTRAS = (9, 10, 11, 20, 21, 23, 24, 28)
assert len(_MUST) + len(_EXTRAS) == _SRC_MAX


def _shuffled(rng: SepSeededRng, seq: tuple[int, ...]) -> list[int]:
    pool = list(seq)
    return [pool.pop(rng.randrange(len(pool))) for _ in range(len(seq))]


@dataclass(frozen=True)
class SepPicSrcCfg:
    """Single source of truth for the PIC source-map walk: every source, seeded order."""

    seed: int
    must: tuple[int, ...]
    extras: tuple[int, ...]

    @classmethod
    def from_seed(cls, seed: int) -> "SepPicSrcCfg":
        rng = SepSeededRng(seed)
        extras = tuple(_shuffled(rng, _EXTRAS))
        return cls(seed=seed, must=_MUST, extras=extras)

    @property
    def sources(self) -> tuple[int, ...]:
        return self.must + self.extras

    def param_words(self) -> list[int]:
        srcs = list(self.sources) + [0] * (_SRC_MAX - len(self.sources))
        return [_PARAM_MAGIC, len(self.sources), *srcs[:_SRC_MAX]]

    def scenario_needle(self) -> str:
        src = ",".join(f"0x{s:08x}" for s in self.sources)
        return f"SCENARIO n=0x{len(self.sources):08x} src={src}"

    def summary(self) -> str:
        return f"seed={self.seed} must={self.must} extras={self.extras} n={len(self.sources)}"


@pyuvm.test()
class sep_pic_irq_source_map_delivery_test(sep_base_test):
    """Boot VeeR EL2 and run the multi-source PIC source-map delivery firmware."""

    build_env = False

    def build_phase(self) -> None:
        super().build_phase()
        self.sb = SepBootScoreboard("sb", self)

    def _stage_dtcm(self) -> str:
        cfg = SepPicSrcCfg.from_seed(self.random_seed())
        patched = os.path.join(os.getcwd(), "sep_dtcm_pic.hex")
        patch_param_block(_DTCM_HEX, patched, _PARAM_MAGIC, cfg.param_words())
        self.logger.info("PIC source-map RANDCFG %s", cfg.summary())
        self._pic_cfg = cfg
        return patched

    async def run_scenario(self) -> None:
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
        cfg = self._pic_cfg
        console = self.sb.console_text()
        if cfg.scenario_needle() not in console:
            raise AssertionError(
                "firmware did not consume the patched PIC cfg "
                f"(missing {cfg.scenario_needle()!r} in console; "
                "patch was inert or the image is stale)"
            )
        # The whole-run checkers must have reported.
        for needle in ("CHK-NONVAC PASS:", "CHK-PIC-COMPLETE PASS:", "CHK-DUMMY PASS:"):
            if needle not in console:
                raise AssertionError(f"firmware missing {needle!r}")
        # Cardinality: one line of each per-source checker for every selected
        # source. The PASS magic cannot show that a source was skipped; a count
        # short of len(cfg.sources) can.
        want = len(cfg.sources)
        for label in ("CHK-DELIVER PASS:", "CHK-ONEHOT PASS:", "CHK-IP-RW1C PASS:"):
            got = console.count(label)
            if got != want:
                raise AssertionError(
                    f"firmware emitted {got} {label!r} lines, expected {want} "
                    f"(one per source in {list(cfg.sources)})"
                )
        # Only now is the verdict known to be a real PASS.
        assert self.sb.fw_done and self.sb.fw_pass, (
            "firmware did not signal a PASS verdict; the console needles above "
            "are not a verdict on their own"
        )
        self.logger.info(
            "CHK-RANDCFG PASS: MUST %s + extras %s (seed=%d); %d sources each "
            "reported CHK-DELIVER / CHK-ONEHOT / CHK-IP-RW1C",
            list(cfg.must),
            list(cfg.extras),
            cfg.seed,
            want,
        )
        self.logger.info(
            "CHK-FW-REPORTED PASS: every firmware checker line is present, and the "
            "per-source checkers appear once per selected source (%d)",
            want,
        )
