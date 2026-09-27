# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""ESRC FIPS_LOCK: certified-configuration write-1 lock.

no_cpu / +skip_fuse_sense. RANDCFG walks every locked field class every
seed (CTRL functional, health-test window/enable, decorrelator,
ring-osc enable/tune, one generator sample-clock divider, FIFO churn,
alert threshold). A pre-lock write moves the field off reset so the
post-lock reject is not a stuck register. Write-0 leaves LOCK=1.
Retired CTRL[0] is RAZ/WI before the lock and does not clear it after;
rst_ni does. The advisory RCT/APT cutoffs track MIN_ENTROPY_H against an
SP 800-90B oracle. BIW observe enable stays writable. Health-test ENABLE
stays 0 so this vehicle does not trip the alert path.

Accepted scope: class walk, not an invert of every swwel bit. Alert
delivery is the sibling vehicle.
"""

from __future__ import annotations

import pyuvm
from sep_base_test import sep_base_test
from seq_lib.sep_esrc_fips_lock_seq import (
    APT_WINDOW,
    SepEsrcFipsLock,
    SepEsrcFipsLockCfg,
    rct_limit_golden,
)


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

        # CTRL[0] is retired: sw = r, hw = na. Prove RAZ/WI here, before the lock,
        # where every other CTRL field is demonstrably writable -- under the lock
        # an unchanged CTRL is explained by the lock alone and says nothing about
        # bit 0. The post-lock repeat below keeps only the "does not clear the
        # lock" half.
        ctrl_before, ctrl_after = await esrc.poke_reserved_ctrl_bit()
        assert ctrl_after == ctrl_before, (
            f"CHK-CTRL-RSVD FAIL: pre-lock CTRL[0] write changed "
            f"0x{ctrl_before:08x} -> 0x{ctrl_after:08x}"
        )
        self.logger.info(
            "CHK-CTRL-RSVD PASS: CTRL[0] is RAZ/WI while CTRL is writable (0x%08x held)",
            ctrl_after,
        )

        # RECOMMENDED_THRESHOLDS is derived combinationally from MIN_ENTROPY_H by
        # entropy_source_rec_thresh_lut. The expected RCT cutoff is re-derived
        # from SP 800-90B 4.4.1 rather than read from that table, so the compare
        # is an oracle. APT_LIMIT is the exact binomial cutoff, which is not a
        # closed form; what the standard does fix is that it is bounded by the
        # 1024-sample window and falls as the assessed min-entropy rises.
        prev_apt = None
        for h in cfg.rec_thresh_h:
            await esrc.write_min_entropy_h(h)
            rct, apt = await esrc.read_recommended_thresholds()
            want = rct_limit_golden(h)
            assert rct == want, (
                f"CHK-REC-THRESH FAIL: MIN_ENTROPY_H=0x{h:02x} gave RCT_LIMIT={rct}, "
                f"SP 800-90B 4.4.1 C = 1 + ceil(20/H) gives {want}"
            )
            assert 1 <= apt <= APT_WINDOW, (
                f"CHK-REC-THRESH FAIL: MIN_ENTROPY_H=0x{h:02x} gave APT_LIMIT={apt}, "
                f"outside the {APT_WINDOW}-sample window"
            )
            if prev_apt is not None:
                assert apt <= prev_apt, (
                    f"CHK-REC-THRESH FAIL: APT_LIMIT rose to {apt} at "
                    f"MIN_ENTROPY_H=0x{h:02x}; the cutoff must fall as H rises"
                )
            prev_apt = apt
            self.logger.info(
                "CHK-REC-THRESH PASS: MIN_ENTROPY_H=0x%02x -> RCT_LIMIT=%d (golden %d) "
                "APT_LIMIT=%d",
                h,
                rct,
                want,
                apt,
            )
        # Restore the locked value the walk established, so CHK-POST-LOCK still
        # compares against what CHK-PRE-LOCK proved.
        h_target = next(t for t in cfg.targets if t.name == "MIN_ENTROPY_H")
        await esrc.write(h_target.addr, h_target.pre)

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
        assert got == cfg.obs_enable, f"CHK-OBS-ENABLE-WRITABLE FAIL: BIW_OBS_CTRL.RAW_ENABLE={got}"
        self.logger.info("CHK-OBS-ENABLE-WRITABLE PASS: BIW_OBS_CTRL.RAW_ENABLE=%d under lock", got)

        await esrc.poke_reserved_ctrl_bit()
        got = await esrc.read_lock()
        assert got == 1, f"CHK-CTRL-RSVD FAIL: CTRL[0] write cleared lock to {got}"
        self.logger.info("CHK-CTRL-RSVD PASS: a CTRL[0] write left FIPS_LOCK.LOCK=1")

        await self.resense()
        got = await esrc.read_lock()
        assert got == 0, f"CHK-RST-NI FAIL: FIPS_LOCK={got} after rst_ni"
        self.logger.info("CHK-RST-NI PASS: rst_ni cleared FIPS_LOCK.LOCK")

        # cfg.release is chosen so its poke differs from the register reset. On a
        # target where the two agree, the reset value alone satisfies the readback
        # and a dropped post-unlock write would still pass.
        rel = cfg.release
        at_reset = await esrc.read(rel.addr)
        assert (at_reset & rel.mask) == (rel.reset & rel.mask), (
            f"CHK-POST-UNLOCK FAIL: {rel.name} did not return to reset after rst_ni: "
            f"0x{at_reset:08x} masked 0x{at_reset & rel.mask:08x} "
            f"want 0x{rel.reset & rel.mask:08x}"
        )
        await esrc.write(rel.addr, rel.poke)
        got = await esrc.read(rel.addr)
        assert (got & rel.mask) == (rel.poke & rel.mask), (
            f"CHK-POST-UNLOCK FAIL: {rel.name} still frozen 0x{got:08x} "
            f"after rst_ni poke 0x{rel.poke:08x}"
        )
        self.logger.info(
            "CHK-POST-UNLOCK PASS: %s moved 0x%08x -> 0x%08x after rst_ni",
            rel.name,
            at_reset & rel.mask,
            got & rel.mask,
        )
        self.logger.info(
            "CHK-RANDCFG PASS: walked %d locked classes: %s",
            cfg.n_cells(),
            ", ".join(t.name for t in cfg.targets),
        )
