# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""CSR reset / RW / RO / reserved sweep over the generated SEP register export.

no_cpu / +skip_fuse_sense. RANDCFG: block order and complement-vs-ones
order come from the run seed. The reset walk is the inventory after
reasoned skips, not the raw OFFSET export.

Two of those skips are read off the RDL rather than named: a write-only
register returns no storage on a read, and a read-only register the RDL gives
no reset value is driven by hardware, so the generated DEFAULT is a field
default and not a POR value. Both read back 0 against a DEFAULT of 0 in most
cases, so keeping them would pass without the DUT having shown anything. The
ABR identity registers in that second group are proven frontdoor by the ABR
KAT tests, and the entropy-pool pair by sep_entropy_pool_aperture_test.

The same rule applies per field. A field the RDL gives no reset value has no
POR value, and the generated DEFAULT holds a 0 placeholder for it. A word made
only of such fields is skipped (HMAC DIGEST_*, MSG_LENGTH_*); a word with some
stays in the walk, and CHK-RESET masks those bits out of its compare (HMAC
CFG.hmac_en/sha_en). Full-mask write-lands covers the
scratch-cold, scratch-warm and CPU_CTRL registers; the inbound START/END
registers use the wrap model.

Write-lands is the anti-vacuity control: a complement write must move
exactly the software-usable mask bits. Inbound-filter START/END use the
full export mask and compare readback to the same-beat wrap model
(peer at reset). Remap and outbound-filter banks are reset-checked
only: an unprogrammed alias region still rewrites a live beat.

The masked storage touch adds a frontdoor RW proof for every register the
safety gate admits -- ``touch_reason`` clear (plain storage) AND
``side_effect_reason`` clear (a write reaches no further than the register):
write seed-derived ``x`` inside the software-usable mask, check
``(readback & mask) == (x & mask)``, restore reset. No key / lock / remap /
outbound filter / GO. The seed picks the values and the block order, not the
register set, so the touch count is the same at every seed. Always-on
threshold registers stay busy until ``prim_reg_cdc`` finishes on
``clk_wdt_i``; this sweep runs that clock at eight core periods so the
readback retires inside the AXI timeout.

CSRNG, EDN and ENTROPY_SOURCE reach the write side through this gate; those
rows are the write coverage of the entropy complex CSRs.
HMAC, KMAC and OTBN contribute INTR_ENABLE only -- the generated interrupt
shim, so those rows are block decode/storage evidence, not evidence about
the engine.
"""

from __future__ import annotations

import pyuvm
from sep_base_test import sep_base_test
from seq_lib.sep_reg_bit_bash_seq import SepRegBitBash, SepRegBitBashCfg, write_mask


@pyuvm.test()
class sep_reg_bit_bash_rand_test(sep_base_test):
    """Reset + write-bash + masked storage touch of the SEP register export."""

    async def run_scenario(self) -> None:
        cfg = SepRegBitBashCfg(self.random_seed())
        self.logger.info("bit-bash config: %s", cfg.summary())
        # Threshold writes return on clk_i. prim_reg_cdc then holds the register
        # busy until the pulse synchronizer finishes on clk_wdt_i, and the next
        # read waits for that. Eight core periods keeps the handshake inside the
        # AXI timeout. The readback compare is still the written value.
        self.cfg.wdt_clk_period_ns = 8 * self.cfg.sys_clk_period_ns
        self.logger.info(
            "WDT sim-timing knob: clk_wdt=%s ns (8x core) so a threshold "
            "readback retires inside the AXI timeout",
            self.cfg.wdt_clk_period_ns,
        )
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
                f"exported reset ({bash.reset_ok} matched)"
            )
        self.logger.info(
            "CHK-RESET PASS: %d register(s) matched the exported reset; %d of them "
            "under a mask that drops fields with no RDL reset",
            bash.reset_ok,
            bash.reset_masked,
        )

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
                f"({bash.lands_ok} lands, {bash.write_ok} restore)"
            )
        self.logger.info(
            "CHK-WRITE-LANDS PASS: %d complementary write(s) moved exactly "
            "the software-usable mask, plus %d inbound START/END that moved "
            "mask[31:3] and matched the same-beat wrap model",
            bash.lands_ok,
            bash.lands_upper_ok,
        )
        # Both counts are floors, not decorations: a regenerated export that
        # widened every mask, or dropped every reserved field, would take the
        # matching count to zero and the PASS line would still print. Assert the
        # population is non-empty so the token cannot outlive the thing it
        # reports on.
        assert bash.ro_ok > 0, (
            "CHK-RO FAIL: no write-bash register carried an out-of-mask bit, so "
            "nothing exercised the read-only contract -- if every mask is now all "
            "ones this check has no population and must be retired, not passed"
        )
        self.logger.info(
            "CHK-RO PASS: %d write-bash register(s) with out-of-mask bits "
            "left them unchanged (registers whose mask is all ones carry no "
            "out-of-mask bits and are not counted)",
            bash.ro_ok,
        )
        assert bash.reserved_ok > 0, (
            "CHK-RESERVED FAIL: no write-bash register carried a non-zero reserved "
            "field, so nothing exercised the reserved-reads-zero contract"
        )
        self.logger.info(
            "CHK-RESERVED PASS: %d write-bash register(s) with a non-zero "
            "reserved field read those bits back as 0",
            bash.reserved_ok,
        )

        touch_fails: list[str] = []
        for info, x in cfg.touch_regs:
            try:
                await bash.touch_write(info, x)
                self.logger.info(
                    "CHK-BLOCK-TOUCH PASS: %s.%s @0x%08x "
                    "readback matched wrote 0x%08x under mask 0x%08x",
                    info.block,
                    info.name,
                    info.addr,
                    x,
                    write_mask(info),
                )
            except AssertionError as exc:
                touch_fails.append(str(exc))
        if touch_fails:
            for line in touch_fails:
                self.logger.error(line)
            raise AssertionError(
                f"CHK-BLOCK-TOUCH FAIL: {len(touch_fails)} storage touch(es) ({bash.touch_ok} ok)"
            )
        self.logger.info(
            "CHK-BLOCK-TOUCH PASS: %d masked storage touch(es) landed inside "
            "the software-usable mask and restored reset",
            bash.touch_ok,
        )
        # Completeness, in the house CHK-RANDCFG sense: the whole seed-built
        # configuration ran in this one invocation. The counts are cfg-computed,
        # so this is not evidence about the DUT -- it is evidence that no part of
        # the walk was skipped. The walk sizes are printed with it so a shrunken
        # inventory is visible in the log rather than inferred from a PASS.
        walked = (
            ("reset", bash.reset_ok, len(cfg.reset_regs)),
            ("write", bash.write_ok, len(cfg.write_regs)),
            ("touch", bash.touch_ok, len(cfg.touch_regs)),
        )
        short = [f"{what} {done}/{want}" for what, done, want in walked if done != want]
        if short:
            raise AssertionError(
                f"CHK-RANDCFG FAIL: walk did not cover the configuration: {', '.join(short)}"
            )
        self.logger.info(
            "CHK-RANDCFG PASS: export=%d inventory=%d nometa=%d "
            "reset=%d write=%d touch=%d ones_first=%d seed=%d",
            cfg.export,
            cfg.inventory,
            cfg.nometa,
            len(cfg.reset_regs),
            len(cfg.write_regs),
            len(cfg.touch_regs),
            int(cfg.ones_first),
            cfg.seed,
        )
