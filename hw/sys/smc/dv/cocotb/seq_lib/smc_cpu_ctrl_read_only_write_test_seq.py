# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Writes at the CPU_CTRL registers software cannot write.

`smc_rdl_field_sweep_test` owns CPU_CTRL and drives every register whose RDL
contract makes it writable. What it never does is write at the addresses of
the registers the contract makes `sw = r`, so the decode row those addresses
take on a write has never been exercised, and neither has a write of 0 into
the `singlepulse` fields of `WDT_TIMEOUT_RESET` -- that leaf writes them set
and then writes 0 only over the half they do not occupy.

The read-only registers here are `TEST_CTRL`, `SMC_ATTRIBUTES` and the four
per-core writeback program counters. Every field of each is `sw = r`, so a
write cannot change one and the claim is exactly that: the register reads the
same word after the write as before it.

`WDT_TIMEOUT_RESET` takes a full-width write of 0. Its four
`reset_cycle_count` fields are `singlepulse`, so neither a 1 nor a 0 is
stored, and the register has to read 0 afterwards. `CORE_RESET_PULSE_COUNT` is
read either side as a second, weaker observation: it holds the two configured
pulse durations and a bit the RDL describes as "logic low while performing
core reset, logic high otherwise", so a core reset in progress when the second
read lands would show there. It does not catch a pulse that began and ended
between the two reads, which is why the `singlepulse` no-store above is the
leg's primary claim.

Nothing here writes a CPU_CTRL register that resets or wedges the bench.
`RESET_CTRL` stays untouched: it carries the per-core and uncore reset levels
and the four core reset-pulse starts, and `smc_rdl_field_sweep_test` excludes
it for that reason.
"""

from __future__ import annotations

import cocotb

from .smc_csr_seq_utils import SmcCsrSeq
from .smc_rdl_regmap import rdl_array, rdl_register

#: CPU_CTRL registers every field of which the RDL makes `sw = r`.
_READ_ONLY_SINGLE: tuple[str, ...] = (
    "smc_cpu_ctrl/TEST_CTRL",
    "smc_cpu_ctrl/SMC_ATTRIBUTES",
)
#: Read-only register arrays; the first element of each is written at.
_READ_ONLY_ARRAYS: tuple[str, ...] = (
    "smc_cpu_ctrl/WB_PC_CORE0",
    "smc_cpu_ctrl/WB_PC_CORE1",
    "smc_cpu_ctrl/WB_PC_CORE2",
    "smc_cpu_ctrl/WB_PC_CORE3",
)
_WDT_TIMEOUT_RESET = "smc_cpu_ctrl/WDT_TIMEOUT_RESET"
_CORE_RESET_PULSE_COUNT = "smc_cpu_ctrl/CORE_RESET_PULSE_COUNT"

#: Word written at a read-only address. Every bit set, so a register that took
#: any part of it shows a change.
_WRITE_PATTERN = 0xFFFF_FFFF_FFFF_FFFF

_ACCESSES_PER_READ_ONLY = 3
_ACCESSES_FOR_WDT = 4
_MUTEX = "smc_cpu_ctrl/MUTEX"
# Accesses one mutex costs: four reads that each take it, two half writes while
# held, a full write carrying a one, two half writes while free, and the release.
_ACCESSES_PER_MUTEX = 10


class smc_cpu_ctrl_read_only_write_test_seq(SmcCsrSeq):
    """Write at every CPU_CTRL address the RDL makes read-only."""

    def __init__(self, name: str = "smc_cpu_ctrl_read_only_write_test_seq") -> None:
        super().__init__(name)
        self.mutexes_held = 0
        self.read_only_registers = 0
        self.pulse_count_before = -1
        self.pulse_count_after = -1

    async def _write_at_read_only(self, path: str, addr: int, width: int) -> None:
        mask = (1 << (width * 8)) - 1
        before = await self.csr_read(f"{path}:before_wr", addr, length=width)
        await self.csr_write(f"{path}:wr", addr, _WRITE_PATTERN & mask, length=width)
        after = await self.csr_read(f"{path}:after_wr", addr, length=width)
        assert after == before, (
            f"{path} @ 0x{addr:08x} read 0x{before:x} before a write of "
            f"0x{_WRITE_PATTERN & mask:x} and 0x{after:x} after it; every field of it is "
            f"`sw = r`, so the write has to take no effect"
        )
        self.read_only_registers += 1

    async def _mutex_leg(self, index: int, addr: int, width: int) -> None:
        """Every combination of the mutex bit and its byte lane, and a one on it.

        `cpu_ctrl.rdl` makes `MUTEX.mutex` bit 0 of a 64-bit register and
        describes it as "HW mutex. Reads will attempt to acquire mutex, 1 on
        success. If the mutex is already acquired, the read will return 0. To
        release the mutex, write any value to the register." So a read is the
        only way to see the field, it takes the mutex, and any write gives it
        back -- whichever half the write selects.

        The leg writes the register with the bit both free and held, and with
        the lane that carries it both selected and not: a four-byte write at the
        low half selects it, one at the upper half does not. Each write while
        held must give the mutex back, which the read after it shows by taking
        it again; each write while free must leave it free. A one is also
        carried on the bit's lane, which the releases elsewhere never do.
        """
        half = width // 2
        name = f"MUTEX{index}"

        async def take(tag: str, why: str) -> None:
            got = await self.csr_read(f"{name}_{tag}", addr, length=width)
            assert got & 1, f"MUTEX[{index}] read 0x{got:x} {why}"

        await take("ACQUIRE", "at the start; the RDL returns 0 when something else holds it")
        await self.csr_write(f"{name}_HELD_LOW", addr, 0, length=4)
        await take("AFTER_HELD_LOW", "after a low-half write while held; any write releases it")
        await self.csr_write(f"{name}_HELD_UPPER", addr + half, 0, length=4)
        await take(
            "AFTER_HELD_UPPER",
            "after an upper-half write while held; that write did not select bit 0's "
            "lane, but any write releases it",
        )
        await self.csr_write(f"{name}_RELEASE_ONE", addr, 1, length=width)
        await self.csr_write(f"{name}_FREE_LOW", addr, 1, length=4)
        await self.csr_write(f"{name}_FREE_UPPER", addr + half, 0, length=4)
        await take(
            "AFTER_FREE",
            "after a low-half and an upper-half write while free; neither may take it, so "
            "it had to still be free",
        )
        await self.csr_write(f"{name}_RELEASE", addr, 0, length=width)
        self.mutexes_held += 1

    async def body(self) -> None:
        await self.wait_fuse_sense_done()

        targets: list[tuple[str, int, int]] = []
        for path in _READ_ONLY_SINGLE:
            reg = rdl_register(path)
            assert reg.rw_mask == 0, (
                f"{path} has a software-writable field, so it does not belong in a leaf "
                f"about writes the RDL says take no effect"
            )
            targets.append((path, reg.addr, reg.width_bytes))
        for path in _READ_ONLY_ARRAYS:
            reg = rdl_array(path)[0]
            assert reg.rw_mask == 0, f"{path}[0] has a software-writable field"
            targets.append((reg.path, reg.addr, reg.width_bytes))
        assert len({addr for _p, addr, _w in targets}) == len(targets), (
            "two of the read-only registers resolve to the same address"
        )

        for path, addr, width in targets:
            await self._write_at_read_only(path, addr, width)
        cocotb.log.info(
            "CHK-CPU-CTRL-READ-ONLY-WRITE: %d CPU_CTRL registers every field of which the "
            "RDL makes `sw = r` each read the same word after a write of all ones at their "
            "address as before it, so the write took no effect",
            self.read_only_registers,
        )

        wdt = rdl_register(_WDT_TIMEOUT_RESET)
        pulses = rdl_register(_CORE_RESET_PULSE_COUNT)
        self.pulse_count_before = await self.csr_read(
            "CORE_RESET_PULSE_COUNT:before", pulses.addr, length=pulses.width_bytes
        )
        await self.csr_write("WDT_TIMEOUT_RESET:zero", wdt.addr, 0, length=wdt.width_bytes)
        after = await self.csr_read(
            "WDT_TIMEOUT_RESET:after_zero", wdt.addr, expected=0, length=wdt.width_bytes
        )
        assert after == 0, (
            f"WDT_TIMEOUT_RESET @ 0x{wdt.addr:08x} reads 0x{after:x} after a full-width "
            f"write of 0; its fields are `singlepulse`, so nothing a write carries is stored"
        )
        self.pulse_count_after = await self.csr_read(
            "CORE_RESET_PULSE_COUNT:after", pulses.addr, length=pulses.width_bytes
        )
        assert self.pulse_count_after == self.pulse_count_before, (
            f"CORE_RESET_PULSE_COUNT moved from 0x{self.pulse_count_before:x} to "
            f"0x{self.pulse_count_after:x} across a write of 0 into the singlepulse reset "
            f"fields; it carries the configured pulse durations and a bit that reads low "
            f"while a core reset is in progress, and none of that may move"
        )
        mutexes = rdl_array(_MUTEX)
        for index, reg in enumerate(mutexes):
            await self._mutex_leg(index, reg.addr, reg.width_bytes)
        assert self.mutexes_held == len(mutexes), (
            f"{self.mutexes_held} of {len(mutexes)} mutexes driven"
        )
        cocotb.log.info(
            "CHK-CPU-CTRL-MUTEX-HALF-WRITE: each of the %d CPU_CTRL mutexes took a "
            "four-byte write at the half its bit occupies and at the half it does not, "
            "both while held and while free, and a one on its bit's lane; every write while "
            "held gave the mutex back, shown by the next read taking it again, every write "
            "while free left it free, and every mutex this leaf took was given back",
            self.mutexes_held,
        )

        cocotb.log.info(
            "CHK-CPU-CTRL-WDT-ZERO-WRITE: a full-width write of 0 into the four "
            "`singlepulse` reset fields of WDT_TIMEOUT_RESET left the register reading 0, "
            "so nothing the write carried was stored, and CORE_RESET_PULSE_COUNT read the "
            "same word (0x%x) either side, with no core reset in progress when the second "
            "read landed",
            self.pulse_count_after,
        )

        expected = (
            len(targets) * _ACCESSES_PER_READ_ONLY
            + _ACCESSES_FOR_WDT
            + len(mutexes) * _ACCESSES_PER_MUTEX
        )
        self.assert_all_reachable(expected, "CPU_CTRL_READ_ONLY_WRITE")
        assert self.read_only_registers == len(targets), (
            f"{self.read_only_registers} of {len(targets)} read-only registers written at"
        )
