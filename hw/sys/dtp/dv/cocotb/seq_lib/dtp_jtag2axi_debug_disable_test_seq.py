# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""JTAG2AXI debug disables and the security demultiplexer on every bridge.

While a bridge's disable is 1 its demultiplexer sends each access to the
error slave: the access ends with sberror 2, a read returns 0xBADCAB1E in each
32 bits, sbaddress keeps the failing address under sbautoincrement, and no
request reaches the port. The bridge's DTMCS, DMI and Debug Module registers
stay live, and alignment and size errors report 3 and 4 as when enabled. A
pass runs these cases in a seeded order:

* matrix: the eight combinations of the three disables, each bridge making one
  access per combination, judged on its own port and on the other two;
* live: the registers of a disabled bridge;
* held: a disable set while the port holds an access, first with READY low
  and then with the response held; the access completes on the port and the
  next one on the error slave;
* race: a disable changed some clk_i cycles after the Update-DR that starts an
  access, in both directions, the delays closing in on the cycle the access
  takes its path in; the access completes on exactly one path, consistently
  on the port, in sberror and in the data;
* reset: a system reset under a seeded mix of disables and one under its
  complement; each bridge's first access takes the path its disable selects.
"""

from __future__ import annotations

import math
import random

import cocotb
from env.dtp_types import JTAG2AXI_TARGETS, DtpDmiStatus, DtpDmReg, pack_sbcs, unpack_sbcs
from ocah_axi_vip import OcahAxiDelays
from ocah_lib import OcahKnobs

from .dtp_jtag2axi_base_test_seq import dtp_jtag2axi_base_test_seq

DBG_DISABLE_CHECK_ID = "CHK-J2A-DBG-DISABLE"
DBG_SWITCH_CHECK_ID = "CHK-J2A-DBG-SWITCH"
DBG_DISABLE_NEGATIVE_KNOB = "DTP_J2A_DBG_DISABLE_NEGATIVE"
DBG_SWITCH_NEGATIVE_KNOB = "DTP_J2A_DBG_SWITCH_NEGATIVE"
ERR_SLAVE_WORD = 0xBADC_AB1E
SBERROR_BUS = 2
SBERROR_ALIGN = 3
SBERROR_SIZE = 4
CASES = ("matrix", "live", "held", "race", "reset")
# READY low for longer than any held case lasts; the case releases it.
READY_HOLD_CYCLES = 1 << 20
# Races per bridge and direction, and the clk_i cycles past two TCK periods
# after Update-DR that bound the first race window, and past the window that a
# race drawn while the access is open lands in.
RACES = 6
RACE_SPREAD = 16


class dtp_jtag2axi_debug_disable_test_seq(dtp_jtag2axi_base_test_seq):
    """The disable matrix, live registers, held and raced disable changes and the reset
    default on every bridge, in a seeded order."""

    def __init__(
        self,
        name: str = "dtp_jtag2axi_debug_disable_test_seq",
        *,
        scenario_seed: int | None = None,
        random_count: int = 5,
    ) -> None:
        super().__init__(name, scenario_seed=scenario_seed, random_count=random_count)
        self._ledger_target: str | None = None

    def bus_ledger_target(self) -> str | None:
        return self._ledger_target

    async def body(self) -> None:
        self.log_banner("Debug disables and the security demultiplexer on every bridge")
        await self.enable_all_debug()
        await self.reset_tap()
        rng = self.rng("debug_disable")
        cases = list(CASES)
        rng.shuffle(cases)
        for case in cases:
            await getattr(self, f"{case}_case")(rng)
            await self.enable_all_debug()
        self.log_summary("Debug disables complete", order=" ".join(cases))

    # --- cases ---------------------------------------------------------------
    async def matrix_case(self, rng: random.Random) -> None:
        """Each combination of the three disables in a seeded order, with one seeded access
        per bridge. Each bridge reads and writes twice on each path over the combinations."""
        targets = list(JTAG2AXI_TARGETS)
        combos = list(range(1 << len(targets)))
        rng.shuffle(combos)
        ops: dict[str, dict[int, bool]] = {}
        for index, target in enumerate(targets):
            ops[target] = {}
            for disabled in (False, True):
                cells = [combo for combo in combos if bool((combo >> index) & 1) == disabled]
                reads = [False, True] * (len(cells) // 2)
                rng.shuffle(reads)
                ops[target].update(zip(cells, reads, strict=True))
        for combo in combos:
            disables = {t: (combo >> i) & 1 for i, t in enumerate(targets)}
            await self.set_bridge_disables(disables)
            order = list(targets)
            rng.shuffle(order)
            for target in order:
                ctx = f"{target}.matrix{combo:03b}"
                await self.ledgered_access(
                    target, rng, read=ops[target][combo], disabled=bool(disables[target]), ctx=ctx
                )

    async def live_case(self, rng: random.Random) -> None:
        """With one bridge disabled at a time, its DTMCS, dmcontrol, sbcs, sbaddress and
        sbdata1 stay readable and writable, and an alignment and a size error report 3
        and 4 with no request."""
        targets = list(JTAG2AXI_TARGETS)
        rng.shuffle(targets)
        for target in targets:
            await self.set_bridge_disables({t: int(t == target) for t in JTAG2AXI_TARGETS})
            self._ledger_target = target
            self.open_bus_ledger()
            await self.live_registers(target, rng, ctx=f"{target}.live")
            self.close_bus_ledger()
            self._ledger_target = None

    async def held_case(self, rng: random.Random) -> None:
        """On each bridge the disable is set while the port holds an access, once with READY
        low and once with the response held, a seeded one of them a read."""
        targets = list(JTAG2AXI_TARGETS)
        rng.shuffle(targets)
        for target in targets:
            stall_read = bool(rng.getrandbits(1))
            for stall, read in ((True, stall_read), (False, not stall_read)):
                await self.set_bridge_disables({t: 0 for t in JTAG2AXI_TARGETS})
                self._ledger_target = target
                self.open_bus_ledger()
                await self.held_switch(target, rng, stall=stall, read=read)
                self.close_bus_ledger()
                self._ledger_target = None

    async def race_case(self, rng: random.Random) -> None:
        """On each bridge, ``RACES`` accesses in each direction whose disable changes a number
        of clk_i cycles after the Update-DR that starts them. The delays close in on the cycle
        in which the access takes its path: two races in three bisect the window between the
        latest delay that took the new path and the earliest that took the old one, and the
        third draws a seeded delay just past that window, while the access is open."""
        targets = list(JTAG2AXI_TARGETS)
        rng.shuffle(targets)
        tck = math.ceil(self.cfg.jtag_period_ns / self.cfg.sys_clk_period_ns)
        for target in targets:
            early, late = 0, 2 * tck + RACE_SPREAD
            directions = [False, True]
            rng.shuffle(directions)
            for to_disabled in directions:
                reads = [False, True] * (RACES // 2)
                rng.shuffle(reads)
                for index, read in enumerate(reads):
                    if index % 3 == 2:
                        delay = rng.randint(late, late + RACE_SPREAD)
                    else:
                        delay = (early + late + 1) // 2
                    self._ledger_target = target
                    self.open_bus_ledger()
                    direction = "disable" if to_disabled else "enable"
                    on_port = await self.race_access(
                        target,
                        rng,
                        read=read,
                        to_disabled=to_disabled,
                        delay=delay,
                        ctx=f"{target}.race.{direction}{index}",
                    )
                    self.close_bus_ledger()
                    self._ledger_target = None
                    if on_port != to_disabled:
                        early = max(early, delay)
                        late = max(late, early + 1)
                    else:
                        late = min(late, delay)
                        early = max(0, min(early, late - 1))

    async def reset_case(self, rng: random.Random) -> None:
        """A system reset under a seeded mix of disables, at least one 0 and one 1, then one
        under its complement: after each, each bridge's first access takes the path its
        disable selects, and with every disable cleared each reaches its port."""
        targets = list(JTAG2AXI_TARGETS)
        while True:
            mix = {t: rng.getrandbits(1) for t in targets}
            if 0 < sum(mix.values()) < len(targets):
                break
        for label, disables in (("mix", mix), ("complement", {t: 1 - v for t, v in mix.items()})):
            await self.set_bridge_disables(disables)
            await self.pulse_system_reset(context=f"debug_disable.reset.{label}")
            for target in targets:
                await self.activate_dm(target)
            for phase, setting in (("held", disables), ("cleared", {t: 0 for t in targets})):
                await self.set_bridge_disables(setting)
                order = list(targets)
                rng.shuffle(order)
                for target in order:
                    await self.ledgered_access(
                        target,
                        rng,
                        read=bool(rng.getrandbits(1)),
                        disabled=bool(setting[target]),
                        ctx=f"{target}.reset.{label}.{phase}",
                    )

    # --- building blocks -----------------------------------------------------
    async def set_bridge_disables(self, disables: dict[str, int]) -> None:
        """Drive the three bridge disables and wait for the synchronizers."""
        await self.set_dbg_disable(
            **{self.target_cfg(t).dbg_disable_bit: value for t, value in disables.items()}
        )

    async def ledgered_access(
        self, target: str, rng: random.Random, *, read: bool, disabled: bool, ctx: str
    ) -> None:
        """One seeded access under a ledger of ``target``'s port; the other ports keep their
        counts."""
        self._ledger_target = target
        self.open_bus_ledger()
        if disabled:
            await self.disabled_access(target, rng, read=read, ctx=ctx)
        else:
            await self.port_access(target, rng, read=read, check_id=DBG_DISABLE_CHECK_ID, ctx=ctx)
        self.close_bus_ledger()
        self._ledger_target = None

    def err_slave_beat(self, target: str) -> int:
        """The error slave's read beat: ``0xBADCAB1E`` in each 32 bits."""
        words = self.target_cfg(target).data_width // 32
        return sum(ERR_SLAVE_WORD << (32 * w) for w in range(words))

    async def disabled_access(
        self, target: str, rng: random.Random, *, read: bool, ctx: str
    ) -> None:
        """A seeded access, under a seeded sbautoincrement, that ends on the error slave:
        sberror 2, the error slave's data on a read, the responder word unchanged on a write,
        sbaddress at the failing address, and no request on the port."""
        addr, size, offset = self.seeded_access(target, rng)
        autoincrement = bool(rng.getrandbits(1))
        before = self.port_counts(target)
        word = self.memory_word(target, addr, size)
        await self.sba_setup(
            target, addr, size, read=read, context=ctx, autoincrement=autoincrement
        )
        if not read:
            data = self.sized_word(rng, size, word)
            if size == 3:
                await self.dmi_write(target, DtpDmReg.SBDATA1, data >> 32, context=f"{ctx}.sbdata1")
            await self.dmi_write(
                target, DtpDmReg.SBDATA0, data & 0xFFFF_FFFF, context=f"{ctx}.sbdata0"
            )
        await self.wait_sba_idle(target, context=ctx, sberror=SBERROR_BUS)
        self.expect_no_bus_request(target, context=ctx)
        fields: list[tuple[str, int, int]] = [
            ("port_transactions", sum(self.port_counts(target)) - sum(before), 0),
            (
                "sbaddress",
                await self.read_sbaddress(target, context=ctx),
                self.masked_addr(target, addr),
            ),
        ]
        if read:
            expected = (self.err_slave_beat(target) >> (8 * offset)) & self.sbdata_mask(size)
            if OcahKnobs.is_set(DBG_DISABLE_NEGATIVE_KNOB):
                expected ^= 0x1
            fields.append(("rdata", await self.read_sbdata(target, size, ctx), expected))
        else:
            fields.append(("memory", self.memory_word(target, addr, size), word))
        self.record_fields(target, DBG_DISABLE_CHECK_ID, fields, context=f"{ctx} disabled")
        await self.clear_sberror(target, size, ctx=ctx)

    async def live_registers(self, target: str, rng: random.Random, *, ctx: str) -> None:
        """The registers of a disabled bridge."""
        cfg = self.target_cfg(target)
        await self.dtmcs_scan(target, 0, status=DtpDmiStatus.SUCCESS, context=f"{ctx}.dtmcs")
        await self.dmi_write(target, DtpDmReg.DMCONTROL, 0x1, context=f"{ctx}.dmcontrol")
        dmcontrol = await self.dmi_read(target, DtpDmReg.DMCONTROL, context=f"{ctx}.dmcontrol")
        size = rng.randint(0, cfg.data_size)
        autoincrement = rng.getrandbits(1)
        await self.dmi_write(
            target,
            DtpDmReg.SBCS,
            pack_sbcs(sbaccess=size, sbautoincrement=autoincrement),
            context=f"{ctx}.sbcs",
        )
        sbcs = await self.dmi_read(target, DtpDmReg.SBCS, context=f"{ctx}.sbcs")
        self.check_sbcs_geometry(target, sbcs, context=f"{ctx}.sbcs")
        addr = self.masked_addr(target, rng.getrandbits(cfg.addr_width))
        if cfg.addr_width > 32:
            await self.dmi_write(
                target, DtpDmReg.SBADDRESS1, addr >> 32, context=f"{ctx}.sbaddress1"
            )
        await self.dmi_write(
            target, DtpDmReg.SBADDRESS0, addr & 0xFFFF_FFFF, context=f"{ctx}.sbaddress0"
        )
        fields = [
            ("dmcontrol", dmcontrol & 0x3, 0x1),
            ("sbaccess", unpack_sbcs(sbcs)["sbaccess"], size),
            ("sbautoincrement", unpack_sbcs(sbcs)["sbautoincrement"], autoincrement),
            ("sbaddress", await self.read_sbaddress(target, context=ctx), addr),
        ]
        if cfg.data_width > 32:
            sbdata1 = rng.getrandbits(32)
            await self.dmi_write(target, DtpDmReg.SBDATA1, sbdata1, context=f"{ctx}.sbdata1")
            read_back = await self.dmi_read(target, DtpDmReg.SBDATA1, context=f"{ctx}.sbdata1")
            fields.append(("sbdata1", read_back, sbdata1))
        self.record_fields(target, DBG_DISABLE_CHECK_ID, fields, context=f"{ctx} registers")
        refusals = [
            (SBERROR_ALIGN, rng.randint(1, cfg.data_size)),
            (SBERROR_SIZE, cfg.data_size + 1),
        ]
        for sberror, size in refusals:
            sub = f"{ctx}.sberror{sberror}"
            # Aligned to the access size for a size error: the alignment error takes precedence.
            addr = self.random_target_addr(target, rng) & ~((1 << size) - 1)
            if sberror == SBERROR_ALIGN:
                addr |= 1
            await self.sba_setup(target, addr, size, read=False, context=sub)
            await self.dmi_write(
                target, DtpDmReg.SBDATA0, rng.getrandbits(32), context=f"{sub}.sbdata0"
            )
            await self.wait_sba_idle(target, context=sub, sberror=sberror)
            self.expect_no_bus_request(target, context=sub)
            await self.clear_sberror(target, size, ctx=sub)

    async def held_switch(
        self, target: str, rng: random.Random, *, stall: bool, read: bool
    ) -> None:
        """Set the disable while the port holds an access: with ``stall`` READY stays low,
        otherwise the response is held. The access completes on the port, a read returning the
        word a write put there first, and the next access ends on the error slave."""
        how = "ready" if stall else "response"
        ctx = f"{target}.held.{how}.{'read' if read else 'write'}"
        cfg = self.target_cfg(target)
        tb_if = self.cfg.tb_if
        size = cfg.data_size
        addr = self.random_target_addr(target, rng)
        data = self.random_distinct_word(rng, target, self.memory_word(target, addr, size))
        if read:
            await self.sba_write(target, addr, data, size=size, context=f"{ctx}.fill")
        valid = f"{cfg.activity_prefix}_{'ar' if read else 'aw'}valid_count"
        valid_before = tb_if.sample(valid)
        before = self.port_counts(target)
        if stall:
            hold = OcahAxiDelays(
                0, long_percent=100, long_min=READY_HOLD_CYCLES, long_max=READY_HOLD_CYCLES
            )
            none = OcahAxiDelays(0)
            self.apply_responder_timing(target, aw=hold, w=hold, ar=hold, b=none, r=none)
        else:
            tb_if.hold_responses(target, b=not read, r=read)
        if read:
            await self.sba_setup(target, addr, size, read=True, context=ctx)
        else:
            self.scoreboard_arm_strobes(target, self.full_wstrb(size), addr, context=ctx)
            await self.sba_setup(target, addr, size, read=False, context=ctx)
            if size == 3:
                await self.dmi_write(target, DtpDmReg.SBDATA1, data >> 32, context=f"{ctx}.sbdata1")
            await self.dmi_write(
                target, DtpDmReg.SBDATA0, data & 0xFFFF_FFFF, context=f"{ctx}.sbdata0"
            )
        open_at_switch = self.port_counts(target) == before and tb_if.sample(valid) > valid_before
        await self.set_dbg_disable(**{cfg.dbg_disable_bit: 1})
        open_after_sync = self.port_counts(target) == before
        sbcs = unpack_sbcs(await self.dmi_read(target, DtpDmReg.SBCS, context=f"{ctx}.held_sbcs"))
        if stall:
            self.clear_responder_timing(target)
        else:
            tb_if.hold_responses(target, b=False, r=False)
        await self.expect_bus_request(
            target,
            read=read,
            addr=addr,
            size=size,
            data=0 if read else data,
            wstrb=0 if read else self.full_wstrb(size),
            context=ctx,
        )
        await self.wait_sba_idle(target, context=f"{ctx}.released")
        after = self.port_counts(target)
        expected_port = 0 if OcahKnobs.is_set(DBG_SWITCH_NEGATIVE_KNOB) else 1
        fields = [
            ("open_at_switch", int(open_at_switch and open_after_sync), 1),
            ("sbbusy_while_held", sbcs["sbbusy"], 1),
            ("port_transactions", after[int(read)] - before[int(read)], expected_port),
        ]
        if read:
            fields.append(("rdata", await self.read_sbdata(target, size, ctx), data))
        else:
            fields.append(("memory", self.memory_word(target, addr, size), data))
        self.record_fields(target, DBG_SWITCH_CHECK_ID, fields, context=f"{ctx} switch")
        await self.disabled_access(target, rng, read=not read, ctx=f"{ctx}.next")

    async def race_access(
        self,
        target: str,
        rng: random.Random,
        *,
        read: bool,
        to_disabled: bool,
        delay: int,
        ctx: str,
    ) -> bool:
        """An access whose disable flips to ``to_disabled`` ``delay`` clk_i cycles after the
        PTAP leaves the Update-DR that starts it. It completes on exactly one path: on the port
        with sberror 0 and the responder's data, or on the error slave with sberror 2 and its
        data. A read's slot holds a word written first. Returns whether the port took it."""
        cfg = self.target_cfg(target)
        tb_if = self.cfg.tb_if
        size = cfg.data_size
        addr = self.random_target_addr(target, rng)
        word = self.memory_word(target, addr, size)
        if read:
            await self.set_bridge_disables({t: 0 for t in JTAG2AXI_TARGETS})
            word = self.random_distinct_word(rng, target, word)
            await self.sba_write(target, addr, word, size=size, context=f"{ctx}.fill")
        data = self.random_distinct_word(rng, target, word)
        await self.set_bridge_disables(
            {t: int(t == target and not to_disabled) for t in JTAG2AXI_TARGETS}
        )
        before = self.port_counts(target)
        await self.dmi_write(
            target,
            DtpDmReg.SBCS,
            pack_sbcs(sbreadonaddr=int(read), sbaccess=size),
            context=f"{ctx}.sbcs",
        )
        if cfg.addr_width > 32:
            await self.dmi_write(
                target, DtpDmReg.SBADDRESS1, addr >> 32, context=f"{ctx}.sbaddress1"
            )
        if not read:
            await self.dmi_write(
                target, DtpDmReg.SBADDRESS0, addr & 0xFFFF_FFFF, context=f"{ctx}.sbaddress0"
            )
            if size == 3:
                await self.dmi_write(target, DtpDmReg.SBDATA1, data >> 32, context=f"{ctx}.sbdata1")
        tb_if.set_dis_race(target, True)
        flip = cocotb.start_soon(self.flip_after_update(target, delay))
        if read:
            await self.dmi_write(
                target, DtpDmReg.SBADDRESS0, addr & 0xFFFF_FFFF, context=f"{ctx}.sbaddress0"
            )
        else:
            await self.dmi_write(
                target, DtpDmReg.SBDATA0, data & 0xFFFF_FFFF, context=f"{ctx}.sbdata0"
            )
        await flip
        tb_if.set_dis_race(target, False)
        moved = self.port_counts(target)[int(read)] - before[int(read)]
        on_port = moved == 1
        self.log.info(
            "%s delay=%d cycles path=%s", ctx, delay, "port" if on_port else "error_slave"
        )
        await self.wait_sba_idle(target, context=ctx, sberror=0 if on_port else SBERROR_BUS)
        if on_port:
            await self.expect_bus_request(
                target,
                read=read,
                addr=addr,
                size=size,
                data=0 if read else data,
                wstrb=0 if read else self.full_wstrb(size),
                context=ctx,
            )
        else:
            self.expect_no_bus_request(target, context=ctx)
        fields = [("port_transactions", int(moved in (0, 1)), 1)]
        if read:
            fields.append(
                (
                    "rdata",
                    await self.read_sbdata(target, size, ctx),
                    word if on_port else self.err_slave_beat(target),
                )
            )
        else:
            fields.append(
                ("memory", self.memory_word(target, addr, size), data if on_port else word)
            )
        self.record_fields(target, DBG_SWITCH_CHECK_ID, fields, context=f"{ctx} race")
        if not on_port:
            await self.clear_sberror(target, size, ctx=ctx)
        return on_port

    async def flip_after_update(self, target: str, delay: int) -> None:
        """Toggle ``target``'s disable ``delay`` clk_i cycles after the PTAP next leaves
        Update-DR."""
        tb_if = self.cfg.tb_if
        await self.wait_update_dr_exit()
        await self.wait_sys_cycles(delay)
        field = self.target_cfg(target).dbg_disable_bit
        tb_if.set_dbg_disable({field: 1 - tb_if.dbg_field(field)})

    async def clear_sberror(self, target: str, size: int, *, ctx: str) -> None:
        """Clear sberror, keeping sbaccess ``size``, and require sbcs idle with no error."""
        await self.dmi_write(
            target, DtpDmReg.SBCS, pack_sbcs(sberror=0x7, sbaccess=size), context=f"{ctx}.clear"
        )
        await self.wait_sba_idle(target, context=f"{ctx}.cleared")
