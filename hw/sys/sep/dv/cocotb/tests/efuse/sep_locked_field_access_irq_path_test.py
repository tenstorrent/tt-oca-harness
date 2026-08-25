# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Locked-field shadow access raises sep_internal_interrupts[33].

no_cpu, real fuse sense, LC_PROD. Stages write-lock and read-lock on two
seed-selected SPARE fields plus an unlocked contrast in the same OTP image,
then accesses the *shadow* aperture. The interrupt is combinational and
pulse-only: watch the probe during the beat. BRESP stays OKAY (not SLVERR;
JTAG deny is a different path). RAND-REP both flavours every seed.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import Event, RisingEdge
import pyuvm

from sep_base_test import sep_base_test
from env.sep_lcc_golden import LC_PROD
from env.sep_locked_field_irq import (
    IRQ_LOCKED_FIELD,
    RESP_OKAY,
    SENTINEL,
    SepLockedFieldIrqCfg,
)
from seq_lib.sep_locked_field_irq_seq import SepLockedFieldIrq

_MAX_SENSE_CYCLES = 20_000


@pyuvm.test()
class sep_locked_field_access_irq_path_test(sep_base_test):
    """Write-lock and read-lock shadow accesses pulse aggregator bit [33]."""

    async def _irq(self) -> int:
        # Combinational pulse: a concurrent watcher samples during the AXI beat,
        # so this path cannot take ReadOnly (that window cannot drive the bus).
        await RisingEdge(cocotb.top.clk_i)
        raw = cocotb.top.sep_internal_interrupts_probe_o.value
        if not raw.is_resolvable:
            raise AssertionError(
                "sep_internal_interrupts X/Z while sampling bit [33]"
            )
        return (int(raw) >> IRQ_LOCKED_FIELD) & 1

    async def _access_watching(self, drv: SepLockedFieldIrq, name: str,
                               *, write: bool = False, wdata: int = 0):
        seen_high = False
        stop = Event()

        async def _watch() -> None:
            nonlocal seen_high
            while not stop.is_set():
                if await self._irq() == 1:
                    seen_high = True

        task = cocotb.start_soon(_watch())
        await RisingEdge(cocotb.top.clk_i)
        seq = await drv.access(name, write=write, wdata=wdata)
        stop.set()
        await task
        return seq, seen_high

    async def run_scenario(self) -> None:
        cfg = SepLockedFieldIrqCfg(self.random_seed())
        self.logger.info("locked-field irq path: %s", cfg.summary())

        img = self.select_efuse_image(lc_raw=LC_PROD, fixed=cfg.image_fixed())
        assert img.lc_raw() == LC_PROD, "test bug: image LC_STATE is not PROD"
        assert img.field_int("LOCKS_SPARE") == cfg.locks_spare
        self.write_efuse_image(img)
        await self.bring_up_and_wait_fuse_sense(max_cycles=_MAX_SENSE_CYCLES)

        drv = SepLockedFieldIrq(self)
        assert await self._irq() == 0, "[33] high before any shadow access"

        # Unlocked contrast: same driver, same aperture; [33] must stay low.
        un_wr, un_irq = await self._access_watching(
            drv, cfg.unlocked_field, write=True, wdata=cfg.unlocked_write)
        assert un_wr.resp_code == RESP_OKAY, (
            f"unlocked write resp={un_wr.resp_code}, expected OKAY"
        )
        assert not un_irq, (
            f"[33] rose during unlocked write of {cfg.unlocked_field}"
        )
        un_rd, un_rd_irq = await self._access_watching(drv, cfg.unlocked_field)
        assert un_rd.resp_code == RESP_OKAY and un_rd.rdata == cfg.unlocked_write, (
            f"unlocked readback 0x{un_rd.rdata:08x} resp={un_rd.resp_code}, "
            f"expected OKAY + 0x{cfg.unlocked_write:08x}"
        )
        assert not un_rd_irq, "[33] rose during unlocked read"
        assert await self._irq() == 0
        self.logger.info(
            "CHK-UNLOCKED PASS: %s write/read no [33], readback=0x%08x",
            cfg.unlocked_field, un_rd.rdata)

        # Write-lock: BRESP OKAY, following read equals pre-write, [33] during write.
        pre, pre_irq = await self._access_watching(drv, cfg.write_field)
        assert pre.resp_code == RESP_OKAY and pre.rdata == cfg.write_pattern, (
            f"write-locked pre-read 0x{pre.rdata:08x}, "
            f"expected 0x{cfg.write_pattern:08x}"
        )
        assert not pre_irq, "[33] rose on a legal read of a write-locked field"
        wr, wr_irq = await self._access_watching(
            drv, cfg.write_field, write=True, wdata=cfg.write_pattern ^ 0xFFFF_FFFF)
        assert wr.resp_code == RESP_OKAY, (
            f"write-lock write resp={wr.resp_code}, expected OKAY (not SLVERR)"
        )
        assert wr_irq, (
            f"[33] stayed low during write-locked write of {cfg.write_field}"
        )
        assert await self._irq() == 0, "[33] still high after write-lock write retired"
        post, post_irq = await self._access_watching(drv, cfg.write_field)
        assert post.resp_code == RESP_OKAY and post.rdata == cfg.write_pattern, (
            f"write-lock following read 0x{post.rdata:08x}, "
            f"expected pre-write 0x{cfg.write_pattern:08x}"
        )
        assert not post_irq, "[33] rose on the following legal read"
        self.logger.info(
            "CHK-WRITE-LOCK PASS: [33] during write, BRESP OKAY, "
            "following read=0x%08x (unchanged); [33] low after retire",
            post.rdata)

        # Read-lock: that read is the denial (sentinel + OKAY + [33]); no legal follow-up.
        rd, rd_irq = await self._access_watching(drv, cfg.read_field)
        assert rd.resp_code == RESP_OKAY, (
            f"read-lock read resp={rd.resp_code}, expected OKAY"
        )
        assert rd.rdata == SENTINEL, (
            f"read-lock RDATA=0x{rd.rdata:08x}, expected sentinel 0x{SENTINEL:08x}"
        )
        assert rd_irq, f"[33] stayed low during read-locked read of {cfg.read_field}"
        assert await self._irq() == 0, "[33] still high after read-lock read retired"
        self.logger.info(
            "CHK-READ-LOCK PASS: [33] during read, RDATA=0x%08x OKAY; "
            "[33] low after retire", rd.rdata)

        self.logger.info("locked-field irq path ALL CHECKS PASS")
