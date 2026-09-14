# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""ESRC shared HT_WATERMARK arming: selector, MODULE_ENABLE, polarity.

One shared register, not a per-mode bank. Arming is health_test_clr
(MODULE_ENABLE 0->1). High modes arm 0x0000; APT_LO / MARKOV_LO arm 0xFFFF.
Changing the selector alone does not re-arm. An unsupported selector maps to
REPCNT_HI. HEALTH_TEST_CTRL.ENABLE stays 0 on every arming leg so a window wrap
cannot move the register between the event and the read. The shared TRNG reset
clears the selector and the watermark together; that path is not claimed here.

SepHtWatermarkCfg is the single source of truth for the walk, the unsupported
selector, and the low-mode fall selector.
"""

from __future__ import annotations

import re
from pathlib import Path

import cocotb
from cocotb.triggers import ClockCycles
from env.sep_seeded_rng import SepSeededRng
from sep_reg_meta import ENTROPY_SOURCE

from seq_lib.sep_axi_reg_driver import SepAxiRegDriver
from seq_lib.sep_esrc_bringup_seq import (
    DECOR_CTRL_DIV8,
    ESRC_CTRL,
    ESRC_DECORRELATOR_CTRL,
    ESRC_HEALTH_TEST_CTRL,
    ESRC_HT_WATERMARK,
    ESRC_HT_WATERMARK_NUM,
    ESRC_RING_OSC_ENABLE,
    RING_OSC_ALL_ON,
)

_RDL = Path(__file__).resolve().parents[5] / "ip" / "entropy_source" / "regs" / "entropy_source.rdl"


def _rdl_watermark_modes() -> dict[str, int]:
    """Encodings of enum WATERMARK_TEST, read from the RDL that defines them."""
    text = _RDL.read_text(encoding="utf-8")
    body = re.search(r"enum WATERMARK_TEST \{(.*?)\n    \};", text, re.S)
    if not body:
        raise RuntimeError(f"enum WATERMARK_TEST not found in {_RDL}")
    return {
        name: int(enc, 16)
        for name, enc in re.findall(r"(\w+)\s*=\s*4'h([0-9A-Fa-f])", body.group(1))
    }


# entropy_source.sv watermark_test_e
REPCNT_HI = 0x0
APT_HI = 0x1
APT_LO = 0x2
MARKOV_HI = 0x3
MARKOV_LO = 0x4
SUPPORTED = (REPCNT_HI, APT_HI, APT_LO, MARKOV_HI, MARKOV_LO)
HIGH_MODES = frozenset({REPCNT_HI, APT_HI, MARKOV_HI})
LOW_MODES = frozenset({APT_LO, MARKOV_LO})
SEL_NAMES = {
    REPCNT_HI: "REPCNT_HI",
    APT_HI: "APT_HI",
    APT_LO: "APT_LO",
    MARKOV_HI: "MARKOV_HI",
    MARKOV_LO: "MARKOV_LO",
}
PATHS = ("module_enable",)
WATERMARK_MASK = 0xFFFF
SEL_MASK = 0xF
ARM_HIGH = 0x0000
ARM_LOW = 0xFFFF
# Independent of SUPPORTED: the count the RDL enum defines, so a walk that
# skips a mode fails the tally in the test rather than shrinking the bound.
RDL_MODE_COUNT = len(_rdl_watermark_modes())


def arm_value(sel: int) -> int:
    """Documented clear value for the resolved selector (unsupported -> REPCNT_HI)."""
    resolved = sel if sel in SUPPORTED else REPCNT_HI
    return ARM_LOW if resolved in LOW_MODES else ARM_HIGH


def sel_name(sel: int) -> str:
    return SEL_NAMES.get(sel, f"UNSUPPORTED_{sel:#x}")


class SepHtWatermarkCfg:
    """RANDCFG: every supported selector through MODULE_ENABLE every seed.

    Continuous knob from the seed: which illegal HT_WATERMARK_NUM value is used
    for the unsupported->REPCNT_HI proof. Both low modes take the fall path on
    every seed -- APT_LO and MARKOV_LO drive separate event counters in
    entropy_source.sv, so picking one per seed would leave the other permanently unproven.
    """

    def __init__(self, seed: int) -> None:
        self.seed = seed
        rng = SepSeededRng(seed)
        self.unsupported = rng.choice(tuple(range(5, 16)))
        self.fall_sels = (APT_LO, MARKOV_LO)
        self.selectors = SUPPORTED
        self.paths = PATHS

    def cells(self):
        for sel in self.selectors:
            for path in self.paths:
                yield sel, path

    def n_cells(self) -> int:
        return len(self.selectors) * len(self.paths)

    def summary(self) -> str:
        return (
            f"seed={self.seed} selectors={list(self.selectors)} paths={list(self.paths)} "
            f"unsupported={self.unsupported:#x} "
            f"fall={[sel_name(s) for s in self.fall_sels]} "
            f"cells={self.n_cells()}"
        )


class SepHtWatermark(SepAxiRegDriver):
    """CPU-LSU driver for HT_WATERMARK_NUM / HT_WATERMARK and the two arming CSRs."""

    _DRIVER_TAG = "HTWM"

    def __init__(self, test, *, logger=None) -> None:
        super().__init__(test, logger=logger)
        self._clk = cocotb.top.clk_i

    async def _settle(self, cycles: int = 4) -> None:
        await ClockCycles(self._clk, cycles)

    async def write_num(self, sel: int) -> None:
        await self._wr(ESRC_HT_WATERMARK_NUM, sel & SEL_MASK)
        # HW writes the sanitized selector every cycle that is not a SW write.
        await self._settle()

    async def read_num(self) -> int:
        return (await self._rd(ESRC_HT_WATERMARK_NUM)) & SEL_MASK

    async def read_watermark(self) -> int:
        return (await self._rd(ESRC_HT_WATERMARK)) & WATERMARK_MASK

    async def hold_health_tests_off(self) -> None:
        await self._wr(
            ESRC_HEALTH_TEST_CTRL,
            ENTROPY_SOURCE.value("HEALTH_TEST_CTRL", ENABLE=0),
        )

    async def enable_health_tests(self) -> None:
        await self._wr(
            ESRC_HEALTH_TEST_CTRL,
            ENTROPY_SOURCE.value("HEALTH_TEST_CTRL"),
        )

    async def pulse_module_enable(self) -> None:
        await self._wr(ESRC_CTRL, ENTROPY_SOURCE.value("CTRL", MODULE_ENABLE=0))
        await self._settle(2)
        await self._wr(ESRC_CTRL, ENTROPY_SOURCE.value("CTRL", MODULE_ENABLE=1))
        await self._settle(2)

    async def enable_sample_path(self) -> None:
        await self._wr(ESRC_DECORRELATOR_CTRL, DECOR_CTRL_DIV8)
        await self._wr(ESRC_RING_OSC_ENABLE, RING_OSC_ALL_ON)


def _selftest() -> None:
    """SUPPORTED and SEL_NAMES must match enum WATERMARK_TEST in the RDL."""
    rdl = _rdl_watermark_modes()
    assert rdl == {name: sel for sel, name in SEL_NAMES.items()}, (
        f"HT_WATERMARK_NUM selector drift: RDL {rdl} vs seq {SEL_NAMES}"
    )
    assert tuple(sorted(rdl.values())) == tuple(sorted(SUPPORTED))
    assert RDL_MODE_COUNT == 5
    assert HIGH_MODES | LOW_MODES == frozenset(SUPPORTED)


_selftest()
