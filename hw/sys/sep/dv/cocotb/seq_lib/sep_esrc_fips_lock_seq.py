# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""ESRC FIPS_LOCK certified-configuration walk.

RANDCFG: every seed walks every field entropy_source.sv marks
``swwel = fips_lock``, except ``CTRL.MODULE_ENABLE`` -- clearing that stops the
block for the rest of the walk, so its lock belongs to the reset-recovery
vehicle. Continuous
knobs (which legal pre-lock value and which rejected poke) come from the
run seed. ``SepEsrcFipsLockCfg`` is the SSOT for both programming and
the post-lock golden. Observe FIFOs stay writable. Retired ``CTRL[0]``
is RAZ/WI; the shared TRNG reset and ``rst_ni`` clear the lock.
"""

from __future__ import annotations

from env.sep_seeded_rng import SepSeededRng
from sep_reg_meta import ENTROPY_SOURCE, sym

from seq_lib.sep_axi_reg_driver import SepAxiRegDriver
from seq_lib.sep_esrc_bringup_seq import (
    DECOR_CTRL_DIV8,
    DECOR_CTRL_DIV64,
    ESRC_ALERT_THRESHOLD,
    ESRC_APT_PROPORTION_1BIT,
    ESRC_APT_PROPORTION_LO,
    ESRC_BIW_OBS_CTRL,
    ESRC_CTRL,
    ESRC_DECORRELATOR_CTRL,
    ESRC_DECORRELATOR_MASK,
    ESRC_FIFO_CTRL,
    ESRC_FIPS_LOCK,
    ESRC_GEN0_SAMPLE_CLK,
    ESRC_HEALTH_TEST_CTRL,
    ESRC_HEALTH_TEST_WINDOW_SIZE,
    ESRC_MARKOV_TEST_PROB_THRESHOLDS,
    ESRC_MIN_ENTROPY_H,
    ESRC_RING_OSC_CTRL,
    ESRC_RING_OSC_ENABLE,
    ESRC_RING_OSC_TUNE,
    RING_OSC_SAMPLECLK_ONLY,
)

LOCK_BIT = 0x1
SHA256_BIT = ENTROPY_SOURCE.fields("CTRL")["SHA256_WHITENING_ENABLE"]["bm"]
CHURN_BIT = ENTROPY_SOURCE.fields("FIFO_CTRL")["ENTROPY_CHURN_ENABLE"]["bm"]
WINDOW_MASK = 0xFFFF
THRESH_MASK = 0xFFFF
# entropy_source.sv locks both HEALTH_TEST_CTRL fields under FIPS_LOCK.LOCK
# (ENABLE and REPETITION_LIMIT both carry swwel = fips_lock), so the compare
# window is both field bitmasks, taken from the generated export rather than a
# hand-typed width.
HT_ENABLE_MASK = (
    ENTROPY_SOURCE.fields("HEALTH_TEST_CTRL")["ENABLE"]["bm"]
    | ENTROPY_SOURCE.fields("HEALTH_TEST_CTRL")["REPETITION_LIMIT"]["bm"]
)


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


def _locked_target(
    name: str, addr: int, reg: str, fields: tuple[str, ...], rng
) -> "SepEsrcFipsLockTarget":
    """Build a target that moves every named locked field off its reset.

    ``pre`` and ``poke`` are two distinct in-field values, both different from
    the register reset, so CHK-PRE-LOCK can fail a stuck register and
    CHK-POST-LOCK can fail a register that accepted a write under lock. The mask
    is the union of the named field bitmasks taken from the generated export, so
    a field that changes width in the RDL changes the compare window with it.
    """
    meta = ENTROPY_SOURCE.fields(reg)
    mask = 0
    pre_over: dict[str, int] = {}
    poke_over: dict[str, int] = {}
    for field in fields:
        info = meta[field]
        mask |= info["bm"]
        width = info["bw"]
        span = 1 << width
        reset_val = info.get("reset", 0)
        # Two distinct values, neither equal to the field reset.
        choices = [v for v in (1, span - 1, span // 2, 2) if v < span and v != reset_val]
        if len(choices) < 2:
            choices = [v for v in range(span) if v != reset_val][:2]
        pre_over[field] = choices[rng.randrange(len(choices))]
        remaining = [v for v in choices if v != pre_over[field]]
        poke_over[field] = remaining[rng.randrange(len(remaining))]
    return SepEsrcFipsLockTarget(
        name,
        addr,
        ENTROPY_SOURCE.value(reg, **pre_over),
        ENTROPY_SOURCE.value(reg, **poke_over),
        mask,
        ENTROPY_SOURCE.reset(reg),
    )


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
        # Both HEALTH_TEST_CTRL fields must move off reset, or the lock on
        # REPETITION_LIMIT is never attempted. Reset is 25.
        _REP_RESET = ENTROPY_SOURCE.fields("HEALTH_TEST_CTRL")["REPETITION_LIMIT"]["reset"]
        _rep_choices = tuple(v for v in (3, 5, 7, 11, 13, 17, 19, 23) if v != _REP_RESET)
        rep_pre = rng.choice(_rep_choices)
        rep_poke = rng.choice(tuple(v for v in _rep_choices if v != rep_pre))
        gen_div_pre = 1 + rng.randrange(15)
        gen_div_poke = gen_div_pre ^ 0x10
        self.targets = (
            # Every locked CTRL field except MODULE_ENABLE. Clearing MODULE_ENABLE
            # would stop the block for the rest of the walk, so that one field's
            # lock is left to the reset-recovery vehicle.
            SepEsrcFipsLockTarget(
                "CTRL",
                ESRC_CTRL,
                ENTROPY_SOURCE.value(
                    "CTRL",
                    MODULE_ENABLE=1,
                    SHA256_WHITENING_ENABLE=sha_pre,
                    AUTOTUNE_ENABLE=1,
                    BYPASS_ENTROPY_COMPRESSOR=1,
                    DOWNSAMPLE_RATE=1,
                ),
                ENTROPY_SOURCE.value(
                    "CTRL",
                    MODULE_ENABLE=1,
                    SHA256_WHITENING_ENABLE=1,
                    AUTOTUNE_ENABLE=0,
                    BYPASS_ENTROPY_COMPRESSOR=0,
                    DOWNSAMPLE_RATE=2,
                ),
                SHA256_BIT
                | ENTROPY_SOURCE.fields("CTRL")["AUTOTUNE_ENABLE"]["bm"]
                | ENTROPY_SOURCE.fields("CTRL")["BYPASS_ENTROPY_COMPRESSOR"]["bm"]
                | ENTROPY_SOURCE.fields("CTRL")["DOWNSAMPLE_RATE"]["bm"],
                ENTROPY_SOURCE.reset("CTRL"),
            ),
            SepEsrcFipsLockTarget(
                "WINDOW", ESRC_HEALTH_TEST_WINDOW_SIZE, win_pre, win_poke, WINDOW_MASK, 0x800
            ),
            SepEsrcFipsLockTarget(
                "HT_ENABLE",
                ESRC_HEALTH_TEST_CTRL,
                ENTROPY_SOURCE.value("HEALTH_TEST_CTRL", ENABLE=0, REPETITION_LIMIT=rep_pre),
                ENTROPY_SOURCE.value("HEALTH_TEST_CTRL", ENABLE=0x7, REPETITION_LIMIT=rep_poke),
                HT_ENABLE_MASK,
                ENTROPY_SOURCE.reset("HEALTH_TEST_CTRL"),
            ),
            SepEsrcFipsLockTarget(
                "DECOR",
                ESRC_DECORRELATOR_CTRL,
                decor_pre,
                decor_poke,
                # Both DECORRELATOR_CTRL fields are locked, so the compare
                # window is SAMPLE_CLK_DIV together with BYPASS.
                ENTROPY_SOURCE.fields("DECORRELATOR_CTRL")["SAMPLE_CLK_DIV"]["bm"]
                | ENTROPY_SOURCE.fields("DECORRELATOR_CTRL")["BYPASS"]["bm"],
                DECOR_CTRL_DIV64,
            ),
            SepEsrcFipsLockTarget(
                "RING_OSC", ESRC_RING_OSC_ENABLE, ring_pre, ring_poke, 0x00FF_FFFF, 0x00FF_FFFF
            ),
            # RING_OSC_TUNE locks DETUNE and SAMPLE_CLK_DETUNE, so both are in
            # the compare window.
            SepEsrcFipsLockTarget(
                "RING_TUNE",
                ESRC_RING_OSC_TUNE,
                tune_pre,
                tune_poke,
                ENTROPY_SOURCE.fields("RING_OSC_TUNE")["DETUNE"]["bm"]
                | ENTROPY_SOURCE.fields("RING_OSC_TUNE")["SAMPLE_CLK_DETUNE"]["bm"],
                ENTROPY_SOURCE.reset("RING_OSC_TUNE"),
            ),
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
            # The remaining registers entropy_source.sv marks swwel = fips_lock.
            _locked_target(
                "MARKOV_THRESH",
                ESRC_MARKOV_TEST_PROB_THRESHOLDS,
                "MARKOV_TEST_PROB_THRESHOLDS",
                ("PROB_01_THRESHOLD", "PROB_10_THRESHOLD"),
                rng,
            ),
            _locked_target(
                "APT_PROP_1BIT", ESRC_APT_PROPORTION_1BIT, "APT_PROPORTION_1BIT", ("LIMIT",), rng
            ),
            _locked_target(
                "APT_PROP_LO", ESRC_APT_PROPORTION_LO, "APT_PROPORTION_LO", ("LIMIT",), rng
            ),
            _locked_target(
                "RING_OSC_SEL", ESRC_RING_OSC_CTRL, "RING_OSC_CTRL", ("SAMPLE_CLK_SELECT",), rng
            ),
            _locked_target(
                "DECOR_MASK",
                ESRC_DECORRELATOR_MASK,
                "DECORRELATOR_MASK",
                ("ENTROPY_BYTE_MASK",),
                rng,
            ),
            _locked_target("MIN_ENTROPY_H", ESRC_MIN_ENTROPY_H, "MIN_ENTROPY_H", ("H",), rng),
        ) + tuple(
            # All twelve per-generator sample-clock dividers are locked.
            _locked_target(
                f"GEN{idx}_DIV",
                sym(f"ENTROPY_SOURCE_GENERATOR_{idx}_SAMPLE_CLK_CONFIG_REG_ADDR"),
                f"GENERATOR_{idx}_SAMPLE_CLK_CONFIG",
                ("SAMPLE_CLK_DIVIDE",),
                rng,
            )
            for idx in range(1, 12)
        )
        self.obs_enable = 1
        # CHK-POST-UNLOCK must land on a target whose poke differs from the
        # register reset. On a target where they agree, the reset value alone
        # satisfies the readback and a dropped post-unlock write still passes.
        self.release = next(t for t in self.targets if (t.poke & t.mask) != (t.reset & t.mask))

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
