# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""KM public-ID OTP fields carry the sensed SEP_*_ID eFuse values; secure test mode
blanks the four secrets to valid zero before the KM captures them.

no_cpu, real fuse sense, LC_PROD, ``+km_rom_hex=km_rom_otp_id.parhex``. RANDCFG.

``SepKmOtpIdCfg(seed)`` stages three public IDs with no zero, all-ones or
shared word, and sets the eFuse read lock of one of them, so every seed grades
a read-locked field next to two unlocked ones. The four secret fields carry
their fixed named vectors. Every expected value comes from the staged image.

Two legs, in this order: strap 0 (``secure_tm_req_i`` = 0, the bring-up) and
strap 1 (a cold reset with ``secure_tm_req_i`` = 1 from before the release and
a second real sense). Each leg releases the KM and waits for the image to
clear KM SRAM word 0 and then to store its done marker, so the strap-1 leg
never reads the marker of the strap-0 leg.

The specification sources: ``hw/sys/sep/doc/otp_fuse_controller.adoc`` routes
SEP_CHIPLET_ID, SEP_SIP_ID and SEP_SYS_ID to the Key Manager and blocks a
read-locked shadow read; ``hw/ip/key_manager/regs/km_csr.rdl`` places each field
at OTP_SEP_*_ID_VAL_0..7 (value) and CPL_0..7 (complement), zeroed while
OTP_READ_LOCK holds the field's bit.

  CHK-KM-ID-PORT        each field on the KM ``otp_data_i`` port is
                        ``{~id, id}`` of the staged value, before and after
                        the KM-side lock.
  CHK-KM-ID-EFUSE-LOCK  a shadow read of the eFuse-read-locked field does not
                        return its staged word; the same read of an unlocked
                        ID returns it, judged by the scoreboard.
  CHK-KM-ID-CSR         the 48 KMCSR words KM firmware read, the eFuse-locked
                        field included, are the staged words and their
                        complements.
  CHK-KM-ID-KM-LOCK     after KM firmware sets the three public-ID bits of
                        OTP_READ_LOCK, the register reads back exactly those
                        bits and the same 48 words read zero (their OR is 0).
  CHK-KM-SECRET-TM0     strap 0: the 32 KMCSR VAL words of the four secret
                        fields equal the staged words, and for each field the
                        AND over k of VAL_k XOR CPL_k is all ones (every CPL
                        word is the complement of its VAL word).
  CHK-KM-SECRET-TM1     strap 1 (``secure_tm_o`` = 1): every secret VAL word
                        reads 0 and every per-field rail word is all ones, so
                        every CPL word reads 0xFFFFFFFF: the valid zero of
                        ``hw/ip/key_manager/doc/architecture.adoc`` (secure test
                        mode replaces the four Class 1 sources with valid zero
                        values before KM captures them; a dual-rail value word is
                        the bitwise inverse of its complement word). A KM read
                        lock gives VAL = CPL = 0 and fails the rail word.
                        Control: CHK-KM-SECRET-TM0 of the same leaf.
  CHK-KM-PUBID-TM1      strap 1 (``secure_tm_o`` = 1): the 48 KMCSR public-ID
                        words KM firmware read, the eFuse-read-locked field
                        included, are the staged words and their complements.
                        ``hw/ip/key_manager/doc/architecture.adoc``: public
                        identities remain available in secure test mode;
                        ``hw/sys/sep/doc/test_mode.adoc`` disconnects only
                        CHIPLET_UID, SIP_UID, SYS_UID and CLASS_KEY. A public
                        ID masked to zero reads VAL = 0 against a staged word
                        that is never 0. Control: CHK-KM-ID-CSR at strap 0.

Logged, not graded: OBS-KM-OTHER-TM1 (the KM port public-ID taps at strap 1,
``OTP_LIFE_CYCLE`` and ``OTP_DEMOTION_STATE`` at both straps).
"""

from __future__ import annotations

from typing import Any

import cocotb
import pyuvm
from cocotb.triggers import RisingEdge
from env.sep_efuse_image import LC_PROD, SepEfuseImage
from env.sep_efuse_test_lib import rst_pulse, wait_bit
from env.sep_km_otp_id import (
    DEMOTION_WORD,
    DONE_MARKER,
    DONE_WORD,
    DUMP_WORDS,
    ID_FIELDS,
    ID_WORDS,
    KM_SECRET_FIELDS,
    LAST_WORD,
    LIFE_CYCLE_WORD,
    LOCK_READBACK_WORD,
    LOCKED_OR_WORD,
    OPEN_DUMP_WORD,
    RAIL_ALL_ONES,
    SECRET_RAIL_WORD,
    SECRET_VAL_WORD,
    SECRET_WORDS,
    SECRETS,
    WORD_BITS,
    WORD_MASK,
    SepKmOtpIdCfg,
    dual_rail,
    expected_window,
    id_word,
    km_id_lock_mask,
    secret_label,
    secret_val_words,
    window_label,
)
from sep_base_test import sep_base_test
from seq_lib.sep_efuse_shadow_check_seq import sep_efuse_shadow_check_seq
from seq_lib.sep_km_mem_smoke_seq import sep_km_release_seq
from seq_lib.sep_locked_field_irq_seq import SepLockedFieldIrq

_MAX_SENSE_CYCLES = 20_000
_MAX_KM_CYCLES = 50_000
_STM_BOUND = 16

_PROBES = {
    "SEP_CHIPLET_ID": "km_otp_sep_chiplet_id_o",
    "SEP_SIP_ID": "km_otp_sep_sip_id_o",
    "SEP_SYS_ID": "km_otp_sep_sys_id_o",
}


@pyuvm.test()
class sep_efuse_km_public_id_test(sep_base_test):
    """Sensed public IDs reach the KM port and KMCSR; each lock domain masks only its own path."""

    required_evidence = (
        "CHK-KM-ID-PORT",
        "CHK-KM-ID-EFUSE-LOCK",
        "CHK-KM-ID-CSR",
        "CHK-KM-ID-KM-LOCK",
        "CHK-KM-SECRET-TM0",
        "CHK-KM-SECRET-TM1",
        "CHK-KM-PUBID-TM1",
    )

    def _check_port(self, cfg: SepKmOtpIdCfg, when: str) -> None:
        for field in ID_FIELDS:
            observed = self.rd_known(getattr(cocotb.top, _PROBES[field]))
            expected = dual_rail(cfg.ids[field])
            assert observed == expected, (
                f"CHK-KM-ID-PORT FAIL ({when}): KM otp_data_i.{field.lower()} = "
                f"0x{observed:0128x}, expected {{~id, id}} = 0x{expected:0128x}"
            )
        self.logger.info(
            "CHK-KM-ID-PORT PASS (%s): KM otp_data_i carries {~id, id} for %s",
            when,
            ", ".join(ID_FIELDS),
        )

    async def _check_efuse_lock(self, cfg: SepKmOtpIdCfg, img: SepEfuseImage) -> None:
        drv = SepLockedFieldIrq(self)
        for k in range(ID_WORDS):
            staged = id_word(cfg.ids[cfg.locked_field], k)
            rd = await drv.access(cfg.locked_field, word_idx=k, locked=True)
            assert rd.rdata != staged, (
                f"CHK-KM-ID-EFUSE-LOCK FAIL: read-locked {cfg.locked_field}[{k}] returned "
                f"its staged word 0x{staged:08x} (resp={rd.resp_code})"
            )
        mark = self.sb_mark()
        await self.start_seq(
            sep_efuse_shadow_check_seq(
                img,
                "km_id_unlocked_shadow",
                fields=list(cfg.unlocked_fields),
                check_sense_status=False,
            )
        )
        self.assert_sb_judged(mark, "CHK-KM-ID-EFUSE-LOCK")
        self.logger.info(
            "CHK-KM-ID-EFUSE-LOCK PASS: %d shadow reads of read-locked %s withheld the "
            "staged words; %d reads of %s returned them",
            ID_WORDS,
            cfg.locked_field,
            ID_WORDS * len(cfg.unlocked_fields),
            " and ".join(cfg.unlocked_fields),
        )

    def _km_sram_words(self) -> list[int]:
        probe = cocotb.top.km_sram_probe_o
        count = len(probe) // WORD_BITS
        assert count > LAST_WORD, (
            f"test bug: km_sram_probe_o holds {count} words, the image writes word {LAST_WORD}"
        )
        value = self.rd_known(probe)
        return [(value >> (WORD_BITS * i)) & WORD_MASK for i in range(count)]

    async def _wait_km_done(self, leg: str) -> None:
        """Wait for word 0 to leave the marker (the image clears it first), then for it."""
        dut: Any = cocotb.top
        cleared = None
        for cycle in range(1, _MAX_KM_CYCLES + 1):
            await RisingEdge(dut.clk_i)
            word0 = self.rd(dut.km_sram_word0_o, allow_unknown=True)
            if cleared is None:
                if word0 != DONE_MARKER:
                    cleared = cycle
                continue
            if word0 == DONE_MARKER:
                self.logger.info(
                    "STEP KM firmware done (%s) after %d cycles, word 0 left the marker at %d",
                    leg,
                    cycle,
                    cleared,
                )
                return
        word0 = self.rd(dut.km_sram_word0_o, allow_unknown=True)
        raise AssertionError(
            f"KM firmware never stored its done marker 0x{DONE_MARKER:08x} to KM SRAM "
            f"word {DONE_WORD} in {_MAX_KM_CYCLES} cycles (word0=0x{word0:08x}, "
            f"KM ROM fetches={self.rd(dut.km_rom_req_count_o)})"
        )

    @staticmethod
    def _mismatches(observed: list[int], expected: list[int]) -> list[str]:
        return [
            f"{window_label(i)}=0x{o:08x} (expected 0x{e:08x})"
            for i, (o, e) in enumerate(zip(observed, expected))
            if o != e
        ]

    async def _km_run(self, leg: str) -> list[int]:
        await self.start_seq(sep_km_release_seq(f"km_release_{leg}"))
        await self._wait_km_done(leg)
        return self._km_sram_words()

    def _secret_check(self, sram: list[int], strap: int) -> tuple[bool, str]:
        vals = sram[SECRET_VAL_WORD : SECRET_VAL_WORD + SECRET_WORDS]
        rails = sram[SECRET_RAIL_WORD : SECRET_RAIL_WORD + len(KM_SECRET_FIELDS)]
        want = secret_val_words(SECRETS) if strap == 0 else [0] * SECRET_WORDS
        bad = [
            f"{secret_label(i)}=0x{o:08x} (expected 0x{e:08x})"
            for i, (o, e) in enumerate(zip(vals, want))
            if o != e
        ]
        bad += [
            f"rail {f}=0x{r:08x} (expected 0x{RAIL_ALL_ONES:08x})"
            for f, r in zip(KM_SECRET_FIELDS, rails)
            if r != RAIL_ALL_ONES
        ]
        line = (
            f"strap={strap} secure_tm_o={strap} val_words={SECRET_WORDS} "
            f"val0=0x{vals[0]:08x} expected0=0x{want[0]:08x} rails="
            + ",".join(f"0x{r:08x}" for r in rails)
        )
        return not bad, line + ("" if not bad else ": " + "; ".join(bad[:8]))

    async def run_scenario(self) -> None:
        cfg = SepKmOtpIdCfg(self.random_seed())
        self.logger.info("KM public-ID readout: %s", cfg.summary())

        img = self.select_efuse_image(lc_raw=LC_PROD, fixed=cfg.image_fixed())
        assert img.lc_raw() == LC_PROD, "test bug: image LC_STATE is not PROD"
        for field in ID_FIELDS:
            assert img.field_int(field) == cfg.ids[field], f"test bug: {field} not pinned"
        assert img.field_int("LOCKS") == cfg.locks, "test bug: LOCKS not pinned"
        for field in KM_SECRET_FIELDS:
            assert img.field_int(field) == SECRETS[field], f"test bug: {field} not pinned"
        self.write_efuse_image(img)
        await self.bring_up_and_wait_fuse_sense(max_cycles=_MAX_SENSE_CYCLES)

        self._check_port(cfg, "after sense")
        await self._check_efuse_lock(cfg, img)

        sram = await self._km_run("strap0")

        opened = sram[OPEN_DUMP_WORD : OPEN_DUMP_WORD + DUMP_WORDS]
        bad = self._mismatches(opened, expected_window(cfg.ids))
        assert not bad, f"CHK-KM-ID-CSR FAIL: {len(bad)} of {DUMP_WORDS} words: " + "; ".join(
            bad[:8]
        )
        self.logger.info(
            "CHK-KM-ID-CSR PASS: KM firmware read %d OTP_SEP_*_ID_{VAL,CPL} words equal "
            "to the staged IDs and their complements (eFuse-read-locked %s included)",
            DUMP_WORDS,
            cfg.locked_field,
        )

        readback = sram[LOCK_READBACK_WORD]
        assert readback == km_id_lock_mask(), (
            f"CHK-KM-ID-KM-LOCK FAIL: OTP_READ_LOCK read back 0x{readback:08x} after "
            f"setting the public-ID bits, expected 0x{km_id_lock_mask():08x}"
        )
        locked_or = sram[LOCKED_OR_WORD]
        assert locked_or == 0, (
            f"CHK-KM-ID-KM-LOCK FAIL: the OR of the {DUMP_WORDS} OTP_SEP_*_ID words read under "
            f"OTP_READ_LOCK is 0x{locked_or:08x}, expected 0"
        )
        self.logger.info(
            "CHK-KM-ID-KM-LOCK PASS: OTP_READ_LOCK=0x%08x; OR of all %d OTP_SEP_*_ID words=0x%08x",
            readback,
            DUMP_WORDS,
            locked_or,
        )
        self._check_port(cfg, "after KM OTP_READ_LOCK")

        ok0, line0 = self._secret_check(sram, 0)
        assert ok0, f"CHK-KM-SECRET-TM0 FAIL: {line0}"
        self.logger.info("CHK-KM-SECRET-TM0 PASS: %s", line0)
        other0 = (sram[LIFE_CYCLE_WORD], sram[DEMOTION_WORD])

        # Strap-1 leg: cold reset with the strap at 1, second real sense.
        dut: Any = cocotb.top
        await rst_pulse(self, strap=1)
        await self.wait_fuse_sense(max_cycles=_MAX_SENSE_CYCLES)
        self.cfg.reset_done.set()
        n = await wait_bit(self, "secure_tm_o", 1, _STM_BOUND)
        await RisingEdge(dut.clk_i)
        assert n is not None, (
            f"CHK-KM-SECRET-TM1 FAIL: precondition: secure_tm_o did not read 1 within "
            f"{_STM_BOUND} cycles after sensing with the strap at 1"
        )
        self.logger.info("STEP strap=1 secure_tm_o=1 after the second sense")
        port = {f: self.rd(getattr(dut, _PROBES[f]), allow_unknown=True) for f in ID_FIELDS}
        sram1 = await self._km_run("strap1")

        ok1, line1 = self._secret_check(sram1, 1)
        assert ok1, f"CHK-KM-SECRET-TM1 FAIL: {line1}"
        self.logger.info("CHK-KM-SECRET-TM1 PASS: %s control_tm0=1", line1)

        opened1 = sram1[OPEN_DUMP_WORD : OPEN_DUMP_WORD + DUMP_WORDS]
        bad1 = self._mismatches(opened1, expected_window(cfg.ids))
        zero1 = sum(1 for w in opened1 if w == 0)
        assert not bad1, (
            f"CHK-KM-PUBID-TM1 FAIL: strap=1 secure_tm_o=1 {len(bad1)} of {DUMP_WORDS} "
            f"words differ from the staged IDs (zero={zero1}): " + "; ".join(bad1[:8])
        )
        self.logger.info(
            "CHK-KM-PUBID-TM1 PASS: strap=1 secure_tm_o=1 KM firmware read %d "
            "OTP_SEP_*_ID_{VAL,CPL} words equal to the staged IDs and their complements "
            "(eFuse-read-locked %s included) zero=%d word0=0x%08x",
            DUMP_WORDS,
            cfg.locked_field,
            zero1,
            opened1[0],
        )
        self.logger.info(
            "OBS-KM-OTHER-TM1: KM port public-ID taps equal to staged at strap 1: %s",
            ",".join(f"{f}:{int(port[f] == dual_rail(cfg.ids[f]))}" for f in ID_FIELDS),
        )
        self.logger.info(
            "OBS-KM-OTHER-TM1: OTP_LIFE_CYCLE strap0=0x%08x strap1=0x%08x "
            "OTP_DEMOTION_STATE strap0=0x%08x strap1=0x%08x OTP_READ_LOCK strap1=0x%08x "
            "locked_or strap1=0x%08x",
            other0[0],
            sram1[LIFE_CYCLE_WORD],
            other0[1],
            sram1[DEMOTION_WORD],
            sram1[LOCK_READBACK_WORD],
            sram1[LOCKED_OR_WORD],
        )
