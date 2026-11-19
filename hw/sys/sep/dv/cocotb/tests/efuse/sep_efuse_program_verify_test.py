# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The reference SHIM verifies every eFuse program and returns the read-back word.

no_cpu, real fuse sense, ``+sep_efuse_prog_fail_count=1``. RANDCFG: the seed
selects one spare field and one bit in it.

Contract. ``hw/ip/efuse/doc/architecture.adoc`` (Interface SHIM): the reference
SHIM always reads back the programmed word after the write, returns it in
``data``, and sets ``status`` when the bit did not stick. ``program_status`` is 0
for no error and 1 for an error, and ``EFUSE_PROGRAM_INTERFACE_READ_DATA`` holds the
data of the last successful program response (``efuse_interface_ctrl.rdl``). The
OTP bank model drops the first N program writes with no APB error, as real OTP
does (``hw/ip/efuse/dv/models/README.md``), so a dropped write is visible only to
the verify step.

The first bank write after reset is dropped:

  CHK-VERIFY-DETECT   program bit A, write dropped: program_done with
                      program_status 1, and the OTP word still holds bit A clear.
  CHK-VERIFY-PROGRAM  control: program bit A again, write kept: program_status 0
                      and the OTP word gains bit A.
  CHK-VERIFY-DATA     after the kept program, EFUSE_PROGRAM_INTERFACE_READ_DATA
                      equals the OTP word golden with bit A set.

Each OTP word is read through ``EFUSE_READ_CTRL`` and compared whole against an
image golden, so a write that lands on the wrong bit also fails. A SHIM that does
not verify fails CHK-VERIFY-DETECT; the control shows the same bit programs when
the write is kept, so the clear bit in the first row is the dropped write and not
a broken path. The image holds the field at 0, so a read-data value of 0 or of the
pre-program word fails CHK-VERIFY-DATA.
"""

from __future__ import annotations

import pyuvm
from env.sep_efuse_image import SepEfuseImage
from env.sep_lcc_golden import LC_TEST_DEV
from env.sep_locked_field_irq import SPARE_COUNT, spare_zero_pins
from env.sep_seeded_rng import SepSeededRng
from sep_base_test import sep_base_test
from seq_lib.sep_efuse_direct_read_seq import sep_efuse_direct_read_seq
from seq_lib.sep_efuse_otp_program_seq import sep_efuse_otp_program_once_seq
from seq_lib.sep_efuse_program_lock_seq import field_bit_addr, spare_field_name

_MAX_SENSE_CYCLES = 20_000


@pyuvm.test()
class sep_efuse_program_verify_test(sep_base_test):
    """The SHIM verify step reports a dropped program write and returns the word."""

    required_evidence = (
        "CHK-VERIFY-DETECT",
        "CHK-VERIFY-PROGRAM",
        "CHK-VERIFY-DATA",
    )

    async def _otp_word(self, word: int) -> int:
        rd = sep_efuse_direct_read_seq(word)
        await self.start_seq(rd)
        assert rd.rdata is not None
        return rd.rdata & 0xFFFF_FFFF

    async def _program(
        self, chk: str, bit_addr: int, *, expect_err: bool, lands: bool
    ) -> sep_efuse_otp_program_once_seq:
        seq = sep_efuse_otp_program_once_seq(bit_addr)
        await self.start_seq(seq)
        if lands:
            self.golden.words[bit_addr // 32] |= 1 << (bit_addr % 32)
        word = await self._otp_word(bit_addr // 32)
        want = self.golden.words[bit_addr // 32]
        faults = []
        if seq.program_err != expect_err:
            faults.append(
                f"program_status={int(seq.program_err)} (EFUSE_PROGRAM_CTRL=0x{seq.status:08x}), "
                f"expected {int(expect_err)}"
            )
        if word != want:
            faults.append(f"OTP word {bit_addr // 32} = 0x{word:08x}, expected 0x{want:08x}")
        assert not faults, (
            f"{chk} FAIL: program bit {bit_addr} write {'kept' if lands else 'dropped'}: "
            + "; ".join(faults)
        )
        self.logger.info(
            "%s PASS: bit %d write %s -> EFUSE_PROGRAM_CTRL=0x%08x "
            "program_status=%d, OTP word %d = 0x%08x (bit %s)",
            chk,
            bit_addr,
            "kept" if lands else "dropped",
            seq.status,
            int(seq.program_err),
            bit_addr // 32,
            word,
            "set" if (word >> (bit_addr % 32)) & 1 else "clear",
        )
        return seq

    async def run_scenario(self) -> None:
        rng = SepSeededRng(self.random_seed())
        field = spare_field_name(rng.randrange(SPARE_COUNT))
        nbits = SepEfuseImage.field(field).n_words * 32
        bit_a = rng.randrange(nbits)
        addr_a = field_bit_addr(field, bit_a)
        self.logger.info(
            "efuse program verify: seed=%d %s bit_a=%d (OTP bit %d)",
            self.random_seed(),
            field,
            bit_a,
            addr_a,
        )

        img = self.select_efuse_image(lc_raw=LC_TEST_DEV, fixed=spare_zero_pins())
        assert img.field_int(field) == 0
        assert img.field_int("LOCKS") == 0 and img.field_int("LOCKS_SPARE") == 0
        self.write_efuse_image(img)
        await self.bring_up_and_wait_fuse_sense(max_cycles=_MAX_SENSE_CYCLES)
        self.golden = SepEfuseImage()
        self.golden.words = list(img.words)

        # The bank model drops the first write (+sep_efuse_prog_fail_count=1).
        await self._program("CHK-VERIFY-DETECT", addr_a, expect_err=True, lands=False)
        kept = await self._program("CHK-VERIFY-PROGRAM", addr_a, expect_err=False, lands=True)

        want = self.golden.words[addr_a // 32]
        got = (kept.read_data or 0) & 0xFFFF_FFFF
        assert kept.read_data is not None and got == want, (
            f"CHK-VERIFY-DATA FAIL: EFUSE_PROGRAM_INTERFACE_READ_DATA = 0x{got:08x} after the "
            f"kept program of bit {addr_a}, expected OTP word {addr_a // 32} = 0x{want:08x}"
        )
        self.logger.info(
            "CHK-VERIFY-DATA PASS: EFUSE_PROGRAM_INTERFACE_READ_DATA = 0x%08x equals OTP word "
            "%d with bit %d set",
            got,
            addr_a // 32,
            addr_a % 32,
        )
