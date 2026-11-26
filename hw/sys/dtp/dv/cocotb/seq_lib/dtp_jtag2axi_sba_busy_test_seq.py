# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""JTAG2AXI System Bus Access while a bus access is outstanding, on every bridge.

On each bridge, every access kind the Debug Module refuses while a bus access is
outstanding runs once per pass, in a seeded order: an sbcs write, sbaddress0 and
sbaddress1 writes, and sbdata0 and sbdata1 writes and reads. A kind runs under a
held write in one pass and a held read in the next. Each case starts a seeded
access with its response held and polls sbcs past the ``SBA_POLLS`` bound, every
poll reading sbbusy 1, then reads sbaddress, which the Debug Module never
refuses. The case's own kind is then refused with the busy status, which a DTMCS
dmireset clears, and one more kind is refused under the sbbusyerror the first
set, which a DMI op-3 scan clears. Neither refusal changes sbcs or sbaddress or
raises a request at the port, and an sbcs write that sets sbbusyerror does not
clear it. Released, the access completes with its data, sbcs keeps sbbusyerror
until a write of 1 clears it, and the next access reaches the port.
"""

from __future__ import annotations

import random

from env.dtp_types import JTAG2AXI_TARGETS, DtpDmiOp, DtpDmiStatus, DtpDmReg, pack_sbcs, unpack_sbcs

from .dtp_jtag2axi_base_test_seq import (
    BUSY_POLLS,
    DTMCS_DMIRESET,
    SBA_BUSY_CHECK_ID,
    dtp_jtag2axi_base_test_seq,
)

# Every access the Debug Module refuses while a bus access is outstanding:
# (register, read).
BUSY_KINDS = {
    "sbcs_write": (DtpDmReg.SBCS, False),
    "sbaddress0_write": (DtpDmReg.SBADDRESS0, False),
    "sbaddress1_write": (DtpDmReg.SBADDRESS1, False),
    "sbdata0_write": (DtpDmReg.SBDATA0, False),
    "sbdata1_write": (DtpDmReg.SBDATA1, False),
    "sbdata0_read": (DtpDmReg.SBDATA0, True),
    "sbdata1_read": (DtpDmReg.SBDATA1, True),
}
# The data a read refused by the Debug Module returns.
DATA_BUSY = 0xB051_B051
_WORD = 0xFFFF_FFFF


class dtp_jtag2axi_sba_busy_test_seq(dtp_jtag2axi_base_test_seq):
    """Every refused access kind under a held response on each bridge, in a seeded order."""

    def __init__(
        self,
        name: str = "dtp_jtag2axi_sba_busy_test_seq",
        *,
        scenario_seed: int | None = None,
        random_count: int = 5,
    ) -> None:
        super().__init__(name, scenario_seed=scenario_seed, random_count=random_count)
        self._ledger_target: str | None = None

    def bus_ledger_target(self) -> str | None:
        return self._ledger_target

    async def body(self) -> None:
        self.log_banner("System Bus Access while a bus access is outstanding on every bridge")
        await self.enable_all_debug()
        await self.reset_tap()
        rng = self.rng("sba_busy")
        targets = list(JTAG2AXI_TARGETS)
        rng.shuffle(targets)
        for target in targets:
            self._ledger_target = target
            self.open_bus_ledger()
            await self.busy_cases(target, rng)
            self.close_bus_ledger()
            self._ledger_target = None
            self.log_summary(f"{target} busy accesses complete")

    async def busy_cases(self, target: str, rng: random.Random) -> None:
        """Every kind once, in a seeded order, then a seeded access. A kind's held access
        is a read when its ``BUSY_KINDS`` position and the pass index differ in parity, so
        every two passes hold each kind under both. A seeded cycle through the kinds names
        the kind each case refuses second, so every kind is also refused once under
        sbbusyerror."""
        kinds = list(BUSY_KINDS)
        rng.shuffle(kinds)
        for i, kind in enumerate(kinds):
            read = (list(BUSY_KINDS).index(kind) + self.loop_index) % 2 == 1
            second = kinds[(i + 1) % len(kinds)]
            await self.held_case(target, rng, read=read, first=kind, second=second)
        await self.port_access(
            target,
            rng,
            read=bool(rng.getrandbits(1)),
            check_id=SBA_BUSY_CHECK_ID,
            ctx=f"{target}.next",
        )

    async def held_case(
        self, target: str, rng: random.Random, *, read: bool, first: str, second: str
    ) -> None:
        """A seeded read or write whose response is held while sbcs is polled and ``first``
        and then ``second`` are refused; released, it completes with its data."""
        cfg = self.target_cfg(target)
        tb_if = self.cfg.tb_if
        ctx = f"{target}.{'read' if read else 'write'}.{first}"
        addr, size, offset = self.seeded_access(target, rng)
        data = self.sized_word(rng, size, self.memory_word(target, addr, size))
        wstrb = self.full_wstrb(size) << offset
        if read:
            lanes = self.data_mask(size) << (8 * offset)
            beat = (rng.getrandbits(cfg.data_width) & ~lanes) | (data << (8 * offset))
            await self.sba_write(
                target, addr - offset, beat, size=cfg.data_size, context=f"{ctx}.fill"
            )
        else:
            self.scoreboard_arm_strobes(target, wstrb, addr, context=ctx)
        since = self.open_request_count(target)
        held = tb_if.sample(f"{target}_{'r' if read else 'b'}_held")
        tb_if.hold_responses(target, b=not read, r=read)
        await self.sba_setup(target, addr, size, read=read, context=ctx)
        if not read:
            if size == 3:
                await self.dmi_write(target, DtpDmReg.SBDATA1, data >> 32, context=f"{ctx}.sbdata1")
            await self.dmi_write(target, DtpDmReg.SBDATA0, data & _WORD, context=f"{ctx}.sbdata0")
        reached = await self.wait_response_held(target, read=read, above=held)
        sbcs = await self.poll_while_held(target, rng.randint(*BUSY_POLLS), context=f"{ctx}.held")
        state = {"sbcs": sbcs, "sbaddress": self.masked_addr(target, addr)}
        sbaddress = await self.read_sbaddress(target, context=f"{ctx}.held")
        self.record_fields(
            target,
            SBA_BUSY_CHECK_ID,
            [("held", int(reached), 1), ("sbaddress", sbaddress, state["sbaddress"])],
            context=f"{ctx}.held",
        )
        await self.refuse(target, first, rng, state, dmireset=True, ctx=f"{ctx}.first")
        await self.refuse(target, second, rng, state, dmireset=False, ctx=f"{ctx}.{second}")
        tb_if.hold_responses(target, b=False, r=False)
        await self.expect_bus_request(
            target,
            read=read,
            addr=addr,
            size=size,
            data=0 if read else data << (8 * offset),
            wstrb=0 if read else wstrb,
            context=ctx,
        )
        released = await self.wait_sba_idle(target, sbbusyerror=1, context=f"{ctx}.released")
        await self.dmi_write(
            target,
            DtpDmReg.SBCS,
            pack_sbcs(sbbusyerror=1, sbaccess=size),
            context=f"{ctx}.sbbusyerror_w1",
        )
        cleared = await self.wait_sba_idle(target, context=f"{ctx}.cleared")
        self.record_fields(
            target,
            SBA_BUSY_CHECK_ID,
            [
                ("sbbusyerror_released", released["sbbusyerror"], 1),
                ("sbbusyerror_cleared", cleared["sbbusyerror"], 0),
            ],
            context=f"{ctx}.released",
        )
        if read:
            rdata = await self.read_sbdata(target, size, ctx)
            self.check_bridge_rdata(target, rdata & self.data_mask(size), data, context=ctx)
        else:
            self.check_target_word(target, addr, data, size=size, context=f"{ctx}.mem")
        self.check_one_transfer(target, since, context=ctx)

    async def refuse(
        self,
        target: str,
        kind: str,
        rng: random.Random,
        state: dict[str, int],
        *,
        dmireset: bool,
        ctx: str,
    ) -> None:
        """A ``kind`` access the Debug Module refuses while the access is outstanding. The next
        DMI capture returns status 3 with the refused access's address and, for a write, its
        data, for a read 0xB051B051. With ``dmireset`` a NOP scan takes that capture and a
        DTMCS dmireset, whose capture reads dmistat 3, clears the status; otherwise a DMI op-3
        scan takes it and clears the status. sbcs then reads sbbusyerror 1 with every other
        field and sbaddress as ``state`` holds them, and the port raised no request."""
        address, read = BUSY_KINDS[kind]
        since = self.open_request_count(target)
        if read:
            await self.dmi_scan(target, address, 0, DtpDmiOp.READ, context=f"{ctx}.refused")
            expect = (int(address), DATA_BUSY)
        else:
            value = self.refused_value(target, kind, rng, state)
            await self.dmi_write(target, address, value, context=f"{ctx}.refused")
            expect = (int(address), value)
        await self.select_dmi(target)
        await self.dmi_raw(
            target,
            0,
            0,
            DtpDmiOp.NOP if dmireset else DtpDmiOp.CLEAR,
            status=DtpDmiStatus.BUSY,
            expect=expect,
            context=f"{ctx}.capture",
        )
        if dmireset:
            await self.dtmcs_scan(
                target, DTMCS_DMIRESET, status=DtpDmiStatus.BUSY, context=f"{ctx}.dmireset"
            )
        sbcs = await self.dmi_read(target, DtpDmReg.SBCS, context=f"{ctx}.sbcs")
        sbaddress = await self.read_sbaddress(target, context=ctx)
        self.record_fields(
            target,
            SBA_BUSY_CHECK_ID,
            [
                ("sbcs", sbcs, state["sbcs"] | pack_sbcs(sbbusyerror=1)),
                ("sbaddress", sbaddress, state["sbaddress"]),
            ],
            context=f"{ctx} kind={kind}",
        )
        self.check_one_transfer(target, since, context=f"{ctx}.refused")

    def refused_value(
        self, target: str, kind: str, rng: random.Random, state: dict[str, int]
    ) -> int:
        """A seeded value for a refused ``kind`` write: for sbcs one that changes every
        writable field and sets both write-1-to-clear fields, for sbaddress one that changes
        the register."""
        if kind == "sbcs_write":
            held = unpack_sbcs(state["sbcs"])
            sizes = [
                s for s in range(self.target_cfg(target).data_size + 1) if s != held["sbaccess"]
            ]
            return pack_sbcs(
                sbbusyerror=1,
                sbreadonaddr=1 - held["sbreadonaddr"],
                sbaccess=rng.choice(sizes),
                sbautoincrement=1,
                sbreadondata=1,
                sberror=0x7,
            )
        current = {
            "sbaddress0_write": state["sbaddress"] & _WORD,
            "sbaddress1_write": state["sbaddress"] >> 32,
        }.get(kind, 0)
        return self.sized_word(rng, 2, current)
