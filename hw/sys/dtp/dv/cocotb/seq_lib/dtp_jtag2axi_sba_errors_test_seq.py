# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""JTAG2AXI System Bus Access errors on every bridge.

A SLVERR or DECERR response to a write or a read sets sberror 2, and an access
size above the data width sets 4 without a bus transfer; either leaves sbaddress
at the failing access under a seeded sbautoincrement. While sberror is not 0
neither an sbdata0 write nor an sbaddress0 write under sbreadonaddr starts an
access; an sbcs write with a nonzero sberror field clears it, and the next
access completes. Each bridge keeps one error while the bridges after it run,
which shows that an error on one bridge leaves the others working.
"""

from __future__ import annotations

import random

from env.dtp_types import JTAG2AXI_TARGETS, DtpDmReg, pack_sbcs, unpack_sbcs
from ocah_axi_vip import RESP_DECERR, RESP_SLVERR
from ocah_lib import OcahKnobs

from .dtp_jtag2axi_base_test_seq import dtp_jtag2axi_base_test_seq

SBA_ERROR_CHECK_ID = "CHK-J2A-SBA-ERROR"
SBA_ERROR_NEGATIVE_KNOB = "DTP_J2A_SBA_ERROR_NEGATIVE"
SBERROR_BUS = 2
SBERROR_SIZE = 4
# The largest sbaccess encoding, 128 bytes.
SBACCESS_MAX = 7
# (response, read) of every bus error.
BUS_ERRORS = tuple((resp, read) for resp in (RESP_SLVERR, RESP_DECERR) for read in (False, True))
RESP_NAMES = {RESP_SLVERR: "slverr", RESP_DECERR: "decerr"}


class dtp_jtag2axi_sba_errors_test_seq(dtp_jtag2axi_base_test_seq):
    """Size errors, bus errors, refused accesses and the clear on each bridge in a seeded
    order, then each bridge's held error checked and cleared."""

    def __init__(
        self,
        name: str = "dtp_jtag2axi_sba_errors_test_seq",
        *,
        scenario_seed: int | None = None,
        random_count: int = 5,
    ) -> None:
        super().__init__(name, scenario_seed=scenario_seed, random_count=random_count)
        self._ledger_target: str | None = None

    def bus_ledger_target(self) -> str | None:
        return self._ledger_target

    async def body(self) -> None:
        self.log_banner("System Bus Access errors on every bridge")
        await self.enable_all_debug()
        await self.reset_tap()
        rng = self.rng("sba_errors")
        targets = list(JTAG2AXI_TARGETS)
        rng.shuffle(targets)
        for target in targets:
            self._ledger_target = target
            self.open_bus_ledger()
            await self.size_error_case(target, rng)
            await self.bus_error_case(target, rng)
            resp, read = rng.choice(BUS_ERRORS)
            await self.bus_error(
                target, resp, read, bool(rng.getrandbits(1)), rng, context=f"{target}.held"
            )
            self.close_bus_ledger()
            self._ledger_target = None
        for target in targets:
            self._ledger_target = target
            self.open_bus_ledger()
            await self.check_sberror(target, SBERROR_BUS, context=f"{target}.held")
            await self.clear_sberror(target, rng, context=f"{target}.held")
            await self.write_neighbour_then_read(
                target,
                self.random_target_addr(target, rng),
                rng,
                context=f"{target}.held.recovery",
            )
            self.close_bus_ledger()
            self._ledger_target = None
            self.log_summary(f"{target} System Bus Access errors complete")

    async def size_error_case(self, target: str, rng: random.Random) -> None:
        """Every sbaccess above the data width, started by an sbdata0 write and by an
        sbaddress0 write, half of them under sbautoincrement, sets sberror 4, reaches no bus
        and leaves sbaddress unchanged."""
        cases = [
            (size, read)
            for size in range(self.target_cfg(target).data_size + 1, SBACCESS_MAX + 1)
            for read in (False, True)
        ]
        rng.shuffle(cases)
        for (size, read), autoincrement in zip(cases, balanced_bits(rng, len(cases)), strict=True):
            ctx = f"{target}.size_error.size{size}.{'read' if read else 'write'}"
            # Aligned to the access size: the alignment error takes precedence.
            addr = self.random_target_addr(target, rng) & ~((1 << size) - 1)
            await self.sba_setup(
                target, addr, size, read=read, context=ctx, autoincrement=autoincrement
            )
            if not read:
                await self.dmi_write(
                    target, DtpDmReg.SBDATA0, rng.getrandbits(32), context=f"{ctx}.sbdata0"
                )
            await self.wait_sba_idle(target, context=ctx, sberror=SBERROR_SIZE)
            await self.check_sberror(target, SBERROR_SIZE, context=ctx)
            await self.check_sba_address(target, addr, context=ctx)
            self.expect_no_bus_request(target, context=ctx)
            await self.clear_sberror(target, rng, context=ctx)

    async def bus_error_case(self, target: str, rng: random.Random) -> None:
        """SLVERR and DECERR on a write and on a read, in a seeded order, half of them under
        sbautoincrement. Each error refuses the next accesses until an sbcs write clears it,
        and an access at the same beat then completes."""
        cases = list(BUS_ERRORS)
        rng.shuffle(cases)
        for (resp, read), autoincrement in zip(cases, balanced_bits(rng, len(cases)), strict=True):
            ctx = f"{target}.{RESP_NAMES[resp]}.{'read' if read else 'write'}"
            base, beat = await self.bus_error(target, resp, read, autoincrement, rng, context=ctx)
            await self.refused_accesses(target, base, rng, context=ctx)
            self.check_target_word(
                target,
                base,
                beat,
                size=self.target_cfg(target).data_size,
                context=f"{ctx}.refused.mem",
            )
            await self.clear_sberror(target, rng, context=ctx)
            await self.write_neighbour_then_read(target, base, rng, context=f"{ctx}.recovery")

    async def bus_error(
        self,
        target: str,
        resp: int,
        read: bool,
        autoincrement: bool,
        rng: random.Random,
        *,
        context: str,
    ) -> tuple[int, int]:
        """A ``resp`` answer to a seeded access of a seeded size sets sberror 2 and leaves
        sbaddress at the access, with ``autoincrement`` as well, and the beat keeps the content
        it was filled with. Returns the beat address and that content."""
        cfg = self.target_cfg(target)
        base = self.random_target_addr(target, rng)
        beat = self.random_distinct_word(rng, target)
        await self.sba_write(target, base, beat, size=cfg.data_size, context=f"{context}.fill")
        size = rng.randint(0, cfg.data_size)
        offset = rng.randrange(0, cfg.beat_bytes, 1 << size)
        self.inject_bus_error(target, base, resp, read=read, context=context)
        if read:
            await self.sba_read_request(
                target,
                base + offset,
                size=size,
                context=context,
                autoincrement=autoincrement,
                sberror=SBERROR_BUS,
            )
        else:
            mask = self.data_mask(size) << (8 * offset)
            while True:
                lanes = (rng.getrandbits(8 << size) << (8 * offset)) & mask
                if lanes != beat & mask:
                    break
            await self.sba_setup(
                target,
                base + offset,
                size,
                read=False,
                context=context,
                autoincrement=autoincrement,
            )
            await self.sba_write_data(
                target,
                base + offset,
                lanes >> (8 * offset),
                size=size,
                context=context,
                sberror=SBERROR_BUS,
            )
        await self.check_sberror(target, SBERROR_BUS, context=context)
        await self.check_sba_address(target, base + offset, context=context)
        self.check_target_word(target, base, beat, size=cfg.data_size, context=f"{context}.mem")
        return base, beat

    async def refused_accesses(
        self, target: str, addr: int, rng: random.Random, *, context: str
    ) -> None:
        """While sberror is set, an sbdata0 write and an sbaddress0 write under sbreadonaddr
        start no access and sberror keeps its value."""
        size = self.target_cfg(target).data_size
        reads = [False, True]
        rng.shuffle(reads)
        for read in reads:
            ctx = f"{context}.refused_{'read' if read else 'write'}"
            await self.sba_setup(target, addr, size, read=read, context=ctx)
            if not read:
                await self.dmi_write(
                    target, DtpDmReg.SBDATA0, rng.getrandbits(32), context=f"{ctx}.sbdata0"
                )
            await self.check_sberror(target, SBERROR_BUS, context=ctx)
            self.expect_no_bus_request(target, context=ctx)

    async def clear_sberror(self, target: str, rng: random.Random, *, context: str) -> None:
        """An sbcs write with a seeded nonzero sberror field clears sberror."""
        await self.dmi_write(
            target,
            DtpDmReg.SBCS,
            pack_sbcs(sberror=rng.randint(1, 7)),
            context=f"{context}.clear.sbcs",
        )
        await self.check_sberror(target, 0, context=f"{context}.clear")

    async def check_sberror(self, target: str, expected: int, *, context: str) -> None:
        """``CHK-J2A-SBA-ERROR``: sbcs reads sberror ``expected``.

        ``DTP_J2A_SBA_ERROR_NEGATIVE=1`` flips the expected bit 0, so the run
        must fail.
        """
        sbcs = unpack_sbcs(await self.dmi_read(target, DtpDmReg.SBCS, context=f"{context}.sbcs"))
        if OcahKnobs.is_set(SBA_ERROR_NEGATIVE_KNOB):
            expected ^= 0x1
        self.check_equal(
            self.target_evidence(target),
            SBA_ERROR_CHECK_ID,
            sbcs["sberror"],
            expected,
            context=f"{context} target={target} sberror",
        )

    async def check_sba_address(self, target: str, expected: int, *, context: str) -> None:
        """``CHK-J2A-SBA-ERROR``: sbaddress reads ``expected``."""
        self.check_equal(
            self.target_evidence(target),
            SBA_ERROR_CHECK_ID,
            await self.read_sbaddress(target, context=context),
            self.masked_addr(target, expected),
            context=f"{context} target={target} sbaddress",
        )


def balanced_bits(rng: random.Random, count: int) -> list[bool]:
    """``count`` seeded bits in a seeded order, half of them set, the odd one seeded."""
    bits = [False, True] * (count // 2) + [bool(rng.getrandbits(1))] * (count % 2)
    rng.shuffle(bits)
    return bits
