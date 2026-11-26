# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""JTAG2AXI instruction decode and the isolation between the bridges.

Each pass first gives a seeded proper subset of the bridges the busy status and
loads distinct DMI cells into the others, then scans each of the six bridge
registers, in a seeded order, past its length: the capture is the selected
bridge's own register, and TDO from the register length on is TDI. Then each
bridge in turn is the victim. Its Debug Module and DMI cells are recorded, with
a bus access held outstanding in odd passes, and its last DMI update leads
straight into a seeded mix of scans of other instructions and of the other two
bridges, with a complete access on each other bridge, one of them held in odd
passes. The victim's DMI capture, dmistat, Debug Module registers and port
counts are then unchanged, and each held access completes on its own port with
its data once released.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from env.dtp_types import (
    DMI_LEN,
    DTMCS_LEN,
    DTP_EXPECTED_DTMCS,
    JTAG2AXI_TARGETS,
    UNDEFINED_BYPASS_INSTRS,
    DtpDmiOp,
    DtpDmiStatus,
    DtpDmReg,
    DtpJtagInstr,
    pack_dmi,
    pack_sbcs,
    unpack_dmi,
    unpack_dtmcs,
)
from ocah_lib import OcahKnobs, OcahRng

from .dtp_jtag2axi_base_test_seq import DTMCS_DMIRESET, dtp_jtag2axi_base_test_seq

DECODE_CHECK_ID = "CHK-J2A-DECODE"
ISOLATION_CHECK_ID = "CHK-J2A-ISOLATION"
DECODE_NEGATIVE_KNOB = "DTP_J2A_DECODE_NEGATIVE"
ISOLATION_NEGATIVE_KNOB = "DTP_J2A_ISOLATION_NEGATIVE"
# Fewest and most bits a decode scan shifts past the register.
EXTRA_BITS = (1, 32)
# Fewest and most scans between the victim's last DMI update and its next capture.
DISTURB_SCANS = (4, 8)
# Fewest and most bits of a scan of a non-bridge instruction.
OTHER_SCAN_BITS = (8, 32)
# Scans of the other bridges and of non-bridge instructions that change no DUT output.
DISTURB_KINDS = ("idcode", "bypass", "undefined", "dtmcs", "dmi_load", "dm_read")
# The undefined opcodes above the bridge instructions, each of which selects BYPASS.
UNDEFINED_INSTRS = tuple(instr for instr in UNDEFINED_BYPASS_INSTRS if instr >= 0x21)
_DTMCS_DMISTAT_LSB = 10
_SBADDRESS0 = int(DtpDmReg.SBADDRESS0)
_OK = DtpDmiStatus.SUCCESS
_BUSY = DtpDmiStatus.BUSY
_WORD = 0xFFFF_FFFF


@dataclass
class _HeldAccess:
    """A bus access whose response a bridge's hold keeps from it."""

    target: str
    read: bool
    addr: int
    size: int
    offset: int
    data: int


class dtp_jtag2axi_isolation_test_seq(dtp_jtag2axi_base_test_seq):
    """The six bridge registers at their lengths, then each bridge left unchanged by scans
    of other instructions and accesses on the other bridges."""

    def __init__(
        self,
        name: str = "dtp_jtag2axi_isolation_test_seq",
        *,
        scenario_seed: int | None = None,
        random_count: int = 5,
    ) -> None:
        super().__init__(name, scenario_seed=scenario_seed, random_count=random_count)
        self._ledger_target: str | None = None

    def bus_ledger_target(self) -> str | None:
        return self._ledger_target

    def switch_ledger(self, target: str | None) -> None:
        """Account ``target``'s port from here on; on opening, every port holds the counts
        the last ledger closed with."""
        self.close_bus_ledger()
        self._ledger_target = target
        self.open_bus_ledger()

    async def body(self) -> None:
        self.log_banner("JTAG2AXI instruction decode and isolation between bridges")
        await self.enable_all_debug()
        await self.reset_tap()
        rng = self.rng("isolation")
        self.log_step(1, "Each bridge register at its length, with its own bridge's capture")
        await self.decode_step(rng)
        held = self.loop_index % 2 == 1
        victims = list(JTAG2AXI_TARGETS)
        rng.shuffle(victims)
        for victim in victims:
            self.log_step(2, "%s unchanged by other scans and accesses, held=%s", victim, held)
            await self.isolation_case(victim, rng, held=held)
        self.switch_ledger(None)
        self.log_summary("decode and isolation complete", held=held)

    # --- decode ----------------------------------------------------------------
    async def decode_step(self, rng: random.Random) -> None:
        """A seeded proper subset of the bridges takes the busy status and the others load
        distinct DMI cells; each of the six registers is then scanned past its length in a
        seeded order, and dmireset clears the busy statuses."""
        names = list(JTAG2AXI_TARGETS)
        busy = set(rng.sample(names, rng.randint(1, len(names) - 1)))
        cells: dict[str, tuple[int, int, DtpDmiStatus]] = {}
        for target in names:
            data = self.cell_data(target, rng, busy=target in busy)
            while any(data == other[1] for other in cells.values()):
                data = self.cell_data(target, rng, busy=target in busy)
            if target in busy:
                cells[target] = await self.take_busy_status(target, data)
            else:
                address = rng.getrandbits(7)
                await self.dmi_scan(target, address, data, DtpDmiOp.NOP, context=f"{target}.load")
                cells[target] = (address, data, _OK)
        registers = [(target, dtmcs) for target in names for dtmcs in (False, True)]
        rng.shuffle(registers)
        for target, dtmcs in registers:
            await self.decode_scan(target, dtmcs, cells[target], rng)
        for target in sorted(busy):
            await self.dtmcs_scan(target, DTMCS_DMIRESET, status=_BUSY, context=f"{target}.clear")

    def cell_data(self, target: str, rng: random.Random, *, busy: bool) -> int:
        """Seeded DMI cell data: for a bridge that takes the busy status, an sbaddress0 value
        within its address width."""
        data = rng.getrandbits(32)
        return self.masked_addr(target, data) & _WORD if busy else data

    async def take_busy_status(self, target: str, sbaddress0: int) -> tuple[int, int, DtpDmiStatus]:
        """A capture during an sbaddress0 read sets the busy status; the cells then hold the
        read's address and the ``sbaddress0`` written first."""
        ctx = f"{target}.busy"
        await self.dmi_write(target, DtpDmReg.SBCS, pack_sbcs(sbaccess=2), context=f"{ctx}.sbcs")
        await self.dmi_write(target, DtpDmReg.SBADDRESS0, sbaddress0, context=f"{ctx}.setup")
        await self.select_dmi(target)
        await self.dmi_raw(
            target, _SBADDRESS0, 0, DtpDmiOp.READ, status=_OK, chain=True, context=ctx
        )
        await self.dmi_raw(
            target, 0, 0, DtpDmiOp.NOP, status=_BUSY, expect=(_SBADDRESS0, 0), context=ctx
        )
        await self.run_test_idle()
        return _SBADDRESS0, sbaddress0, _BUSY

    async def decode_scan(
        self,
        target: str,
        dtmcs: bool,
        cell: tuple[int, int, DtpDmiStatus],
        rng: random.Random,
    ) -> None:
        """``CHK-J2A-DECODE`` on one scan of a bridge register a seeded 1 to 32 bits past its
        length: the low bits are the bridge's own capture, and TDO from the register length
        on is the TDI shifted in first. The last register-length bits shifted in leave the
        register unchanged.

        ``DTP_J2A_DECODE_NEGATIVE=1`` expects a register one bit longer, so the run must
        fail.
        """
        cfg = self.target_cfg(target)
        address, data, status = cell
        length = DTMCS_LEN if dtmcs else DMI_LEN
        extra = rng.randint(*EXTRA_BITS)
        tail = rng.randrange(1, 1 << extra)
        if dtmcs:
            payload, capture = 0, DTP_EXPECTED_DTMCS | (int(status) << _DTMCS_DMISTAT_LSB)
        else:
            payload, capture = (
                pack_dmi(address, data, DtpDmiOp.NOP),
                pack_dmi(address, data, status),
            )
        await self.load_ir(cfg.dtmcs_instr if dtmcs else cfg.dmi_instr)
        item = await self.shift_dr(tail | (payload << extra), length + extra)
        delay = int(OcahKnobs.is_set(DECODE_NEGATIVE_KNOB))
        self.record_fields(
            target,
            DECODE_CHECK_ID,
            [
                ("capture", item.result & OcahRng.bit_mask(length), capture),
                (
                    "passthrough",
                    (item.result >> length) & OcahRng.bit_mask(extra),
                    (tail << delay) & OcahRng.bit_mask(extra),
                ),
            ],
            context=f"{target}.{'dtmcs' if dtmcs else 'dmi'} length={length} extra={extra}",
        )

    # --- isolation -------------------------------------------------------------
    async def isolation_case(self, victim: str, rng: random.Random, *, held: bool) -> None:
        """``CHK-J2A-ISOLATION`` on ``victim`` across a seeded mix of scans and accesses on
        everything else, with a bus access held on it, and on one other bridge, when
        ``held``."""
        ctx = f"{victim}.isolation.{'held' if held else 'idle'}"
        holds: list[_HeldAccess] = []
        self.switch_ledger(victim)
        if held:
            holds.append(await self.start_held(victim, rng, ctx=f"{ctx}.start"))
        else:
            await self.port_access(
                victim, rng, read=bool(rng.getrandbits(1)), check_id=ISOLATION_CHECK_ID, ctx=ctx
            )
        before = await self.dm_state(victim, held=held, ctx=f"{ctx}.before")
        counts = self.port_counts(victim)
        last = await self.last_update(victim, rng, before, ctx=ctx)
        await self.disturb(victim, rng, holds, held=held, ctx=ctx)
        self.switch_ledger(victim)
        await self.run_test_idle()
        await self.check_victim(victim, last, before, counts, held=held, ctx=f"{ctx}.after")
        rng.shuffle(holds)
        for access in holds:
            self.switch_ledger(access.target)
            await self.release(access, ctx=f"{ctx}.release")
        self.switch_ledger(None)

    async def dm_state(self, target: str, *, held: bool, ctx: str) -> dict[str, int]:
        """sbcs and sbaddress, and sbdata0 without a held access."""
        state = {
            "sbcs": await self.dmi_read(target, DtpDmReg.SBCS, context=f"{ctx}.sbcs"),
            "sbaddress": await self.read_sbaddress(target, context=ctx),
        }
        if not held:
            state["sbdata0"] = await self.dmi_read(
                target, DtpDmReg.SBDATA0, context=f"{ctx}.sbdata0"
            )
        return state

    async def last_update(
        self, victim: str, rng: random.Random, before: dict[str, int], *, ctx: str
    ) -> tuple[int, int]:
        """The victim's last DMI update before the disturbance, ending in Run-Test/Idle with
        no idle cycles: a seeded op-0 load, or an sbaddress0 read. Returns the address and
        data its next capture shows."""
        await self.select_dmi(victim)
        if rng.getrandbits(1):
            address, data = rng.getrandbits(7), rng.getrandbits(32)
            await self.dmi_raw(
                victim, address, data, DtpDmiOp.NOP, status=_OK, context=f"{ctx}.load"
            )
            return address, data
        await self.dmi_raw(
            victim,
            _SBADDRESS0,
            rng.getrandbits(32),
            DtpDmiOp.READ,
            status=_OK,
            context=f"{ctx}.read",
        )
        return _SBADDRESS0, before["sbaddress"] & _WORD

    async def disturb(
        self, victim: str, rng: random.Random, holds: list[_HeldAccess], *, held: bool, ctx: str
    ) -> None:
        """One access on each other bridge and seeded scans of the other bridges and of
        non-bridge instructions, 4 to 8 in all, in a seeded order. With ``held`` one seeded
        other bridge's access is held."""
        others = [name for name in JTAG2AXI_TARGETS if name != victim]
        held_other = rng.choice(others) if held else None
        items: list[tuple[str, str | None]] = [("access", name) for name in others]
        for _ in range(rng.randint(*DISTURB_SCANS) - len(items)):
            kind = rng.choice(DISTURB_KINDS)
            items.append(
                (kind, rng.choice(others) if kind in ("dtmcs", "dmi_load", "dm_read") else None)
            )
        rng.shuffle(items)
        for i, (kind, target) in enumerate(items):
            step = f"{ctx}.{i}.{kind}"
            if kind == "access":
                self.switch_ledger(target)
                if target == held_other:
                    holds.append(await self.start_held(target, rng, ctx=step))
                else:
                    await self.port_access(
                        target,
                        rng,
                        read=bool(rng.getrandbits(1)),
                        check_id=ISOLATION_CHECK_ID,
                        ctx=step,
                    )
                self.switch_ledger(victim)
            else:
                await self.disturb_scan(kind, target, rng, ctx=step)

    async def disturb_scan(
        self, kind: str, target: str | None, rng: random.Random, *, ctx: str
    ) -> None:
        """One scan that leaves every DUT output as it is."""
        if kind in ("idcode", "bypass", "undefined"):
            instr = {
                "idcode": DtpJtagInstr.IDCODE,
                "bypass": rng.choice((DtpJtagInstr.BYPASS_00, DtpJtagInstr.BYPASS_3F)),
                "undefined": rng.choice(UNDEFINED_INSTRS),
            }[kind]
            width = rng.randint(*OTHER_SCAN_BITS)
            await self.load_ir(instr)
            await self.shift_dr(rng.getrandbits(width), width)
        elif kind == "dtmcs":
            await self.dtmcs_scan(
                target, DTMCS_DMIRESET * rng.getrandbits(1), status=_OK, context=ctx
            )
        elif kind == "dmi_load":
            await self.dmi_scan(
                target, rng.getrandbits(7), rng.getrandbits(32), DtpDmiOp.NOP, context=ctx
            )
        else:
            await self.dmi_read(
                target, rng.choice((DtpDmReg.DMCONTROL, DtpDmReg.SBCS)), context=ctx
            )

    async def start_held(self, target: str, rng: random.Random, *, ctx: str) -> _HeldAccess:
        """A seeded read or write whose response ``target``'s hold keeps from the bridge."""
        cfg = self.target_cfg(target)
        tb_if = self.cfg.tb_if
        read = bool(rng.getrandbits(1))
        addr, size, offset = self.seeded_access(target, rng)
        data = self.sized_word(rng, size, self.memory_word(target, addr, size))
        if read:
            lanes = self.data_mask(size) << (8 * offset)
            beat = (rng.getrandbits(cfg.data_width) & ~lanes) | (data << (8 * offset))
            await self.sba_write(
                target, addr - offset, beat, size=cfg.data_size, context=f"{ctx}.fill"
            )
        else:
            self.scoreboard_arm_strobes(target, self.full_wstrb(size) << offset, addr, context=ctx)
        held = tb_if.sample(f"{target}_{'r' if read else 'b'}_held")
        tb_if.hold_responses(target, b=not read, r=read)
        await self.sba_setup(target, addr, size, read=read, context=ctx)
        if not read:
            if size == 3:
                await self.dmi_write(target, DtpDmReg.SBDATA1, data >> 32, context=f"{ctx}.sbdata1")
            await self.dmi_write(target, DtpDmReg.SBDATA0, data & _WORD, context=f"{ctx}.sbdata0")
        reached = await self.wait_response_held(target, read=read, above=held)
        self.record_fields(target, ISOLATION_CHECK_ID, [("held", int(reached), 1)], context=ctx)
        return _HeldAccess(target, read, addr, size, offset, data)

    async def release(self, access: _HeldAccess, *, ctx: str) -> None:
        """Release a held access; it completes on its own port with its data."""
        target, read, size, offset = access.target, access.read, access.size, access.offset
        ctx = f"{ctx}.{target}"
        self.cfg.tb_if.hold_responses(target, b=False, r=False)
        await self.expect_bus_request(
            target,
            read=read,
            addr=access.addr,
            size=size,
            data=0 if read else access.data << (8 * offset),
            wstrb=0 if read else self.full_wstrb(size) << offset,
            context=ctx,
        )
        await self.wait_sba_idle(target, context=ctx)
        if read:
            rdata = await self.read_sbdata(target, size, ctx)
            self.check_bridge_rdata(target, rdata & self.data_mask(size), access.data, context=ctx)
        else:
            self.check_target_word(target, access.addr, access.data, size=size, context=ctx)

    async def check_victim(
        self,
        victim: str,
        last: tuple[int, int],
        before: dict[str, int],
        counts: tuple[int, int],
        *,
        held: bool,
        ctx: str,
    ) -> None:
        """``CHK-J2A-ISOLATION``: the victim's DMI capture returns its last update's address
        and data with status 0, dmistat reads 0, its port completed nothing more, and its
        Debug Module registers read as before. The scan that takes the capture loads the
        same address and data.

        ``DTP_J2A_ISOLATION_NEGATIVE=1`` expects the captured data inverted, so the run
        must fail.
        """
        address, data = last
        expected = data ^ _WORD if OcahKnobs.is_set(ISOLATION_NEGATIVE_KNOB) else data
        await self.select_dmi(victim)
        item = await self.shift_dr(pack_dmi(address, data, DtpDmiOp.NOP), DMI_LEN)
        cap_address, cap_data, cap_status = unpack_dmi(item.result)
        dtmcs = await self.read_tdr(self.target_cfg(victim).dtmcs_reg)
        writes, reads = self.port_counts(victim)
        after = await self.dm_state(victim, held=held, ctx=ctx)
        self.record_fields(
            victim,
            ISOLATION_CHECK_ID,
            [
                ("dmi_address", cap_address, address),
                ("dmi_data", cap_data, expected),
                ("dmi_status", cap_status, int(_OK)),
                ("dmistat", unpack_dtmcs(dtmcs)["dmistat"], int(_OK)),
                ("writes", writes, counts[0]),
                ("reads", reads, counts[1]),
                *[(name, after[name], value) for name, value in before.items()],
            ],
            context=ctx,
        )
