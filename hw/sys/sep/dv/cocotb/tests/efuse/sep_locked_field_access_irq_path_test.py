# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Locked-field shadow access raises sep_internal_interrupts[33].

no_cpu, real fuse sense, LC_PROD. Stages write-lock and read-lock on two
seed-selected SPARE fields plus an unlocked contrast in the same OTP image,
then accesses the *shadow* aperture. The interrupt is combinational and
pulse-only: watch the probe during the beat. BRESP stays OKAY (not SLVERR;
JTAG deny is a different path). RAND-REP both flavours every seed.

The shared config in ``env/sep_locked_field_irq.py`` is also the SECURE_TM
leaf's image. Its four-spare draw and ``SIP_DIS`` / ``SYS_DIS`` = 0 pins
are this leaf's seed-to-image map.

``+secure_tm_lock`` selects the SECURE_TM leaf instead: the field map marks
LOCKS/LOCKS_SPARE, LC_STATE, SIP_DIS and SYS_DIS ``SECURE_TM_LOCK``, so a
shadow write to any of them is refused while the latched strap is high
(``secure_tm_i & lock[3]`` in efuse_shadow_reg_access_control). Each field is
written twice with the same seeded payload -- once with the strap low, where it
must land, and once with it high, where the value must not move and [33] must
pulse. The strap-low half is the positive control: without it a DUT whose
shadow writes never work at all would pass the deny half. LOCKS and
LOCKS_SPARE are one field-map entry, so LOCKS_SPARE carries their shared
positive control, and LOCKS takes its own on the slot-31 write-lock bit.
LC_STATE is written in
bytes [31:8], which OR-merge as ordinary shadow bytes and leave the lifecycle
nibble alone.
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.triggers import Event, ReadOnly, RisingEdge
from env.sep_lcc_golden import LC_PROD
from env.sep_locked_field_irq import (
    IRQ_LOCKED_FIELD,
    RESP_OKAY,
    SECURE_TM_LOCK_FIELDS,
    SENTINEL,
    SepLockedFieldIrqCfg,
)
from sep_base_test import sep_base_test
from seq_lib.sep_locked_field_irq_seq import SepLockedFieldIrq

_MAX_SENSE_CYCLES = 20_000


@pyuvm.test()
class sep_locked_field_access_irq_path_test(sep_base_test):
    """Write-lock and read-lock shadow accesses pulse aggregator bit [33]."""

    async def _irq(self) -> int:
        # Combinational 1-cycle pulse. Sample every posedge in ReadOnly.
        # This helper only observes; a second edge to leave ReadOnly would
        # skip a cycle and miss the pulse. Callers that drive AXI wait
        # their own edge after this returns.
        await RisingEdge(cocotb.top.clk_i)
        await ReadOnly()
        raw = cocotb.top.sep_internal_interrupts_probe_o.value
        if not raw.is_resolvable:
            raise AssertionError("sep_internal_interrupts X/Z while sampling bit [33]")
        return (int(raw) >> IRQ_LOCKED_FIELD) & 1

    async def _access_watching(
        self,
        drv: SepLockedFieldIrq,
        name: str,
        *,
        write: bool = False,
        wdata: int = 0,
        word_idx: int = 0,
    ):
        seen_high = False
        stop = Event()

        async def _watch() -> None:
            nonlocal seen_high
            while not stop.is_set():
                if await self._irq() == 1:
                    seen_high = True

        task = cocotb.start_soon(_watch())
        await RisingEdge(cocotb.top.clk_i)
        seq = await drv.access(name, write=write, wdata=wdata, word_idx=word_idx)
        stop.set()
        await task
        return seq, seen_high

    async def _sectm_write(self, drv, cfg, name: str, blocked: bool) -> None:
        """One payload write to ``name``; require it to land, or to be refused."""
        word, payload = cfg.sectm_payload[name]
        before = (await drv.access(name, word_idx=word)).rdata
        wr, irq = await self._access_watching(drv, name, word_idx=word, write=True, wdata=payload)
        after = (await drv.access(name, word_idx=word)).rdata
        assert wr.resp_code == RESP_OKAY, (
            f"{name}[{word}] write resp={wr.resp_code}, expected OKAY (not SLVERR)"
        )
        if blocked:
            assert after == before, (
                f"CHK-SECTM-BLOCK FAIL: {name}[{word}] moved 0x{before:08x} -> 0x{after:08x} "
                f"while secure_tm=1 (payload 0x{payload:08x})"
            )
            assert irq, f"CHK-SECTM-BLOCK FAIL: [33] stayed low on the refused {name} write"
            assert await self._irq() == 0, "[33] still high after the refused write retired"
            self.logger.info(
                "CHK-SECTM-BLOCK PASS: %s[%d] stayed 0x%08x, [33] pulsed, BRESP OKAY",
                name,
                word,
                after,
            )
        else:
            want = before | payload
            assert after == want, (
                f"CHK-SECTM-CONTROL FAIL: {name}[{word}] = 0x{after:08x}, expected "
                f"0x{want:08x} (0x{before:08x} | 0x{payload:08x}) at secure_tm=0"
            )
            assert after != before, (
                f"test bug: {name}[{word}] payload 0x{payload:08x} sets no new bit over "
                f"0x{before:08x}, so the deny half below would pass vacuously"
            )
            assert not irq, f"[33] rose on a legal {name} write at secure_tm=0"
            self.logger.info(
                "CHK-SECTM-CONTROL PASS: %s[%d] 0x%08x | 0x%08x = 0x%08x at secure_tm=0",
                name,
                word,
                before,
                payload,
                after,
            )

    async def _run_secure_tm_scenario(self, cfg) -> None:
        img = self.select_efuse_image(lc_raw=LC_PROD, fixed=cfg.image_fixed())
        self.write_efuse_image(img)
        await self.bring_up_and_wait_fuse_sense(max_cycles=_MAX_SENSE_CYCLES)
        assert int(cocotb.top.secure_tm_o.value) & 1 == 0, "strap low but secure_tm_o=1"
        assert await self._irq() == 0, "[33] high before any shadow access"

        drv = SepLockedFieldIrq(self)

        # Positive control, strap low: every field takes the write it is
        # refused below. The LOCKS payload is the slot-31 (SEP_SYS_ID)
        # write-lock bit, which nothing later in the leaf reads, and resense
        # restores the shadow from OTP before the deny half.
        for name in SECURE_TM_LOCK_FIELDS:
            await self._sectm_write(drv, cfg, name, blocked=False)

        # Latch TEST_EN. resense pulses rst_ni and re-samples the strap, so the
        # shadow returns to its sensed values and every "before" below is read
        # again after the strap is up.
        cocotb.top.test_en_strap_i.value = 1
        await self.resense(max_cycles=_MAX_SENSE_CYCLES)
        assert int(cocotb.top.secure_tm_o.value) & 1 == 1, (
            "TEST_EN strap raised and resensed, but secure_tm_o is still 0"
        )

        for name in SECURE_TM_LOCK_FIELDS:
            await self._sectm_write(drv, cfg, name, blocked=True)

        # Contrast: a SECURE_TM_UNLOCK spare still takes a write with the strap
        # up, so the deny above is the lock and not a dead write path.
        un_wr, un_irq = await self._access_watching(
            drv, cfg.unlocked_field, write=True, wdata=cfg.unlocked_write
        )
        assert un_wr.resp_code == RESP_OKAY, f"contrast write resp={un_wr.resp_code}"
        assert not un_irq, f"[33] rose during the secure_tm=1 write of {cfg.unlocked_field}"
        un_rd, _ = await self._access_watching(drv, cfg.unlocked_field)
        assert un_rd.rdata == cfg.unlocked_write, (
            f"CHK-SECTM-CONTRAST FAIL: {cfg.unlocked_field} readback 0x{un_rd.rdata:08x}, "
            f"expected 0x{cfg.unlocked_write:08x} -- the strap disabled more than the lock"
        )
        self.logger.info(
            "CHK-SECTM-CONTRAST PASS: %s still writable at secure_tm=1 (0x%08x)",
            cfg.unlocked_field,
            un_rd.rdata,
        )
        self.logger.info("secure_tm shadow-write lock ALL CHECKS PASS")

    async def run_scenario(self) -> None:
        cfg = SepLockedFieldIrqCfg(self.random_seed())
        self.logger.info("locked-field irq path: %s", cfg.summary())

        if "secure_tm_lock" in cocotb.plusargs:
            await self._run_secure_tm_scenario(cfg)
            return

        img = self.select_efuse_image(lc_raw=LC_PROD, fixed=cfg.image_fixed())
        assert img.lc_raw() == LC_PROD, "test bug: image LC_STATE is not PROD"
        assert img.field_int("LOCKS_SPARE") == cfg.locks_spare
        self.write_efuse_image(img)
        await self.bring_up_and_wait_fuse_sense(max_cycles=_MAX_SENSE_CYCLES)

        drv = SepLockedFieldIrq(self)
        assert await self._irq() == 0, "[33] high before any shadow access"

        # Unlocked contrast: same driver, same aperture; [33] must stay low.
        un_wr, un_irq = await self._access_watching(
            drv, cfg.unlocked_field, write=True, wdata=cfg.unlocked_write
        )
        assert un_wr.resp_code == RESP_OKAY, f"unlocked write resp={un_wr.resp_code}, expected OKAY"
        assert not un_irq, f"[33] rose during unlocked write of {cfg.unlocked_field}"
        un_rd, un_rd_irq = await self._access_watching(drv, cfg.unlocked_field)
        assert un_rd.resp_code == RESP_OKAY and un_rd.rdata == cfg.unlocked_write, (
            f"unlocked readback 0x{un_rd.rdata:08x} resp={un_rd.resp_code}, "
            f"expected OKAY + 0x{cfg.unlocked_write:08x}"
        )
        assert not un_rd_irq, "[33] rose during unlocked read"
        assert await self._irq() == 0
        self.logger.info(
            "CHK-UNLOCKED PASS: %s write/read no [33], readback=0x%08x",
            cfg.unlocked_field,
            un_rd.rdata,
        )

        # Write-lock: BRESP OKAY, following read equals pre-write, [33] during write.
        pre, pre_irq = await self._access_watching(drv, cfg.write_field)
        assert pre.resp_code == RESP_OKAY and pre.rdata == cfg.write_pattern, (
            f"write-locked pre-read 0x{pre.rdata:08x}, expected 0x{cfg.write_pattern:08x}"
        )
        assert not pre_irq, "[33] rose on a legal read of a write-locked field"
        wr, wr_irq = await self._access_watching(
            drv, cfg.write_field, write=True, wdata=cfg.write_pattern ^ 0xFFFF_FFFF
        )
        assert wr.resp_code == RESP_OKAY, (
            f"write-lock write resp={wr.resp_code}, expected OKAY (not SLVERR)"
        )
        assert wr_irq, f"[33] stayed low during write-locked write of {cfg.write_field}"
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
            post.rdata,
        )

        # Read-lock: that read is the denial (sentinel + OKAY + [33]); no legal follow-up.
        rd, rd_irq = await self._access_watching(drv, cfg.read_field)
        assert rd.resp_code == RESP_OKAY, f"read-lock read resp={rd.resp_code}, expected OKAY"
        assert rd.rdata == SENTINEL, (
            f"read-lock RDATA=0x{rd.rdata:08x}, expected sentinel 0x{SENTINEL:08x}"
        )
        assert rd_irq, f"[33] stayed low during read-locked read of {cfg.read_field}"
        assert await self._irq() == 0, "[33] still high after read-lock read retired"
        self.logger.info(
            "CHK-READ-LOCK PASS: [33] during read, RDATA=0x%08x OKAY; [33] low after retire",
            rd.rdata,
        )

        self.logger.info("locked-field irq path ALL CHECKS PASS")
