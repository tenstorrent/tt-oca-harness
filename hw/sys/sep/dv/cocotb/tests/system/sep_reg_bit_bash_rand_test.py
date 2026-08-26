# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""CSR reset / RW / RO / reserved sweep over the generated SEP register export.

no_cpu / +skip_fuse_sense. RANDCFG: block order and complement-vs-ones
order come from the run seed. Every reset-eligible register and every
write-safe register is walked in one invocation.

Write-lands is the anti-vacuity control: a complement write must move
exactly the software-usable mask bits. Inbound-filter START/END use the
full export mask and compare readback to the same-beat wrap model
(peer at reset). Remap and outbound-filter banks are reset-checked
only: an unprogrammed alias region still rewrites a live beat.

BLOCK_TOUCH adds one seed-selected frontdoor RW storage proof per other
major IP from the export candidate list: write seed-derived ``x``, check
``(readback & mask) == (x & mask)``, restore reset. No GO/key/remap.
"""

from __future__ import annotations

import pyuvm

from sep_base_test import sep_base_test
from seq_lib.sep_reg_bit_bash_seq import SepRegBitBash, SepRegBitBashCfg


@pyuvm.test()
class sep_reg_bit_bash_rand_test(sep_base_test):
    """Reset + write-bash + per-IP storage touch of the SEP register export."""

    async def run_scenario(self) -> None:
        cfg = SepRegBitBashCfg(self.random_seed())
        self.logger.info("bit-bash config: %s", cfg.summary())
        await self.bring_up_no_cpu()
        bash = SepRegBitBash(self)

        reset_fails: list[str] = []
        for info in cfg.reset_regs:
            miss = await bash.check_reset(info)
            if miss is not None:
                reset_fails.append(miss)
        if reset_fails:
            for line in reset_fails:
                self.logger.error(line)
            raise AssertionError(
                f"CHK-RESET FAIL: {len(reset_fails)} register(s) missed the "
                f"exported reset ({bash.reset_ok} matched)")
        self.logger.info(
            "CHK-RESET PASS: %d register(s) matched the exported reset",
            bash.reset_ok)

        write_fails: list[str] = []
        for info in cfg.write_regs:
            try:
                await bash.bash_write(info, ones_first=cfg.ones_first)
            except AssertionError as exc:
                write_fails.append(str(exc))
        if write_fails:
            for line in write_fails:
                self.logger.error(line)
            raise AssertionError(
                f"CHK-WRITE FAIL: {len(write_fails)} register(s) "
                f"({bash.lands_ok} lands, {bash.write_ok} restore)")
        self.logger.info(
            "CHK-WRITE-LANDS PASS: %d complementary write(s) moved exactly "
            "the software-usable mask",
            bash.lands_ok)
        self.logger.info(
            "CHK-RO PASS: %d write-bash register(s) left bits outside mask "
            "unchanged",
            bash.write_ok)
        self.logger.info(
            "CHK-RESERVED PASS: reserved bits read back 0 on every "
            "write-bash register with a software-usable field")

        touch_fails: list[str] = []
        for info, x in cfg.touch_regs:
            try:
                await bash.touch_write(info, x)
                self.logger.info(
                    "CHK-BLOCK-TOUCH PASS: %s.%s @0x%08x "
                    "(read & mask 0x%08x) == (x 0x%08x & mask)",
                    info.block, info.name, info.addr, info.mask, x)
            except AssertionError as exc:
                touch_fails.append(str(exc))
        if touch_fails:
            for line in touch_fails:
                self.logger.error(line)
            raise AssertionError(
                f"CHK-BLOCK-TOUCH FAIL: {len(touch_fails)} IP touch(es) "
                f"({bash.touch_ok} ok)")
        self.logger.info(
            "CHK-BLOCK-TOUCH PASS: %d IP storage touch(es)",
            bash.touch_ok)
        self.logger.info(
            "CHK-RANDCFG PASS: reset=%d write=%d touch=%d ones_first=%d "
            "from seed %d",
            len(cfg.reset_regs), len(cfg.write_regs), len(cfg.touch_regs),
            int(cfg.ones_first), cfg.seed)
