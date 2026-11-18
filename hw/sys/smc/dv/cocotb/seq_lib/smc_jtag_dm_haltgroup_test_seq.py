# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""CPU Debug Module halt group 1 through the dmcs2 DMI register.

Spec sources: hw/sys/smc/doc/cpu.adoc (Debug Module Configuration: the dmcs2 halt-group
paragraph and the DMI register inventory table), RISC-V External Debug Support 1.0
section 3.14.11 (dmcs2 layout).
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles
from cocotb.utils import get_sim_time

from .smc_cpu_vip_utils import (
    CPU_CTRL_RESET_CTRL,
    CPU_RESET_CTRL_DEBUG_RELEASE,
    cpu_ctrl_u32,
)
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_jtag_protocol_vip import SmcJtagTap

DEBUG_RESET_N = cpu_ctrl_u32("CPU_CTRL__RESET_CTRL__DEBUG_RESET_N_N0_SCAN_bm")

NUM_HARTS = 4
DMI_DMCONTROL = 0x10
DMI_DMSTATUS = 0x11
DMI_ABSTRACTCS = 0x16
DMI_DMCS2 = 0x32
DMI_HALTSUM0 = 0x40

DMCONTROL_DMACTIVE = 1 << 0
DMCONTROL_HARTSELLO_SHIFT = 16
DMCONTROL_RESUMEREQ = 1 << 30
DMCONTROL_HALTREQ = 1 << 31

DMSTATUS_ANYHALTED = 1 << 8
DMSTATUS_ALLHALTED = 1 << 9
DMSTATUS_ANYRUNNING = 1 << 10
DMSTATUS_ALLRUNNING = 1 << 11
DMSTATUS_ALLRESUMEACK = 1 << 17

ABSTRACTCS_BUSY = 1 << 12

DMCS2_HGSELECT = 1 << 0
DMCS2_HGWRITE = 1 << 1
DMCS2_GROUP_SHIFT = 2
DMCS2_GROUP_MASK = 0x1F
HALT_GROUP_1 = 1

GROUP_HARTS = (0, 1)
TRIGGER_HART = 0
FOLLOWER_HART = 1
OUTSIDE_HART = 3
HGSELECT_HART = TRIGGER_HART
HALTSUM_MASK = (1 << NUM_HARTS) - 1

STEPS = tuple(f"S{i}" for i in range(1, 7))
CHK_AFTER_STEP = (
    ("CHK-DM-HALTGROUP1-MEMBERSHIP", "S2"),
    ("CHK-DM-HALTGROUP1-PROPAGATES", "S3"),
    ("CHK-DM-HGSELECT-IGNORED", "S4"),
)
FENCE_TERMS = {
    "S1": "RELEASED_ACTIVE",
    "S2": "GROUP_1_MEMBERSHIP",
    "S3": "GROUP_1_PROPAGATION",
    "S4": "HGSELECT_IGNORED",
    "S5": "GROUP_CLEARED",
    "S6": "RESUMED",
}
_POLL_BOUND = 16
VIP_FILE = "seq_lib/smc_jtag_protocol_vip.py"
VIP_DMI_BUSY_RETRIES = 4


def _dmcontrol(hartsel: int, *flags: int) -> int:
    word = DMCONTROL_DMACTIVE | (hartsel << DMCONTROL_HARTSELLO_SHIFT)
    for flag in flags:
        word |= flag
    return word


def _group(dmcs2: int) -> int:
    return (dmcs2 >> DMCS2_GROUP_SHIFT) & DMCS2_GROUP_MASK


class smc_jtag_dm_haltgroup_test_seq(SmcCsrSeq):
    """Put harts 0 and 1 into halt group 1, halt hart 0 and read hart 1, then write dmcs2 with
    hgselect set for hart 2."""

    def __init__(self, name: str = "smc_jtag_dm_haltgroup_test_seq") -> None:
        super().__init__(name)
        self.dm_ok: bool = False
        self.group_trace: list[int] = []
        self._tap: SmcJtagTap | None = None
        self._abits: int = 7
        self._idle: int = 5
        self._events: list[tuple[str, str, int]] = []
        self._last_dmi = 0
        self._last_dmstatus = 0
        self._polls: dict[str, int] = {}

    async def _dmi_read(self, addr: int) -> int:
        assert self._tap is not None
        value = await self._tap.dmi_read(addr, abits=self._abits, idle=self._idle)
        self._last_dmi = value
        if addr == DMI_DMSTATUS:
            self._last_dmstatus = value
        return value

    async def _dmi_write(self, addr: int, data: int) -> None:
        assert self._tap is not None
        await self._tap.dmi_write(addr, data, abits=self._abits, idle=self._idle)

    def _step_done(self, step: str) -> None:
        self._events.append(("step", step, int(get_sim_time("ps"))))

    def _chk(self, cid: str, text: str) -> None:
        cocotb.log.info("%s: %s", cid, text)
        self._events.append(("chk", cid, int(get_sim_time("ps"))))

    def _assert_fence(self) -> None:
        steps = [e for e in self._events if e[0] == "step"]
        assert [e[1] for e in steps] == list(STEPS), f"step order {[e[1] for e in steps]}"
        stamps = [e[2] for e in steps]
        assert all(b > a for a, b in zip(stamps, stamps[1:])), f"stamps not increasing {stamps}"
        chks = [e for e in self._events if e[0] == "chk"]
        assert [c[1] for c in chks] == [c for c, _ in CHK_AFTER_STEP], (
            f"checker order {[c[1] for c in chks]}"
        )
        index = {e: i for i, e in enumerate(self._events)}
        for chk, (cid, step) in zip(chks, CHK_AFTER_STEP):
            step_event = steps[STEPS.index(step)]
            assert index[chk] > index[step_event], f"{cid} printed before {step} completed"
            assert chk[2] >= step_event[2], f"{cid} printed before the {step} stamp"
        cocotb.log.info(
            "CHK-NONVAC: ordered fence %s; checker lines %s; stamps %s",
            " < ".join(FENCE_TERMS[e[1]] for e in steps),
            ", ".join(c[1] for c in chks),
            ",".join(str(s) for s in stamps),
        )

    def _state(self) -> str:
        return f"last dmstatus=0x{self._last_dmstatus:08X} last DMI response=0x{self._last_dmi:08X}"

    async def _poll(self, label: str, addr: int, done) -> int:
        """Read addr until done(value) holds; raise after _POLL_BOUND reads."""
        for n in range(1, _POLL_BOUND + 1):
            value = await self._dmi_read(addr)
            if done(value):
                self._polls[label] = n
                return value
        raise AssertionError(
            f"{label}: not satisfied after {_POLL_BOUND} DMI reads of 0x{addr:02X}; {self._state()}"
        )

    async def _hart_status(self, hartsel: int) -> int:
        await self._dmi_write(DMI_DMCONTROL, _dmcontrol(hartsel))
        return await self._dmi_read(DMI_DMSTATUS)

    async def _dmcs2_write(self, hartsel: int, word: int) -> int:
        """Select hartsel, write dmcs2, return the dmcs2 readback for that hart."""
        await self._dmi_write(DMI_DMCONTROL, _dmcontrol(hartsel))
        await self._dmi_write(DMI_DMCS2, word)
        value = await self._dmi_read(DMI_DMCS2)
        self.group_trace.append(value)
        return value

    @staticmethod
    def _halted(word: int) -> bool:
        return bool(word & DMSTATUS_ALLHALTED) and not word & DMSTATUS_ANYRUNNING

    @staticmethod
    def _running(word: int) -> bool:
        return bool(word & DMSTATUS_ALLRUNNING) and not word & DMSTATUS_ANYHALTED

    async def body(self) -> None:
        clk = cocotb.top.clk_smc_i
        await self.csr_write(
            "CPU_CTRL_DEBUG_RESET_RELEASE",
            CPU_CTRL_RESET_CTRL,
            CPU_RESET_CTRL_DEBUG_RELEASE,
            length=8,
        )
        await ClockCycles(clk, 64)
        reset_ctrl = await self.csr_read("CPU_CTRL_RESET_CTRL_RB", CPU_CTRL_RESET_CTRL, length=8)
        assert reset_ctrl & DEBUG_RESET_N, (
            f"debug_reset_n not set in RESET_CTRL (got 0x{reset_ctrl:X})"
        )
        self._tap = SmcJtagTap(name="smc_jtag_dm_haltgroup")
        self._tap.init_signals()
        await self._tap.reset_tap()
        await self._tap.read_idcode(check=True)
        await self._tap.read_dmstatus()
        dtmcs = await self._tap.read_dtmcs()
        self._abits = ((dtmcs >> 4) & 0x3F) or 7
        self._idle = max((dtmcs >> 12) & 0x7, 5)
        await self._poll("activate_idle", DMI_ABSTRACTCS, lambda v: not v & ABSTRACTCS_BUSY)
        status0 = [await self._hart_status(h) for h in range(NUM_HARTS)]
        haltsum0 = await self._dmi_read(DMI_HALTSUM0)
        self._step_done("S1")
        assert all(self._running(w) for w in status0) and haltsum0 & HALTSUM_MASK == 0, (
            f"not every hart runs before the test: dmstatus {[f'0x{w:08X}' for w in status0]} "
            f"haltsum0=0x{haltsum0:08X}"
        )

        await self._dmi_write(DMI_DMCONTROL, _dmcontrol(TRIGGER_HART))
        dmcs2_reset = await self._dmi_read(DMI_DMCS2)
        join = DMCS2_HGWRITE | (HALT_GROUP_1 << DMCS2_GROUP_SHIFT)
        joined = {h: await self._dmcs2_write(h, join) for h in GROUP_HARTS}
        await self._dmi_write(DMI_DMCONTROL, _dmcontrol(OUTSIDE_HART))
        outside = await self._dmi_read(DMI_DMCS2)
        self._step_done("S2")
        groups = {h: _group(v) for h, v in joined.items()}
        text = (
            f"dmcs2 reset 0x{dmcs2_reset:08X}; after hgwrite haltgroup 1 for harts "
            f"{GROUP_HARTS}: "
            + ", ".join(
                f"hart {h} dmcs2=0x{v:08X} haltgroup={groups[h]}" for h, v in joined.items()
            )
            + f"; hart {OUTSIDE_HART} dmcs2=0x{outside:08X} haltgroup={_group(outside)}"
        )
        assert all(g == HALT_GROUP_1 for g in groups.values()) and _group(outside) == 0, (
            f"CHK-DM-HALTGROUP1-MEMBERSHIP FAIL: {text}"
        )
        self._chk("CHK-DM-HALTGROUP1-MEMBERSHIP", text)

        await self._dmi_write(DMI_DMCONTROL, _dmcontrol(TRIGGER_HART, DMCONTROL_HALTREQ))
        trigger = await self._poll("trigger_halt", DMI_DMSTATUS, self._halted)
        await self._dmi_write(DMI_DMCONTROL, _dmcontrol(FOLLOWER_HART))
        follower = await self._poll("follower_halt", DMI_DMSTATUS, self._halted)
        outside_status = await self._hart_status(OUTSIDE_HART)
        haltsum1 = await self._dmi_read(DMI_HALTSUM0)
        self._step_done("S3")
        assert self._running(outside_status), (
            f"CHK-DM-HALTGROUP1-PROPAGATES FAIL: hart {OUTSIDE_HART} outside the group "
            f"dmstatus=0x{outside_status:08X} after hart {TRIGGER_HART} halted"
        )
        self._chk(
            "CHK-DM-HALTGROUP1-PROPAGATES",
            f"haltreq on hart {TRIGGER_HART} alone: hart {TRIGGER_HART} dmstatus 0x{trigger:08X} "
            f"({self._polls['trigger_halt']} polls), hart {FOLLOWER_HART} in the same group "
            f"dmstatus 0x{follower:08X} halted without a request "
            f"({self._polls['follower_halt']} polls), hart {OUTSIDE_HART} outside the group "
            f"dmstatus 0x{outside_status:08X} running; haltsum0=0x{haltsum1:08X}",
        )

        select = DMCS2_HGWRITE | DMCS2_HGSELECT
        hgselect_rb = await self._dmcs2_write(HGSELECT_HART, select)
        hgselect_status = await self._hart_status(HGSELECT_HART)
        self._step_done("S4")
        assert _group(hgselect_rb) == HALT_GROUP_1 and not hgselect_rb & DMCS2_HGSELECT, (
            f"CHK-DM-HGSELECT-IGNORED FAIL: hart {HGSELECT_HART} dmcs2=0x{hgselect_rb:08X} "
            f"haltgroup={_group(hgselect_rb)} hgselect={int(bool(hgselect_rb & DMCS2_HGSELECT))} "
            f"after a write of 0x{select:08X} (hgwrite, hgselect, haltgroup 0)"
        )
        self._chk(
            "CHK-DM-HGSELECT-IGNORED",
            f"dmcs2 write 0x{select:08X} (hgwrite, hgselect, haltgroup 0) for hart "
            f"{HGSELECT_HART}, a member of group 1: readback 0x{hgselect_rb:08X} "
            f"haltgroup={_group(hgselect_rb)} hgselect={int(bool(hgselect_rb & DMCS2_HGSELECT))}, "
            f"dmstatus 0x{hgselect_status:08X}",
        )

        leave = DMCS2_HGWRITE
        left = {h: await self._dmcs2_write(h, leave) for h in GROUP_HARTS}
        self._step_done("S5")
        assert all(_group(v) == 0 for v in left.values()), (
            f"halt group not cleared: {[f'0x{v:08X}' for v in left.values()]}"
        )

        for hart in GROUP_HARTS:
            await self._dmi_write(DMI_DMCONTROL, _dmcontrol(hart, DMCONTROL_RESUMEREQ))
            await self._poll(
                f"resume_{hart}",
                DMI_DMSTATUS,
                lambda v: bool(v & DMSTATUS_ALLRESUMEACK) and bool(v & DMSTATUS_ALLRUNNING),
            )
            await self._dmi_write(DMI_DMCONTROL, _dmcontrol(hart))
        haltsum2 = await self._dmi_read(DMI_HALTSUM0)
        await self._dmi_write(DMI_DMCONTROL, _dmcontrol(0))
        await ClockCycles(clk, 2)
        self._step_done("S6")
        assert haltsum2 & HALTSUM_MASK == 0, f"haltsum0=0x{haltsum2:08X} after the resumes"

        self._assert_fence()
        cocotb.log.info(
            "CHK-TIMEOUT-PATHS: 3 bounded waits: dmi_busy_retry=%d enforced-by=%s "
            "fail-on-expiry=SmcJtagTapError last=%s; "
            "dm_active_poll=16 enforced-by=%s fail-on-expiry=AssertionError "
            "last=dmcontrol.dmactive; dmstatus_wait=%d fail-on-expiry=AssertionError "
            "last=dmstatus (max reads used %d)",
            VIP_DMI_BUSY_RETRIES,
            VIP_FILE,
            self._state(),
            VIP_FILE,
            _POLL_BOUND,
            max(self._polls.values()),
        )
        self.dm_ok = True
