# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""ESRC FIPS_LOCK: certified-configuration write-1 lock.

no_cpu / +skip_fuse_sense. RANDCFG walks every locked field class every
seed (CTRL functional, health-test window/enable, decorrelator,
ring-osc enable/tune, one generator sample-clock divider, FIFO churn,
alert threshold). A pre-lock write moves the field off reset so the
post-lock reject is not a stuck register. Write-0 leaves LOCK=1.
Retired CTRL[0] is RAZ/WI and does not clear the lock; rst_ni does.
BIW observe enable stays writable. Health-test ENABLE stays 0 so this
vehicle does not trip the alert path.

Accepted scope: class walk, not an invert of every swwel bit. Alert
delivery is the sibling vehicle.
"""

from __future__ import annotations

import pyuvm
from sep_base_test import sep_base_test
from seq_lib.sep_esrc_fips_lock_seq import SepEsrcFipsLock, SepEsrcFipsLockCfg


@pyuvm.test()
class sep_esrc_fips_lock_test(sep_base_test):
    """Lock freezes certified config; observe FIFO and rst_ni still work."""

    async def _check_pre(self, esrc: SepEsrcFipsLock, target) -> None:
        await esrc.write(target.addr, target.pre)
        got = await esrc.read(target.addr)
        assert (got & target.mask) == (target.pre & target.mask), (
            f"CHK-PRE-LOCK FAIL: {target.name} wrote 0x{target.pre:08x} "
            f"read 0x{got:08x} mask 0x{target.mask:x}"
        )
        self.logger.info("CHK-PRE-LOCK PASS: %s = 0x%08x", target.name, got & target.mask)

    async def _check_post(self, esrc: SepEsrcFipsLock, target) -> None:
        await esrc.write(target.addr, target.poke)
        got = await esrc.read(target.addr)
        assert (got & target.mask) == (target.pre & target.mask), (
            f"CHK-POST-LOCK FAIL: {target.name} poke 0x{target.poke:08x} "
            f"moved 0x{target.pre:08x} -> 0x{got:08x}"
        )
        self.logger.info(
            "CHK-POST-LOCK PASS: %s held 0x%08x after poke 0x%08x",
            target.name,
            got & target.mask,
            target.poke,
        )

    async def run_scenario(self) -> None:
        await self.bring_up_no_cpu()
        cfg = SepEsrcFipsLockCfg(self.random_seed())
        esrc = SepEsrcFipsLock(self)
        self.logger.info("esrc fips lock: %s", cfg.summary())

        for target in cfg.targets:
            await self._check_pre(esrc, target)

        await esrc.set_lock()
        got = await esrc.read_lock()
        assert got == 1, f"CHK-LOCK-SET FAIL: FIPS_LOCK={got}"
        self.logger.info("CHK-LOCK-SET PASS: FIPS_LOCK.LOCK=1")

        await esrc.try_unlock()
        got = await esrc.read_lock()
        assert got == 1, f"CHK-LOCK-W1S FAIL: write-0 cleared lock to {got}"
        self.logger.info("CHK-LOCK-W1S PASS: write-0 left FIPS_LOCK.LOCK=1")

        for target in cfg.targets:
            await self._check_post(esrc, target)

        await esrc.write_obs_enable(cfg.obs_enable)
        got = await esrc.read_obs_enable()
        assert got == cfg.obs_enable, f"CHK-FIFO-LIVE FAIL: BIW_OBS_CTRL.RAW_ENABLE={got}"
        self.logger.info("CHK-FIFO-LIVE PASS: BIW_OBS_CTRL.RAW_ENABLE=%d under lock", got)

        ctrl_before, ctrl_after = await esrc.poke_reserved_ctrl_bit()
        assert ctrl_after == ctrl_before, (
            f"CHK-CTRL-RSVD FAIL: CTRL[0] write changed "
            f"0x{ctrl_before:08x} -> 0x{ctrl_after:08x}"
        )
        got = await esrc.read_lock()
        assert got == 1, f"CHK-CTRL-RSVD FAIL: CTRL[0] write cleared lock to {got}"
        self.logger.info(
            "CHK-CTRL-RSVD PASS: CTRL[0] is RAZ/WI and left FIPS_LOCK.LOCK=1")

        await self.resense()
        got = await esrc.read_lock()
        assert got == 0, f"CHK-RST-NI FAIL: FIPS_LOCK={got} after rst_ni"
        self.logger.info("CHK-RST-NI PASS: rst_ni cleared FIPS_LOCK.LOCK")

        rel = cfg.targets[0]
        await esrc.write(rel.addr, rel.poke)
        got = await esrc.read(rel.addr)
        assert (got & rel.mask) == (rel.poke & rel.mask), (
            f"CHK-POST-UNLOCK FAIL: {rel.name} still frozen 0x{got:08x} "
            f"after rst_ni poke 0x{rel.poke:08x}"
        )
        self.logger.info("CHK-POST-UNLOCK PASS: %s writable after rst_ni", rel.name)
        self.logger.info(
            "CHK-RANDCFG PASS: walked %d classes "
            "(CTRL, WINDOW, HT_ENABLE, DECOR, RING_OSC, RING_TUNE, "
            "GEN0_DIV, FIFO_CHURN, ALERT_THRESH)",
            cfg.n_cells(),
        )
