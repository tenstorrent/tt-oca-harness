# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The reference SHIM verifies every eFuse program and returns the read-back word.

no_cpu, real fuse sense, ``+sep_efuse_prog_fail_count=1``. RANDCFG: the seed
selects one spare field and bit A in it, then the READ word of the hold check,
then a second spare field and two distinct bits X and Y in it.

Contract. ``hw/ip/efuse/doc/architecture.adoc`` (Interface SHIM): the reference
SHIM always reads back the programmed word after the write, returns it in
``data``, and sets ``status`` when the bit did not stick. ``program_status`` is 0
for no error and 1 for an error, and ``EFUSE_PROGRAM_INTERFACE_READ_DATA`` holds the
data of the last successful program response (``efuse_interface_ctrl.rdl``). The
OTP bank model drops the first N program writes with no APB error, as real OTP
does (``hw/ip/efuse/dv/models/README.md``), so a dropped write is visible only to
the verify step. A program ends when ``program_busy`` clears and ``program_done``
is set (``doc/programmer/src/smc-programming.adoc``, program steps). The guard
checks the target of a program when it is started; a lock set after a command has
been issued does not affect that command, and a locked target completes with an
error and sets ``efuse_req_error`` without a fuse command
(``hw/ip/efuse/doc/architecture.adoc``, eFuse guard).

Hooks and taps: ``efuse_shim_resp_hold_i`` withholds the shim response of a PROGRAM
command while it is high; ``efuse_bank_prog_drop_o`` and
``efuse_bank_prog_drop_paddr_o`` show each write the bank model drops and its
``paddr``; ``efuse_shim_cmd_*_o`` show each command after the guard.

The first bank write after reset is dropped:

  CHK-VERIFY-DETECT   program bit A, write dropped: program_done 1 with
                      program_busy 0 and program_status 1 in the same
                      EFUSE_PROGRAM_CTRL read, and the OTP word still holds bit A
                      clear.
  CHK-VERIFY-PROGRAM  control: program bit A again, write kept: program_done 1,
                      program_busy 0, program_status 0, and the OTP word gains bit A.
  CTRL-VERIFY-DROP    from the end of bring-up to the end of the second program,
                      the drop tap is high on exactly one clock, inside the first
                      program, with ``paddr >> 2`` equal to the OTP word of bit A.
  CHK-VERIFY-DATA     after the kept program, EFUSE_PROGRAM_INTERFACE_READ_DATA
                      equals the OTP word golden with bit A set.
  CHK-VERIFY-DATA-HOLD  after one READ command of a non-secret data word whose
                      golden has a bit set that is clear in the held word, the READ
                      returns its golden and EFUSE_PROGRAM_INTERFACE_READ_DATA still
                      equals the word of the kept program
                      (``hw/ip/efuse/regs/efuse_interface_ctrl.rdl:156``: held until the
                      next successful program). A register that loads, ORs in, or
                      loads only a non-zero READ result fails.

A lock set while a program is in flight (last step, after the dropped write is spent):

  CTRL-VERIFY-INFLIGHT-HELD  with the response held, the command tap shows one
                      PROGRAM command at bit X, ``program_busy`` reads 1 before the
                      ``LOCKS_SPARE`` write and again after its readback, and the
                      readback equals the write-lock bit of X's spare field.
  CHK-VERIFY-INFLIGHT-LOCK  after the hold drops: program_done 1, program_busy 0,
                      program_status 0, ``efuse_req_error`` 0 (it read 0 before the
                      go), and the OTP word of X equals its golden with bit X set.
  CTRL-VERIFY-INFLIGHT-LOCK  the lock took effect: a program of bit Y in the same
                      field ends with program_done 1 and program_status 1,
                      ``efuse_req_error`` goes from 0 to 1, the command tap shows no
                      fuse command after the go, and the OTP word of Y is unchanged.

Each OTP word is read through ``EFUSE_READ_CTRL`` and compared whole against an
image golden, so a write that lands on the wrong bit also fails. A SHIM that does
not verify fails CHK-VERIFY-DETECT; the control shows the same bit programs when
the write is kept, and CTRL-VERIFY-DROP shows the bank model dropped that one
write, so the clear bit in the first row is the dropped write and not a broken
path or an APB error. The image holds the field at 0, so a read-data value of 0
or of the pre-program word fails CHK-VERIFY-DATA.
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles, ReadOnly, RisingEdge
from env.sep_axi_agent import SepAxiOp
from env.sep_efuse_bank_watch import SepShimCmdMonitor
from env.sep_efuse_image import SepEfuseImage
from env.sep_efuse_plan import PROGRAM_CTRL_ADDR, STATUS_ADDR, program_ctrl_word, shadow_addr
from env.sep_efuse_test_lib import SepEfuseFd
from env.sep_lcc_golden import LC_TEST_DEV
from env.sep_locked_field_irq import SPARE_COUNT, spare_zero_pins
from env.sep_seeded_rng import SepSeededRng
from sep_base_test import sep_base_test
from sep_reg_meta import EFUSE_INTERFACE_CTRL, RegBlock
from seq_lib.sep_efuse_direct_read_seq import sep_efuse_direct_read_seq
from seq_lib.sep_efuse_otp_program_seq import sep_efuse_otp_program_once_seq
from seq_lib.sep_efuse_program_lock_seq import field_bit_addr, spare_field_name

_MAX_SENSE_CYCLES = 20_000
_PROGRAM_READ_DATA = EFUSE_INTERFACE_CTRL.addr("EFUSE_PROGRAM_INTERFACE_READ_DATA")
_IC = EFUSE_INTERFACE_CTRL
_M_PG_BUSY = _IC.field_mask("EFUSE_PROGRAM_CTRL", "program_busy")
_M_PG_DONE = _IC.field_mask("EFUSE_PROGRAM_CTRL", "program_done")
_M_PG_STATUS = _IC.field_mask("EFUSE_PROGRAM_CTRL", "program_status")
_M_REQ_ERR = _IC.field_mask("EFUSE_INTERFACE_CTRL_STATUS", "efuse_req_error")
_M_REQ_ERR_CLEAR = _IC.field_mask("EFUSE_INTERFACE_CTRL_STATUS", "efuse_req_error_clear")
_EFUSE_MAP = RegBlock("SEP_EFUSE_MAP")
# Frontdoor reads of a program_busy or program_done poll, one clock apart; the
# same limit as sep_efuse_otp_program_once_seq.
_POLL_READS = 200


def _b(v: int, m: int) -> int:
    return int(bool(v & m))


def _hold_read_words(golden: SepEfuseImage, held: int) -> list[int]:
    """Non-secret data words whose golden has a bit set that is clear in ``held``."""
    secret = golden.secret_words()
    return [
        w
        for fld in golden.fields
        if fld.kind == "data"
        for w in range(fld.word, fld.word + fld.n_words)
        if w not in secret and golden.words[w] & ~held
    ]


@pyuvm.test()
class sep_efuse_program_verify_test(sep_base_test):
    """The SHIM verify step reports a dropped program write and returns the word."""

    required_evidence = (
        "CHK-VERIFY-DETECT",
        "CHK-VERIFY-PROGRAM",
        "CHK-VERIFY-DATA",
        "CHK-VERIFY-DATA-HOLD",
        "CHK-VERIFY-INFLIGHT-LOCK",
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
        busy, done = _b(seq.status, _M_PG_BUSY), _b(seq.status, _M_PG_DONE)
        if busy != 0 or done != 1:
            faults.append(
                f"program_busy={busy} program_done={done} (EFUSE_PROGRAM_CTRL=0x{seq.status:08x}), "
                "expected busy 0 and done 1"
            )
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
            "%s PASS: bit %d write %s -> EFUSE_PROGRAM_CTRL=0x%08x program_busy=%d "
            "program_done=%d program_status=%d, OTP word %d = 0x%08x (bit %s)",
            chk,
            bit_addr,
            "kept" if lands else "dropped",
            seq.status,
            busy,
            done,
            int(seq.program_err),
            bit_addr // 32,
            word,
            "set" if (word >> (bit_addr % 32)) & 1 else "clear",
        )
        return seq

    async def _check_data_hold(self, held: int, read_word: int) -> None:
        """CHK-VERIFY-DATA-HOLD: one READ command leaves the program read data unchanged."""
        golden = self.golden.words[read_word]
        got_read = await self._otp_word(read_word)
        got = await self.fd.rd(_PROGRAM_READ_DATA)
        assert got_read == golden and got == held, (
            f"CHK-VERIFY-DATA-HOLD FAIL: after a READ of OTP word {read_word} "
            f"(read 0x{got_read:08x}, golden 0x{golden:08x}), "
            f"EFUSE_PROGRAM_INTERFACE_READ_DATA = 0x{got:08x}, expected the held 0x{held:08x}"
        )
        self.logger.info(
            "CHK-VERIFY-DATA-HOLD PASS: after a READ of OTP word %d = 0x%08x (golden 0x%08x, "
            "bits 0x%08x clear in the held word), EFUSE_PROGRAM_INTERFACE_READ_DATA = 0x%08x "
            "(held 0x%08x)",
            read_word,
            got_read,
            golden,
            golden & ~held,
            got,
            held,
        )

    async def _drop_mon(self) -> None:
        """Counts clocks and records (clock, paddr) of every clock with the drop tap high."""
        dut = cocotb.top
        while True:
            await RisingEdge(dut.clk_i)
            await ReadOnly()
            self.clk += 1
            if self.rd(dut.efuse_bank_prog_drop_o):
                self.drops.append((self.clk, self.rd(dut.efuse_bank_prog_drop_paddr_o)))

    def _check_drop(self, addr_a: int, p1: tuple[int, int], end: int) -> None:
        """CTRL-VERIFY-DROP: one drop, inside program 1, at the OTP word of ``addr_a``."""
        seen = [(c, a) for c, a in self.drops if c <= end]
        in_p1 = [(c, a) for c, a in seen if p1[0] <= c <= p1[1]]
        words = [a >> 2 for _, a in seen]
        ok = len(seen) == 1 and len(in_p1) == 1 and words == [addr_a // 32]
        fields = (
            f"drops={len(seen)} drops_p1={len(in_p1)} drops_outside_p1={len(seen) - len(in_p1)} "
            f"words={words} exp_word={addr_a // 32} drop_clks={[c for c, _ in seen]} "
            f"p1_clks={p1[0]}..{p1[1]} end_clk={end}"
        )
        assert ok, f"CTRL-VERIFY-DROP FAIL: {fields}"
        self.logger.info("CTRL-VERIFY-DROP PASS: %s", fields)

    async def _poll_pg(self, mask: int) -> int | None:
        """Read ``EFUSE_PROGRAM_CTRL`` until every bit of ``mask`` is 1; None at the bound."""
        for _ in range(_POLL_READS):
            v = await self.fd.rd(PROGRAM_CTRL_ADDR)
            if v & mask == mask:
                return v
            await ClockCycles(cocotb.top.clk_i, 1)
        return None

    async def _req_err(self) -> int:
        return _b(await self.fd.rd(STATUS_ADDR), _M_REQ_ERR)

    async def _clear_req_err(self) -> int:
        """Write-one clear of ``efuse_req_error``; returns the flag read back after it."""
        await self.fd.wr(STATUS_ADDR, _M_REQ_ERR_CLEAR)
        return await self._req_err()

    async def _inflight_lock(self, spare_x: int, x: int, y: int) -> None:
        """A write-lock set while the program of ``x`` is held; then a program of ``y``."""
        dut = cocotb.top
        lock_addr = shadow_addr("LOCKS_SPARE")
        lock_mask = _EFUSE_MAP.field_mask("LOCKS_SPARE", f"spare{spare_x}_write_lock")
        word_x, word_y = x // 32, y // 32
        cmds = SepShimCmdMonitor(dut).start()

        pre_err = await self._clear_req_err()
        m_x = cmds.mark()
        dut.efuse_shim_resp_hold_i.value = 1
        await self.fd.wr(PROGRAM_CTRL_ADDR, program_ctrl_word(x))
        busy_pre = await self._poll_pg(_M_PG_BUSY)
        lock_seq = await self.fd.access(SepAxiOp.WRITE, lock_addr, lock_mask, unverified_write=True)
        lock_rb = await self.fd.rd(lock_addr)
        busy_post = await self.fd.rd(PROGRAM_CTRL_ADDR)
        held_cmds = len(cmds.programs_since(m_x, address=x))
        held = (
            f"bit_x={x} spare_x={spare_x} held_prog_cmds={held_cmds} "
            f"busy_pre={'none' if busy_pre is None else _b(busy_pre, _M_PG_BUSY)} "
            f"busy_post={_b(busy_post, _M_PG_BUSY)} done_post={_b(busy_post, _M_PG_DONE)} "
            f"lock_resp={'OKAY' if lock_seq.resp_ok else lock_seq.resp_code} "
            f"locks_spare=0x{lock_rb:08x} exp=0x{lock_mask:08x}"
        )
        held_ok = (
            pre_err == 0
            and busy_pre is not None
            and held_cmds == 1
            and _b(busy_post, _M_PG_BUSY) == 1
            and _b(busy_post, _M_PG_DONE) == 0
            and lock_rb == lock_mask
        )
        dut.efuse_shim_resp_hold_i.value = 0
        assert held_ok, f"CTRL-VERIFY-INFLIGHT-HELD FAIL: pre_req_err={pre_err} {held}"
        self.logger.info("CTRL-VERIFY-INFLIGHT-HELD PASS: pre_req_err=%d %s", pre_err, held)

        pg = await self._poll_pg(_M_PG_DONE)
        err_x = await self._req_err()
        await self.fd.wr(PROGRAM_CTRL_ADDR, 0)
        self.golden.words[word_x] |= 1 << (x % 32)
        got_x = await self._otp_word(word_x)
        want_x = self.golden.words[word_x]
        line = (
            f"bit_x={x} pg={'none' if pg is None else f'0x{pg:08x}'} "
            f"program_done={'none' if pg is None else _b(pg, _M_PG_DONE)} "
            f"program_busy={'none' if pg is None else _b(pg, _M_PG_BUSY)} "
            f"program_status={'none' if pg is None else _b(pg, _M_PG_STATUS)} "
            f"pre_req_err={pre_err} req_err={err_x} otp_word={word_x} "
            f"got=0x{got_x:08x} exp=0x{want_x:08x}"
        )
        ok = (
            pg is not None
            and _b(pg, _M_PG_BUSY) == 0
            and _b(pg, _M_PG_STATUS) == 0
            and err_x == 0
            and got_x == want_x
        )
        assert ok, f"CHK-VERIFY-INFLIGHT-LOCK FAIL: {line}"
        self.logger.info("CHK-VERIFY-INFLIGHT-LOCK PASS: %s", line)

        want_y = self.golden.words[word_y]
        pre_y = await self._req_err()
        m_y = cmds.mark()
        await self.fd.wr(PROGRAM_CTRL_ADDR, program_ctrl_word(y))
        pg_y = await self._poll_pg(_M_PG_DONE)
        err_y = await self._req_err()
        await self.fd.wr(PROGRAM_CTRL_ADDR, 0)
        y_cmds = len(cmds.commands_since(m_y))
        await cmds.stop()
        clr_y = await self._clear_req_err()
        got_y = await self._otp_word(word_y)
        line = (
            f"bit_y={y} pg={'none' if pg_y is None else f'0x{pg_y:08x}'} "
            f"program_done={'none' if pg_y is None else _b(pg_y, _M_PG_DONE)} "
            f"program_status={'none' if pg_y is None else _b(pg_y, _M_PG_STATUS)} "
            f"req_err={pre_y}->{err_y} clr_req_err={clr_y} cmds={y_cmds} "
            f"otp_word={word_y} got=0x{got_y:08x} exp=0x{want_y:08x}"
        )
        ok = (
            pg_y is not None
            and _b(pg_y, _M_PG_STATUS) == 1
            and pre_y == 0
            and err_y == 1
            and y_cmds == 0
            and got_y == want_y
        )
        assert ok, f"CTRL-VERIFY-INFLIGHT-LOCK FAIL: {line}"
        self.logger.info("CTRL-VERIFY-INFLIGHT-LOCK PASS: %s", line)

    async def run_scenario(self) -> None:
        rng = SepSeededRng(self.random_seed())
        spare_a = rng.randrange(SPARE_COUNT)
        field = spare_field_name(spare_a)
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
        self.fd = SepEfuseFd(self)
        self.clk = 0
        self.drops: list[tuple[int, int]] = []
        cocotb.start_soon(self._drop_mon())

        # The bank model drops the first write (+sep_efuse_prog_fail_count=1).
        p1_start = self.clk
        await self._program("CHK-VERIFY-DETECT", addr_a, expect_err=True, lands=False)
        p1_end = self.clk
        kept = await self._program("CHK-VERIFY-PROGRAM", addr_a, expect_err=False, lands=True)
        await ClockCycles(cocotb.top.clk_i, 1)
        self._check_drop(addr_a, (p1_start, p1_end), self.clk)

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

        pool = _hold_read_words(self.golden, want)
        assert pool, (
            "CHK-VERIFY-DATA-HOLD FAIL: no non-secret data word in the image has a golden "
            f"bit set that is clear in the held 0x{want:08x}"
        )
        await self._check_data_hold(want, pool[rng.randrange(len(pool))])

        others = [k for k in range(SPARE_COUNT) if k != spare_a]
        spare_x = others[rng.randrange(len(others))]
        field_x = spare_field_name(spare_x)
        nbits_x = SepEfuseImage.field(field_x).n_words * 32
        bit_x = rng.randrange(nbits_x)
        bit_y = rng.randrange(nbits_x - 1)
        bit_y += int(bit_y >= bit_x)
        x, y = field_bit_addr(field_x, bit_x), field_bit_addr(field_x, bit_y)
        self.logger.info(
            "efuse program verify in-flight lock: seed=%d %s bit_x=%d (OTP bit %d) "
            "bit_y=%d (OTP bit %d)",
            self.random_seed(),
            field_x,
            bit_x,
            x,
            bit_y,
            y,
        )
        await self._inflight_lock(spare_x, x, y)
