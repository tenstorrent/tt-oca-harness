# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""ESRC FIPS_LOCK certified-configuration walk.

RANDCFG: every seed walks the documented locked field classes. Continuous
knobs (which legal pre-lock value and which rejected poke) come from the
run seed. ``SepEsrcFipsLockCfg`` is the SSOT for both programming and
the post-lock golden. Observe FIFOs stay writable. Retired ``CTRL[0]``
is RAZ/WI; the shared TRNG reset and ``rst_ni`` clear the lock.
"""

from __future__ import annotations

from env.sep_seeded_rng import SepSeededRng
from sep_reg_meta import ENTROPY_SOURCE

from seq_lib.sep_axi_reg_driver import SepAxiRegDriver
from seq_lib.sep_esrc_bringup_seq import (
    DECOR_CTRL_DIV8,
    DECOR_CTRL_DIV64,
    ESRC_ALERT_THRESHOLD,
    ESRC_BIW_OBS_CTRL,
    ESRC_CTRL,
    ESRC_DECORRELATOR_CTRL,
    ESRC_FIFO_CTRL,
    ESRC_FIPS_LOCK,
    ESRC_GEN0_SAMPLE_CLK,
    ESRC_HEALTH_TEST_CTRL,
    ESRC_HEALTH_TEST_WINDOW_SIZE,
    ESRC_RING_OSC_ENABLE,
    ESRC_RING_OSC_TUNE,
    RING_OSC_SAMPLECLK_ONLY,
)

LOCK_BIT = 0x1
SHA256_BIT = 1 << 28
CHURN_BIT = 1 << 4
WINDOW_MASK = 0xFFFF
THRESH_MASK = 0xFFFF
HT_ENABLE_MASK = 0xFF


class SepEsrcFipsLockTarget:
    """One certified-configuration word: pre-lock value and rejected poke."""

    def __init__(
        self,
        name: str,
        addr: int,
        pre: int,
        poke: int,
        mask: int,
        reset: int,
    ) -> None:
        self.name = name
        self.addr = addr
        self.pre = pre
        self.poke = poke
        self.mask = mask
        self.reset = reset
        assert (pre & mask) != (poke & mask), name
        assert (pre & mask) != (reset & mask), f"{name} pre matches reset"

    def summary(self) -> str:
        return f"{self.name}@0x{self.addr:08x} pre=0x{self.pre:x} poke=0x{self.poke:x}"


class SepEsrcFipsLockCfg:
    """Walk every locked class every seed; values from the seed."""

    def __init__(self, seed: int) -> None:
        self.seed = seed
        rng = SepSeededRng(seed)
        # Pre-lock values stay off reset so CHK-PRE-LOCK can fail a stuck register.
        sha_pre = 0
        win_pre = 1024
        win_poke = 4096
        thresh_pre = 8 if rng.getrandbits(1) else 16
        decor_pre = DECOR_CTRL_DIV8
        decor_poke = DECOR_CTRL_DIV64
        ring_pre = RING_OSC_SAMPLECLK_ONLY
        ring_poke = 0x00FF_FFFF
        tune_pre = 1 << rng.randrange(12)
        tune_poke = 1 << ((rng.randrange(11) + 1) % 12)
        if tune_poke == tune_pre:
            tune_poke ^= 0x2
        gen_div_pre = 1 + rng.randrange(15)
        gen_div_poke = gen_div_pre ^ 0x10
        self.targets = (
            SepEsrcFipsLockTarget(
                "CTRL.SHA256",
                ESRC_CTRL,
                ENTROPY_SOURCE.value("CTRL", MODULE_ENABLE=1, SHA256_WHITENING_ENABLE=sha_pre),
                ENTROPY_SOURCE.value("CTRL", MODULE_ENABLE=1, SHA256_WHITENING_ENABLE=1),
                SHA256_BIT,
                ENTROPY_SOURCE.reset("CTRL"),
            ),
            SepEsrcFipsLockTarget(
                "WINDOW", ESRC_HEALTH_TEST_WINDOW_SIZE, win_pre, win_poke, WINDOW_MASK, 0x800
            ),
            SepEsrcFipsLockTarget(
                "HT_ENABLE",
                ESRC_HEALTH_TEST_CTRL,
                ENTROPY_SOURCE.value("HEALTH_TEST_CTRL", ENABLE=0),
                ENTROPY_SOURCE.value("HEALTH_TEST_CTRL", ENABLE=0x7),
                HT_ENABLE_MASK,
                ENTROPY_SOURCE.reset("HEALTH_TEST_CTRL"),
            ),
            SepEsrcFipsLockTarget(
                "DECOR",
                ESRC_DECORRELATOR_CTRL,
                decor_pre,
                decor_poke,
                0xFFFF_F000,
                DECOR_CTRL_DIV64,
            ),
            SepEsrcFipsLockTarget(
                "RING_OSC", ESRC_RING_OSC_ENABLE, ring_pre, ring_poke, 0x00FF_FFFF, 0x00FF_FFFF
            ),
            SepEsrcFipsLockTarget("RING_TUNE", ESRC_RING_OSC_TUNE, tune_pre, tune_poke, 0xFFF, 0),
            SepEsrcFipsLockTarget(
                "GEN0_DIV", ESRC_GEN0_SAMPLE_CLK, gen_div_pre, gen_div_poke, 0x1F, 0
            ),
            SepEsrcFipsLockTarget(
                "FIFO_CHURN",
                ESRC_FIFO_CTRL,
                ENTROPY_SOURCE.value("FIFO_CTRL", ENABLE=1, ENTROPY_CHURN_ENABLE=1),
                ENTROPY_SOURCE.value("FIFO_CTRL", ENABLE=1, ENTROPY_CHURN_ENABLE=0),
                CHURN_BIT,
                ENTROPY_SOURCE.reset("FIFO_CTRL"),
            ),
            SepEsrcFipsLockTarget(
                "ALERT_THRESH", ESRC_ALERT_THRESHOLD, thresh_pre, 1, THRESH_MASK, 4
            ),
        )
        self.obs_enable = 1

    def n_cells(self) -> int:
        return len(self.targets)

    def summary(self) -> str:
        cells = " ".join(t.summary() for t in self.targets)
        return f"seed={self.seed} cells={self.n_cells()} {cells}"


class SepEsrcFipsLock(SepAxiRegDriver):
    """CPU-LSU driver for FIPS_LOCK and the certified-configuration bank."""

    _DRIVER_TAG = "ESRC"

    async def write(self, addr: int, data: int) -> None:
        await self._wr(addr, data)

    async def read(self, addr: int) -> int:
        return await self._rd(addr)

    async def read_lock(self) -> int:
        return (await self._rd(ESRC_FIPS_LOCK)) & LOCK_BIT

    async def set_lock(self) -> None:
        await self._wr(ESRC_FIPS_LOCK, LOCK_BIT)

    async def try_unlock(self) -> None:
        await self._wr(ESRC_FIPS_LOCK, 0)

    async def poke_reserved_ctrl_bit(self) -> tuple[int, int]:
        cur = await self._rd(ESRC_CTRL)
        await self._wr(ESRC_CTRL, cur | 0x1)
        return cur, await self._rd(ESRC_CTRL)

    async def write_obs_enable(self, enable: int) -> None:
        await self._wr(ESRC_BIW_OBS_CTRL, enable & 0x1)

    async def read_obs_enable(self) -> int:
        return (await self._rd(ESRC_BIW_OBS_CTRL)) & 0x1
