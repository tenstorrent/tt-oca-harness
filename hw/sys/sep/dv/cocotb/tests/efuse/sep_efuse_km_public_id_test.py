# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""KM public-ID OTP fields carry the sensed SEP_*_ID eFuse values.

no_cpu, real fuse sense, LC_PROD, ``+km_rom_hex=km_rom_otp_id.parhex``. RANDCFG.

``SepKmOtpIdCfg(seed)`` stages three public IDs with no zero, all-ones or
shared word, and sets the eFuse read lock of one of them, so every seed grades
a read-locked field next to two unlocked ones. Every expected value comes from
the staged image.

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
                        bits and the same 48 words read zero.
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.triggers import RisingEdge
from env.sep_efuse_image import LC_PROD, SepEfuseImage
from env.sep_km_otp_id import (
    DONE_MARKER,
    DONE_WORD,
    DUMP_WORDS,
    ID_FIELDS,
    ID_WORDS,
    LOCK_READBACK_WORD,
    LOCKED_DUMP_WORD,
    OPEN_DUMP_WORD,
    WORD_BITS,
    WORD_MASK,
    SepKmOtpIdCfg,
    dual_rail,
    expected_window,
    id_word,
    km_id_lock_mask,
    window_label,
)
from sep_base_test import sep_base_test
from seq_lib.sep_efuse_shadow_check_seq import sep_efuse_shadow_check_seq
from seq_lib.sep_km_mem_smoke_seq import sep_km_release_seq
from seq_lib.sep_locked_field_irq_seq import SepLockedFieldIrq

_MAX_SENSE_CYCLES = 20_000
_MAX_KM_CYCLES = 50_000

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
        assert count > LOCK_READBACK_WORD, (
            f"test bug: km_sram_probe_o holds {count} words, the image writes word "
            f"{LOCK_READBACK_WORD}"
        )
        value = self.rd_known(probe)
        return [(value >> (WORD_BITS * i)) & WORD_MASK for i in range(count)]

    async def _wait_km_done(self) -> None:
        dut = cocotb.top
        for cycle in range(1, _MAX_KM_CYCLES + 1):
            await RisingEdge(dut.clk_i)
            if self.rd(dut.km_sram_word0_o, allow_unknown=True) == DONE_MARKER:
                self.logger.info("STEP KM firmware done after %d cycles", cycle)
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

    async def run_scenario(self) -> None:
        cfg = SepKmOtpIdCfg(self.random_seed())
        self.logger.info("KM public-ID readout: %s", cfg.summary())

        img = self.select_efuse_image(lc_raw=LC_PROD, fixed=cfg.image_fixed())
        assert img.lc_raw() == LC_PROD, "test bug: image LC_STATE is not PROD"
        for field in ID_FIELDS:
            assert img.field_int(field) == cfg.ids[field], f"test bug: {field} not pinned"
        assert img.field_int("LOCKS") == cfg.locks, "test bug: LOCKS not pinned"
        self.write_efuse_image(img)
        await self.bring_up_and_wait_fuse_sense(max_cycles=_MAX_SENSE_CYCLES)

        self._check_port(cfg, "after sense")
        await self._check_efuse_lock(cfg, img)

        await self.start_seq(sep_km_release_seq("km_release"))
        await self._wait_km_done()
        sram = self._km_sram_words()

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
        locked = sram[LOCKED_DUMP_WORD : LOCKED_DUMP_WORD + DUMP_WORDS]
        bad = self._mismatches(locked, [0] * DUMP_WORDS)
        assert not bad, (
            f"CHK-KM-ID-KM-LOCK FAIL: {len(bad)} of {DUMP_WORDS} words still readable "
            "under OTP_READ_LOCK: " + "; ".join(bad[:8])
        )
        self.logger.info(
            "CHK-KM-ID-KM-LOCK PASS: OTP_READ_LOCK=0x%08x; all %d OTP_SEP_*_ID words read 0",
            readback,
            DUMP_WORDS,
        )
        self._check_port(cfg, "after KM OTP_READ_LOCK")
