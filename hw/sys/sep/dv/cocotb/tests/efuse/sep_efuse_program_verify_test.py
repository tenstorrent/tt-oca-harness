# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The reference SHIM verifies every eFuse program and returns the read-back word.

no_cpu, real fuse sense, ``+sep_efuse_prog_fail_count=1``. RANDCFG: the seed
selects one spare field and bit A in it, then a second spare field and two distinct
bits B and C in it.

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
  CHK-VERIFY-DATA-HOLD  after one READ command of the OTP word of B (golden 0, so it
                      differs from the word of A), EFUSE_PROGRAM_INTERFACE_READ_DATA
                      still equals the word of the kept program
                      (``hw/ip/efuse/regs/efuse_interface_ctrl.rdl:156``: held until the
                      next successful program).
  CHK-INFLIGHT-LOCK   program bit B and write the write-lock of its spare field to
                      ``LOCKS_SPARE`` after the go and before program_done: the program
                      completes with program_status 0, ``efuse_req_error`` stays 0 and
                      the OTP word gains bit B (``hw/ip/efuse/doc/architecture.adoc:252-255``:
                      the guard checks the target when the command starts, and a lock
                      set after a command has been issued does not affect that command).
                      It runs last, because the lock holds until reset.

Controls of CHK-INFLIGHT-LOCK: before the go, ``efuse_req_error`` reads 0 and the lock
bit reads 0 (``CTRL-INFLIGHT-PRE``). ``program_busy`` reads 1 after the go and again after
the lock write completes, and ``LOCKS_SPARE`` reads the lock bit back
(``CTRL-INFLIGHT-WINDOW``), so the lock lands while the program is in flight.
``EFUSE_BANK_INIT_TIME`` is raised for this program only, to widen that window, and is
restored before the OTP read. After the lock, a program of bit C of the same field is
refused: program_status 1, ``efuse_req_error`` 1 and bit C clear (``CTRL-INFLIGHT-LOCK-LIVE``,
``hw/sys/sep/doc/otp_fuse_controller.adoc:110-111``: a write-lock blocks fuse programming),
so the lock write is live.

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
from env.sep_efuse_plan import PROGRAM_CTRL_ADDR, STATUS_ADDR, program_ctrl_word, shadow_addr
from env.sep_efuse_test_lib import SepEfuseFd
from env.sep_lcc_golden import LC_TEST_DEV
from env.sep_locked_field_irq import SPARE_COUNT, spare_zero_pins
from env.sep_seeded_rng import SepSeededRng
from sep_base_test import sep_base_test
from sep_reg_meta import EFUSE_INTERFACE_CTRL, RegBlock, sym
from seq_lib.sep_efuse_direct_read_seq import sep_efuse_direct_read_seq
from seq_lib.sep_efuse_otp_program_seq import sep_efuse_otp_program_once_seq
from seq_lib.sep_efuse_program_lock_seq import field_bit_addr, spare_field_name

_MAX_SENSE_CYCLES = 20_000
_PROGRAM_READ_DATA = EFUSE_INTERFACE_CTRL.addr("EFUSE_PROGRAM_INTERFACE_READ_DATA")
_PG_BUSY = EFUSE_INTERFACE_CTRL.field_mask("EFUSE_PROGRAM_CTRL", "program_busy")
_PG_DONE = EFUSE_INTERFACE_CTRL.field_mask("EFUSE_PROGRAM_CTRL", "program_done")
_PG_STATUS = EFUSE_INTERFACE_CTRL.field_mask("EFUSE_PROGRAM_CTRL", "program_status")
_REQ_ERROR = EFUSE_INTERFACE_CTRL.field_mask("EFUSE_INTERFACE_CTRL_STATUS", "efuse_req_error")
_LOCKS_SPARE_ADDR = shadow_addr("LOCKS_SPARE")
_EFUSE_MAP = RegBlock("SEP_EFUSE_MAP")
_INIT_TIME_ADDR = RegBlock("SEP_EXTERNAL_EFUSE_SHIM_CTRL").addr("EFUSE_BANK_INIT_TIME")
_INIT_TIME_RESET = sym("EFUSE_SHIM_CTRL_EFUSE_BANK_INIT_TIME_REG_DEFAULT")
# Bank wait cycles for the in-flight program (test parameter): it keeps the program
# busy across the frontdoor lock write, which CTRL-INFLIGHT-WINDOW then shows.
_INIT_TIME_INFLIGHT = 512
# Frontdoor reads of EFUSE_PROGRAM_CTRL that wait for program_done of that program.
_INFLIGHT_POLLS = 400


@pyuvm.test()
class sep_efuse_program_verify_test(sep_base_test):
    """The SHIM verify step reports a dropped program write and returns the word."""

    required_evidence = (
        "CHK-VERIFY-DETECT",
        "CHK-VERIFY-PROGRAM",
        "CHK-VERIFY-DATA",
        "CHK-VERIFY-DATA-HOLD",
        "CHK-INFLIGHT-LOCK",
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

    async def _check_data_hold(self, held: int, read_word: int) -> None:
        """CHK-VERIFY-DATA-HOLD: one READ command leaves the program read data unchanged."""
        golden = self.golden.words[read_word]
        if golden == held:
            raise AssertionError(
                f"test bug: OTP word {read_word} golden 0x{golden:08x} equals the held "
                "program read data, so a READ that overwrote it would not show"
            )
        got_read = await self._otp_word(read_word)
        got = await self.fd.rd(_PROGRAM_READ_DATA)
        assert got_read == golden and got == held, (
            f"CHK-VERIFY-DATA-HOLD FAIL: after a READ of OTP word {read_word} "
            f"(read 0x{got_read:08x}, golden 0x{golden:08x}), "
            f"EFUSE_PROGRAM_INTERFACE_READ_DATA = 0x{got:08x}, expected the held 0x{held:08x}"
        )
        self.logger.info(
            "CHK-VERIFY-DATA-HOLD PASS: after a READ of OTP word %d = 0x%08x, "
            "EFUSE_PROGRAM_INTERFACE_READ_DATA = 0x%08x (held)",
            read_word,
            got_read,
            got,
        )

    async def _set_init_time(self, value: int) -> None:
        await self.fd.wr(_INIT_TIME_ADDR, value)
        got = await self.fd.rd(_INIT_TIME_ADDR)
        assert got == value, (
            f"CTRL-INFLIGHT-INIT FAIL: EFUSE_BANK_INIT_TIME reads 0x{got:08x} after a write "
            f"of 0x{value:08x}"
        )
        self.logger.info("CTRL-INFLIGHT-INIT PASS: EFUSE_BANK_INIT_TIME = 0x%08x", got)

    async def _check_inflight_lock(self, field: str, bit_b: int, bit_c: int) -> None:
        """CHK-INFLIGHT-LOCK: a write-lock written while the program of B is busy does not
        affect that program."""
        addr_b = field_bit_addr(field, bit_b)
        addr_c = field_bit_addr(field, bit_c)
        lock = _EFUSE_MAP.field_mask("LOCKS_SPARE", f"{field.lower()}_write_lock")

        status = await self.fd.rd(STATUS_ADDR)
        locks = await self.fd.rd(_LOCKS_SPARE_ADDR)
        assert not status & _REQ_ERROR and not locks & lock, (
            f"CTRL-INFLIGHT-PRE FAIL: before the go, STATUS=0x{status:08x} "
            f"LOCKS_SPARE=0x{locks:08x}; efuse_req_error and lock 0x{lock:08x} must read 0"
        )
        self.logger.info(
            "CTRL-INFLIGHT-PRE PASS: STATUS=0x%08x LOCKS_SPARE=0x%08x before the go",
            status,
            locks,
        )

        await self._set_init_time(_INIT_TIME_INFLIGHT)
        await self.fd.wr(PROGRAM_CTRL_ADDR, program_ctrl_word(addr_b))
        pg_go = await self.fd.rd(PROGRAM_CTRL_ADDR)
        await self.fd.wr(_LOCKS_SPARE_ADDR, lock)
        pg_lock = await self.fd.rd(PROGRAM_CTRL_ADDR)
        locks = await self.fd.rd(_LOCKS_SPARE_ADDR)
        assert pg_go & _PG_BUSY and pg_lock & _PG_BUSY and locks & lock, (
            f"CTRL-INFLIGHT-WINDOW FAIL: EFUSE_PROGRAM_CTRL=0x{pg_go:08x} after the go and "
            f"0x{pg_lock:08x} after the lock write, LOCKS_SPARE=0x{locks:08x}; program_busy "
            f"must read 1 at both reads and lock 0x{lock:08x} must read back set"
        )
        self.logger.info(
            "CTRL-INFLIGHT-WINDOW PASS: program_busy=1 after the go (0x%08x) and after the "
            "lock write (0x%08x), LOCKS_SPARE=0x%08x",
            pg_go,
            pg_lock,
            locks,
        )

        pg = pg_lock
        for _ in range(_INFLIGHT_POLLS):
            pg = await self.fd.rd(PROGRAM_CTRL_ADDR)
            if pg & _PG_DONE:
                break
        else:
            raise AssertionError(
                f"CHK-INFLIGHT-LOCK FAIL: program of bit {addr_b} shows no program_done "
                f"after {_INFLIGHT_POLLS} reads (EFUSE_PROGRAM_CTRL=0x{pg:08x})"
            )
        await self.fd.wr(PROGRAM_CTRL_ADDR, 0)
        status = await self.fd.rd(STATUS_ADDR)
        await self._set_init_time(_INIT_TIME_RESET)
        self.golden.words[addr_b // 32] |= 1 << (addr_b % 32)
        word = await self._otp_word(addr_b // 32)
        want = self.golden.words[addr_b // 32]
        assert not pg & _PG_STATUS and not status & _REQ_ERROR and word == want, (
            f"CHK-INFLIGHT-LOCK FAIL: program of bit {addr_b} with its lock written in flight: "
            f"EFUSE_PROGRAM_CTRL=0x{pg:08x} (program_status 0 expected), "
            f"STATUS=0x{status:08x} (efuse_req_error 0 expected), "
            f"OTP word {addr_b // 32} = 0x{word:08x}, expected 0x{want:08x}"
        )
        self.logger.info(
            "CHK-INFLIGHT-LOCK PASS: bit %d programmed with its lock written in flight: "
            "EFUSE_PROGRAM_CTRL=0x%08x program_status=0, STATUS=0x%08x, OTP word %d = 0x%08x",
            addr_b,
            pg,
            status,
            addr_b // 32,
            word,
        )

        refused = sep_efuse_otp_program_once_seq(addr_c)
        await self.start_seq(refused)
        status = await self.fd.rd(STATUS_ADDR)
        word = await self._otp_word(addr_c // 32)
        want = self.golden.words[addr_c // 32]
        assert refused.program_err and status & _REQ_ERROR and word == want, (
            f"CTRL-INFLIGHT-LOCK-LIVE FAIL: program of bit {addr_c} after the lock: "
            f"program_status={int(bool(refused.program_err))} (1 expected), "
            f"STATUS=0x{status:08x} (efuse_req_error 1 expected), "
            f"OTP word {addr_c // 32} = 0x{word:08x}, expected 0x{want:08x}"
        )
        self.logger.info(
            "CTRL-INFLIGHT-LOCK-LIVE PASS: program of bit %d refused after the lock: "
            "EFUSE_PROGRAM_CTRL=0x%08x STATUS=0x%08x, OTP word %d = 0x%08x",
            addr_c,
            refused.status,
            status,
            addr_c // 32,
            word,
        )

    async def run_scenario(self) -> None:
        rng = SepSeededRng(self.random_seed())
        spare_a = rng.randrange(SPARE_COUNT)
        field = spare_field_name(spare_a)
        nbits = SepEfuseImage.field(field).n_words * 32
        bit_a = rng.randrange(nbits)
        addr_a = field_bit_addr(field, bit_a)
        spare_b = rng.randrange(SPARE_COUNT - 1)
        field_b = spare_field_name(spare_b + (spare_b >= spare_a))
        nbits_b = SepEfuseImage.field(field_b).n_words * 32
        bit_b = rng.randrange(nbits_b)
        bit_c = (bit_b + 1 + rng.randrange(nbits_b - 1)) % nbits_b
        self.logger.info(
            "efuse program verify: seed=%d %s bit_a=%d (OTP bit %d) %s bit_b=%d bit_c=%d",
            self.random_seed(),
            field,
            bit_a,
            addr_a,
            field_b,
            bit_b,
            bit_c,
        )

        img = self.select_efuse_image(lc_raw=LC_TEST_DEV, fixed=spare_zero_pins())
        assert img.field_int(field) == 0 and img.field_int(field_b) == 0
        assert img.field_int("LOCKS") == 0 and img.field_int("LOCKS_SPARE") == 0
        self.write_efuse_image(img)
        await self.bring_up_and_wait_fuse_sense(max_cycles=_MAX_SENSE_CYCLES)
        self.golden = SepEfuseImage()
        self.golden.words = list(img.words)
        self.fd = SepEfuseFd(self)

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

        await self._check_data_hold(want, field_bit_addr(field_b, bit_b) // 32)
        await self._check_inflight_lock(field_b, bit_b, bit_c)
