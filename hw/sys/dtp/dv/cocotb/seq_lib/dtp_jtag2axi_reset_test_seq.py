# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""JTAG2AXI TAP resets and the bridge reset on every bridge.

A TAP reset, by TRST, by five TMS-high cycles or by power-on reset, resets the
bridges' DTMCS and DMI TDR cells but not the bridges: the DMI capture after it
returns the last update's address and data with the sticky status, and the
Debug Module keeps dmactive and its System Bus Access registers. The bridge
reset, rst_n_i outside test mode and scan_rst_ni in it, returns every bridge
to its reset state and drops the access in flight; outside test mode its
release reaches clk_i and TCK each on the synchronizer's depth of that clock's
rising edges, and in test mode it follows scan_rst_ni. A pass runs these cases
in a seeded order:

* tap_idle: on each bridge, a TAP reset from each source after an access;
* tap_open: on each bridge, a TAP reset from each source while the port holds
  an access, by READY or by a held response; the access completes on the
  port;
* tap_sticky: on each bridge, a TAP reset from each source with the sticky
  busy status set, which survives it until a dmireset clears it;
* bridge_access: on each bridge, the bridge reset in each phase of a read and
  of a write: started and not at the port, the request or the write data held
  by READY, a read's address just accepted with the response owed, once
  released on the pulse's own clk_i edge and once held for scans, the
  response held, and completed on the port before a scan fetches the result;
* scan_in_reset: on each bridge, DMI and DTMCS scans while the bridge reset
  is asserted, and the TCK side's release once TCK runs again;
* unreleased_hold: on each bridge, a read and a write whose response stays
  held, sbbusy reading 1 past the poll bound until the bridge reset drops the
  access;
* test_mode: test_en set, in which every bridge reaches its port, keeps its
  state through an rst_n_i pulse and resets on a scan_rst_ni pulse.

Every reset is asserted and released at a seeded time between two clk_i
edges, and released while TCK is stopped, except the read-armed reset: it
asserts on the clk_i edge that completes the read's address handshake and,
unless the sequence holds it, releases on a clk_i edge with TCK running.
"""

from __future__ import annotations

import random
from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager

import cocotb
from cocotb.triggers import FallingEdge, RisingEdge, Timer
from env.dtp_types import (
    DTP_J2A_RESET_SYNC_TCK,
    JTAG2AXI_TARGETS,
    DtpDmiOp,
    DtpDmiStatus,
    DtpDmReg,
    pack_dmi,
    pack_sbcs,
    unpack_dmi,
    unpack_dtmcs,
)
from ocah_axi_vip import OcahAxiDelays
from ocah_lib import OcahKnobs

from .dtp_jtag2axi_base_test_seq import (
    BUSY_POLLS,
    DTMCS_DMIRESET,
    PORT_COMPLETION_CYCLES,
    dtp_jtag2axi_base_test_seq,
)

TAP_RESET_CHECK_ID = "CHK-J2A-TAP-RESET"
BRIDGE_RESET_CHECK_ID = "CHK-J2A-BRIDGE-RESET"
RESET_RELEASE_CHECK_ID = "CHK-J2A-RESET-RELEASE"
TAP_RESET_NEGATIVE_KNOB = "DTP_J2A_TAP_RESET_NEGATIVE"
BRIDGE_RESET_NEGATIVE_KNOB = "DTP_J2A_BRIDGE_RESET_NEGATIVE"
RESET_RELEASE_NEGATIVE_KNOB = "DTP_J2A_RESET_RELEASE_NEGATIVE"
CASES = (
    "tap_idle",
    "tap_open",
    "tap_sticky",
    "bridge_access",
    "scan_in_reset",
    "unreleased_hold",
    "test_mode",
)
TAP_SOURCES = ("tlr", "trst", "por")
# The phases of a read and of a write the bridge reset lands in.
READ_PHASES = ("launched", "request", "armed", "armed_held", "response", "done")
WRITE_PHASES = ("launched", "request", "w", "response", "done")
# READY low for longer than any held access lasts; the case releases it.
READY_HOLD_CYCLES = 1 << 20
# Most clk_i cycles a reset stays asserted, and that the bridge reset lands
# past the cycle its phase begins in.
RESET_HOLD_MAX = 8
PHASE_DELAY_MAX = 4
# Most clk_i cycles TCK stays stopped, past twice the synchronizer depth,
# after a release.
TCK_STOPPED_MAX = 16
ALL_BRIDGES = (1 << len(JTAG2AXI_TARGETS)) - 1
_WORD = 0xFFFF_FFFF
_SBCS_RESET = pack_sbcs(sbaccess=2)


class dtp_jtag2axi_reset_test_seq(dtp_jtag2axi_base_test_seq):
    """TAP resets with each bridge idle, holding an access and holding a sticky status; the
    bridge reset in each phase of an access, during scans and in test mode; in a seeded
    order."""

    def __init__(
        self,
        name: str = "dtp_jtag2axi_reset_test_seq",
        *,
        scenario_seed: int | None = None,
        random_count: int = 5,
    ) -> None:
        super().__init__(name, scenario_seed=scenario_seed, random_count=random_count)
        self._ledger_target: str | None = None
        self._release_errors = 0

    def bus_ledger_target(self) -> str | None:
        return self._ledger_target

    async def body(self) -> None:
        self.log_banner("TAP resets and the bridge reset on every bridge")
        await self.enable_all_debug()
        await self.reset_tap()
        self._release_errors = self.cfg.tb_if.sample("j2a_release_err_count")
        rng = self.rng("reset")
        cases = list(CASES)
        rng.shuffle(cases)
        for case in cases:
            await getattr(self, f"{case}_case")(rng)
        self.log_summary("TAP and bridge resets complete", order=" ".join(cases))

    # --- cases ---------------------------------------------------------------
    async def tap_idle_case(self, rng: random.Random) -> None:
        """On each bridge, a TAP reset from each source in a seeded order after a seeded access
        and a NOP scan of a seeded address and data. The DMI capture then returns that address
        and data with status 0, dmistat reads 0, dmactive and the System Bus Access registers
        keep their values, and the next access reaches the port without a dmactive write."""
        for target in self.shuffled(JTAG2AXI_TARGETS, rng):
            for source in self.shuffled(TAP_SOURCES, rng):
                ctx = f"{target}.tap_idle.{source}"
                with self.ledgered(target):
                    await self.activate_dm(target)
                    await self.seeded_port_access(target, rng, TAP_RESET_CHECK_ID, f"{ctx}.access")
                    before = await self.bridge_state(target, ctx=f"{ctx}.before")
                    peek = (rng.getrandbits(7), rng.getrandbits(32))
                    await self.dmi_scan(target, *peek, DtpDmiOp.NOP, context=f"{ctx}.peek")
                    await self.tap_reset(source, rng)
                    after = await self.bridge_state(target, peek=peek, ctx=f"{ctx}.after")
                    expected = {**before, **self.tap_capture(peek, DtpDmiStatus.SUCCESS)}
                    self.check_bridge_state(target, TAP_RESET_CHECK_ID, after, expected, ctx=ctx)
                    await self.seeded_port_access(target, rng, TAP_RESET_CHECK_ID, f"{ctx}.next")

    async def tap_open_case(self, rng: random.Random) -> None:
        """On each bridge, a TAP reset from each source in a seeded order while the port holds a
        seeded read or write, by READY low or by a held response; power-on reset holds by READY,
        since it clears the response holds. The access completes on the port with its data, and
        the DMI capture after the reset returns the update that started it."""
        for target in self.shuffled(JTAG2AXI_TARGETS, rng):
            for source in self.shuffled(TAP_SOURCES, rng):
                read = bool(rng.getrandbits(1))
                stall = source == "por" or bool(rng.getrandbits(1))
                how = "ready" if stall else "response"
                ctx = f"{target}.tap_open.{source}.{how}.{'read' if read else 'write'}"
                with self.ledgered(target):
                    await self.activate_dm(target)
                    await self.open_access_reset(
                        target, rng, read=read, stall=stall, source=source, ctx=ctx
                    )

    async def tap_sticky_case(self, rng: random.Random) -> None:
        """On each bridge, a TAP reset from each source in a seeded order with the sticky busy
        status set. The DMI capture keeps its address, data and status 3 through the reset,
        dmistat reads 3, a dmireset clears the status, and the next access reaches the port."""
        for target in self.shuffled(JTAG2AXI_TARGETS, rng):
            for source in self.shuffled(TAP_SOURCES, rng):
                ctx = f"{target}.tap_sticky.{source}"
                with self.ledgered(target):
                    await self.activate_dm(target)
                    await self.raise_sticky_busy(target, ctx=ctx)
                    held = await self.dmi_capture(target, (0, 0), ctx=f"{ctx}.before")
                    await self.tap_reset(source, rng)
                    after = await self.dmi_capture(target, (0, 0), ctx=f"{ctx}.after")
                    dmistat = await self.read_dmistat(target, DTMCS_DMIRESET, ctx=ctx)
                    cleared = await self.dmi_capture(target, held[:2], ctx=f"{ctx}.cleared")
                    expected = self.tap_capture(held[:2], DtpDmiStatus.BUSY)
                    fields = [
                        (name, after[i], value) for i, (name, value) in enumerate(expected.items())
                    ]
                    fields += [
                        ("dmistat", dmistat, int(DtpDmiStatus.BUSY)),
                        ("cleared_status", cleared[2], int(DtpDmiStatus.SUCCESS)),
                    ]
                    self.record_fields(target, TAP_RESET_CHECK_ID, fields, context=ctx)
                    await self.seeded_port_access(target, rng, TAP_RESET_CHECK_ID, f"{ctx}.next")

    async def bridge_access_case(self, rng: random.Random) -> None:
        """On each bridge, the bridge reset in each phase of a read and of a write, in a seeded
        order."""
        for target in self.shuffled(JTAG2AXI_TARGETS, rng):
            subcases = [(True, phase) for phase in READ_PHASES]
            subcases += [(False, phase) for phase in WRITE_PHASES]
            rng.shuffle(subcases)
            for read, phase in subcases:
                ctx = f"{target}.bridge_access.{'read' if read else 'write'}.{phase}"
                with self.ledgered(target):
                    await self.reset_access(target, rng, read=read, phase=phase, ctx=ctx)

    async def scan_in_reset_case(self, rng: random.Random) -> None:
        """On each bridge, scans while the bridge reset is asserted: DTMCS with dmireset reads
        dmistat 0, and DMI writes of dmactive and of a seeded sbaddress0 capture 0. None of
        them takes effect: after the release the bridge reads its reset state. TCK stays
        stopped for a seeded number of clk_i cycles after the release, in which the clk_i side
        leaves reset and the TCK side does not."""
        for target in self.shuffled(JTAG2AXI_TARGETS, rng):
            ctx = f"{target}.scan_in_reset"
            with self.ledgered(target):
                await self.activate_dm(target)
                await self.write_sbaddress0(target, rng, ctx=ctx)
                before = self.reset_counts()
                await self.drive_reset("sys_rst_n", 0, rng)
                await self.scan_in_reset(target, rng, ctx=ctx)
                await self.release_and_check(target, rng, before, ctx=ctx)
                await self.recover(target, rng, ctx=ctx)

    async def unreleased_hold_case(self, rng: random.Random) -> None:
        """On each bridge, a full-beat read and write in a seeded order, each with its response
        held: sbcs reads sbbusy 1 past the poll bound, the bridge reset lands while the response
        is held, and the hold is cleared while the reset is asserted. After the release the
        bridge reads its reset state, the held response never reached it, and the next access
        reaches the port."""
        for target in self.shuffled(JTAG2AXI_TARGETS, rng):
            for read in rng.sample((False, True), 2):
                ctx = f"{target}.unreleased_hold.{'read' if read else 'write'}"
                with self.ledgered(target):
                    await self.unreleased_hold(target, rng, read=read, ctx=ctx)

    async def test_mode_case(self, rng: random.Random) -> None:
        """With test_en 1: every bridge reaches its port; an rst_n_i pulse with the bridges idle
        leaves the synchronized resets high and each bridge's dmactive, sbaddress0 and sticky
        status in place; a scan_rst_ni pulse resets every bridge, its synchronized resets
        following it with no clock edge. With test_en back at 0 and dmactive set again, every
        bridge reaches its port."""
        targets = self.shuffled(JTAG2AXI_TARGETS, rng)
        await self.set_test_mode(1)
        kept: dict[str, tuple[int, tuple[int, int, int]]] = {}
        for target in targets:
            ctx = f"{target}.test_mode"
            with self.ledgered(target):
                await self.activate_dm(target)
                await self.seeded_port_access(target, rng, BRIDGE_RESET_CHECK_ID, f"{ctx}.access")
                sbaddress = await self.write_sbaddress0(target, rng, ctx=ctx)
                await self.raise_sticky_busy(target, ctx=ctx)
                kept[target] = (sbaddress, await self.dmi_capture(target, (0, 0), ctx=ctx))
        await self.pulse_in_test_mode("sys_rst_n", targets[0], rng)
        for target in targets:
            ctx = f"{target}.test_mode.rst_n"
            sbaddress, capture = kept[target]
            with self.ledgered(target):
                after = await self.dmi_capture(target, (0, 0), ctx=ctx)
                dmistat = await self.read_dmistat(target, DTMCS_DMIRESET, ctx=ctx)
                dmcontrol = await self.dmi_read(
                    target, DtpDmReg.DMCONTROL, context=f"{ctx}.dmcontrol"
                )
                observed = await self.dmi_read(
                    target, DtpDmReg.SBADDRESS0, context=f"{ctx}.sbaddress0"
                )
                fields = [
                    ("capture", pack_dmi(*after), pack_dmi(*capture)),
                    ("dmistat", dmistat, int(DtpDmiStatus.BUSY)),
                    ("dmactive", dmcontrol & 0x1, self.kept_dmactive(1)),
                    ("sbaddress0", observed, sbaddress),
                ]
                self.record_fields(target, BRIDGE_RESET_CHECK_ID, fields, context=ctx)
                await self.seeded_port_access(target, rng, BRIDGE_RESET_CHECK_ID, f"{ctx}.access")
        await self.pulse_in_test_mode("scan_rst_n", targets[0], rng)
        for target in targets:
            ctx = f"{target}.test_mode.scan_rst"
            with self.ledgered(target):
                state = await self.bridge_state(target, ctx=ctx)
                self.check_bridge_state(
                    target, BRIDGE_RESET_CHECK_ID, state, self.reset_state(), ctx=ctx
                )
        await self.set_test_mode(0)
        for target in targets:
            with self.ledgered(target):
                await self.recover(target, rng, ctx=f"{target}.test_mode.exit")

    # --- TAP resets ------------------------------------------------------------
    async def tap_reset(self, source: str, rng: random.Random) -> None:
        """Reset the TAP from ``source``: five TMS-high cycles to Test-Logic-Reset, TRST changed
        with TCK stopped and held over a seeded number of TCK cycles, or power-on reset followed
        by the settle of the debug-disable synchronizers it set."""
        if source == "tlr":
            for _ in range(5):
                await self.tms_step(1)
        elif source == "trst":
            await self.assert_trst(cycles=rng.randint(1, 4))
            await self.deassert_trst()
        else:
            await self.pulse_por(cycles=rng.randint(1, 4))
            await self.wait_dbg_disable_sync()

    @staticmethod
    def tap_capture(peek: tuple[int, int], status: DtpDmiStatus) -> dict[str, int]:
        """The DMI capture a TAP reset leaves: ``peek``'s address and data with ``status``.

        ``DTP_J2A_TAP_RESET_NEGATIVE=1`` expects the capture the bridge reset leaves, 0, so
        the run must fail.
        """
        if OcahKnobs.is_set(TAP_RESET_NEGATIVE_KNOB):
            return {"capture_address": 0, "capture_data": 0, "capture_status": 0}
        return {"capture_address": peek[0], "capture_data": peek[1], "capture_status": int(status)}

    async def open_access_reset(
        self, target: str, rng: random.Random, *, read: bool, stall: bool, source: str, ctx: str
    ) -> None:
        """A full-beat read or write held at the port across a TAP reset from ``source``. A
        read's slot holds a word written first."""
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
        self.hold_port(target, read=read, request=stall)
        if read:
            await self.sba_setup(target, addr, size, read=True, context=ctx)
            update = (int(DtpDmReg.SBADDRESS0), self.masked_addr(target, addr) & _WORD)
        else:
            self.scoreboard_arm_strobes(target, self.full_wstrb(size), addr, context=ctx)
            await self.sba_setup(target, addr, size, read=False, context=ctx)
            if size == 3:
                await self.dmi_write(target, DtpDmReg.SBDATA1, data >> 32, context=f"{ctx}.sbdata1")
            await self.dmi_write(target, DtpDmReg.SBDATA0, data & _WORD, context=f"{ctx}.sbdata0")
            update = (int(DtpDmReg.SBDATA0), data & _WORD)
        open_at_reset = self.port_counts(target) == before and tb_if.sample(valid) > valid_before
        await self.tap_reset(source, rng)
        captured = await self.dmi_capture(target, update, ctx=f"{ctx}.after")
        open_at_reset &= self.port_counts(target) == before
        self.release_port(target)
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
        expected = self.tap_capture(update, DtpDmiStatus.SUCCESS)
        fields = [(name, captured[i], value) for i, (name, value) in enumerate(expected.items())]
        fields += [
            ("open_at_reset", int(open_at_reset), 1),
            ("port_transactions", self.port_counts(target)[int(read)] - before[int(read)], 1),
        ]
        if read:
            fields.append(("rdata", await self.read_sbdata(target, size, ctx), data))
        else:
            fields.append(("memory", self.memory_word(target, addr, size), data))
        self.record_fields(target, TAP_RESET_CHECK_ID, fields, context=ctx)

    async def raise_sticky_busy(self, target: str, *, ctx: str) -> None:
        """Set the sticky busy status: a dmcontrol write of dmactive 1 whose scan chains into a
        scan that captures while the write is in progress."""
        await self.select_dmi(target)
        await self.dmi_raw(
            target,
            int(DtpDmReg.DMCONTROL),
            0x1,
            DtpDmiOp.WRITE,
            status=DtpDmiStatus.SUCCESS,
            chain=True,
            context=f"{ctx}.sticky",
        )
        await self.dmi_zero_shift()
        await self.run_test_idle()

    # --- the bridge reset --------------------------------------------------------
    async def reset_access(
        self, target: str, rng: random.Random, *, read: bool, phase: str, ctx: str
    ) -> None:
        """A full-beat read or write with the bridge reset asserted in ``phase`` and released
        with TCK stopped. Before dmactive is written again the bridge reads its reset state, and
        the port completes the access only when the reset found it completed. A read's slot
        holds a word written first."""
        cfg = self.target_cfg(target)
        size = cfg.data_size
        addr = self.random_target_addr(target, rng)
        data = self.random_distinct_word(rng, target, self.memory_word(target, addr, size))
        masked = self.masked_addr(target, addr)
        await self.activate_dm(target)
        if read:
            await self.sba_write(target, addr, data, size=size, context=f"{ctx}.fill")
            start = (DtpDmReg.SBADDRESS0, masked & _WORD)
        else:
            start = (DtpDmReg.SBDATA0, data & _WORD)
        if phase in ("request", "w"):
            self.hold_port(target, read=read, request=True, w_only=phase == "w")
        elif phase == "response":
            self.hold_port(target, read=read, request=False)
        await self.dmi_write(
            target,
            DtpDmReg.SBCS,
            pack_sbcs(sbreadonaddr=int(read), sbaccess=size),
            context=f"{ctx}.sbcs",
        )
        if cfg.addr_width > 32:
            await self.dmi_write(
                target, DtpDmReg.SBADDRESS1, masked >> 32, context=f"{ctx}.sbaddress1"
            )
        if not read:
            await self.dmi_write(
                target, DtpDmReg.SBADDRESS0, masked & _WORD, context=f"{ctx}.sbaddress0"
            )
            if size == 3:
                await self.dmi_write(target, DtpDmReg.SBDATA1, data >> 32, context=f"{ctx}.sbdata1")
        completed = int(phase == "done")
        if completed and not read:
            self.scoreboard_arm_strobes(target, self.full_wstrb(size), addr, context=ctx)
        before = self.port_counts(target)
        counts = self.reset_counts()
        if completed:
            await self.dmi_write(target, *start, context=f"{ctx}.start")
            began = await self.wait_port_completion(target, read=read, above=before[int(read)])
            await self.wait_cycles(rng.randint(0, PHASE_DELAY_MAX))
            await self.drive_reset("sys_rst_n", 0, rng)
        elif phase in ("armed", "armed_held"):
            began = await self.armed_start(
                target, rng, start, counts, held=phase == "armed_held", ctx=ctx
            )
        else:
            trigger = cocotb.start_soon(self.reset_in_phase(target, rng, read=read, phase=phase))
            await self.dmi_write(target, *start, context=f"{ctx}.start")
            began = await trigger
        self.release_port(target)
        moved = self.port_counts(target)[int(read)] - before[int(read)]
        if phase == "armed":
            await self.check_released(target, rng, counts, tck_stopped=False, ctx=ctx)
        else:
            await self.release_and_check(target, rng, counts, ctx=ctx)
        if completed:
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
        fields = [
            ("phase_reached", int(began), 1),
            ("port_transactions", moved, completed),
            ("response_valid_cycles", self.response_valid_cycles(target, read=read), 0),
        ]
        self.record_fields(target, BRIDGE_RESET_CHECK_ID, fields, context=f"{ctx} port")
        await self.recover(target, rng, ctx=ctx)

    async def armed_start(
        self,
        target: str,
        rng: random.Random,
        start: tuple[DtpDmReg, int],
        counts: tuple[int, int],
        *,
        held: bool,
        ctx: str,
    ) -> bool:
        """Start a read with rst_n_i armed to assert for a seeded number of clk_i cycles from
        the edge that completes its AR handshake, so the reset lands while the responder owes
        the R; returns whether it asserted. With ``held`` the sequence holds the reset from a
        seeded time before the pulse's first clk_i edge and scans the bridge in it."""
        tb_if = self.cfg.tb_if
        period_ps = round(self.cfg.sys_clk_period_ns * 1000)
        hold = None
        tb_if.arm_reset_on_read(target, cycles=rng.randint(1, RESET_HOLD_MAX))
        if held:
            hold = cocotb.start_soon(self.hold_armed_reset(rng.randint(1, period_ps - 1)))
        await self.dmi_write(target, *start, context=f"{ctx}.start")
        for _ in range(PORT_COMPLETION_CYCLES):
            if self.reset_counts()[0] > counts[0] and (held or tb_if.sample("rst_n")):
                break
            await self.wait_sys_cycles(1)
        tb_if.disarm_reset_on_read()
        began = self.reset_counts()[0] > counts[0]
        if hold is not None:
            if began:
                await hold
                await self.scan_in_reset(target, rng, ctx=ctx)
            else:
                hold.cancel()
        return began

    async def hold_armed_reset(self, delay_ps: int) -> None:
        """Drive sys_rst_n low ``delay_ps`` after rst_n_i next falls."""
        tb_if = self.cfg.tb_if
        await FallingEdge(tb_if.rst_n)
        await Timer(delay_ps, unit="ps")
        tb_if.handle("sys_rst_n").value = 0

    async def scan_in_reset(self, target: str, rng: random.Random, *, ctx: str) -> None:
        """Scans while the bridge reset is asserted: DTMCS with dmireset reads dmistat 0, and DMI
        writes of dmactive and of a seeded sbaddress0 capture 0."""
        cfg = self.target_cfg(target)
        dmistat = await self.read_dmistat(target, DTMCS_DMIRESET, ctx=f"{ctx} in_reset")
        fields = [("dmistat", dmistat, 0)]
        for address, data in (
            (DtpDmReg.DMCONTROL, 0x1),
            (DtpDmReg.SBADDRESS0, self.random_target_addr(target, rng) & _WORD),
        ):
            captured = await self.read_tdr(
                cfg.dmi_reg, pack_dmi(int(address), data, DtpDmiOp.WRITE)
            )
            fields.append((f"{address.name.lower()}_capture", captured, 0))
        self.record_fields(target, BRIDGE_RESET_CHECK_ID, fields, context=f"{ctx} in_reset")

    async def unreleased_hold(
        self, target: str, rng: random.Random, *, read: bool, ctx: str
    ) -> None:
        """A full-beat read or write whose response stays held through ``BUSY_POLLS`` sbcs
        polls and the bridge reset. A read's slot holds a word written first."""
        cfg = self.target_cfg(target)
        tb_if = self.cfg.tb_if
        size = cfg.data_size
        addr = self.random_target_addr(target, rng)
        data = self.random_distinct_word(rng, target, self.memory_word(target, addr, size))
        await self.activate_dm(target)
        if read:
            await self.sba_write(target, addr, data, size=size, context=f"{ctx}.fill")
        held = tb_if.sample(f"{target}_{'r' if read else 'b'}_held")
        before = self.port_counts(target)
        self.hold_port(target, read=read, request=False)
        await self.sba_setup(target, addr, size, read=read, context=ctx)
        if not read:
            if size == 3:
                await self.dmi_write(target, DtpDmReg.SBDATA1, data >> 32, context=f"{ctx}.sbdata1")
            await self.dmi_write(target, DtpDmReg.SBDATA0, data & _WORD, context=f"{ctx}.sbdata0")
        reached = await self.wait_response_held(target, read=read, above=held)
        await self.poll_while_held(target, rng.randint(*BUSY_POLLS), context=f"{ctx}.held")
        counts = self.reset_counts()
        await self.drive_reset("sys_rst_n", 0, rng)
        self.release_port(target)
        moved = self.port_counts(target)[int(read)] - before[int(read)]
        await self.release_and_check(target, rng, counts, ctx=ctx)
        self.expect_no_bus_request(target, context=ctx)
        fields = [
            ("held", int(reached), 1),
            ("port_transactions", moved, 0),
            ("response_valid_cycles", self.response_valid_cycles(target, read=read), 0),
        ]
        self.record_fields(target, BRIDGE_RESET_CHECK_ID, fields, context=f"{ctx} port")
        await self.recover(target, rng, ctx=ctx)

    async def reset_in_phase(
        self, target: str, rng: random.Random, *, read: bool, phase: str
    ) -> bool:
        """Assert the bridge reset in ``phase`` of the access the next Update-DR starts; returns
        whether the access was in that phase. A launched access has raised no request at the
        port; the other phases begin on a rise of ``phase_marker``, which the reset follows by
        a seeded number of clk_i cycles."""
        marker = self.phase_marker(target, read=read, phase=phase)
        start = marker()
        await self.wait_update_dr_exit()
        if phase == "launched":
            await self.drive_reset("sys_rst_n", 0, rng)
            return marker() == start
        for _ in range(PORT_COMPLETION_CYCLES):
            if marker() > start:
                break
            await self.wait_sys_cycles(1)
        began = marker() > start
        await self.wait_cycles(rng.randint(0, PHASE_DELAY_MAX))
        await self.drive_reset("sys_rst_n", 0, rng)
        return began

    def phase_marker(self, target: str, *, read: bool, phase: str) -> Callable[[], int]:
        """A counter of ``target``'s port that rises when ``phase`` begins: the request VALID
        cycles, the write-data stall cycles or the held responses."""
        prefix = self.target_cfg(target).activity_prefix
        name = {
            "launched": f"{prefix}_{'ar' if read else 'aw'}valid_count",
            "request": f"{prefix}_{'ar' if read else 'aw'}valid_count",
            "w": f"{prefix}_w_stall_count",
            "response": f"{target}_{'r' if read else 'b'}_held",
        }[phase]
        return lambda: self.cfg.tb_if.sample(name)

    async def release_and_check(
        self, target: str, rng: random.Random, before: tuple[int, int], *, ctx: str
    ) -> None:
        """Release the bridge reset asserted since the counts ``before``, after a seeded hold,
        and judge both releases and the state the bridge then reads."""
        await self.wait_sys_cycles(rng.randint(1, RESET_HOLD_MAX))
        await self.drive_reset("sys_rst_n", 1, rng)
        await self.check_released(target, rng, before, tck_stopped=True, ctx=ctx)

    async def check_released(
        self,
        target: str,
        rng: random.Random,
        before: tuple[int, int],
        *,
        tck_stopped: bool,
        ctx: str,
    ) -> None:
        """Judge the release of the bridge reset asserted since the counts ``before`` after a
        seeded number of clk_i cycles: with ``tck_stopped`` since the release, the clk_i side
        has left reset and the TCK side has not; once scans run TCK both have, and the bridge
        reads its reset state."""
        stopped = rng.randint(
            2 * DTP_J2A_RESET_SYNC_TCK + 1, 2 * DTP_J2A_RESET_SYNC_TCK + TCK_STOPPED_MAX
        )
        await self.wait_sys_cycles(stopped)
        self.check_reset_counted(
            "j2a_rst_assert_count", before[1], self.reset_counts()[1], f"{ctx} bridge_reset"
        )
        if tck_stopped:
            self.record_fields(
                target,
                RESET_RELEASE_CHECK_ID,
                self.release_fields(tck_released=False, test_mode=False),
                context=f"{ctx} tck_stopped={stopped}",
            )
        state = await self.bridge_state(target, ctx=f"{ctx}.reset_state")
        self.record_fields(
            target,
            RESET_RELEASE_CHECK_ID,
            self.release_fields(tck_released=True, test_mode=False),
            context=f"{ctx} tck_running",
        )
        self.check_bridge_state(target, BRIDGE_RESET_CHECK_ID, state, self.reset_state(), ctx=ctx)

    async def pulse_in_test_mode(self, member: str, target: str, rng: random.Random) -> None:
        """Pulse the dtp_tb_if reset ``member`` in test mode with the bridges idle. An rst_n_i
        pulse leaves the synchronized resets high and counts no bridge reset; a scan_rst_ni
        pulse holds them low while it lasts and releases them after no clock edge."""
        tb_if = self.cfg.tb_if
        scan = member == "scan_rst_n"
        before = self.reset_counts()
        await self.drive_reset(member, 0, rng)
        await self.wait_sys_cycles(rng.randint(1, RESET_HOLD_MAX))
        held = (tb_if.sample("j2a_arst_clk_n"), tb_if.sample("j2a_arst_tck_n"))
        await self.drive_reset(member, 1, rng)
        await self.wait_sys_cycles(2)
        after = self.reset_counts()
        counter = ("sys_rst_assert_count", "j2a_rst_assert_count")[int(scan)]
        self.check_reset_counted(
            counter, before[int(scan)], after[int(scan)], f"test_mode.{member}"
        )
        expected = 0 if scan else ALL_BRIDGES
        fields = [("arst_clk_n_held", held[0], expected), ("arst_tck_n_held", held[1], expected)]
        if scan:
            fields += self.release_fields(tck_released=True, test_mode=True)
        else:
            fields += [
                ("bridge_resets", after[1] - before[1], 0),
                ("errors", tb_if.sample("j2a_release_err_count") - self._release_errors, 0),
            ]
        self.record_fields(target, RESET_RELEASE_CHECK_ID, fields, context=f"test_mode.{member}")

    def release_fields(self, *, tck_released: bool, test_mode: bool) -> list[tuple[str, int, int]]:
        """Every bridge's synchronized resets released on clk_i, and on TCK once
        ``tck_released``, each after the synchronizer's depth of its clock's rising edges
        outside test mode and after none in it, with no change that breaks a reset rule.

        ``DTP_J2A_RESET_RELEASE_NEGATIVE=1`` expects one edge fewer outside test mode, so the
        run must fail.
        """
        tb_if = self.cfg.tb_if
        edges = 0 if test_mode else DTP_J2A_RESET_SYNC_TCK
        if edges and OcahKnobs.is_set(RESET_RELEASE_NEGATIVE_KNOB):
            edges -= 1
        fields = [
            ("arst_clk_n", tb_if.sample("j2a_arst_clk_n"), ALL_BRIDGES),
            ("arst_tck_n", tb_if.sample("j2a_arst_tck_n"), ALL_BRIDGES if tck_released else 0),
            ("errors", tb_if.sample("j2a_release_err_count") - self._release_errors, 0),
        ]
        clk_edges = tb_if.sample("j2a_clk_release_edges")
        tck_edges = tb_if.sample("j2a_tck_release_edges")
        for name, cfg in JTAG2AXI_TARGETS.items():
            shift = 8 * cfg.reset_arm_bit
            fields.append((f"{name}.clk_edges", (clk_edges >> shift) & 0xFF, edges))
            if tck_released:
                fields.append((f"{name}.tck_edges", (tck_edges >> shift) & 0xFF, edges))
        return fields

    def reset_state(self) -> dict[str, int]:
        """The state every bridge reads after the bridge reset.

        ``DTP_J2A_BRIDGE_RESET_NEGATIVE=1`` expects dmactive to survive it, so the run must
        fail.
        """
        return {
            "capture_address": 0,
            "capture_data": 0,
            "capture_status": 0,
            "dmistat": 0,
            "dmactive": self.kept_dmactive(0),
            "sbcs": _SBCS_RESET,
            "sbaddress": 0,
            "sbdata": 0,
        }

    @staticmethod
    def kept_dmactive(expected: int) -> int:
        """``expected`` dmactive, inverted by ``DTP_J2A_BRIDGE_RESET_NEGATIVE=1``."""
        return expected ^ int(OcahKnobs.is_set(BRIDGE_RESET_NEGATIVE_KNOB))

    async def recover(self, target: str, rng: random.Random, *, ctx: str) -> None:
        """Set dmactive again; a read of a word a full-beat write put there first then reaches
        the port."""
        await self.activate_dm(target)
        await self.port_access(
            target, rng, read=True, check_id=BRIDGE_RESET_CHECK_ID, ctx=f"{ctx}.recover"
        )

    async def set_test_mode(self, value: int) -> None:
        """Drive test_en, with scan_rst_n and rst_n both 1."""
        self.cfg.tb_if.handle("test_en").value = value
        await self.wait_sys_cycles(2)

    # --- building blocks -------------------------------------------------------
    @staticmethod
    def shuffled(items: Iterable[str], rng: random.Random) -> list[str]:
        order = list(items)
        rng.shuffle(order)
        return order

    @contextmanager
    def ledgered(self, target: str) -> Iterator[None]:
        """Account ``target``'s port for the operations inside; the other ports keep their
        counts."""
        self._ledger_target = target
        self.open_bus_ledger()
        yield
        self.close_bus_ledger()
        self._ledger_target = None

    async def seeded_port_access(
        self, target: str, rng: random.Random, check_id: str, ctx: str
    ) -> None:
        """A seeded read or write that reaches the port."""
        await self.port_access(
            target, rng, read=bool(rng.getrandbits(1)), check_id=check_id, ctx=ctx
        )

    async def write_sbaddress0(self, target: str, rng: random.Random, *, ctx: str) -> int:
        """Write a seeded sbaddress0 after an sbcs write that clears sbreadonaddr, so no read
        starts; returns the value written."""
        sbaddress = self.random_target_addr(target, rng) & _WORD
        await self.dmi_write(
            target,
            DtpDmReg.SBCS,
            pack_sbcs(sbaccess=self.target_cfg(target).data_size),
            context=f"{ctx}.sbcs",
        )
        await self.dmi_write(target, DtpDmReg.SBADDRESS0, sbaddress, context=f"{ctx}.sbaddress0")
        return sbaddress

    def response_valid_cycles(self, target: str, *, read: bool) -> int:
        """Cycles ``target`` has seen RVALID, or BVALID without ``read``, since rst_n_i last
        released."""
        prefix = self.target_cfg(target).activity_prefix
        return self.cfg.tb_if.sample(f"{prefix}_{'r' if read else 'b'}valid_count")

    def reset_counts(self) -> tuple[int, int]:
        """(rst_n_i assertions, bridge reset assertions)."""
        tb_if = self.cfg.tb_if
        return tb_if.sample("sys_rst_assert_count"), tb_if.sample("j2a_rst_assert_count")

    async def drive_reset(self, member: str, value: int, rng: random.Random) -> None:
        """Drive the dtp_tb_if reset ``member`` at a seeded time between two clk_i edges."""
        period_ps = round(self.cfg.sys_clk_period_ns * 1000)
        await RisingEdge(self.cfg.tb_if.clk)
        await Timer(rng.randint(1, period_ps - 1), unit="ps")
        self.cfg.tb_if.handle(member).value = value

    async def wait_cycles(self, cycles: int) -> None:
        """``wait_sys_cycles`` that also takes 0."""
        if cycles:
            await self.wait_sys_cycles(cycles)

    def hold_port(self, target: str, *, read: bool, request: bool, w_only: bool = False) -> None:
        """Hold ``target``'s next access at the port: with ``request`` by READY low on every
        request channel, or on W alone with ``w_only``; otherwise by holding its response."""
        if request:
            hold = OcahAxiDelays(
                0, long_percent=100, long_min=READY_HOLD_CYCLES, long_max=READY_HOLD_CYCLES
            )
            none = OcahAxiDelays(0)
            self.apply_responder_timing(
                target, aw=none if w_only else hold, w=hold, ar=hold, b=none, r=none
            )
        else:
            self.cfg.tb_if.hold_responses(target, b=not read, r=read)

    def release_port(self, target: str) -> None:
        """Return ``target``'s responder to READY high and release its response holds."""
        self.clear_responder_timing(target)
        self.cfg.tb_if.hold_responses(target, b=False, r=False)

    async def dmi_capture(
        self, target: str, peek: tuple[int, int], *, ctx: str
    ) -> tuple[int, int, int]:
        """The (address, data, status) a DMI NOP scan carrying ``peek`` captures; the scan
        loads what it captures when that is ``peek`` or the status is not 0."""
        cfg = self.target_cfg(target)
        captured = await self.read_tdr(cfg.dmi_reg, pack_dmi(peek[0], peek[1], DtpDmiOp.NOP))
        self.log.debug("%s dmi_capture=0x%x", ctx, captured)
        return unpack_dmi(captured)

    async def read_dmistat(self, target: str, shift_value: int = 0, *, ctx: str) -> int:
        """DTMCS dmistat, from a scan that shifts ``shift_value``; ``CHK-J2A-DTM-CAPTURE``
        judges the other fields, which no reset changes."""
        captured = await self.read_tdr(self.target_cfg(target).dtmcs_reg, shift_value)
        self.check_dtmcs_fields(target, captured, context=ctx)
        return unpack_dtmcs(captured)["dmistat"]

    async def bridge_state(
        self, target: str, *, ctx: str, peek: tuple[int, int] = (0, 0)
    ) -> dict[str, int]:
        """The bridge as JTAG reads it: the DMI capture, then DTMCS dmistat, and with the
        captured status 0 dmactive, sbcs, sbaddress and sbdata. An sbcs read with dmactive 1
        also takes CHK-J2A-GEOMETRY."""
        cfg = self.target_cfg(target)
        address, data, status = await self.dmi_capture(target, peek, ctx=ctx)
        state = {
            "capture_address": address,
            "capture_data": data,
            "capture_status": status,
            "dmistat": await self.read_dmistat(target, ctx=ctx),
        }
        if status == DtpDmiStatus.SUCCESS:
            dmcontrol = await self.dmi_read(target, DtpDmReg.DMCONTROL, context=f"{ctx}.dmcontrol")
            state["dmactive"] = dmcontrol & 0x1
            state["sbcs"] = await self.dmi_read(target, DtpDmReg.SBCS, context=f"{ctx}.sbcs")
            if state["dmactive"]:
                self.check_sbcs_geometry(target, state["sbcs"], context=f"{ctx}.sbcs")
            state["sbaddress"] = await self.read_sbaddress(target, context=ctx)
            state["sbdata"] = await self.read_sbdata(target, cfg.data_size, ctx)
        return state

    def check_bridge_state(
        self,
        target: str,
        check_id: str,
        observed: dict[str, int],
        expected: dict[str, int],
        *,
        ctx: str,
    ) -> None:
        """``check_id`` on every field of ``expected``; a field ``observed`` lacks reads -1."""
        fields = [(name, observed.get(name, -1), value) for name, value in expected.items()]
        self.record_fields(target, check_id, fields, context=ctx)
