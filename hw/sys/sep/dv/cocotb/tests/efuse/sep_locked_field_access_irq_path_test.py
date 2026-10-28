# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Locked-field shadow access raises sep_internal_interrupts[33].

no_cpu, real fuse sense, LC_PROD. Stages write-lock and read-lock on two
seed-selected SPARE fields plus an unlocked contrast in the same OTP image,
then accesses the *shadow* aperture. Source 34 (vector bit [33]) is the eFuse
locked-field access violation interrupt (hw/sys/sep/doc/interrupts.adoc:190-192;
:23, bit i is PIC source i + 1). No specification sentence states its level
after the access, its duration or how it clears, so the probe is watched on
every clock of each access, and the level after a locked access is logged as
OBS-LF-IRQ-DEASSERT and not graded. RAND-REP: every seed runs both the
write-lock and the read-lock case.

Every graded [33] value is taken while no earlier locked access can still
drive the line: each locked access is the first one after a SEP reset
(``resense``), and CTRL-IRQ-IDLE requires [33] low before it. The unlocked
access and the write-lock pre-read run after the same reset, before the locked
write. The read that follows a locked write grades only its data; its [33]
level is logged. The reset restores every shadow from OTP, and the base test
compares the shadow with the staged image after each sense.

Each access kind runs twice. Run 1 grades the unlocked, write-locked and
read-locked access with the FCOV owner window closed; run 2 repeats them inside
the window of this leaf. Inside the window ``cp_locked_field_irq`` and
``cp_src_exclusive_other[s34]`` hold the sample of each access with the step
tag the leaf writes before it (``set_ef_hold_tag``), and sample it only when
the leaf writes that tag as the pass label (``set_ef_hold_pass``) after every
check of the step passed. A FAIL closes the window before it is raised, which
drops the held samples. The read after the locked write runs with tag 0, so it
samples nothing. A vector watch on the whole interrupt vector grades
CHK-SRC34-EXCL at every rise of bit [33]: no other bit moves in that clock.

The specification (hw/sys/sep/doc/otp_fuse_controller.adoc, Shadow Register
and JTAG Access Control) says only that a write-locked shadow is not writable
and a read-locked shadow is not readable. It names no response code and no
read data for the AXI shadow path. So the locked checks grade the observable
effect: a write-locked field keeps its pre-write value, and a read-locked read
does not return the stored field value. The response code and the returned data
of a locked access are logged at info level and are not graded. The stored
value is read from the sensed shadow (``efuse_shadow_probe_o``) before each
locked read: the sensing FSM reads a read-locked fuse into its shadow
(otp_fuse_controller.adoc:109-110), so CTRL-READ-STAGED requires that shadow
word to equal the staged pattern, and CHK-READ-LOCK compares the read data
with that probed word. The pattern is staged in the OTP image at time 0, and
every sense of the leaf senses that image.

The shared config in ``env/sep_locked_field_irq.py`` is also the SECURE_TM
leaf's image. Its four-spare draw and ``SIP_DIS`` / ``SYS_DIS`` = 0 pins
are this leaf's seed-to-image map.

``+secure_tm_lock`` selects the SECURE_TM leaf instead: the field map marks
LOCKS/LOCKS_SPARE, LC_STATE, SIP_DIS and SYS_DIS ``SecureTmLock``, so a
shadow write to any of them is refused while the latched strap is high. Each field is
written twice with the same seeded payload -- once with the strap low, where it
must land, and once with it high, where the value must not move: the bus
readback equals the read before the write, and the sensed shadow word
(``efuse_shadow_probe_o``) equals the word staged in the OTP image.
CTRL-SECTM-LATCH logs ``secure_tm_o`` after each sense and requires 0 before
the control half and 1 before the deny half. No
specification sentence ties a SECURE_TM refusal to source 34
(hw/sys/sep/doc/otp_fuse_controller.adoc:176-178 names no interrupt), so the [33]
level during and after the refused write is logged as OBS-SECTM-IRQ and not
graded. The [33] level during the contrast write that follows the refused
writes is logged the same way: the level after a refused write is not stated.
The strap-low half is the positive control: without it a DUT whose
shadow writes never work at all would pass the deny half. LOCKS and
LOCKS_SPARE are one field-map entry, so LOCKS_SPARE carries their shared
positive control, and LOCKS takes its own on the slot-31 write-lock bit.
LC_STATE is written in bytes [31:8], which OR-merge as ordinary shadow bytes
and leave the lifecycle nibble alone.
"""

from __future__ import annotations

from typing import NoReturn

import cocotb
import pyuvm
from cocotb.triggers import Event, NextTimeStep, ReadOnly, RisingEdge
from env.sep_bit_watch import SepVecWatch, VecMark, VecWatchNoRiseError, pic_vector_watch
from env.sep_efuse_image import SepEfuseImage
from env.sep_efuse_test_lib import shadow_word
from env.sep_fcov_gate import (
    close_graded_window,
    open_graded_window,
    set_ef_hold_pass,
    set_ef_hold_tag,
)
from env.sep_lcc_golden import LC_PROD
from env.sep_locked_field_irq import (
    IRQ_LOCKED_FIELD,
    SECURE_TM_LOCK_FIELDS,
    SepLockedFieldIrqCfg,
)
from sep_base_test import sep_base_test
from seq_lib.sep_locked_field_irq_seq import SepLockedFieldIrq

_MAX_SENSE_CYCLES = 20_000
_TEST = "sep_locked_field_access_irq_path_test"
# Graded steps of one run: unlocked, write-lock pre-read, locked write, locked read.
_STEPS = 4


@pyuvm.test()
class sep_locked_field_access_irq_path_test(sep_base_test):
    """Write-lock and read-lock shadow accesses raise aggregator bit [33]."""

    async def _irq(self) -> int:
        # The specification states no duration for source 34, so a high
        # level of one clock must be seen: sample every posedge in ReadOnly.
        # This helper only observes; a second edge to leave ReadOnly would
        # skip a cycle. Callers that drive AXI wait their own edge after this
        # returns.
        await RisingEdge(cocotb.top.clk_i)
        await ReadOnly()
        raw = cocotb.top.sep_internal_interrupts_probe_o.value
        if not raw.is_resolvable:
            raise AssertionError("sep_internal_interrupts X/Z while sampling bit [33]")
        return (int(raw) >> IRQ_LOCKED_FIELD) & 1

    async def _irq_low(self) -> bool:
        """True when bit [33] is low at the next clk_i edge.

        It samples like ``_irq`` and then leaves the ReadOnly phase
        (``NextTimeStep``), so a gate write or a drive that follows it lands
        in a writable phase. No clock edge passes in between."""
        low = await self._irq() == 0
        await NextTimeStep()
        return low

    async def _access_watching(
        self,
        drv: SepLockedFieldIrq,
        name: str,
        *,
        write: bool = False,
        wdata: int = 0,
        word_idx: int = 0,
        locked: bool = False,
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
        seq = await drv.access(name, write=write, wdata=wdata, word_idx=word_idx, locked=locked)
        stop.set()
        await task
        # The watcher ends in ReadOnly; leave it before the caller grades,
        # writes the gate or drives.
        await NextTimeStep()
        return seq, seen_high

    async def _sectm_write(self, drv, cfg, name: str, blocked: bool) -> None:
        """One payload write to ``name``; require it to land, or to be refused.

        A refused write is graded twice: the bus readback equals the read
        before the write, and the sensed shadow word on
        ``efuse_shadow_probe_o`` equals the word staged in the OTP image. The
        resense before the deny half reloads every shadow from that image, so
        the staged word is the stored value. The probe does not use the bus
        read path, so a read path that returns 0 at secure_tm=1 cannot hide a
        refused write that landed in the shadow.
        """
        word, payload = cfg.sectm_payload[name]
        before = (await drv.access(name, word_idx=word)).rdata
        wr, irq = await self._access_watching(
            drv, name, word_idx=word, write=True, wdata=payload, locked=blocked
        )
        after = (await drv.access(name, word_idx=word)).rdata
        if blocked:
            assert after == before, (
                f"CHK-SECTM-BLOCK FAIL: {name}[{word}] moved 0x{before:08x} -> 0x{after:08x} "
                f"while secure_tm=1 (payload 0x{payload:08x})"
            )
            sh_idx = SepEfuseImage.field(name).word + word
            staged = self._sectm_img.words[sh_idx]
            probe = shadow_word(self, sh_idx)
            assert probe == staged, (
                f"CHK-SECTM-BLOCK FAIL: {name}[{word}] shadow word {sh_idx} = 0x{probe:08x} "
                f"after the refused write, staged 0x{staged:08x} (payload 0x{payload:08x}, "
                f"bus readback 0x{after:08x})"
            )
            low_after = await self._irq_low()
            self.logger.info(
                "CHK-SECTM-BLOCK PASS: %s[%d] stayed 0x%08x, shadow word %d = 0x%08x "
                "(staged 0x%08x, payload 0x%08x; BRESP=%d, not graded)",
                name,
                word,
                after,
                sh_idx,
                probe,
                staged,
                payload,
                wr.resp_code,
            )
            # No specification sentence ties a SECURE_TM refusal to source 34,
            # so the [33] level of the refused write is logged only.
            self.logger.info(
                "OBS-SECTM-IRQ: %s[%d] refused write: [33] pulsed=%d low_after=%d",
                name,
                word,
                int(irq),
                int(low_after),
            )
        else:
            assert wr.resp_ok, f"{name}[{word}] write at secure_tm=0 resp={wr.resp_code}"
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

    def _latch(self, want: int, when: str) -> None:
        """CTRL-SECTM-LATCH: ``secure_tm_o`` holds the strap that the last sense sampled.

        hw/sys/sep/doc/test_mode.adoc:29: fuse-sense completion samples the
        strap. The strap is stable before each sense of this leaf, so the
        latched value equals the strap (0 for the control half, 1 for the
        deny half). Any other value, or an X, fails the leaf here.
        """
        got = self.rd_known(cocotb.top.secure_tm_o) & 1
        if got != want:
            msg = f"secure_tm_o={got}, expected {want} ({when})"
            self.logger.error("CTRL-SECTM-LATCH FAIL: %s", msg)
            raise AssertionError(f"CTRL-SECTM-LATCH FAIL: {msg}")
        self.logger.info("CTRL-SECTM-LATCH PASS: secure_tm_o=%d (%s)", got, when)

    async def _run_secure_tm_scenario(self, cfg) -> None:
        img = self.select_efuse_image(lc_raw=LC_PROD, fixed=cfg.image_fixed())
        self.write_efuse_image(img)
        self._sectm_img = img
        await self.bring_up_and_wait_fuse_sense(max_cycles=_MAX_SENSE_CYCLES)
        self._latch(0, "strap low, after the first sense")
        assert await self._irq_low(), "[33] high before any shadow access"

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
        self._latch(1, "strap raised, after the resense")

        for name in SECURE_TM_LOCK_FIELDS:
            await self._sectm_write(drv, cfg, name, blocked=True)

        # Contrast: a SECURE_TM_UNLOCK spare still takes a write with the strap
        # up, so the deny above is the lock and not a dead write path.
        un_wr, un_irq = await self._access_watching(
            drv, cfg.unlocked_field, write=True, wdata=cfg.unlocked_write
        )
        assert un_wr.resp_ok, f"contrast write resp={un_wr.resp_code}"
        # The refused writes above may have raised source 34, and the level
        # after such a write is not stated, so the level here is logged only.
        self.logger.info(
            "OBS-SECTM-IRQ: %s contrast write at secure_tm=1: [33] seen=%d",
            cfg.unlocked_field,
            int(un_irq),
        )
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

    def _fail(self, name: str, msg: str) -> NoReturn:
        """A FAIL of a graded check: close the owner window first, then raise."""
        close_graded_window(self.logger)
        self.logger.error("CHK-%s FAIL: %s", name, msg)
        raise AssertionError(f"CHK-{name} FAIL: {msg}")

    def _grade(self, name: str, cond: bool, msg: str) -> None:
        if not cond:
            self._fail(name, msg)

    @staticmethod
    def _tag(run: int, step: int) -> int:
        """Step tag of the held FCOV samples, distinct for every step of the leaf."""
        return (run - 1) * _STEPS + step

    async def _release(self, tag: int) -> None:
        """Pass label of step ``tag``, written after every check of the step passed.

        The sampler samples the held samples of the tag at the next ``clk_i``
        edge; the label returns to 0 one clock later.
        """
        set_ef_hold_pass(tag, self.logger)
        await RisingEdge(cocotb.top.clk_i)
        set_ef_hold_pass(0, self.logger)

    async def _require_idle(self, run: int, before: str) -> None:
        """CTRL-IRQ-IDLE: [33] is low after a SEP reset, before the first access.

        No locked access has run since the reset, so no locked-field access
        violation is pending. A high level means the rise of the next locked
        access cannot be graded, so the leaf fails here.
        """
        if not await self._irq_low():
            close_graded_window(self.logger)
            msg = f"run={run} [33] high after the reset, before {before}"
            self.logger.error("CTRL-IRQ-IDLE FAIL: %s", msg)
            raise AssertionError(f"CTRL-IRQ-IDLE FAIL: {msg}")
        self.logger.info("CTRL-IRQ-IDLE PASS: run=%d [33] low before %s", run, before)

    async def _reset_and_sense(self, vec: SepVecWatch) -> SepVecWatch:
        """SEP reset and re-sense, with the vector watch stopped across the reset.

        The reset ends any [33] level that a locked access left, and the sense
        restores every shadow from OTP (the base test compares the shadow with
        the staged image). Returns a new vector watch started after the sense.
        """
        await vec.stop()
        await self.resense(max_cycles=_MAX_SENSE_CYCLES)
        return pic_vector_watch({"s34": IRQ_LOCKED_FIELD}).start()

    def _check_excl(self, vec: SepVecWatch, mark: VecMark, run: int, access: str) -> None:
        """CHK-SRC34-EXCL: at each rise of bit [33] every other bit keeps its value.

        interrupts.adoc:23 states bit i of the vector is PIC source i + 1, and
        :190-192 assigns source 34 (bit [33]) to the locked-field access alone,
        so no other bit moves at its rise. The six bits with an unstated idle
        level are not compared (pic_vector_watch). The locked access raises no
        other source, so no bit is exempt for the same clock. Each locked
        access is the first one after a reset, with [33] low before it
        (CTRL-IRQ-IDLE), so a run with no rise after the mark fails.
        """
        try:
            rises = vec.rises_since(mark, "s34")
            smears = vec.smears_since(mark, "s34")
        except VecWatchNoRiseError as exc:
            self._fail("SRC34-EXCL", f"run={run} access={access} {exc}")
        first = rises[0]
        self._grade(
            "SRC34-EXCL",
            not smears,
            f"run={run} access={access} rises={len(rises)} "
            f"moved={[(c, hex(m)) for c, m in smears]} "
            f"before=0x{first.before:011x} after=0x{first.after:011x}",
        )
        self.logger.info(
            "CHK-SRC34-EXCL PASS: run=%d access=%s rises=%d rise_clk=%s "
            "before=0x%011x after=0x%011x moved=0x0 (idle bits not compared)",
            run,
            access,
            len(rises),
            [r.clk for r in rises],
            first.before,
            first.after,
        )

    def _read_staged(self, cfg: SepLockedFieldIrqCfg, run: int) -> int:
        """CTRL-READ-STAGED: the sensed shadow of the read-locked spare holds the pattern.

        The sensing FSM reads a read-locked fuse into its shadow
        (otp_fuse_controller.adoc:109-110), and the pattern is in the OTP image
        before every sense of the leaf. A shadow word that differs means the
        read-lock check below would compare against a value the field never
        held, so the leaf fails here. Returns the probed word.
        """
        word = SepEfuseImage.field(cfg.read_field).word
        shadow = shadow_word(self, word)
        if shadow != cfg.read_pattern:
            close_graded_window(self.logger)
            msg = (
                f"run={run} {cfg.read_field} shadow word {word} = 0x{shadow:08x}, "
                f"staged 0x{cfg.read_pattern:08x}"
            )
            self.logger.error("CTRL-READ-STAGED FAIL: %s", msg)
            raise AssertionError(f"CTRL-READ-STAGED FAIL: {msg}")
        self.logger.info(
            "CTRL-READ-STAGED PASS: run=%d %s shadow word %d = 0x%08x (staged 0x%08x)",
            run,
            cfg.read_field,
            word,
            shadow,
            cfg.read_pattern,
        )
        return shadow

    async def _unlocked(self, drv: SepLockedFieldIrq, cfg: SepLockedFieldIrqCfg, run: int) -> None:
        """CHK-UNLOCKED: the unlocked spare takes a write and reads it back, and [33] stays low.

        The access is the first of its segment after a reset, so the field
        holds the staged ``unlocked_pattern`` and the line is low before it
        (CTRL-IRQ-IDLE). An unlocked access is no locked-field access
        violation (interrupts.adoc:190-192), so [33] does not rise.
        """
        if cfg.unlocked_write == cfg.unlocked_pattern:
            raise AssertionError(
                f"test bug: {cfg.unlocked_field} already holds 0x{cfg.unlocked_write:08x}, "
                "so CHK-UNLOCKED would pass on a dead write path"
            )
        tag = self._tag(run, 1)
        set_ef_hold_tag(tag, self.logger)
        un_wr, un_irq = await self._access_watching(
            drv, cfg.unlocked_field, write=True, wdata=cfg.unlocked_write
        )
        un_rd, un_rd_irq = await self._access_watching(drv, cfg.unlocked_field)
        low_after = await self._irq_low()
        self._grade(
            "UNLOCKED",
            un_wr.resp_ok
            and not un_irq
            and un_rd.resp_ok
            and un_rd.rdata == cfg.unlocked_write
            and not un_rd_irq
            and low_after,
            f"run={run} {cfg.unlocked_field} BRESP={un_wr.resp_code} wr_irq={int(un_irq)} "
            f"RRESP={un_rd.resp_code} readback=0x{un_rd.rdata:08x} "
            f"expected=0x{cfg.unlocked_write:08x} rd_irq={int(un_rd_irq)} "
            f"low_after={int(low_after)}",
        )
        self.logger.info(
            "CHK-UNLOCKED PASS: run=%d %s write/read OKAY, no [33], readback=0x%08x "
            "(staged before 0x%08x)",
            run,
            cfg.unlocked_field,
            un_rd.rdata,
            cfg.unlocked_pattern,
        )
        await self._release(tag)

    async def _write_lock(
        self, drv: SepLockedFieldIrq, cfg: SepLockedFieldIrqCfg, vec: SepVecWatch, run: int
    ) -> None:
        """CHK-WRITE-LOCK: [33] during the locked write, and the field keeps its value.

        The pre-read runs before any locked access of the segment, so it must
        raise no [33]. The read after the locked write grades only the data:
        the [33] level after a locked access is not stated, so that read runs
        with step tag 0 and its level is logged (OBS-LF-IRQ-DEASSERT). The
        write response is logged, not graded.
        """
        tag = self._tag(run, 2)
        set_ef_hold_tag(tag, self.logger)
        pre, pre_irq = await self._access_watching(drv, cfg.write_field)
        self._grade(
            "WRITE-LOCK",
            pre.resp_ok and pre.rdata == cfg.write_pattern and not pre_irq,
            f"run={run} pre-read RRESP={pre.resp_code} 0x{pre.rdata:08x}, expected OKAY "
            f"0x{cfg.write_pattern:08x}, irq={int(pre_irq)}",
        )
        self.logger.info(
            "CHK-WRITE-LOCK PASS: run=%d pre-read %s OKAY 0x%08x, no [33]",
            run,
            cfg.write_field,
            pre.rdata,
        )
        await self._release(tag)

        tag = self._tag(run, 3)
        set_ef_hold_tag(tag, self.logger)
        mark = vec.mark()
        wr, wr_irq = await self._access_watching(
            drv, cfg.write_field, write=True, wdata=cfg.write_pattern ^ 0xFFFF_FFFF, locked=True
        )
        wr_low = await self._irq_low()
        set_ef_hold_tag(0, self.logger)
        post, post_irq = await self._access_watching(drv, cfg.write_field)
        self.logger.info(
            "OBS-LF-IRQ-DEASSERT: run=%d access=write_lock [33] low_after=%d "
            "following_read_irq=%d (not graded: the level after the access is not stated)",
            run,
            int(wr_low),
            int(post_irq),
        )
        self._grade(
            "WRITE-LOCK",
            wr_irq and post.resp_ok and post.rdata == cfg.write_pattern,
            f"run={run} {cfg.write_field} wr_irq={int(wr_irq)} "
            f"following RRESP={post.resp_code} 0x{post.rdata:08x}, expected pre-write "
            f"0x{cfg.write_pattern:08x}",
        )
        self.logger.info(
            "CHK-WRITE-LOCK PASS: run=%d [33] during write, following read=0x%08x "
            "(unchanged; BRESP=%d, not graded)",
            run,
            post.rdata,
            wr.resp_code,
        )
        self._check_excl(vec, mark, run, "write_lock")
        await self._release(tag)

    async def _read_lock(
        self, drv: SepLockedFieldIrq, cfg: SepLockedFieldIrqCfg, vec: SepVecWatch, run: int
    ) -> None:
        """CHK-READ-LOCK: [33] during the locked read, and the data is not the stored value.

        The stored value is the sensed shadow word of the read-locked spare
        (CTRL-READ-STAGED). The staged pattern never equals the error-slave
        marker (env/sep_locked_field_irq.py), so a marker readback still
        differs. The read response code is logged, not graded; the [33] level
        after the read is logged (OBS-LF-IRQ-DEASSERT).
        """
        stored = self._read_staged(cfg, run)
        tag = self._tag(run, 4)
        set_ef_hold_tag(tag, self.logger)
        mark = vec.mark()
        rd, rd_irq = await self._access_watching(drv, cfg.read_field, locked=True)
        rd_low = await self._irq_low()
        set_ef_hold_tag(0, self.logger)
        self.logger.info(
            "OBS-LF-IRQ-DEASSERT: run=%d access=read_lock [33] low_after=%d "
            "(not graded: the level after the access is not stated)",
            run,
            int(rd_low),
        )
        self._grade(
            "READ-LOCK",
            rd.rdata != stored and rd_irq,
            f"run={run} {cfg.read_field} RDATA=0x{rd.rdata:08x} stored(shadow)=0x{stored:08x} "
            f"irq={int(rd_irq)} (RRESP={rd.resp_code})",
        )
        self.logger.info(
            "CHK-READ-LOCK PASS: run=%d [33] during read, RDATA=0x%08x != stored(shadow) "
            "0x%08x (RRESP=%d, not graded)",
            run,
            rd.rdata,
            stored,
            rd.resp_code,
        )
        self._check_excl(vec, mark, run, "read_lock")
        await self._release(tag)

    async def _graded_run(
        self, drv: SepLockedFieldIrq, cfg: SepLockedFieldIrqCfg, vec: SepVecWatch, run: int
    ) -> SepVecWatch:
        """One instance of each graded access, in two segments that each start after a reset.

        Segment 1: unlocked, then write-lock. Segment 2, after its own reset:
        read-lock. Run 2 opens the owner window for each segment and closes it
        before the reset. Returns the vector watch of segment 2.
        """
        window = run == 2
        await self._require_idle(run, "the unlocked access")
        if window:
            open_graded_window(_TEST, self.logger)
        await self._unlocked(drv, cfg, run)
        await self._write_lock(drv, cfg, vec, run)
        if window:
            close_graded_window(self.logger)
        vec = await self._reset_and_sense(vec)
        await self._require_idle(run, "the read-locked read")
        if window:
            open_graded_window(_TEST, self.logger)
        await self._read_lock(drv, cfg, vec, run)
        if window:
            close_graded_window(self.logger)
        return vec

    async def run_scenario(self) -> None:
        cfg = SepLockedFieldIrqCfg(self.random_seed())
        self.logger.info("locked-field irq path: %s", cfg.summary())

        if "secure_tm_lock" in cocotb.plusargs:
            await self._run_secure_tm_scenario(cfg)
            return

        # CTRL-IRQ-IDLE fails the leaf itself when its precondition is false;
        # the evidence list names the graded CHK lines only.
        self.required_evidence = (
            "CHK-UNLOCKED",
            "CHK-WRITE-LOCK",
            "CHK-READ-LOCK",
            "CHK-SRC34-EXCL",
        )
        img = self.select_efuse_image(lc_raw=LC_PROD, fixed=cfg.image_fixed())
        assert img.lc_raw() == LC_PROD, "test bug: image LC_STATE is not PROD"
        assert img.field_int("LOCKS_SPARE") == cfg.locks_spare
        self.write_efuse_image(img)
        await self.bring_up_and_wait_fuse_sense(max_cycles=_MAX_SENSE_CYCLES)

        drv = SepLockedFieldIrq(self)
        vec = pic_vector_watch({"s34": IRQ_LOCKED_FIELD}).start()

        # Run 1 grades every access with the owner window closed. Run 2 repeats
        # each access inside the window. Any exception closes the window
        # before it propagates.
        try:
            vec = await self._graded_run(drv, cfg, vec, run=1)
            vec = await self._reset_and_sense(vec)
            vec = await self._graded_run(drv, cfg, vec, run=2)
        except BaseException:
            # A raise from inside ``_irq`` leaves the ReadOnly phase first.
            await NextTimeStep()
            close_graded_window(self.logger)
            raise
        await vec.stop()

        self.logger.info("locked-field irq path ALL CHECKS PASS")
