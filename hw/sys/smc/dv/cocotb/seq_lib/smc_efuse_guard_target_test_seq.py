# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The eFuse guard judging a read and a program by the field they target.

`efuse_guard.sv` sits between the eFuse read and program interfaces and the
bank, and looks up the field a request targets to apply that field's
hardware locks: `hw/ip/efuse/doc/architecture.adoc` gives every shadow field a
read lock and a write lock in `LOCKS`, and a locked access is answered rather
than executed. `smc_efuse_lock_guard_test` drives the locks on the shadow
register path; every leaf that uses the read or program interface targets bit
0, which lies in `LOCKS` itself, a field hardware never applies locks to. So
the guard had never looked a target up and found a field.

This leaf targets SPARE fields, whose locks the default image leaves clear
(the sequence checks), and sets their locks through the `LOCKS` CSR, which is
write-1-to-set:

* **An unlocked read.** The default image leaves every SPARE word at zero, so a
  read of one cannot tell a disclosed word from a withheld one. One bit of
  SPARE[6] is therefore first set by an unlocked read-back program, and a read
  of the word through the read interface must then complete without error and
  return the asset word with that bit set.
* **A read-locked read.** With SPARE[6]'s read lock set, the same read must
  complete with `READ_STATUS` set and `EFUSE_REQ_ERROR` raised, and must not
  return the word.
* **A write-locked program.** With SPARE[7]'s write lock set, a program with
  read-back of a bit the asset holds at 0 must complete with `PROGRAM_STATUS`
  set and `EFUSE_REQ_ERROR` raised. The command never reaches the bank: a
  read of the word afterwards must still return the asset's value. The
  program is a read-back program, the kind the regression's policy admits.

Locks set through `LOCKS` hold until reset, so SPARE[6] and SPARE[7] are left
locked; no other leaf in the run uses them.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import RisingEdge
from env.smc_sys_axi_agent import SmcSysAxiItem, SmcSysAxiOp

from .smc_addr_map import efuse_ifc_u32, smc_addr, smc_efuse_map_u32, smc_indexed_addr
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_efuse_read_program_timeout_test_seq import (
    PROG_DATA,
    PROG_DONE,
    PROG_EN,
    PROG_ERR,
    PROG_GO,
    PROG_RB,
    PROGRAM_CTRL,
    READ_CTRL,
    READ_DATA,
    READ_DONE,
    READ_EN,
    READ_ERR,
    READ_GO,
    REQ_ERR,
    REQ_ERR_CLR,
    STATUS,
)
from .smc_efuse_vip_utils import EFUSE_MAP_BASE, efuse_preload_word_at

LOCKS = smc_addr("SMC_TOP_SMC_EFUSE_MAP_LOCKS_BASE_ADDR")
READ_FIELD = 6
PROGRAM_FIELD = 7
READ_WORD_ADDR = smc_indexed_addr("SMC_TOP_SMC_EFUSE_MAP_SPARE_BASE_ADDR", READ_FIELD)
PROGRAM_WORD_ADDR = smc_indexed_addr("SMC_TOP_SMC_EFUSE_MAP_SPARE_BASE_ADDR", PROGRAM_FIELD)
READ_LOCK = smc_efuse_map_u32(f"SMC_EFUSE_MAP__LOCKS__SPARE{READ_FIELD}_READ_LOCK_bm")
WRITE_LOCK = smc_efuse_map_u32(f"SMC_EFUSE_MAP__LOCKS__SPARE{PROGRAM_FIELD}_WRITE_LOCK_bm")
ADDR_BM = efuse_ifc_u32("EFUSE_INTERFACE_CTRL__EFUSE_READ_CTRL__EFUSE_ADDR_bm")
_LOCKS_BYTES = 8
_POLL = 10_000


def _bit_addr(map_addr: int, bit: int = 0) -> int:
    """The eFuse bit address of `bit` in the word at SMC_EFUSE_MAP address `map_addr`."""
    return ((map_addr - EFUSE_MAP_BASE) * 8 + bit) & ADDR_BM


class smc_efuse_guard_target_test_seq(SmcCsrSeq):
    """Read and program SPARE fields through the interfaces, unlocked and locked."""

    async def _wait(self, addr: int, mask: int, label: str) -> int:
        value = 0
        for _ in range(_POLL):
            value = await self.csr_read(label, addr)
            if value & mask:
                return value
            await RisingEdge(cocotb.top.clk_smc_i)
        raise AssertionError(f"{label}: 0x{mask:x} never set (0x{value:08x})")

    async def _read(self, label: str, bit_addr: int) -> tuple[int, int]:
        await self.csr_write(f"{label}_GO", READ_CTRL, bit_addr | READ_GO | READ_EN)
        ctrl = await self._wait(READ_CTRL, READ_DONE, f"{label}_DONE")
        data = await self.csr_read(f"{label}_DATA", READ_DATA)
        await self.csr_write(f"{label}_IDLE", READ_CTRL, bit_addr)
        return ctrl, data

    async def _clear_req_err(self, label: str) -> None:
        await self.csr_write(f"{label}_ERR_CLR", STATUS, REQ_ERR_CLR)
        await self.csr_write(f"{label}_ERR_CLR0", STATUS, 0)
        status = await self.csr_read(f"{label}_ERR_CLEARED", STATUS)
        assert not status & REQ_ERR, f"{label}: EFUSE_REQ_ERROR did not clear (0x{status:08x})"

    async def _set_lock(self, label: str, bit: int) -> None:
        item = SmcSysAxiItem(f"wr_{label}")
        item.op = SmcSysAxiOp.WRITE
        item.addr = LOCKS
        item.length = _LOCKS_BYTES
        item.wdata = bit
        await self.start_item(item)
        await self.finish_item(item)
        self.accesses += 1
        got = await self.csr_read(f"{label}_RB", LOCKS)
        assert got & bit, f"{label}: LOCKS reads 0x{got:08x} without bit 0x{bit:x}"

    async def body(self) -> None:
        await self.wait_fuse_sense_done()
        locks = await self.csr_read("LOCKS_ENTRY", LOCKS)
        assert not locks & (READ_LOCK | WRITE_LOCK), (
            f"LOCKS=0x{locks:08x}: a lock this leaf sets is already set"
        )
        await self._clear_req_err("ENTRY")

        read_bit = _bit_addr(READ_WORD_ADDR)
        asset_word = efuse_preload_word_at(READ_WORD_ADDR)
        free = [b for b in range(32) if not (asset_word >> b) & 1]
        assert free, f"SPARE[{READ_FIELD}] word 0 is all ones in the asset"
        await self.csr_write(
            "MARK_GO",
            PROGRAM_CTRL,
            _bit_addr(READ_WORD_ADDR, free[0]) | PROG_DATA | PROG_GO | PROG_RB | PROG_EN,
        )
        ctrl = await self._wait(PROGRAM_CTRL, PROG_DONE, "MARK_DONE")
        await self.csr_write("MARK_IDLE", PROGRAM_CTRL, 0)
        assert not ctrl & PROG_ERR, (
            f"an unlocked read-back program of SPARE[{READ_FIELD}] bit {free[0]} failed "
            f"(PROGRAM_CTRL=0x{ctrl:08x})"
        )
        read_word = asset_word | (1 << free[0])
        ctrl, data = await self._read("OPEN", read_bit)
        status = await self.csr_read("OPEN_STATUS", STATUS)
        assert not ctrl & READ_ERR and not status & REQ_ERR and data == read_word, (
            f"unlocked read of SPARE[{READ_FIELD}]: READ_CTRL=0x{ctrl:08x} STATUS=0x"
            f"{status:08x} data=0x{data:08x}; the asset word with the bit just programmed is "
            f"0x{read_word:08x}"
        )

        await self._set_lock("READ_LOCK", READ_LOCK)
        ctrl, data = await self._read("LOCKED", read_bit)
        status = await self.csr_read("LOCKED_STATUS", STATUS)
        assert ctrl & READ_ERR and status & REQ_ERR, (
            f"read-locked read of SPARE[{READ_FIELD}]: READ_CTRL=0x{ctrl:08x} "
            f"STATUS=0x{status:08x}; READ_STATUS and EFUSE_REQ_ERROR must both set"
        )
        assert data != read_word, (
            f"read-locked read of SPARE[{READ_FIELD}] returned the word 0x{data:08x}"
        )
        await self._clear_req_err("LOCKED")
        cocotb.log.info(
            "CHK-EFUSE-GUARD-READ-TARGET: after an unlocked read-back program of one bit, a "
            "read of SPARE[%d] through the read interface returned 0x%08x with no error; with "
            "its read lock set the same read set READ_STATUS and EFUSE_REQ_ERROR and returned "
            "0x%08x instead",
            READ_FIELD,
            read_word,
            data,
        )

        program_word = efuse_preload_word_at(PROGRAM_WORD_ADDR)
        zero_bits = [b for b in range(32) if not (program_word >> b) & 1]
        assert zero_bits, f"SPARE[{PROGRAM_FIELD}] word 0 is all ones in the asset"
        program_bit = _bit_addr(PROGRAM_WORD_ADDR, zero_bits[0])
        await self._set_lock("WRITE_LOCK", WRITE_LOCK)
        await self.csr_write(
            "PROGRAM_GO", PROGRAM_CTRL, program_bit | PROG_DATA | PROG_GO | PROG_RB | PROG_EN
        )
        ctrl = await self._wait(PROGRAM_CTRL, PROG_DONE, "PROGRAM_DONE")
        status = await self.csr_read("PROGRAM_STATUS", STATUS)
        await self.csr_write("PROGRAM_IDLE", PROGRAM_CTRL, program_bit)
        assert ctrl & PROG_ERR and status & REQ_ERR, (
            f"write-locked program of SPARE[{PROGRAM_FIELD}]: PROGRAM_CTRL=0x{ctrl:08x} "
            f"STATUS=0x{status:08x}; PROGRAM_STATUS and EFUSE_REQ_ERROR must both set"
        )
        await self._clear_req_err("PROGRAM")
        ctrl, data = await self._read("AFTER", _bit_addr(PROGRAM_WORD_ADDR))
        assert not ctrl & READ_ERR and data == program_word, (
            f"after the refused program SPARE[{PROGRAM_FIELD}] reads 0x{data:08x} "
            f"(READ_CTRL=0x{ctrl:08x}); the asset holds 0x{program_word:08x}"
        )
        cocotb.log.info(
            "CHK-EFUSE-GUARD-PROGRAM-TARGET: with SPARE[%d]'s write lock set, a read-back "
            "program of bit %d set PROGRAM_STATUS and EFUSE_REQ_ERROR, and the word still read "
            "0x%08x through the read interface afterwards",
            PROGRAM_FIELD,
            zero_bits[0],
            program_word,
        )
