# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""ESRC FIPS_LOCK certified-configuration walk.

RANDCFG: every seed walks every field ``entropy_source.rdl`` marks ``swwel``
-- the certified-configuration inventory FIPS_LOCK.LOCK freezes -- except
``CTRL.MODULE_ENABLE``, where clearing the field stops the block for the rest
of the walk, so its lock belongs to the reset-recovery vehicle. ``_WALK_FIELDS``
below declares what this walk covers and is reconciled against the RDL at
import, so a lock added or dropped in the RDL fails here instead of silently
leaving the walk short. Continuous
knobs (which legal pre-lock value and which rejected poke) come from the
run seed. ``SepEsrcFipsLockCfg`` is the SSOT for both programming and
the post-lock golden. The lock also freezes the debug-pin mux, which the walk
covers like any other locked register, and the two observe-tap enables
(``BIW_OBS_CTRL.RAW_ENABLE``, ``NOISE_OBS_CTRL.RAW_ENABLE``). Those two are
single-bit, so the two-value walk cannot reach them; ``SepEsrcFipsLockCfg``
holds one at 1 and the other at 0 across the lock, picked by the seed, so each
seed grades a rejected clear and a rejected set. ``NOISE_OBS_CTRL.LANE_SEL``
stays writable under the lock. Reserved ``CTRL.RSVD0`` is RAZ/WI; the shared
TRNG reset and ``rst_ni`` clear the lock.
"""

from __future__ import annotations

from env.sep_seeded_rng import SepSeededRng
from env.sep_spec_tables import esrc_fips_locked_fields
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
    ESRC_RECOMMENDED_THRESHOLDS,
    ESRC_RING_OSC_CTRL,
    ESRC_RING_OSC_ENABLE,
    ESRC_RING_OSC_TUNE,
    RING_OSC_SAMPLECLK_ONLY,
)

LOCK_BIT = ENTROPY_SOURCE.fields("FIPS_LOCK")["LOCK"]["bm"]
ESRC_NOISE_OBS_CTRL = sym("ENTROPY_SOURCE_NOISE_OBS_CTRL_REG_ADDR")
ESRC_DEBUG_CTRL = sym("ENTROPY_SOURCE_DEBUG_CTRL_REG_ADDR")
# The two observe-tap control registers, by RDL name, with their bus address.
OBS_CTRL_ADDR: dict[str, int] = {
    "BIW_OBS_CTRL": ESRC_BIW_OBS_CTRL,
    "NOISE_OBS_CTRL": ESRC_NOISE_OBS_CTRL,
}
NOISE_LANE_SEL = ENTROPY_SOURCE.fields("NOISE_OBS_CTRL")["LANE_SEL"]
# entropy_source has twelve generator lanes; LANE_SEL values 12-15 select none.
NOISE_LANES = 12
SHA256_BIT = ENTROPY_SOURCE.fields("CTRL")["SHA256_WHITENING_ENABLE"]["bm"]
CTRL_RSVD0_BIT = ENTROPY_SOURCE.fields("CTRL")["RSVD0"]["bm"]
CHURN_BIT = ENTROPY_SOURCE.fields("FIFO_CTRL")["ENTROPY_CHURN_ENABLE"]["bm"]
FIFO_ENABLE_BIT = ENTROPY_SOURCE.fields("FIFO_CTRL")["ENABLE"]["bm"]
WINDOW_MASK = ENTROPY_SOURCE.fields("HEALTH_TEST_WINDOW_SIZE")["SIZE"]["bm"]
WINDOW_RESET = ENTROPY_SOURCE.reset("HEALTH_TEST_WINDOW_SIZE")
THRESH_MASK = ENTROPY_SOURCE.fields("ALERT_THRESHOLD")["THRESHOLD"]["bm"]
THRESH_RESET = ENTROPY_SOURCE.reset("ALERT_THRESHOLD")
RING_OSC_MASK = (
    ENTROPY_SOURCE.fields("RING_OSC_ENABLE")["ENABLE"]["bm"]
    | ENTROPY_SOURCE.fields("RING_OSC_ENABLE")["SAMPLE_CLK_ENABLE"]["bm"]
)
RING_OSC_RESET = ENTROPY_SOURCE.reset("RING_OSC_ENABLE")
GEN_DIV_MASK = ENTROPY_SOURCE.fields("GENERATOR_0_SAMPLE_CLK_CONFIG")["SAMPLE_CLK_DIVIDE"]["bm"]
GEN_DIV_RESET = ENTROPY_SOURCE.reset("GENERATOR_0_SAMPLE_CLK_CONFIG")
MIN_ENTROPY_H_MASK = ENTROPY_SOURCE.fields("MIN_ENTROPY_H")["H"]["bm"]
RCT_LIMIT = ENTROPY_SOURCE.fields("RECOMMENDED_THRESHOLDS")["RCT_LIMIT"]
APT_LIMIT = ENTROPY_SOURCE.fields("RECOMMENDED_THRESHOLDS")["APT_LIMIT"]
# SP 800-90B 4.4.2 fixes the APT window at 1024 samples, so the advisory high
# cutoff can never exceed it. entropy_source.rdl states the window in the
# APT_LIMIT description.
APT_WINDOW = 1024
# entropy_source.rdl marks both HEALTH_TEST_CTRL fields swwel, so the compare
# window is both field bitmasks, taken from the generated export rather than a
# hand-typed width.
HT_ENABLE_MASK = (
    ENTROPY_SOURCE.fields("HEALTH_TEST_CTRL")["ENABLE"]["bm"]
    | ENTROPY_SOURCE.fields("HEALTH_TEST_CTRL")["REPETITION_LIMIT"]["bm"]
)


# What this walk covers, declared per register. Reconciled against the swwel
# inventory in entropy_source.rdl at import: a field the RDL locks and this walk
# does not reach fails here, and so does a field named here that the RDL does
# not lock. The RTL is not consulted -- it is hand-written and maintained apart
# from the RDL, so it is the thing under test, not the expectation.
_WALK_FIELDS: dict[str, frozenset[str]] = {
    "CTRL": frozenset(
        {
            "AUTOTUNE_ENABLE",
            "BYPASS_ENTROPY_COMPRESSOR",
            "DOWNSAMPLE_RATE",
            "SHA256_WHITENING_ENABLE",
        }
    ),
    "HEALTH_TEST_CTRL": frozenset({"ENABLE", "REPETITION_LIMIT"}),
    "HEALTH_TEST_WINDOW_SIZE": frozenset({"SIZE"}),
    "DECORRELATOR_CTRL": frozenset({"BYPASS", "SAMPLE_CLK_DIV"}),
    "DECORRELATOR_MASK": frozenset({"ENTROPY_BYTE_MASK"}),
    "RING_OSC_ENABLE": frozenset({"ENABLE", "SAMPLE_CLK_ENABLE"}),
    "RING_OSC_TUNE": frozenset({"DETUNE", "SAMPLE_CLK_DETUNE"}),
    "RING_OSC_CTRL": frozenset({"SAMPLE_CLK_SELECT"}),
    "FIFO_CTRL": frozenset({"ENABLE", "ENTROPY_CHURN_ENABLE"}),
    "ALERT_THRESHOLD": frozenset({"THRESHOLD"}),
    "MARKOV_TEST_PROB_THRESHOLDS": frozenset({"PROB_01_THRESHOLD", "PROB_10_THRESHOLD"}),
    "APT_PROPORTION_1BIT": frozenset({"LIMIT"}),
    "APT_PROPORTION_LO": frozenset({"LIMIT"}),
    "MIN_ENTROPY_H": frozenset({"H"}),
    "DEBUG_CTRL": frozenset({"SELECT_SIGNAL", "SELECT_FREQ_DIV"}),
    **{f"GENERATOR_{idx}_SAMPLE_CLK_CONFIG": frozenset({"SAMPLE_CLK_DIVIDE"}) for idx in range(12)},
}

# Locked fields this walk deliberately does not poke, each with the reason it
# cannot be reached here. An entry is a standing exception, not a gap to ignore.
_WALK_EXCLUDED: dict[tuple[str, str], str] = {
    ("CTRL", "MODULE_ENABLE"): (
        "clearing it idles the main state machine for the rest of the walk; its "
        "lock is proven by the reset-recovery vehicle instead"
    ),
    ("BIW_OBS_CTRL", "RAW_ENABLE"): (
        "single-bit observe-tap enable; the two-distinct-value walk cannot move a "
        "lone 1-bit field to a second off-reset value. CHK-OBS-PRE-LOCK and "
        "CHK-OBS-ENABLE-LOCKED grade its lock in both directions instead"
    ),
    ("NOISE_OBS_CTRL", "RAW_ENABLE"): (
        "single-bit observe-tap enable, graded by CHK-OBS-PRE-LOCK and "
        "CHK-OBS-ENABLE-LOCKED like BIW_OBS_CTRL.RAW_ENABLE"
    ),
}


def _reconcile_walk_with_rdl() -> None:
    """Fail import if the declared walk and the RDL lock inventory disagree."""
    rdl = esrc_fips_locked_fields()
    expected = {(r, f) for r, fields in rdl.items() for f in fields}
    walked = {(r, f) for r, fields in _WALK_FIELDS.items() for f in fields}
    missing = expected - walked - set(_WALK_EXCLUDED)
    if missing:
        raise RuntimeError(
            "entropy_source.rdl locks fields this FIPS_LOCK walk does not reach, "
            f"and they are not declared exclusions: {sorted(missing)}"
        )
    unknown = walked - expected
    if unknown:
        raise RuntimeError(
            f"this walk names fields entropy_source.rdl does not mark swwel: {sorted(unknown)}"
        )
    stale = set(_WALK_EXCLUDED) - expected
    if stale:
        raise RuntimeError(f"excluded fields are no longer locked in the RDL: {sorted(stale)}")


_reconcile_walk_with_rdl()


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
        # Each of these three registers locks two fields. Both fields must leave
        # their reset in `pre`, or the second one sits inside the compare mask
        # without ever being written and its lock is not exercised.
        decor_bypass_pre = 1 << rng.randrange(12)
        decor_pre = DECOR_CTRL_DIV8 | ENTROPY_SOURCE.value(
            "DECORRELATOR_CTRL", BYPASS=decor_bypass_pre, SAMPLE_CLK_DIV=0
        )
        decor_poke = DECOR_CTRL_DIV64
        ring_clk_pre = 0xFFF ^ (1 << rng.randrange(12))
        ring_pre = RING_OSC_SAMPLECLK_ONLY & ~ENTROPY_SOURCE.fields("RING_OSC_ENABLE")[
            "SAMPLE_CLK_ENABLE"
        ]["bm"] | ENTROPY_SOURCE.value("RING_OSC_ENABLE", ENABLE=0, SAMPLE_CLK_ENABLE=ring_clk_pre)
        ring_poke = RING_OSC_RESET
        detune_pre = 1 << rng.randrange(12)
        sample_detune_pre = 1 << rng.randrange(12)
        detune_poke = rng.choice(tuple(1 << i for i in range(12) if (1 << i) != detune_pre))
        sample_detune_poke = rng.choice(
            tuple(1 << i for i in range(12) if (1 << i) != sample_detune_pre)
        )
        tune_pre = ENTROPY_SOURCE.value(
            "RING_OSC_TUNE",
            DETUNE=detune_pre,
            SAMPLE_CLK_DETUNE=sample_detune_pre,
        )
        tune_poke = ENTROPY_SOURCE.value(
            "RING_OSC_TUNE",
            DETUNE=detune_poke,
            SAMPLE_CLK_DETUNE=sample_detune_poke,
        )
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
                "WINDOW", ESRC_HEALTH_TEST_WINDOW_SIZE, win_pre, win_poke, WINDOW_MASK, WINDOW_RESET
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
                ENTROPY_SOURCE.reset("DECORRELATOR_CTRL"),
            ),
            SepEsrcFipsLockTarget(
                "RING_OSC", ESRC_RING_OSC_ENABLE, ring_pre, ring_poke, RING_OSC_MASK, RING_OSC_RESET
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
                "GEN0_DIV",
                ESRC_GEN0_SAMPLE_CLK,
                gen_div_pre,
                gen_div_poke,
                GEN_DIV_MASK,
                GEN_DIV_RESET,
            ),
            # Both FIFO_CTRL fields are locked. ENABLE is cleared before the
            # lock, so the rejected poke is software turning the seed-read path
            # back on.
            SepEsrcFipsLockTarget(
                "FIFO_CTRL",
                ESRC_FIFO_CTRL,
                ENTROPY_SOURCE.value("FIFO_CTRL", ENABLE=0, ENTROPY_CHURN_ENABLE=1),
                ENTROPY_SOURCE.value("FIFO_CTRL", ENABLE=1, ENTROPY_CHURN_ENABLE=0),
                FIFO_ENABLE_BIT | CHURN_BIT,
                ENTROPY_SOURCE.reset("FIFO_CTRL"),
            ),
            SepEsrcFipsLockTarget(
                "ALERT_THRESH", ESRC_ALERT_THRESHOLD, thresh_pre, 1, THRESH_MASK, THRESH_RESET
            ),
            # The remaining registers entropy_source.rdl marks swwel.
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
            # The debug observation-pin selection and divider. SEP leaves
            # signal_monitor_o unconnected, so the value has no side effect here.
            _locked_target(
                "DEBUG_CTRL",
                ESRC_DEBUG_CTRL,
                "DEBUG_CTRL",
                ("SELECT_SIGNAL", "SELECT_FREQ_DIV"),
                rng,
            ),
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
        # Observe-tap enables across the lock: one tap is held at 1 and must
        # reject a clear, the other is held at 0 and must reject a set, so every
        # seed grades both directions. The seed picks which tap gets which.
        biw_held = rng.getrandbits(1)
        self.obs_held = {"BIW_OBS_CTRL": biw_held, "NOISE_OBS_CTRL": biw_held ^ 1}
        # NOISE_OBS_CTRL.LANE_SEL is not locked. The pre-lock lane is off reset,
        # and the lane written under the lock differs from it, so CHK-OBS-LANE-SEL
        # can fail a lock that freezes the whole register.
        lane_reset = NOISE_LANE_SEL.get("reset", 0)
        self.lane_pre = rng.choice(tuple(v for v in range(NOISE_LANES) if v != lane_reset))
        self.lane_post = rng.choice(tuple(v for v in range(NOISE_LANES) if v != self.lane_pre))
        # Ascending MIN_ENTROPY_H points for the advisory-threshold sweep. The
        # three anchors are the register reset and both ends of the Q4.4 range,
        # where the closed form saturates; the rest come from the seed so the
        # sweep is not pinned to one corner of the LUT.
        h_anchors = {0x00, ENTROPY_SOURCE.reset("MIN_ENTROPY_H"), MIN_ENTROPY_H_MASK}
        while len(h_anchors) < 8:
            h_anchors.add(rng.randrange(1, MIN_ENTROPY_H_MASK))
        self.rec_thresh_h = tuple(sorted(h_anchors))
        # CHK-POST-UNLOCK must land on a target whose poke differs from the
        # register reset. On a target where they agree, the reset value alone
        # satisfies the readback and a dropped post-unlock write still passes.
        self.release = next(t for t in self.targets if (t.poke & t.mask) != (t.reset & t.mask))

    def n_cells(self) -> int:
        return len(self.targets)

    def summary(self) -> str:
        cells = " ".join(t.summary() for t in self.targets)
        return (
            f"seed={self.seed} cells={self.n_cells()} obs_held={self.obs_held} "
            f"lane_pre={self.lane_pre} lane_post={self.lane_post} "
            f"rec_thresh_h={[f'0x{h:02x}' for h in self.rec_thresh_h]} {cells}"
        )


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
        await self._wr(ESRC_CTRL, cur | CTRL_RSVD0_BIT)
        return cur, await self._rd(ESRC_CTRL)

    async def write_obs(self, reg: str, enable: int, lane: int = 0) -> None:
        """Write RAW_ENABLE of one observe-tap register; LANE_SEL for NOISE_OBS_CTRL."""
        fields = {"RAW_ENABLE": enable}
        if reg == "NOISE_OBS_CTRL":
            fields["LANE_SEL"] = lane
        await self._wr(OBS_CTRL_ADDR[reg], ENTROPY_SOURCE.value(reg, **fields))

    async def read_obs(self, reg: str) -> tuple[int, int]:
        """RAW_ENABLE and (NOISE_OBS_CTRL only, else 0) LANE_SEL, read from the DUT."""
        raw = await self._rd(OBS_CTRL_ADDR[reg])
        en = ENTROPY_SOURCE.fields(reg)["RAW_ENABLE"]
        enable = (raw & en["bm"]) >> en["bp"]
        lane = 0
        if reg == "NOISE_OBS_CTRL":
            lane = (raw & NOISE_LANE_SEL["bm"]) >> NOISE_LANE_SEL["bp"]
        return enable, lane

    async def write_min_entropy_h(self, h: int) -> None:
        await self._wr(ESRC_MIN_ENTROPY_H, h & MIN_ENTROPY_H_MASK)

    async def read_recommended_thresholds(self) -> tuple[int, int]:
        """The advisory RCT and APT cutoffs the LUT derives from MIN_ENTROPY_H."""
        raw = await self._rd(ESRC_RECOMMENDED_THRESHOLDS)
        rct = (raw & RCT_LIMIT["bm"]) >> RCT_LIMIT["bp"]
        apt = (raw & APT_LIMIT["bm"]) >> APT_LIMIT["bp"]
        return rct, apt


def rct_limit_golden(h: int) -> int:
    """SP 800-90B 4.4.1 repetition cutoff C = 1 + ceil(20 / H), H in Q4.4.

    Derived from the standard, not read from entropy_source_rec_thresh_lut.sv,
    which is what makes the compare an oracle rather than a mirror. H = 0 carries
    no entropy, so no finite cutoff applies and the field saturates.
    """
    if h == 0:
        return RCT_LIMIT["bm"]
    return 1 + -(-320 // h)
