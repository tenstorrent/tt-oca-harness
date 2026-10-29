# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""ESRC FIPS_LOCK freezes every locked field class, and only rst_ni clears the lock.

no_cpu / +skip_fuse_sense. RANDCFG: every locked field class is walked on every
seed, and the seed picks the values (CTRL functional, health-test window/enable, decorrelator,
ring-osc enable/tune, every generator sample-clock divider, FIFO enable and churn,
alert threshold, debug-pin mux). A pre-lock write moves the field off reset so the
post-lock reject is not a stuck register. Write-0 leaves LOCK=1.
Reserved CTRL.RSVD0 is RAZ/WI before the lock and does not clear it after;
rst_ni does. For every H > 0 the RCT cutoff is checked against the RDL formula
C = 1 + ceil(20 / H), and the APT cutoff against the SP 800-90B 4.4.2 binomial
cutoff for the 1024-sample window with the same alpha = 2^-20 (SP 800-90B 4.4:
alpha = 2^-20 is used in all the calculations of that section). At H = 0 neither
cutoff has a stated value; the read is logged as OBS-REC-THRESH-H0 and not graded.
Both observe-tap enables are writable before the lock and
frozen after it: one tap is held at 1 and rejects a clear, the other is held
at 0 and rejects a set (CHK-OBS-ENABLE-LOCKED). NOISE_OBS_CTRL.LANE_SEL stays
writable under the lock (CHK-OBS-LANE-SEL), and after rst_ni the tap held at 0
can be set again (CHK-OBS-POST-UNLOCK). Health-test ENABLE
stays 0 so this test does not trip the alert path.

Every write the lock must reject, and the reserved CTRL write, grades its OKAY
B response in the same CHK line, so a write that never reached the DUT fails.
CHK-RANDCFG grades the (register, field) pairs that the walked targets cover,
taken from their bus addresses and compare masks, against every field the RDL
marks swwel less the declared exclusions.

FCOV: the threshold sweep runs once with the owner window closed. The window
then opens, the sweep runs again, and the window stays open through
CHK-OBS-POST-UNLOCK; the first FAIL closes it. So the threshold bin samples only
on stimulus whose check already passed.

Scope: one field per locked class, not every swwel bit.
`sep_esrc_alert_delivery_test` covers alert delivery.
"""

from __future__ import annotations

import pyuvm
from cocotb.triggers import NextTimeStep
from env.sep_fabric_common import RESP_NAME, RESP_OKAY
from env.sep_fcov_gate import close_graded_window, open_graded_window
from sep_base_test import sep_base_test
from sep_reg_meta import ENTROPY_SOURCE
from seq_lib.sep_esrc_fips_lock_seq import (
    APT_WINDOW,
    CTRL_RSVD0_BIT,
    LOCK_BIT,
    SepEsrcFipsLock,
    SepEsrcFipsLockCfg,
    apt_limit_golden,
    rct_limit_golden,
    walk_must_cover,
    walked_locked_fields,
)

TEST = "sep_esrc_fips_lock_test"
WORD_MASK = 0xFFFF_FFFF


def _resp(code: int | None) -> str:
    return "none" if code is None else RESP_NAME.get(code, str(code))


def _lock_of(word: int) -> int:
    """FIPS_LOCK.LOCK as 0 or 1 from the whole register word."""
    return 1 if word & LOCK_BIT else 0


def _rsvd_of(word: int) -> str:
    """FIPS_LOCK reserved bits: no reset value in the register table, logged only."""
    return f"OBS rsvd=0x{word & ~LOCK_BIT & WORD_MASK:08x}"


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

    def _grade(self, chk: str, ok: bool, text: str) -> None:
        """Log one PASS line, or close the FCOV window and raise on FAIL."""
        if ok:
            self.logger.info("%s PASS: %s", chk, text)
            return
        self.logger.error("%s FAIL: %s", chk, text)
        close_graded_window(self.logger)
        raise AssertionError(f"{chk} FAIL: {text}")

    async def _check_pre(self, esrc: SepEsrcFipsLock, target) -> None:
        await esrc.write(target.addr, target.pre)
        got = await esrc.read(target.addr)
        self._grade(
            "CHK-PRE-LOCK",
            (got & target.mask) == (target.pre & target.mask),
            f"{target.name} wrote 0x{target.pre:08x} read 0x{got:08x} "
            f"mask 0x{target.mask:x} masked 0x{got & target.mask:08x}",
        )

    async def _check_post(self, esrc: SepEsrcFipsLock, target) -> None:
        # The target constructor asserts poke & mask != pre & mask, so a write
        # the lock let through moves the masked value.
        self._walked.append(target)
        resp = await esrc.write_resp(target.addr, target.poke)
        got = await esrc.read(target.addr)
        self._grade(
            "CHK-POST-LOCK",
            resp == RESP_OKAY and (got & target.mask) == (target.pre & target.mask),
            f"{target.name} poke 0x{target.poke:08x} B={_resp(resp)} pre 0x{target.pre:08x} "
            f"read 0x{got:08x} mask 0x{target.mask:x} held 0x{got & target.mask:08x} "
            f"want 0x{target.pre & target.mask:08x}",
        )

    async def _rec_thresh_sweep(self, esrc: SepEsrcFipsLock, cfg, label: str) -> None:
        """CHK-REC-THRESH over every sweep point; ``label`` names the pass."""
        # RECOMMENDED_THRESHOLDS is derived from MIN_ENTROPY_H per SP 800-90B.
        # The RCT cutoff golden is the RCT_LIMIT field formula, the APT cutoff
        # golden the 4.4.2 binomial cutoff for W = 1024 (apt_limit_golden);
        # neither comes from the design table. At H = 0 neither field has a
        # stated value, so that point is logged as OBS and graded by nothing.
        for h in cfg.rec_thresh_h:
            await esrc.write_min_entropy_h(h)
            rct, apt = await esrc.read_recommended_thresholds()
            want = rct_limit_golden(h)
            want_apt = apt_limit_golden(h)
            if want is None:
                self.logger.info(
                    "OBS-REC-THRESH-H0: %s MIN_ENTROPY_H=0x%02x RCT_LIMIT=%d APT_LIMIT=%d "
                    "(no stated RCT or APT value at H = 0)",
                    label,
                    h,
                    rct,
                    apt,
                )
                continue
            self._grade(
                "CHK-REC-THRESH",
                rct == want and apt == want_apt,
                f"{label} MIN_ENTROPY_H=0x{h:02x} RCT_LIMIT={rct} "
                f"golden={want} APT_LIMIT={apt} golden={want_apt} window={APT_WINDOW}",
            )

    async def run_scenario(self) -> None:
        await self.bring_up_no_cpu()
        cfg = SepEsrcFipsLockCfg(self.random_seed())
        esrc = SepEsrcFipsLock(self)
        self._walked: list = []
        self.logger.info("esrc fips lock: %s", cfg.summary())

        # The threshold bin samples at the RECOMMENDED_THRESHOLDS read, before
        # the compare. Grade the whole sweep with the window closed first, so the
        # in-window repeat runs only on stimulus that already passed.
        await self._rec_thresh_sweep(esrc, cfg, "window-closed")

        open_graded_window(TEST, self.logger)
        try:
            await self._graded(esrc, cfg)
        except BaseException:
            # A failure may resume from ReadOnly, where no value can be written.
            await NextTimeStep()
            close_graded_window(self.logger)
            raise
        close_graded_window(self.logger)
        # The pairs covered by the targets that CHK-POST-LOCK poked under the
        # lock, against the RDL swwel inventory less the declared exclusions.
        walked = self._walked
        covered = walked_locked_fields(walked)
        want = walk_must_cover()
        self._grade(
            "CHK-RANDCFG",
            covered == want,
            f"walked {len(walked)} targets covering {len(covered)} of {len(want)} locked "
            f"fields; missing={sorted(want - covered)} extra={sorted(covered - want)}",
        )

    async def _graded(self, esrc: SepEsrcFipsLock, cfg) -> None:
        """Every step from the in-window sweep to CHK-OBS-POST-UNLOCK."""
        # The sweep runs before the pre-lock walk, so the walk's MIN_ENTROPY_H
        # write sets the value CHK-POST-LOCK later compares.
        await self._rec_thresh_sweep(esrc, cfg, "window-open")

        for target in cfg.targets:
            await self._check_pre(esrc, target)

        # entropy_source.rdl: CTRL.RSVD0 is sw = r, hw = na, "Reserved; reads zero
        # and ignores writes." Prove RAZ/WI here, before the lock, where every other
        # CTRL field is demonstrably writable -- under the lock an unchanged CTRL is
        # explained by the lock alone and says nothing about RSVD0. The post-lock
        # repeat below keeps only the "does not clear the lock" half.
        ctrl_t = next(t for t in cfg.targets if t.name == "CTRL")
        ctrl_before, resp, ctrl_after = await esrc.poke_reserved_ctrl_bit()
        self._grade(
            "CHK-CTRL-RSVD",
            resp == RESP_OKAY
            and (ctrl_before & ctrl_t.mask) == (ctrl_t.pre & ctrl_t.mask)
            and (ctrl_before & CTRL_RSVD0_BIT) == 0
            and ctrl_after == ctrl_before,
            f"pre-lock CTRL 0x{ctrl_before:08x} (fields 0x{ctrl_before & ctrl_t.mask:08x} "
            f"want 0x{ctrl_t.pre & ctrl_t.mask:08x}), RSVD0 write B={_resp(resp)}, "
            f"CTRL after 0x{ctrl_after:08x} RSVD0={int(bool(ctrl_after & CTRL_RSVD0_BIT))}",
        )

        # Prove each observe-tap enable takes both values before the lock, then
        # leave it at the value it holds across the lock. A tap stuck at either
        # value fails here, so the post-lock freeze cannot pass on a stuck bit.
        for reg, held in cfg.obs_held.items():
            for want in (held ^ 1, held):
                await esrc.write_obs(reg, want, cfg.lane_pre)
                got, lane = await esrc.read_obs(reg)
                self._grade(
                    "CHK-OBS-PRE-LOCK",
                    got == want and (reg != "NOISE_OBS_CTRL" or lane == cfg.lane_pre),
                    f"{reg}.RAW_ENABLE wrote {want} read {got}; LANE_SEL wrote "
                    f"{cfg.lane_pre if reg == 'NOISE_OBS_CTRL' else 'n/a'} read {lane}",
                )

        resp = await esrc.set_lock()
        word = await esrc.read_lock_word()
        self._grade(
            "CHK-LOCK-SET",
            resp == RESP_OKAY and _lock_of(word) == 1,
            f"FIPS_LOCK.LOCK={_lock_of(word)} after a write of 1 B={_resp(resp)} "
            f"({_rsvd_of(word)})",
        )

        resp = await esrc.try_unlock()
        word = await esrc.read_lock_word()
        self._grade(
            "CHK-LOCK-W1S",
            resp == RESP_OKAY and _lock_of(word) == 1,
            f"FIPS_LOCK.LOCK={_lock_of(word)} after a write of 0 B={_resp(resp)} "
            f"({_rsvd_of(word)})",
        )

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
            self._grade(
                "CHK-OBS-ENABLE-LOCKED",
                got == held,
                f"{reg}.RAW_ENABLE read {got} after a {direction} under lock (held {held})",
            )
            if reg == "NOISE_OBS_CTRL":
                self._grade(
                    "CHK-OBS-LANE-SEL",
                    lane == cfg.lane_post,
                    f"NOISE_OBS_CTRL.LANE_SEL wrote {cfg.lane_post} read {lane} under lock "
                    f"(pre-lock {cfg.lane_pre})",
                )

        ctrl_before, resp, ctrl_after = await esrc.poke_reserved_ctrl_bit()
        word = await esrc.read_lock_word()
        self._grade(
            "CHK-CTRL-RSVD",
            resp == RESP_OKAY
            and (ctrl_after & ctrl_t.mask) == (ctrl_t.pre & ctrl_t.mask)
            and (ctrl_after & CTRL_RSVD0_BIT) == 0
            and _lock_of(word) == 1,
            f"locked CTRL RSVD0 write B={_resp(resp)}; CTRL 0x{ctrl_before:08x} -> "
            f"0x{ctrl_after:08x} (fields 0x{ctrl_after & ctrl_t.mask:08x} want "
            f"0x{ctrl_t.pre & ctrl_t.mask:08x}); FIPS_LOCK.LOCK={_lock_of(word)} "
            f"({_rsvd_of(word)})",
        )
        lock_before_rst = _lock_of(word)

        await self.resense()
        word = await esrc.read_lock_word()
        self._grade(
            "CHK-RST-NI",
            lock_before_rst == 1 and _lock_of(word) == 0,
            f"FIPS_LOCK.LOCK={lock_before_rst} before rst_ni, {_lock_of(word)} after rst_ni "
            f"({_rsvd_of(word)})",
        )

        # cfg.release is chosen so its poke differs from the register reset. On a
        # target where the two agree, the reset value alone satisfies the readback
        # and a dropped post-unlock write would still pass.
        rel = cfg.release
        at_reset = await esrc.read(rel.addr)
        await esrc.write(rel.addr, rel.poke)
        got = await esrc.read(rel.addr)
        self._grade(
            "CHK-POST-UNLOCK",
            (at_reset & rel.mask) == (rel.reset & rel.mask)
            and (got & rel.mask) == (rel.poke & rel.mask),
            f"{rel.name} read 0x{at_reset & rel.mask:08x} after rst_ni (reset "
            f"0x{rel.reset & rel.mask:08x}), then 0x{got & rel.mask:08x} after poke "
            f"0x{rel.poke & rel.mask:08x}",
        )
        # After rst_ni the tap that held 0 under the lock reads its reset and
        # accepts the set the lock rejected; then clear it again.
        rel_tap = next(reg for reg, held in cfg.obs_held.items() if held == 0)
        raw_reset = ENTROPY_SOURCE.fields(rel_tap)["RAW_ENABLE"]["reset"]
        at_reset, _ = await esrc.read_obs(rel_tap)
        await esrc.write_obs(rel_tap, 1)
        got, _ = await esrc.read_obs(rel_tap)
        self._grade(
            "CHK-OBS-POST-UNLOCK",
            at_reset == raw_reset and got == 1,
            f"{rel_tap}.RAW_ENABLE read {at_reset} after rst_ni (reset {raw_reset}) and "
            f"{got} after a set",
        )
        await esrc.write_obs(rel_tap, 0)
