# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Read-back verify reports a dropped eFuse program write; a plain program does not.

no_cpu, real fuse sense, ``+sep_efuse_prog_fail_count=2``. RANDCFG: the seed
selects one spare field and two distinct bits in it.

Contract. ``EFUSE_PROGRAM_CTRL.efuse_program_read_back`` (``efuse_interface_ctrl.rdl``)
selects a read back after the program; ``hw/ip/efuse/doc/interface.adoc`` names
the two commands ``FUSE_COMMAND_PROGRAM`` and ``FUSE_COMMAND_PROGRAM_READ_BACK``
("program with verification"), and ``program_status`` is 0 for no error and 1
for an error. The OTP bank model drops the first N program writes with no APB
error, as real OTP does (``hw/ip/efuse/dv/models/README.md``), so a dropped
write is visible only to the read-back compare.

The first two bank writes after reset are dropped:

  CHK-NORB-UNVERIFIED  program bit A without read-back, write dropped:
                       program_done with program_status 0, and the OTP word
                       still holds bit A clear.
  CHK-RB-DETECT        program bit B with read-back, write dropped:
                       program_done with program_status 1, and the OTP word
                       still holds bit B clear.
  CHK-NORB-PROGRAM     control: program bit A again without read-back, write
                       kept: program_status 0 and the OTP word gains bit A.
  CHK-RB-PROGRAM       control: program bit B again with read-back, write
                       kept: program_status 0 and the OTP word gains bit B.

Each OTP word is read through ``EFUSE_READ_CTRL`` and compared whole against an
image golden, so a write that lands on the wrong bit also fails. A controller
that always verifies fails CHK-NORB-UNVERIFIED; one that never verifies fails
CHK-RB-DETECT; the two controls show the same bit and the same command program
when the write is kept, so a clear bit in the first two rows is the dropped
write and not a broken path.
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
class sep_efuse_program_read_back_select_test(sep_base_test):
    """Read-back verify catches a dropped program write; a plain program does not."""

    required_evidence = (
        "CHK-NORB-UNVERIFIED",
        "CHK-RB-DETECT",
        "CHK-NORB-PROGRAM",
        "CHK-RB-PROGRAM",
    )

    async def _otp_word(self, word: int) -> int:
        rd = sep_efuse_direct_read_seq(word)
        await self.start_seq(rd)
        assert rd.rdata is not None
        return rd.rdata & 0xFFFF_FFFF

    async def _program(
        self, chk: str, bit_addr: int, *, read_back: bool, expect_err: bool, lands: bool
    ) -> None:
        seq = sep_efuse_otp_program_once_seq(bit_addr, read_back=read_back)
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
            f"{chk} FAIL: program bit {bit_addr} read_back={int(read_back)} "
            f"write {'kept' if lands else 'dropped'}: " + "; ".join(faults)
        )
        self.logger.info(
            "%s PASS: bit %d read_back=%d write %s -> EFUSE_PROGRAM_CTRL=0x%08x "
            "program_status=%d, OTP word %d = 0x%08x (bit %s)",
            chk,
            bit_addr,
            int(read_back),
            "kept" if lands else "dropped",
            seq.status,
            int(seq.program_err),
            bit_addr // 32,
            word,
            "set" if (word >> (bit_addr % 32)) & 1 else "clear",
        )

    async def run_scenario(self) -> None:
        rng = SepSeededRng(self.random_seed())
        field = spare_field_name(rng.randrange(SPARE_COUNT))
        nbits = SepEfuseImage.field(field).n_words * 32
        bit_a = rng.randrange(nbits)
        bit_b = (bit_a + 1 + rng.randrange(nbits - 1)) % nbits
        addr_a = field_bit_addr(field, bit_a)
        addr_b = field_bit_addr(field, bit_b)
        self.logger.info(
            "efuse read-back select: seed=%d %s bit_a=%d (OTP bit %d) bit_b=%d (OTP bit %d)",
            self.random_seed(),
            field,
            bit_a,
            addr_a,
            bit_b,
            addr_b,
        )

        img = self.select_efuse_image(lc_raw=LC_TEST_DEV, fixed=spare_zero_pins())
        assert img.field_int(field) == 0
        assert img.field_int("LOCKS") == 0 and img.field_int("LOCKS_SPARE") == 0
        self.write_efuse_image(img)
        await self.bring_up_and_wait_fuse_sense(max_cycles=_MAX_SENSE_CYCLES)
        self.golden = SepEfuseImage()
        self.golden.words = list(img.words)

        # The bank model drops the first two writes (+sep_efuse_prog_fail_count=2).
        await self._program(
            "CHK-NORB-UNVERIFIED", addr_a, read_back=False, expect_err=False, lands=False
        )
        await self._program("CHK-RB-DETECT", addr_b, read_back=True, expect_err=True, lands=False)
        await self._program(
            "CHK-NORB-PROGRAM", addr_a, read_back=False, expect_err=False, lands=True
        )
        await self._program("CHK-RB-PROGRAM", addr_b, read_back=True, expect_err=False, lands=True)
