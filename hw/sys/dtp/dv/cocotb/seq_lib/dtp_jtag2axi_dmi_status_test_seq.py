# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""JTAG2AXI DTMCS and sticky DMI status on every bridge.

Each case starts and ends with the status at 0 and the TAP in Run-Test/Idle.
A DMI scan chained from Update-DR captures two TCK cycles after the update,
one from Run-Test/Idle three cycles after it, and a scan that shifts no bit
updates four cycles after it, all inside the DTP_DMI_BUSY_TCK window in which
the operation is in progress.
"""

from __future__ import annotations

import random

from env.dtp_types import (
    JTAG2AXI_TARGETS,
    DtpDmiOp,
    DtpDmiStatus,
    DtpDmReg,
    pack_sbcs,
    unpack_sbcs,
)

from .dtp_jtag2axi_base_test_seq import (
    DTMCS_DMIHARDRESET,
    DTMCS_DMIRESET,
    FAULT_STATUS_CHECK_ID,
    dtp_jtag2axi_base_test_seq,
)

# The data a read refused by the Debug Module returns.
DATA_BUSY = 0xB051_B051
# System cycles TCK stays stopped in Run-Test/Idle after a read's Update-DR.
TCK_STOP_CYCLES = (200, 1000)

_OK = DtpDmiStatus.SUCCESS
_BUSY = DtpDmiStatus.BUSY
_SBADDRESS0 = int(DtpDmReg.SBADDRESS0)


class dtp_jtag2axi_dmi_status_test_seq(dtp_jtag2axi_base_test_seq):
    """Every DMI operation, every cause of the busy status and both ways to clear it, on each
    bridge in a seeded order."""

    def __init__(
        self,
        name: str = "dtp_jtag2axi_dmi_status_test_seq",
        *,
        scenario_seed: int | None = None,
        random_count: int = 5,
    ) -> None:
        super().__init__(name, scenario_seed=scenario_seed, random_count=random_count)
        self._ledger_target: str | None = None

    def bus_ledger_target(self) -> str | None:
        return self._ledger_target

    async def body(self) -> None:
        self.log_banner("DMI status on every bridge")
        await self.enable_all_debug()
        await self.reset_tap()
        rng = self.rng("dmi_status")
        targets = list(JTAG2AXI_TARGETS)
        rng.shuffle(targets)
        for target in targets:
            cases = [
                self.dtmcs_case,
                self.ops_case,
                self.capture_during_read_case,
                self.update_during_write_case,
                self.update_during_read_case,
                self.dm_busy_case,
                self.tck_stop_case,
            ]
            rng.shuffle(cases)
            self._ledger_target = target
            self.open_bus_ledger()
            await self.activate_dm(target)
            await self.dmi_write(
                target,
                DtpDmReg.SBCS,
                pack_sbcs(sbaccess=self.target_cfg(target).data_size),
                context=f"{target}.sbcs",
            )
            for case in cases:
                await case(target, rng)
            self.close_bus_ledger()
            self._ledger_target = None
            self.log_summary(
                f"{target} DMI status complete", cases=[case.__name__ for case in cases]
            )

    async def dtmcs_case(self, target: str, rng: random.Random) -> None:
        """DTMCS shows the sticky status in dmistat; dmihardreset leaves it and dmireset
        clears it, keeping the DMI address and data, and dmireset with status 0 changes
        nothing."""
        ctx = f"{target}.dtmcs"
        await self.dtmcs_scan(target, DTMCS_DMIRESET, status=_OK, context=f"{ctx}.clear")
        address, data = int(DtpDmReg.DMCONTROL), 0x1
        await self.select_dmi(target)
        await self.dmi_raw(
            target, address, data, DtpDmiOp.WRITE, status=_OK, chain=True, context=f"{ctx}.write"
        )
        await self.dmi_zero_shift()
        await self.run_test_idle()
        await self.dtmcs_scan(target, DTMCS_DMIHARDRESET, status=_BUSY, context=f"{ctx}.hard")
        await self.dtmcs_scan(target, DTMCS_DMIRESET, status=_BUSY, context=f"{ctx}.dmireset")
        await self.dtmcs_scan(target, 0, status=_OK, context=f"{ctx}.cleared")
        await self.select_dmi(target)
        await self.dmi_raw(
            target, 0, 0, DtpDmiOp.NOP, status=_OK, expect=(address, data), context=f"{ctx}.kept"
        )

    async def ops_case(self, target: str, rng: random.Random) -> None:
        """With status 0, NOP and op 3 load the scanned address and data, a write reaches the
        Debug Module register and a read returns it."""
        ctx = f"{target}.ops"
        nop = (rng.getrandbits(7), rng.getrandbits(32))
        clear = (rng.getrandbits(7), rng.getrandbits(32))
        sbaddress0 = self.random_sbaddress0(target, rng)
        await self.select_dmi(target)
        await self.dmi_raw(target, *nop, DtpDmiOp.NOP, status=_OK, context=f"{ctx}.nop")
        await self.dmi_raw(
            target, *clear, DtpDmiOp.CLEAR, status=_OK, expect=nop, context=f"{ctx}.clear"
        )
        await self.dmi_raw(
            target,
            _SBADDRESS0,
            sbaddress0,
            DtpDmiOp.WRITE,
            status=_OK,
            expect=clear,
            context=f"{ctx}.write",
        )
        await self.run_test_idle()
        await self.dmi_raw(
            target,
            _SBADDRESS0,
            rng.getrandbits(32),
            DtpDmiOp.READ,
            status=_OK,
            expect=(_SBADDRESS0, sbaddress0),
            context=f"{ctx}.read",
        )
        await self.run_test_idle()
        await self.dmi_raw(
            target,
            0,
            0,
            DtpDmiOp.NOP,
            status=_OK,
            expect=(_SBADDRESS0, sbaddress0),
            context=f"{ctx}.fetch",
        )

    async def capture_during_read_case(self, target: str, rng: random.Random) -> None:
        """A capture during a read is busy and shows the read's own address and data; the
        update that follows is ignored, and op 3 clears the status over the read data."""
        ctx = f"{target}.capture_during_read"
        sbaddress0 = self.random_sbaddress0(target, rng)
        ignored = sbaddress0 ^ 0x1
        op_data = rng.getrandbits(32)
        await self.dmi_write(target, DtpDmReg.SBADDRESS0, sbaddress0, context=f"{ctx}.setup")
        await self.select_dmi(target)
        await self.dmi_raw(
            target, _SBADDRESS0, op_data, DtpDmiOp.READ, status=_OK, chain=True, context=ctx
        )
        await self.dmi_raw(
            target,
            _SBADDRESS0,
            ignored,
            DtpDmiOp.WRITE,
            status=_BUSY,
            expect=(_SBADDRESS0, op_data),
            context=f"{ctx}.busy",
        )
        await self.run_test_idle()
        for op, status in ((DtpDmiOp.CLEAR, _BUSY), (DtpDmiOp.NOP, _OK)):
            await self.dmi_raw(
                target,
                0,
                0,
                op,
                status=status,
                expect=(_SBADDRESS0, sbaddress0),
                context=f"{ctx}.after_{op.name.lower()}",
            )
        await self.dmi_raw(target, _SBADDRESS0, 0, DtpDmiOp.READ, status=_OK, context=ctx)
        await self.run_test_idle()
        await self.dmi_raw(
            target,
            0,
            0,
            DtpDmiOp.NOP,
            status=_OK,
            expect=(_SBADDRESS0, sbaddress0),
            context=f"{ctx}.unwritten",
        )

    async def update_during_write_case(self, target: str, rng: random.Random) -> None:
        """An update during a write is busy while the write still reaches the Debug Module;
        a later write is ignored without a bus access, and dmireset clears the status."""
        ctx = f"{target}.update_during_write"
        sbaddress0 = self.random_sbaddress0(target, rng)
        await self.select_dmi(target)
        await self.dmi_raw(
            target, _SBADDRESS0, sbaddress0, DtpDmiOp.WRITE, status=_OK, chain=True, context=ctx
        )
        await self.dmi_zero_shift()
        await self.run_test_idle()
        await self.dmi_raw(
            target,
            int(DtpDmReg.SBDATA0),
            rng.getrandbits(32),
            DtpDmiOp.WRITE,
            status=_BUSY,
            expect=(_SBADDRESS0, sbaddress0),
            context=f"{ctx}.ignored",
        )
        await self.run_test_idle()
        await self.dtmcs_scan(target, DTMCS_DMIRESET, status=_BUSY, context=f"{ctx}.dmireset")
        await self.select_dmi(target)
        await self.dmi_raw(
            target,
            _SBADDRESS0,
            0,
            DtpDmiOp.READ,
            status=_OK,
            expect=(_SBADDRESS0, sbaddress0),
            context=f"{ctx}.read",
        )
        await self.run_test_idle()
        await self.dmi_raw(
            target,
            0,
            0,
            DtpDmiOp.NOP,
            status=_OK,
            expect=(_SBADDRESS0, sbaddress0),
            context=f"{ctx}.written",
        )

    async def update_during_read_case(self, target: str, rng: random.Random) -> None:
        """A scan that shifts no bit over a read captures busy and updates op 3, which clears
        the status; the read completes."""
        ctx = f"{target}.update_during_read"
        sbaddress0 = self.random_sbaddress0(target, rng)
        await self.dmi_write(target, DtpDmReg.SBADDRESS0, sbaddress0, context=f"{ctx}.setup")
        await self.select_dmi(target)
        await self.dmi_raw(
            target,
            _SBADDRESS0,
            rng.getrandbits(32),
            DtpDmiOp.READ,
            status=_OK,
            chain=True,
            context=ctx,
        )
        await self.dmi_zero_shift()
        await self.run_test_idle()
        await self.dmi_raw(
            target,
            0,
            0,
            DtpDmiOp.NOP,
            status=_OK,
            expect=(_SBADDRESS0, sbaddress0),
            context=f"{ctx}.completed",
        )

    async def dm_busy_case(self, target: str, rng: random.Random) -> None:
        """While a held write is outstanding the Debug Module refuses an sbaddress0 write and
        sets sbbusyerror; once the write completes it refuses an sbdata0 read with 0xB051B051
        until sbbusyerror is cleared."""
        ctx = f"{target}.dm_busy"
        cfg = self.target_cfg(target)
        size = cfg.data_size
        addr = self.random_target_addr(target, rng)
        data = self.random_distinct_word(rng, target)
        wstrb = self.full_wstrb(size)
        refused = rng.getrandbits(32)
        self.scoreboard_arm_strobes(target, wstrb, addr, context=ctx)
        await self.sba_setup(target, addr, size, read=False, context=ctx)
        self.cfg.tb_if.hold_responses(target, b=True, r=False)
        if size == 3:
            await self.dmi_write(target, DtpDmReg.SBDATA1, data >> 32, context=f"{ctx}.sbdata1")
        await self.dmi_write(target, DtpDmReg.SBDATA0, data & 0xFFFF_FFFF, context=f"{ctx}.sbdata0")
        await self.dmi_write(target, DtpDmReg.SBADDRESS0, refused, context=f"{ctx}.refused")
        await self.select_dmi(target)
        await self.dmi_raw(
            target,
            0,
            0,
            DtpDmiOp.CLEAR,
            status=_BUSY,
            expect=(_SBADDRESS0, refused),
            context=f"{ctx}.clear",
        )
        sbcs = unpack_sbcs(await self.dmi_read(target, DtpDmReg.SBCS, context=f"{ctx}.sbcs"))
        self.check_equal(
            self.target_evidence(target),
            FAULT_STATUS_CHECK_ID,
            (sbcs["sbbusy"], sbcs["sbbusyerror"]),
            (1, 1),
            context=f"{ctx} target={target} held (sbbusy, sbbusyerror)",
        )
        self.cfg.tb_if.hold_responses(target, b=False, r=False)
        await self.expect_bus_request(
            target, read=False, addr=addr, size=size, data=data, wstrb=wstrb, context=ctx
        )
        await self.wait_sba_idle(target, sbbusyerror=1, context=f"{ctx}.released")
        self.check_target_word(target, addr, data, size=size, context=f"{ctx}.mem")
        await self.select_dmi(target)
        await self.dmi_raw(
            target, int(DtpDmReg.SBDATA0), 0, DtpDmiOp.READ, status=_OK, context=f"{ctx}.read"
        )
        await self.run_test_idle()
        for op in (DtpDmiOp.NOP, DtpDmiOp.CLEAR):
            await self.dmi_raw(
                target,
                0,
                0,
                op,
                status=_BUSY,
                expect=(int(DtpDmReg.SBDATA0), DATA_BUSY),
                context=f"{ctx}.refused_read_{op.name.lower()}",
            )
        await self.dmi_write(
            target,
            DtpDmReg.SBCS,
            pack_sbcs(sbbusyerror=1, sbaccess=size),
            context=f"{ctx}.sbbusyerror_w1",
        )
        await self.wait_sba_idle(target, context=f"{ctx}.cleared")

    async def tck_stop_case(self, target: str, rng: random.Random) -> None:
        """A read stays in progress while TCK is stopped in Run-Test/Idle, so the next capture
        is busy; with TCK running it completes. The busy scan reads dmstatus, so the captures
        after it tell an ignored read from one that ran."""
        ctx = f"{target}.tck_stop"
        sbaddress0 = self.random_sbaddress0(target, rng)
        op_data = rng.getrandbits(32)
        await self.dmi_write(target, DtpDmReg.SBADDRESS0, sbaddress0, context=f"{ctx}.setup")
        await self.select_dmi(target)
        await self.dmi_raw(target, _SBADDRESS0, op_data, DtpDmiOp.READ, status=_OK, context=ctx)
        await self.wait_sys_cycles(rng.randint(*TCK_STOP_CYCLES))
        await self.dmi_raw(
            target,
            int(DtpDmReg.DMSTATUS),
            0,
            DtpDmiOp.READ,
            status=_BUSY,
            expect=(_SBADDRESS0, op_data),
            context=f"{ctx}.stopped",
        )
        await self.run_test_idle()
        for op, status in ((DtpDmiOp.CLEAR, _BUSY), (DtpDmiOp.NOP, _OK)):
            await self.dmi_raw(
                target,
                0,
                0,
                op,
                status=status,
                expect=(_SBADDRESS0, sbaddress0),
                context=f"{ctx}.after_{op.name.lower()}",
            )
