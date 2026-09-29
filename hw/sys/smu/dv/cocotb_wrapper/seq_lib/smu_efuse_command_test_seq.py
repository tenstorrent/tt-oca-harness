# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SEP and SMC eFuse read and program commands from the SEP debug system bus.

Both subsystems carry an ``efuse_interface_ctrl`` block (``hw/ip/efuse`` register
description) whose EFUSE_READ_CTRL and EFUSE_PROGRAM_CTRL start one fuse-command
each on the subsystem's fuse-command port, which leaves the SMU for the eFuse
shim of the wrapper. The SEP block is on the SEP map; the SMC block is reached
through the SEP view of the SMC window. A command addresses a fuse bit; an
address at or beyond the fuse array (the ``*_efuse_map`` size in bits) is
rejected with the sticky address error and never leaves as a command.

S0..S3 are ``smu_dtp_sep_dm_dmi_test``. Then, for the SEP and then the SMC:
S4: a read at bit address 0, and at the middle of the array with each address
    bit set in turn, completes with ``read_done`` and no ``read_status`` error.
    The middle of the array is spare space no lock field in the shadow
    preloads covers.
S5: programs of bits of the fuse word at the middle of the array, with and
    without read-back, complete without error, and a read of that word returns
    every bit programmed; a program with ``efuse_data`` 0, which the description says is
    ignored, changes nothing. ``program_enable`` is cleared before the read-back:
    while it is set the controller gives the fuse-command port to the program
    interface (``efuse_interface_controller.sv``).
S6: a read and a program one bit past the array complete with an error, set
    the sticky address errors, and the clear strobes clear them.
S7 (before S5): the bank model fails the first program after reset
    (``+*_efuse_prog_fail_count=1``); a program with read-back of a fresh bit
    reports the error and the bit reads clear.
S8 (before S6): every bit of one more word is programmed; the word reads back
    all ones and the unprogrammed word after it all zeros.
"""

from __future__ import annotations

from seq_lib.smu_addr_map import c_header_u32
from seq_lib.smu_dtp_sep_dm_dmi_test_seq import smu_dtp_sep_dm_dmi_test_seq
from seq_lib.smu_sep_sba_fabric_sweep_test_seq import (
    _REPO_ROOT,
    _SEP_ADDR_H,
    _SMC_ADDR_H,
    smu_sep_sba_fabric_sweep_test_seq,
)

_EFUSE_C = _REPO_ROOT / "hw" / "ip" / "efuse" / "regs" / "gen" / "c"
_EFUSE_H = _EFUSE_C / "efuse_interface_ctrl.h"
_EFUSE_ADDR_H = _EFUSE_C / "efuse_interface_ctrl_addr.h"


def _f(name: str) -> int:
    return c_header_u32(_EFUSE_H, f"EFUSE_INTERFACE_CTRL__{name}")


def _off(name: str) -> int:
    return c_header_u32(_EFUSE_ADDR_H, f"EFUSE_INTERFACE_CTRL_{name}_BASE_ADDR")


STATUS = _off("EFUSE_INTERFACE_CTRL_STATUS")
PROGRAM_CTRL = _off("EFUSE_PROGRAM_CTRL")
READ_CTRL = _off("EFUSE_READ_CTRL")
READ_DATA = _off("EFUSE_READ_INTERFACE_READ_DATA")

READ_ENABLE = _f("EFUSE_READ_CTRL__READ_ENABLE_bm")
READ_GO = _f("EFUSE_READ_CTRL__EFUSE_READ_GO_bm")
READ_DONE = _f("EFUSE_READ_CTRL__READ_DONE_bm")
READ_ERROR = _f("EFUSE_READ_CTRL__READ_STATUS_bm")
PROGRAM_ENABLE = _f("EFUSE_PROGRAM_CTRL__PROGRAM_ENABLE_bm")
PROGRAM_GO = _f("EFUSE_PROGRAM_CTRL__EFUSE_PROGRAM_GO_bm")
PROGRAM_READ_BACK = _f("EFUSE_PROGRAM_CTRL__EFUSE_PROGRAM_READ_BACK_bm")
PROGRAM_DATA = _f("EFUSE_PROGRAM_CTRL__EFUSE_DATA_bm")
PROGRAM_DONE = _f("EFUSE_PROGRAM_CTRL__PROGRAM_DONE_bm")
PROGRAM_ERROR = _f("EFUSE_PROGRAM_CTRL__PROGRAM_STATUS_bm")
READ_ADDR_ERROR = _f("EFUSE_INTERFACE_CTRL_STATUS__EFUSE_READ_ADDR_ERROR_bm")
PROGRAM_ADDR_ERROR = _f("EFUSE_INTERFACE_CTRL_STATUS__EFUSE_PROGRAM_ADDR_ERROR_bm")
READ_ADDR_ERROR_CLEAR = _f("EFUSE_INTERFACE_CTRL_STATUS__EFUSE_READ_ADDR_ERROR_CLEAR_bm")
PROGRAM_ADDR_ERROR_CLEAR = _f("EFUSE_INTERFACE_CTRL_STATUS__EFUSE_PROGRAM_ADDR_ERROR_CLEAR_bm")

SEP_EFUSE_CTRL = c_header_u32(_SEP_ADDR_H, "SEP_TOP_EFUSE_INTERFACE_CTRL_BASE_ADDR")
SEP_FUSE_BITS = 8 * c_header_u32(_SEP_ADDR_H, "SEP_TOP_SEP_EFUSE_MAP_SIZE")
SMC_EFUSE_CTRL = c_header_u32(_SMC_ADDR_H, "SMC_TOP_EFUSE_INTERFACE_CTRL_BASE_ADDR")
SMC_FUSE_BITS = 8 * c_header_u32(_SMC_ADDR_H, "SMC_TOP_SMC_EFUSE_MAP_SIZE")

PROGRAM_BITS = (0, 7, 18, 31)
WORD_BITS = 32
COMMAND_POLLS = 64


class smu_efuse_command_test_seq(smu_sep_sba_fabric_sweep_test_seq):
    """eFuse read and program commands on both fuse-command ports."""

    def __init__(self, test) -> None:
        super().__init__(test)
        self.steps = {"sep": False, "smc": False}

    async def _rd(self, jtag, addr: int) -> int:
        err, value = await self._sb(jtag, addr, 2)
        if err:
            raise AssertionError(f"eFuse CSR read 0x{addr:08x}: sberror={err}")
        return value

    async def _command(self, jtag, ctrl: int, reg: int, value: int, done: int) -> int:
        await self._sb_ok(jtag, ctrl + reg, 2, value)
        status = 0
        for _ in range(COMMAND_POLLS):
            status = await self._rd(jtag, ctrl + reg)
            if status & done:
                return status
        raise AssertionError(
            f"eFuse command 0x{value:08x} at 0x{ctrl + reg:08x} never finished: "
            f"ctrl=0x{status:08x} status=0x{await self._rd(jtag, ctrl + STATUS):08x}"
        )

    async def _read(self, jtag, ctrl: int, bit: int) -> tuple[int, int]:
        status = await self._command(jtag, ctrl, READ_CTRL, READ_ENABLE | READ_GO | bit, READ_DONE)
        return int(bool(status & READ_ERROR)), await self._rd(jtag, ctrl + READ_DATA)

    async def _program(self, jtag, ctrl: int, bit: int, *, data: int = 1, read_back: bool = False):
        value = PROGRAM_ENABLE | PROGRAM_GO | bit | (PROGRAM_DATA if data else 0)
        if read_back:
            value |= PROGRAM_READ_BACK
        status = await self._command(jtag, ctrl, PROGRAM_CTRL, value, PROGRAM_DONE)
        return int(bool(status & PROGRAM_ERROR))

    async def _side(self, jtag, sb, name: str, ctrl: int, fuse_bits: int) -> None:
        # Every address bit set in turn inside the unlocked spare area at the
        # middle of the array; the reads at 0 and there clear and set bit 12.
        word = fuse_bits // 2
        walk = [0] + [word | (1 << k) for k in range((fuse_bits - 1).bit_length())]
        reads = {bit: (await self._read(jtag, ctrl, bit))[0] for bit in walk}
        self._log(f"CHK-EFUSE-CMD-READ {name} {reads}")
        sb.expect_eq(
            f"CHK-EFUSE-CMD-READ {name}",
            reads,
            {bit: 0 for bit in walk},
            evidence="CHK-EFUSE-CMD-READ",
        )

        # The bank model fails the first program after reset (the testlist's
        # +*_efuse_prog_fail_count=1): the bit stays clear, so only a program
        # with read-back reports it (efuse_bank_model.sv, efuse_interface_shim.sv).
        failed_bit = word + WORD_BITS + 1
        fail_err = await self._program(jtag, ctrl, failed_bit, read_back=True)
        await self._sb_ok(jtag, ctrl + PROGRAM_CTRL, 2, 0)
        _, failed_word = await self._read(jtag, ctrl, failed_bit - 1)
        self._log(f"CHK-EFUSE-CMD-PROGRAM-FAIL {name} error={fail_err} word=0x{failed_word:08x}")
        sb.expect_eq(
            f"CHK-EFUSE-CMD-PROGRAM-FAIL {name}",
            (fail_err, failed_word),
            (1, 0),
            evidence="CHK-EFUSE-CMD-PROGRAM-FAIL",
        )

        _, before = await self._read(jtag, ctrl, word)
        programs = {
            bit: await self._program(jtag, ctrl, word + bit, read_back=bool(i & 1))
            for i, bit in enumerate(PROGRAM_BITS)
        }
        zero = await self._program(jtag, ctrl, word + 1, data=0)
        # A set program enable holds the fuse-command port for the program
        # interface, so it is cleared before the read-back.
        await self._sb_ok(jtag, ctrl + PROGRAM_CTRL, 2, 0)
        err, after = await self._read(jtag, ctrl, word)
        mask = sum(1 << bit for bit in PROGRAM_BITS)
        self._log(
            f"CHK-EFUSE-CMD-PROGRAM {name} before=0x{before:08x} programs={programs} "
            f"zero={zero} after=0x{after:08x}"
        )
        sb.expect_eq(
            f"CHK-EFUSE-CMD-PROGRAM {name}",
            (programs, err, after),
            ({bit: 0 for bit in PROGRAM_BITS}, 0, before | mask),
            evidence="CHK-EFUSE-CMD-PROGRAM",
        )

        # Every bit of one more word, so the read data carries each bit set
        # and, on the next read of an unprogrammed word, clear.
        ones = word + 2 * WORD_BITS
        ones_errs = [await self._program(jtag, ctrl, ones + bit) for bit in range(WORD_BITS)]
        await self._sb_ok(jtag, ctrl + PROGRAM_CTRL, 2, 0)
        _, ones_word = await self._read(jtag, ctrl, ones)
        _, zero_word = await self._read(jtag, ctrl, ones + WORD_BITS)
        self._log(
            f"CHK-EFUSE-CMD-WORD {name} errors={sum(ones_errs)} word=0x{ones_word:08x} "
            f"next=0x{zero_word:08x}"
        )
        sb.expect_eq(
            f"CHK-EFUSE-CMD-WORD {name}",
            (sum(ones_errs), ones_word, zero_word),
            (0, (1 << WORD_BITS) - 1, 0),
            evidence="CHK-EFUSE-CMD-WORD",
        )

        read_err, _ = await self._read(jtag, ctrl, fuse_bits)
        program_err = await self._program(jtag, ctrl, fuse_bits)
        await self._sb_ok(jtag, ctrl + PROGRAM_CTRL, 2, 0)
        sticky = await self._rd(jtag, ctrl + STATUS) & (READ_ADDR_ERROR | PROGRAM_ADDR_ERROR)
        await self._sb_ok(jtag, ctrl + STATUS, 2, READ_ADDR_ERROR_CLEAR | PROGRAM_ADDR_ERROR_CLEAR)
        cleared = await self._rd(jtag, ctrl + STATUS) & (READ_ADDR_ERROR | PROGRAM_ADDR_ERROR)
        self._log(
            f"CHK-EFUSE-CMD-OOB {name} read={read_err} program={program_err} "
            f"sticky=0x{sticky:x} cleared=0x{cleared:x}"
        )
        sb.expect_eq(
            f"CHK-EFUSE-CMD-OOB {name}",
            (read_err, program_err, sticky, cleared),
            (1, 1, READ_ADDR_ERROR | PROGRAM_ADDR_ERROR, 0),
            evidence="CHK-EFUSE-CMD-OOB",
        )
        self.steps[name] = True

    async def run(self) -> None:
        await smu_dtp_sep_dm_dmi_test_seq.run(self)
        sb = self.test.env.scoreboard
        jtag = self.jtag
        self.smc_base = int(self.dut.smc_global_base_o.value)
        await self._side(jtag, sb, "sep", SEP_EFUSE_CTRL, SEP_FUSE_BITS)
        await self._side(jtag, sb, "smc", self._smc_view(SMC_EFUSE_CTRL), SMC_FUSE_BITS)
