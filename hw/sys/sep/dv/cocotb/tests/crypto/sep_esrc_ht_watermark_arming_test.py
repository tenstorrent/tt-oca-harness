# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""ESRC HT_WATERMARK arming (shared register, mode-aware clear).

no_cpu / +skip_fuse_sense / +esrc_noise_force. Does not stretch the
ESRC->DRBG->EDN datapath smoke: HEALTH_TEST_CTRL.ENABLE stays 0 on every
arming leg. RANDCFG walks every supported selector through MODULE_ENABLE,
then an unsupported selector and one low-mode fall.

SepHtWatermarkCfg is the SSOT for the walk and the seed-selected knobs.
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.triggers import RisingEdge
from sep_base_test import sep_base_test
from seq_lib.sep_esrc_ht_watermark_seq import (
    APT_LO,
    ARM_HIGH,
    ARM_LOW,
    RDL_MODE_COUNT,
    REPCNT_HI,
    SepHtWatermark,
    SepHtWatermarkCfg,
    arm_value,
    sel_name,
)

_FALL_TIMEOUT_CYCLES = 80_000
_FALL_POLL_EVERY = 64


@pyuvm.test()
class sep_esrc_ht_watermark_arming_test(sep_base_test):
    """Arm HT_WATERMARK per selected mode on the MODULE_ENABLE clear path."""

    async def _force_polarity(self, ht: SepHtWatermark, *, high: bool) -> int:
        """Arm the opposite polarity so the next leg's expected value can fail."""
        sel = REPCNT_HI if high else APT_LO
        want = ARM_HIGH if high else ARM_LOW
        await ht.write_num(sel)
        await ht.pulse_module_enable()
        got = await ht.read_watermark()
        assert got == want, (
            f"entry polarity {'high' if high else 'low'}: HT_WATERMARK=0x{got:04x} "
            f"want 0x{want:04x}"
        )
        return got

    async def _arm_leg(
        self,
        ht: SepHtWatermark,
        sel: int,
        path: str,
    ) -> int:
        want = arm_value(sel)
        entry = await self._force_polarity(ht, high=(want == ARM_LOW))
        assert entry != want, (
            f"{sel_name(sel)}/{path}: entry 0x{entry:04x} already equals the "
            f"arm value (leg cannot fail)"
        )
        await ht.write_num(sel)
        still = await ht.read_watermark()
        assert still == entry, (
            f"CHK-NO-REARM FAIL: {sel_name(sel)} selector write moved "
            f"HT_WATERMARK 0x{entry:04x} -> 0x{still:04x}"
        )
        self.logger.info(
            "CHK-NO-REARM PASS: %s write left HT_WATERMARK=0x%04x before %s",
            sel_name(sel),
            still,
            path,
        )
        await ht.pulse_module_enable()
        tag = "CHK-ARM-MEN"
        got = await ht.read_watermark()
        assert got == want, (
            f"{tag} FAIL: {sel_name(sel)}/{path} HT_WATERMARK=0x{got:04x} want 0x{want:04x}"
        )
        self.logger.info("%s PASS: %s %s HT_WATERMARK=0x%04x", tag, sel_name(sel), path, got)
        return got

    async def _check_unsupported(self, ht: SepHtWatermark, sel: int) -> None:
        entry = await self._force_polarity(ht, high=False)
        await ht.write_num(sel)
        got_sel = await ht.read_num()
        assert got_sel == REPCNT_HI, (
            f"CHK-UNSUPPORTED FAIL: wrote {sel:#x}, read {got_sel:#x}, want REPCNT_HI"
        )
        still = await ht.read_watermark()
        assert still == entry, (
            f"CHK-NO-REARM FAIL: unsupported {sel:#x} moved HT_WATERMARK "
            f"0x{entry:04x} -> 0x{still:04x}"
        )
        await ht.pulse_module_enable()
        got = await ht.read_watermark()
        assert got == ARM_HIGH, (
            f"CHK-UNSUPPORTED FAIL: after MODULE_ENABLE HT_WATERMARK=0x{got:04x} "
            f"want 0x{ARM_HIGH:04x} (REPCNT_HI)"
        )
        self.logger.info(
            "CHK-UNSUPPORTED PASS: %s resolved to REPCNT_HI and armed 0x%04x", f"0x{sel:x}", got
        )

    async def _check_low_fall(self, ht: SepHtWatermark, sel: int) -> None:
        await ht.write_num(sel)
        await ht.pulse_module_enable()
        armed = await ht.read_watermark()
        assert armed == ARM_LOW, (
            f"CHK-LOW-FALL FAIL: {sel_name(sel)} armed 0x{armed:04x}, want 0x{ARM_LOW:04x}"
        )
        await ht.enable_sample_path()
        await ht.enable_health_tests()
        dut = cocotb.top
        got = armed
        for cycle in range(_FALL_TIMEOUT_CYCLES):
            dut.esrc_noise_ext_i.value = cycle & 1
            await RisingEdge(dut.clk_i)
            if cycle % _FALL_POLL_EVERY != 0:
                continue
            got = await ht.read_watermark()
            if got < ARM_LOW:
                break
        else:
            raise AssertionError(
                f"CHK-LOW-FALL FAIL: {sel_name(sel)} stayed 0x{got:04x} for "
                f"{_FALL_TIMEOUT_CYCLES} cycles after ENABLE"
            )
        self.logger.info(
            "CHK-LOW-FALL PASS: %s fell 0x%04x -> 0x%04x once events were allowed",
            sel_name(sel),
            ARM_LOW,
            got,
        )
        await ht.hold_health_tests_off()

    async def run_scenario(self) -> None:
        await self.bring_up_no_cpu()
        cfg = SepHtWatermarkCfg(self.random_seed())
        ht = SepHtWatermark(self)
        self.logger.info("esrc ht watermark arming: %s", cfg.summary())

        await ht.hold_health_tests_off()
        # Count only the selectors whose DUT readback matched the documented arm
        # value, and hold that count against the size of enum WATERMARK_TEST as
        # the RDL itself defines it. The bound does not move with the generator
        # that drove the loop, so a walk that skips a mode fails here.
        proven: list[int] = []
        for sel, path in cfg.cells():
            armed = await self._arm_leg(ht, sel, path)
            if armed == arm_value(sel):
                proven.append(sel)
        assert len(proven) == RDL_MODE_COUNT, (
            f"CHK-RANDCFG FAIL: {len(proven)} selectors armed to their documented "
            f"value, want {RDL_MODE_COUNT} (proven={sorted(proven)})"
        )
        await self._check_unsupported(ht, cfg.unsupported)
        for fall_sel in cfg.fall_sels:
            await self._check_low_fall(ht, fall_sel)
        self.logger.info(
            "CHK-RANDCFG PASS: %d of %d HT_WATERMARK_NUM encodings armed; unsupported=%s fall=%s",
            len(proven),
            RDL_MODE_COUNT,
            f"0x{cfg.unsupported:x}",
            [sel_name(s) for s in cfg.fall_sels],
        )
