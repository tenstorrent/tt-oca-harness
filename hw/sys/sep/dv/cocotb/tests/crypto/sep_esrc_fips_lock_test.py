# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""ESRC FIPS_LOCK freezes every locked field class, and only rst_ni clears the lock.

no_cpu / +skip_fuse_sense. RANDCFG: every locked field class is walked on every
seed, and the seed picks the values (CTRL functional, health-test window/enable, decorrelator,
ring-osc enable/tune, every generator sample-clock divider, FIFO enable and churn,
alert threshold, debug-pin mux). A pre-lock write moves the field off reset so the
post-lock reject is not a stuck register. Write-0 leaves LOCK=1.
Reserved CTRL.RSVD0 is RAZ/WI before the lock and does not clear it after;
rst_ni does. The RCT cutoff is checked against an SP 800-90B 4.4.1 oracle. The
APT cutoff is checked to stay in the 1024-sample window and to fall as
MIN_ENTROPY_H rises. Both observe-tap enables are writable before the lock and
frozen after it: one tap is held at 1 and rejects a clear, the other is held
at 0 and rejects a set (CHK-OBS-ENABLE-LOCKED). NOISE_OBS_CTRL.LANE_SEL stays
writable under the lock (CHK-OBS-LANE-SEL), and after rst_ni the tap held at 0
can be set again (CHK-OBS-POST-UNLOCK). Health-test ENABLE
stays 0 so this test does not trip the alert path.

Scope: one field per locked class, not every swwel bit.
`sep_esrc_alert_delivery_test` covers alert delivery.
"""

from __future__ import annotations

import pyuvm
from sep_base_test import sep_base_test
from seq_lib.sep_esrc_fips_lock_seq import (
    APT_WINDOW,
    CTRL_RSVD0_BIT,
    SepEsrcFipsLock,
    SepEsrcFipsLockCfg,
    rct_limit_golden,
)


@pyuvm.test()
class sep_esrc_fips_lock_test(sep_base_test):
    """Lock freezes certified config, the debug pin and both observe-tap enables."""

    required_evidence = (
        "CHK-PRE-LOCK",
        "CHK-CTRL-RSVD",
        "CHK-REC-THRESH",
        "CHK-OBS-PRE-LOCK",
        "CHK-LOCK-SET",
        "CHK-LOCK-W1S",
        "CHK-POST-LOCK",
        "CHK-OBS-ENABLE-LOCKED",
        "CHK-OBS-LANE-SEL",
        "CHK-RST-NI",
        "CHK-POST-UNLOCK",
        "CHK-OBS-POST-UNLOCK",
        "CHK-RANDCFG",
    )

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

        # entropy_source.rdl: CTRL.RSVD0 is sw = r, hw = na, "Reserved; reads zero
        # and ignores writes." Prove RAZ/WI here, before the lock, where every other
        # CTRL field is demonstrably writable -- under the lock an unchanged CTRL is
        # explained by the lock alone and says nothing about RSVD0. The post-lock
        # repeat below keeps only the "does not clear the lock" half.
        ctrl_before, ctrl_after = await esrc.poke_reserved_ctrl_bit()
        assert (ctrl_before & CTRL_RSVD0_BIT) == 0 and (ctrl_after & CTRL_RSVD0_BIT) == 0, (
            f"CHK-CTRL-RSVD FAIL: CTRL.RSVD0 does not read zero "
            f"(0x{ctrl_before:08x} before, 0x{ctrl_after:08x} after the write)"
        )
        assert ctrl_after == ctrl_before, (
            f"CHK-CTRL-RSVD FAIL: pre-lock CTRL.RSVD0 write changed "
            f"0x{ctrl_before:08x} -> 0x{ctrl_after:08x}"
        )
        self.logger.info(
            "CHK-CTRL-RSVD PASS: CTRL.RSVD0 is RAZ/WI while CTRL is writable (0x%08x held)",
            ctrl_after,
        )

        # RECOMMENDED_THRESHOLDS is derived combinationally from MIN_ENTROPY_H by
        # entropy_source_rec_thresh_lut. The expected RCT cutoff is re-derived
        # from SP 800-90B 4.4.1 rather than read from that table, so the compare
        # is an oracle. APT_LIMIT is the exact binomial cutoff, which is not a
        # closed form; what the standard does fix is that it is bounded by the
        # 1024-sample window and falls as the assessed min-entropy rises.
        prev_apt = None
        first_apt = None
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
            if first_apt is None:
                first_apt = apt
            prev_apt = apt
            self.logger.info(
                "CHK-REC-THRESH PASS: MIN_ENTROPY_H=0x%02x -> RCT_LIMIT=%d (golden %d) "
                "APT_LIMIT=%d",
                h,
                rct,
                want,
                apt,
            )
        # The sweep runs from H=0x00 to the Q4.4 maximum, so across it the cutoff
        # must actually drop: a constant APT_LIMIT is never-rising but not falling.
        assert prev_apt < first_apt, (
            f"CHK-REC-THRESH FAIL: APT_LIMIT={prev_apt} at MIN_ENTROPY_H="
            f"0x{cfg.rec_thresh_h[-1]:02x} is not below {first_apt} at "
            f"0x{cfg.rec_thresh_h[0]:02x}; the cutoff must fall as H rises"
        )
        self.logger.info(
            "CHK-REC-THRESH PASS: APT_LIMIT fell %d -> %d across MIN_ENTROPY_H 0x%02x..0x%02x",
            first_apt,
            prev_apt,
            cfg.rec_thresh_h[0],
            cfg.rec_thresh_h[-1],
        )
        # Restore the locked value the walk established, so CHK-POST-LOCK still
        # compares against what CHK-PRE-LOCK proved.
        h_target = next(t for t in cfg.targets if t.name == "MIN_ENTROPY_H")
        await esrc.write(h_target.addr, h_target.pre)

        # Prove each observe-tap enable takes both values before the lock, then
        # leave it at the value it holds across the lock. A tap stuck at either
        # value fails here, so the post-lock freeze cannot pass on a stuck bit.
        for reg, held in cfg.obs_held.items():
            for want in (held ^ 1, held):
                await esrc.write_obs(reg, want, cfg.lane_pre)
                got, lane = await esrc.read_obs(reg)
                assert got == want, (
                    f"CHK-OBS-PRE-LOCK FAIL: {reg}.RAW_ENABLE wrote {want} read {got} before lock"
                )
            if reg == "NOISE_OBS_CTRL":
                assert lane == cfg.lane_pre, (
                    f"CHK-OBS-PRE-LOCK FAIL: NOISE_OBS_CTRL.LANE_SEL wrote {cfg.lane_pre} "
                    f"read {lane} before lock"
                )
            self.logger.info(
                "CHK-OBS-PRE-LOCK PASS: %s.RAW_ENABLE took %d then %d before lock",
                reg,
                held ^ 1,
                held,
            )

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

        # Under the lock, write the opposite value to each tap enable. For
        # NOISE_OBS_CTRL the same write moves LANE_SEL, which is not locked: the
        # lane moving while RAW_ENABLE holds shows the write reached the register
        # and the lock is per field, not a dropped write or a whole-register freeze.
        for reg, held in cfg.obs_held.items():
            await esrc.write_obs(reg, held ^ 1, cfg.lane_post)
            got, lane = await esrc.read_obs(reg)
            direction = "set" if held == 0 else "clear"
            assert got == held, (
                f"CHK-OBS-ENABLE-LOCKED FAIL: {reg}.RAW_ENABLE={got} accepted a {direction} "
                f"under lock (held {held})"
            )
            self.logger.info(
                "CHK-OBS-ENABLE-LOCKED PASS: %s.RAW_ENABLE held %d, rejected a %s under lock",
                reg,
                got,
                direction,
            )
            if reg == "NOISE_OBS_CTRL":
                assert lane == cfg.lane_post, (
                    f"CHK-OBS-LANE-SEL FAIL: NOISE_OBS_CTRL.LANE_SEL wrote {cfg.lane_post} "
                    f"read {lane} under lock (pre-lock {cfg.lane_pre})"
                )
                self.logger.info(
                    "CHK-OBS-LANE-SEL PASS: NOISE_OBS_CTRL.LANE_SEL moved %d -> %d under lock",
                    cfg.lane_pre,
                    lane,
                )

        await esrc.poke_reserved_ctrl_bit()
        got = await esrc.read_lock()
        assert got == 1, f"CHK-CTRL-RSVD FAIL: CTRL.RSVD0 write cleared lock to {got}"
        self.logger.info("CHK-CTRL-RSVD PASS: a CTRL.RSVD0 write left FIPS_LOCK.LOCK=1")

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
        # After rst_ni the tap that held 0 under the lock reads its reset and
        # accepts the set the lock rejected; then clear it again.
        rel_tap = next(reg for reg, held in cfg.obs_held.items() if held == 0)
        at_reset, _ = await esrc.read_obs(rel_tap)
        await esrc.write_obs(rel_tap, 1)
        got, _ = await esrc.read_obs(rel_tap)
        assert at_reset == 0 and got == 1, (
            f"CHK-OBS-POST-UNLOCK FAIL: {rel_tap}.RAW_ENABLE read {at_reset} after rst_ni "
            f"and {got} after a set"
        )
        await esrc.write_obs(rel_tap, 0)
        self.logger.info(
            "CHK-OBS-POST-UNLOCK PASS: %s.RAW_ENABLE read 0 after rst_ni and took a set",
            rel_tap,
        )
        self.logger.info(
            "CHK-RANDCFG PASS: walked %d locked classes: %s",
            cfg.n_cells(),
            ", ".join(t.name for t in cfg.targets),
        )
